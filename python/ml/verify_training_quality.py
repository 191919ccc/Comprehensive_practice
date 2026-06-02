"""Verify the latest daily ML training result from MySQL.

This script is intentionally read-only. Run it after formal training to check
whether the model version written to ``ml_model_metrics`` satisfies the risk
training quality gate.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
from typing import Any

import pymysql

from python.common.config import settings


DEFAULT_THRESHOLDS = {
    "min_lift": 0.0,
    "min_down_precision": 0.55,
    "min_down_coverage": 0.03,
    "max_down_coverage": 0.35,
    "min_lightgbm_weight": 0.95,
    "max_drop_ratio": 0.05,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify latest daily ML training quality from MySQL.")
    parser.add_argument("--version-prefix", default="", help="Only inspect model versions starting with this prefix.")
    parser.add_argument("--min-lift", type=float, default=DEFAULT_THRESHOLDS["min_lift"])
    parser.add_argument("--min-down-precision", type=float, default=DEFAULT_THRESHOLDS["min_down_precision"])
    parser.add_argument("--min-down-coverage", type=float, default=DEFAULT_THRESHOLDS["min_down_coverage"])
    parser.add_argument("--max-down-coverage", type=float, default=DEFAULT_THRESHOLDS["max_down_coverage"])
    parser.add_argument("--min-lightgbm-weight", type=float, default=DEFAULT_THRESHOLDS["min_lightgbm_weight"])
    parser.add_argument("--max-drop-ratio", type=float, default=DEFAULT_THRESHOLDS["max_drop_ratio"])
    return parser.parse_args()


def as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def metric_key(model_name: str, metric_name: str) -> tuple[str, str]:
    return model_name, metric_name


def fetch_latest_version(cursor, version_prefix: str) -> str | None:
    if version_prefix:
        cursor.execute(
            """
            SELECT model_version
            FROM ml_model_metrics
            WHERE model_version LIKE %s
            GROUP BY model_version
            ORDER BY MAX(id) DESC
            LIMIT 1
            """,
            (f"{version_prefix}%",),
        )
    else:
        cursor.execute(
            """
            SELECT model_version
            FROM ml_model_metrics
            GROUP BY model_version
            ORDER BY MAX(id) DESC
            LIMIT 1
            """
        )
    row = cursor.fetchone()
    return str(row["model_version"]) if row else None


def fetch_recent_versions(cursor, limit: int = 5) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT model_version, COUNT(*) AS metric_count, MAX(created_at) AS latest_metric_time
        FROM ml_model_metrics
        GROUP BY model_version
        ORDER BY MAX(id) DESC
        LIMIT %s
        """,
        (limit,),
    )
    return list(cursor.fetchall())


def fetch_metrics(cursor, version: str) -> dict[tuple[str, str], float]:
    cursor.execute(
        """
        SELECT model_name, metric_name, metric_value
        FROM ml_model_metrics
        WHERE model_version = %s
        """,
        (version,),
    )
    return {
        metric_key(str(row["model_name"]), str(row["metric_name"])): as_float(row["metric_value"])
        for row in cursor.fetchall()
    }


def fetch_prediction_summary(cursor, version: str) -> dict[str, Any]:
    prediction_version = f"ensemble-{version}"
    cursor.execute(
        """
        SELECT
            COUNT(*) AS rows_count,
            SUM(predicted_signal = 'DOWN') AS raw_down,
            SUM(predicted_signal = 'UP') AS raw_up,
            SUM(predicted_signal = 'WATCH') AS raw_watch,
            SUM(alert_signal = 'DOWN') AS alert_down,
            SUM(alert_signal = 'UP') AS alert_up,
            SUM(alert_signal = 'WATCH') AS alert_watch,
            AVG(final_risk_score) AS avg_risk,
            MAX(final_risk_score) AS max_risk
        FROM ml_predictions
        WHERE model_version = %s
        """,
        (prediction_version,),
    )
    row = cursor.fetchone() or {}
    return {
        "prediction_version": prediction_version,
        "rows_count": int(row.get("rows_count") or 0),
        "raw_down": int(row.get("raw_down") or 0),
        "raw_up": int(row.get("raw_up") or 0),
        "raw_watch": int(row.get("raw_watch") or 0),
        "alert_down": int(row.get("alert_down") or 0),
        "alert_up": int(row.get("alert_up") or 0),
        "alert_watch": int(row.get("alert_watch") or 0),
        "avg_risk": as_float(row.get("avg_risk")),
        "max_risk": as_float(row.get("max_risk")),
    }


