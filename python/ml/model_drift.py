from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

import pymysql

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from python.common.config import settings
from python.ml.daily_bar_store import DAILY_STOCK_TABLE, ensure_daily_bar_tables

DEFAULT_SIGNAL_THRESHOLD = float(settings.ml_direction_threshold)
DEFAULT_PREDICTION_HORIZON = max(1, int(settings.ml_prediction_horizon))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check recent ML prediction accuracy and raise model-drift alerts.")
    parser.add_argument("--window", type=int, default=50, help="Evaluated prediction count required before drift decision.")
    parser.add_argument("--threshold", type=float, default=0.55, help="Accuracy lower than this value triggers drift alert.")
    parser.add_argument(
        "--signal-threshold",
        type=float,
        default=DEFAULT_SIGNAL_THRESHOLD,
        help="Minimum return needed to label actual movement as UP/DOWN; smaller moves are WATCH.",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=DEFAULT_PREDICTION_HORIZON,
        help="Evaluate against the N-th later price event for the same symbol.",
    )
    return parser.parse_args()


def actual_signal(current_price: float, actual_price: float, signal_threshold: float = DEFAULT_SIGNAL_THRESHOLD) -> str:
    if actual_price > current_price * (1 + signal_threshold):
        return "UP"
    if actual_price < current_price * (1 - signal_threshold):
        return "DOWN"
    return "WATCH"


def find_prediction_base_event_time(cursor, row: dict):
    for table in (DAILY_STOCK_TABLE, "price_ticks"):
        cursor.execute(
            f"""
            SELECT event_time
            FROM {table}
            WHERE symbol = %s
              AND ABS(last_price - %s) < 0.005
              AND created_at <= %s
            ORDER BY event_time DESC, created_at DESC, id DESC
            LIMIT 1
            """,
            (row["symbol"], row["current_price"], row["predicted_at"]),
        )
        matched = cursor.fetchone()
        if matched is not None:
            return matched["event_time"]
    for table in (DAILY_STOCK_TABLE, "price_ticks"):
        cursor.execute(
            f"""
            SELECT event_time
            FROM {table}
            WHERE symbol = %s
              AND created_at <= %s
            ORDER BY event_time DESC, created_at DESC, id DESC
            LIMIT 1
            """,
            (row["symbol"], row["predicted_at"]),
        )
        fallback = cursor.fetchone()
        if fallback is not None:
            return fallback["event_time"]
    return None


def find_horizon_actual_price(cursor, symbol: str, base_event_time, horizon: int):
    for table in (DAILY_STOCK_TABLE, "price_ticks"):
        cursor.execute(
            f"""
            SELECT last_price, event_time
            FROM {table}
            WHERE symbol = %s
              AND event_time > %s
            ORDER BY event_time ASC, id ASC
            LIMIT 1 OFFSET %s
            """,
            (symbol, base_event_time, max(horizon - 1, 0)),
        )
        row = cursor.fetchone()
        if row is not None:
            return row
    return None


def evaluated_predictions(
    cursor,
    limit: int,
    signal_threshold: float = DEFAULT_SIGNAL_THRESHOLD,
    horizon: int = DEFAULT_PREDICTION_HORIZON,
) -> list[dict]:
    cursor.execute(
        """
        SELECT id, symbol, company_name, category, sector, current_price, predicted_signal, model_version, predicted_at
        FROM ml_prediction_history
        ORDER BY predicted_at DESC, id DESC
        LIMIT %s
        """,
        (limit * 4,),
    )
    rows = cursor.fetchall()
    evaluated: list[dict] = []
    for row in rows:
        base_event_time = find_prediction_base_event_time(cursor, row)
        if base_event_time is None:
            continue
        actual = find_horizon_actual_price(cursor, row["symbol"], base_event_time, horizon)
        if actual is None:
            continue
        signal = actual_signal(float(row["current_price"]), float(actual["last_price"]), signal_threshold)
        evaluated.append(
            {
                **row,
                "base_event_time": base_event_time,
                "actual_event_time": actual["event_time"],
                "actual_signal": signal,
                "correct": signal == row["predicted_signal"],
            }
        )
        if len(evaluated) >= limit:
            break
    return evaluated


def write_metric(cursor, accuracy: float, evaluated_count: int) -> None:
    cursor.execute(
        """
        INSERT INTO ml_model_metrics (model_name, metric_name, metric_value, model_version)
        VALUES (%s, %s, %s, %s)
        """,
        ("drift_monitor", "recent_direction_accuracy", accuracy, f"window_{evaluated_count}"),
    )


def write_drift_alert(cursor, accuracy: float, threshold: float) -> None:
    cursor.execute(
        """
        INSERT INTO alert_events
        (event_id, symbol, company_name, category, sector, market, open_price, high_price, low_price,
         last_price, previous_close, change_pct, volume, turnover, event_time, source, alert_type, alert_level)
        VALUES (%s, %s, %s, %s, %s, %s, 0, 0, 0, 0, 0, %s, 1, 0, NOW(), %s, %s, %s)
        """,
        (
            str(uuid.uuid4()),
            "MODEL_DRIFT",
            "模型漂移监控",
            "System",
            "Model",
            "SYSTEM",
            round(accuracy * 100, 4),
            "model_drift",
            "model_drift",
            "HIGH" if accuracy < threshold else "MEDIUM",
        ),
    )


def check_model_drift(
    window: int,
    threshold: float,
    signal_threshold: float = DEFAULT_SIGNAL_THRESHOLD,
    horizon: int = DEFAULT_PREDICTION_HORIZON,
) -> dict:
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cursor:
            ensure_daily_bar_tables(cursor)
            evaluated = evaluated_predictions(cursor, window, signal_threshold, horizon)
            if len(evaluated) < window:
                return {
                    "ready": False,
                    "evaluated": len(evaluated),
                    "window": window,
                    "signal_threshold": signal_threshold,
                    "horizon": horizon,
                }
            accuracy = sum(1 for row in evaluated if row["correct"]) / len(evaluated)
            write_metric(cursor, accuracy, len(evaluated))
            drift = accuracy < threshold
            if drift:
                write_drift_alert(cursor, accuracy, threshold)
            return {
                "ready": True,
                "evaluated": len(evaluated),
                "accuracy": accuracy,
                "threshold": threshold,
                "signal_threshold": signal_threshold,
                "horizon": horizon,
                "drift": drift,
            }
    finally:
        conn.close()


def main() -> None:
    args = parse_args()
    result = check_model_drift(args.window, args.threshold, args.signal_threshold, args.horizon)
    print(result)
    if result.get("ready") and result.get("drift"):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
