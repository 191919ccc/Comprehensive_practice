from datetime import datetime

from python.ml.stock_ml import (
    collect_metrics,
    limit_training_dataset,
    load_price_ticks,
    predict_latest_ensemble,
    prepare_dataset,
    save_models,
    select_best_model,
    threshold_experiment_metrics,
    train_models,
    write_results,
)
from python.ml.model_drift import check_model_drift
import python.ml.stock_ml as stock_ml


def main() -> None:
    """Train the minute/tick-based ML pipeline.

    This entry uses `price_ticks`, so its samples come from the real-time
    crawler and Spark stream. The prediction horizon is three future rows per
    symbol, not a guaranteed wall-clock three minutes.
    """
    stock_ml.MIN_DIRECTION_RETURN = float(stock_ml.settings.ml_direction_threshold)
    stock_ml.DIRECTION_FIXED_THRESHOLD = float(stock_ml.settings.ml_direction_threshold)
    stock_ml.PREDICTION_HORIZON = 3
    stock_ml.LSTM_WINDOW_SIZE = 20
    print("[ml] loading ticks", flush=True)
    ticks = load_price_ticks()
    print(f"[ml] loaded ticks={len(ticks)}", flush=True)

    dataset = prepare_dataset(ticks)
    print(f"[ml] prepared samples={len(dataset)}", flush=True)
    dataset = limit_training_dataset(dataset)

    version = datetime.now().strftime("%Y%m%d%H%M%S")
    model_results = train_models(dataset)

    print("[ml] selecting operational model", flush=True)
    operational_candidates = [result for result in model_results if result.name != "random_forest"] or model_results
    best_model = select_best_model(operational_candidates)

    print("[ml] predicting latest rows", flush=True)
    predictions = predict_latest_ensemble(ticks, model_results, version)

    print("[ml] saving models", flush=True)
    save_models(model_results, version)

    metrics = collect_metrics(model_results, best_model.name)
    metrics.extend(threshold_experiment_metrics(dataset))
    print("[ml] writing results", flush=True)
    write_results(predictions, metrics, version)
    drift_result = check_model_drift(window=50, threshold=0.55)

    print(f"trained {len(model_results)} stock ML models with {len(dataset)} samples, version={version}")
    print("prediction_model=ensemble" if len(operational_candidates) >= 2 else f"prediction_model={best_model.name}")
    print(f"best_non_baseline_model={best_model.name}")
    print(metrics)
    print(f"drift_check={drift_result}")


if __name__ == "__main__":
    main()