def evaluate_quality(metrics: dict[tuple[str, str], float], args: argparse.Namespace) -> tuple[bool, dict[str, bool]]:
    checks = {
        "quality_gate_written": metric_key("quality_gate", "passed") in metrics,
        "quality_gate_passed": metrics.get(metric_key("quality_gate", "passed"), 0.0) >= 1.0,
        "lightgbm_lift_ok": metrics.get(metric_key("lightgbm", "walk_forward_direction_lift_over_baseline"), -1.0)
        > args.min_lift,
        "lightgbm_down_precision_ok": metrics.get(metric_key("lightgbm", "walk_forward_down_precision"), 0.0)
        >= args.min_down_precision,
        "lightgbm_down_coverage_ok": args.min_down_coverage
        <= metrics.get(metric_key("lightgbm", "walk_forward_predicted_down_ratio"), 1.0)
        <= args.max_down_coverage,
        "lightgbm_weight_ok": metrics.get(metric_key("ensemble", "lightgbm_weight"), 0.0) >= args.min_lightgbm_weight,
        "training_drop_ratio_ok": metrics.get(metric_key("training_data", "drop_ratio"), 1.0) <= args.max_drop_ratio,
    }
    return all(checks.values()), checks


def print_metric(metrics: dict[tuple[str, str], float], model_name: str, metric_name: str) -> None:
    value = metrics.get(metric_key(model_name, metric_name))
    if value is not None:
        print(f"[verify-ml]   {model_name}.{metric_name}={value:.4f}", flush=True)


def main() -> None:
    args = parse_args()
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cursor:
            version = fetch_latest_version(cursor, args.version_prefix)
            if not version:
                recent_versions = fetch_recent_versions(cursor)
                prefix_text = f" with prefix {args.version_prefix!r}" if args.version_prefix else ""
                print(f"[verify-ml] no ml_model_metrics version found{prefix_text}.", flush=True)
                if recent_versions:
                    print("[verify-ml] recent versions:", flush=True)
                    for row in recent_versions:
                        print(
                            f"[verify-ml]   {row['model_version']} "
                            f"metrics={row['metric_count']} latest={row['latest_metric_time']}",
                            flush=True,
                        )
                print("[verify-ml] run .\\tools\\train_clean_risk.ps1 before verifying clean-risk output.", flush=True)
                raise SystemExit(1)
            metrics = fetch_metrics(cursor, version)
            passed, checks = evaluate_quality(metrics, args)
            prediction_summary = fetch_prediction_summary(cursor, version)
    finally:
        conn.close()

    print(f"[verify-ml] version={version}", flush=True)
    print(f"[verify-ml] quality_gate={'PASS' if passed else 'FAIL'}", flush=True)
    for check_name, ok in checks.items():
        print(f"[verify-ml]   {check_name}={1 if ok else 0}", flush=True)
    for model_name, metric_name in (
        ("quality_gate", "passed"),
        ("lightgbm", "walk_forward_direction_lift_over_baseline"),
        ("lightgbm", "walk_forward_down_precision"),
        ("lightgbm", "walk_forward_predicted_down_ratio"),
        ("ensemble", "lightgbm_weight"),
        ("ensemble", "lstm_weight"),
        ("training_data", "drop_ratio"),
    ):
        print_metric(metrics, model_name, metric_name)
    print(f"[verify-ml] predictions={prediction_summary}", flush=True)
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
