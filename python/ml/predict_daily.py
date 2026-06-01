from __future__ import annotations

from datetime import datetime

import python.ml.stock_ml as stock_ml
from python.ml.stock_ml import (
    load_latest_model_results,
    load_price_ticks,
    predict_latest_ensemble,
    write_results,
)


def main() -> None:
    """Generate daily predictions from the latest trained daily models without retraining."""
    stock_ml.MIN_DIRECTION_RETURN = float(stock_ml.settings.ml_direction_threshold)
    stock_ml.DIRECTION_FIXED_THRESHOLD = float(stock_ml.settings.ml_direction_threshold)
    stock_ml.PREDICTION_HORIZON = max(1, int(stock_ml.settings.ml_prediction_horizon))
    stock_ml.LSTM_WINDOW_SIZE = max(5, int(stock_ml.settings.ml_lstm_window_size))

    print("[daily-predict] loading daily_stock_bars", flush=True)
    ticks = load_price_ticks(source="akshare_cold_start")
    print(f"[daily-predict] loaded daily ticks={len(ticks)} symbols={ticks['symbol'].nunique() if not ticks.empty else 0}", flush=True)
    if ticks.empty:
        raise SystemExit("[daily-predict] no daily bars found; run: python -m python.ml.cold_start --days 900")
    print("[daily-predict] loading daily_index_bars", flush=True)
    index_ticks = load_price_ticks(source="akshare_index")
    print(
        f"[daily-predict] loaded index ticks={len(index_ticks)} symbols={index_ticks['symbol'].nunique() if not index_ticks.empty else 0}",
        flush=True,
    )

    model_results, trained_version = load_latest_model_results(version_prefix="daily-")
    predict_version = "daily-predict-" + datetime.now().strftime("%Y%m%d%H%M%S")
    print(f"[daily-predict] loaded model_version={trained_version}", flush=True)
    print("[daily-predict] predicting latest daily rows", flush=True)
    predictions = predict_latest_ensemble(ticks, model_results, predict_version, index_ticks)
    print("[daily-predict] writing predictions without replacing validation metrics", flush=True)
    write_results(predictions, metrics=[], version=predict_version, update_metrics=False)
    print(f"daily prediction done rows={len(predictions)} trained_version={trained_version} predict_version={predict_version}")


if __name__ == "__main__":
    main()
