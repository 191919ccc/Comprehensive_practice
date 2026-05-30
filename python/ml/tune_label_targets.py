"""Compare daily ML label horizons and direction thresholds."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import python.ml.stock_ml as stock_ml
from python.ml.stock_ml import limit_training_dataset, load_price_ticks, prepare_dataset


def parse_float_list(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def parse_int_list(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test T+N horizons and UP/DOWN/WATCH thresholds.")
    parser.add_argument("--horizons", default="1,3,5,10", help="Comma-separated prediction horizons.")
    parser.add_argument("--thresholds", default="0.005,0.01,0.015,0.02,0.03", help="Comma-separated direction thresholds.")
    parser.add_argument("--max-rows", type=int, default=120000, help="Dataset row cap for each label test.")
    parser.add_argument("--out-dir", default="reports/ml_label_targets", help="Output directory.")
    return parser.parse_args()


@contextmanager
def patched_stock_ml(**values: Any):
    old_values = {key: getattr(stock_ml, key) for key in values}
    try:
        for key, value in values.items():
            setattr(stock_ml, key, value)
        yield
    finally:
        for key, value in old_values.items():
            setattr(stock_ml, key, value)


def label_metrics(dataset: pd.DataFrame, horizon: int, threshold: float) -> dict[str, Any]:
    labels = dataset["next_direction"].to_numpy(dtype=int)
    counts = np.bincount(labels, minlength=len(stock_ml.DIRECTION_LABELS)).astype(float)
    total = float(counts.sum())
    returns = pd.to_numeric(dataset["next_return"], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return {
        "horizon": horizon,
        "threshold": threshold,
        "rows": int(total),
        "symbols": int(dataset["symbol"].nunique()),
        "down_ratio": counts[stock_ml.DIRECTION_DOWN] / total if total else 0,
        "up_ratio": counts[stock_ml.DIRECTION_UP] / total if total else 0,
        "watch_ratio": counts[stock_ml.DIRECTION_FLAT] / total if total else 0,
        "majority_baseline_accuracy": counts.max() / total if total else 0,
        "next_return_mean": float(returns.mean()) if len(returns) else 0,
        "next_return_std": float(returns.std()) if len(returns) else 0,
        "next_return_abs_median": float(returns.abs().median()) if len(returns) else 0,
    }


def main() -> None:
    args = parse_args()
    horizons = parse_int_list(args.horizons)
    thresholds = parse_float_list(args.thresholds)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ticks = load_price_ticks(source="akshare_cold_start")
    index_ticks = load_price_ticks(source="akshare_index")
    rows: list[dict[str, Any]] = []
    for horizon in horizons:
        for threshold in thresholds:
            with patched_stock_ml(PREDICTION_HORIZON=horizon, MIN_DIRECTION_RETURN=threshold, DIRECTION_FIXED_THRESHOLD=threshold):
                dataset = prepare_dataset(ticks, index_ticks)
                if args.max_rows > 0:
                    old_max = stock_ml.settings.ml_max_train_rows
                    stock_ml.settings.ml_max_train_rows = args.max_rows
                    try:
                        dataset = limit_training_dataset(dataset)
                    finally:
                        stock_ml.settings.ml_max_train_rows = old_max
                rows.append(label_metrics(dataset, horizon, threshold))
                print(f"[label] T+{horizon} threshold={threshold:g} rows={len(dataset)}")
    report = pd.DataFrame(rows).sort_values(["majority_baseline_accuracy", "watch_ratio"])
    path = out_dir / f"daily_label_targets_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
    report.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"[label] wrote {path}")


if __name__ == "__main__":
    main()
