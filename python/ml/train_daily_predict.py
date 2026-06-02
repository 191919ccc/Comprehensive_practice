import argparse
import time
from contextlib import contextmanager
from datetime import datetime

import python.ml.stock_ml as stock_ml
from python.ml.model_drift import check_model_drift
from python.ml.stock_ml import (
    collect_metrics,
    data_quality_metrics,
    horizon_experiment_metrics,
    load_price_ticks,
    predict_latest_ensemble,
    prepare_model_datasets,
    save_models,
    select_best_model,
    threshold_experiment_metrics,
    train_models,
    write_results,
)


VALID_MODEL_NAMES = {"random_forest", "lightgbm", "lstm"}


@contextmanager
def log_stage(name: str):
    """Print start/end message and elapsed seconds for each training stage."""
    start = time.perf_counter()
    print(f"[daily-ml] >>> {name} start", flush=True)
    try:
        yield
    finally:
        cost = time.perf_counter() - start
        print(f"[daily-ml] <<< {name} done, cost={cost:.1f}s", flush=True)


def log_dataset(name: str, df) -> None:
    """Print common dataframe information without breaking if columns are absent."""
    if df is None:
        print(f"[daily-ml] {name}: None", flush=True)
        return
    rows = len(df)
    symbols = df["symbol"].nunique() if hasattr(df, "empty") and not df.empty and "symbol" in df.columns else 0
    msg = f"[daily-ml] {name}: rows={rows}, symbols={symbols}"
    if hasattr(df, "columns") and "trade_date" in df.columns and rows > 0:
        msg += f", date_range={df['trade_date'].min()} -> {df['trade_date'].max()}"
    elif hasattr(df, "columns") and "date" in df.columns and rows > 0:
        msg += f", date_range={df['date'].min()} -> {df['date'].max()}"
    print(msg, flush=True)


def latest_data_date(df):
    """Return latest trade/event date in a pandas dataframe, or None."""
    if df is None or df.empty:
        return None
    column = "trade_date" if "trade_date" in df.columns else "event_time" if "event_time" in df.columns else None
    if column is None:
        return None
    latest = stock_ml.pd.to_datetime(df[column], errors="coerce").max()
    if stock_ml.pd.isna(latest):
        return None
    return latest.date()


def assert_daily_data_freshness(ticks, index_ticks, allow_stale: bool = False) -> None:
    """Stop training when daily bars are stale unless explicitly overridden."""
    max_age = int(stock_ml.settings.ml_max_daily_data_age_days)
    today = datetime.now().date()
    checks = [
        ("daily_stock_bars", latest_data_date(ticks)),
        ("daily_index_bars", latest_data_date(index_ticks)),
    ]
    stale_messages: list[str] = []
    for name, latest in checks:
        if latest is None:
            stale_messages.append(f"{name}: no usable trade_date/event_time")
            continue
        age_days = (today - latest).days
        print(f"[daily-ml] freshness {name}: latest={latest}, age_days={age_days}, max_age_days={max_age}", flush=True)
        if age_days > max_age:
            stale_messages.append(f"{name}: latest={latest}, age_days={age_days} > {max_age}")
    if not stale_messages:
        return
    message = "[daily-ml] daily data is stale; update daily bars before training: " + "; ".join(stale_messages)
    if allow_stale or stock_ml.settings.ml_allow_stale_daily_data:
        print(f"[daily-ml][warn] {message}", flush=True)
        return
    raise SystemExit(message + ". To override for debugging only, pass --allow-stale-data or set ML_ALLOW_STALE_DAILY_DATA=true.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a daily-bar stock ML model.")
    parser.add_argument(
        "--direction-threshold",
        type=float,
        default=None,
        help="Override every model's UP/DOWN/WATCH threshold. Omit this to use the searched best per-model thresholds.",
    )
    parser.add_argument("--no-write", action="store_true", help="Train and print metrics without saving models or writing MySQL predictions.")
    parser.add_argument("--version-label", default="daily", help="Version prefix label.")
    parser.add_argument(
        "--models",
        default="lightgbm,lstm",
        help="Comma-separated models to train: random_forest, lightgbm, lstm. Defaults to production LightGBM+LSTM.",
    )
    parser.add_argument(
        "--allow-stale-data",
        action="store_true",
        help="Allow training even when daily_stock_bars or daily_index_bars are older than ML_MAX_DAILY_DATA_AGE_DAYS.",
    )
    parser.add_argument(
        "--prediction-horizon",
        type=int,
        default=stock_ml.settings.ml_prediction_horizon,
        help="Predict the direction after N trading bars. Use 1, 3, or 5 to compare short horizons.",
    )
    parser.add_argument(
        "--horizon-experiments",
        default=stock_ml.settings.ml_horizon_experiments,
        help="Comma-separated horizons used for label-distribution diagnostics, for example 1,3,5.",
    )
    return parser.parse_args()


def parse_model_names(value: str) -> set[str]:
    names = {item.strip().lower() for item in value.split(",") if item.strip()}
    invalid = names - VALID_MODEL_NAMES
    if invalid:
        raise SystemExit(f"[daily-ml] invalid --models value: {', '.join(sorted(invalid))}")
    if not names:
        raise SystemExit("[daily-ml] --models must include at least one model.")
    return names


def parse_int_list(value: str) -> list[int]:
    """Parse comma-separated positive integers from CLI/env text."""
    items: list[int] = []
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        parsed = int(item)
        if parsed <= 0:
            raise SystemExit("[daily-ml] horizons must be positive integers.")
        items.append(parsed)
    return items


def metric_lookup(metrics: list[tuple[str, str, float]]) -> dict[tuple[str, str], float]:
    """Build a stable lookup for collected metric tuples."""
    return {(model_name, metric_name): float(metric_value) for model_name, metric_name, metric_value in metrics}


def append_training_quality_gate(metrics: list[tuple[str, str, float]]) -> dict[str, float]:
    """Append pass/fail metrics for the production risk-training gate."""
    lookup = metric_lookup(metrics)
    lightgbm_lift = lookup.get(("lightgbm", "walk_forward_direction_lift_over_baseline"), -1.0)
    lightgbm_precision = lookup.get(("lightgbm", "walk_forward_down_precision"), 0.0)
    lightgbm_coverage = lookup.get(("lightgbm", "walk_forward_predicted_down_ratio"), 1.0)
    lightgbm_weight = lookup.get(("ensemble", "lightgbm_weight"), 1.0)
    lstm_weight = lookup.get(("ensemble", "lstm_weight"), 0.0)
    drop_ratio = lookup.get(("training_data", "drop_ratio"), 0.0)

    checks = {
        "lightgbm_lift_ok": 1.0 if lightgbm_lift > 0 else 0.0,
        "lightgbm_down_precision_ok": 1.0 if lightgbm_precision >= 0.55 else 0.0,
        "lightgbm_down_coverage_ok": 1.0 if 0.03 <= lightgbm_coverage <= 0.35 else 0.0,
        "lightgbm_weight_ok": 1.0 if lightgbm_weight >= 0.95 else 0.0,
        "training_drop_ratio_ok": 1.0 if drop_ratio <= 0.05 else 0.0,
    }
    passed = 1.0 if all(value >= 1.0 for value in checks.values()) else 0.0
    gate_metrics = {
        "passed": passed,
        "lightgbm_walk_forward_lift": lightgbm_lift,
        "lightgbm_walk_forward_down_precision": lightgbm_precision,
        "lightgbm_walk_forward_predicted_down_ratio": lightgbm_coverage,
        "ensemble_lightgbm_weight": lightgbm_weight,
        "ensemble_lstm_weight": lstm_weight,
        "training_data_drop_ratio": drop_ratio,
        **checks,
    }
    metrics.extend(("quality_gate", name, value) for name, value in gate_metrics.items())
    return gate_metrics


def print_training_quality_summary(metrics: list[tuple[str, str, float]], predictions) -> None:
    """Print the key post-training evidence instead of only a long metric list."""
    lookup = metric_lookup(metrics)
    gate_passed = lookup.get(("quality_gate", "passed"), 0.0) >= 1.0
    status = "PASS" if gate_passed else "FAIL"
    print(f"[daily-ml] quality_gate={status}", flush=True)
    for model_name, metric_name in (
        ("lightgbm", "walk_forward_direction_lift_over_baseline"),
        ("lightgbm", "walk_forward_down_precision"),
        ("lightgbm", "walk_forward_predicted_down_ratio"),
        ("lightgbm", "calibration_down_precision"),
        ("ensemble", "lightgbm_weight"),
        ("ensemble", "lstm_weight"),
        ("training_data", "drop_ratio"),
    ):
        if (model_name, metric_name) in lookup:
            print(f"[daily-ml]   {model_name}.{metric_name}={lookup[(model_name, metric_name)]:.4f}", flush=True)
    if predictions is not None and not predictions.empty:
        raw_counts = predictions.get("predicted_signal", stock_ml.pd.Series(dtype=str)).value_counts().to_dict()
        alert_counts = predictions.get("alert_signal", stock_ml.pd.Series(dtype=str)).value_counts().to_dict()
        avg_risk = float(predictions.get("final_risk_score", stock_ml.pd.Series([0.0])).mean())
        max_risk = float(predictions.get("final_risk_score", stock_ml.pd.Series([0.0])).max())
        print(f"[daily-ml]   latest_raw_signal_counts={raw_counts}", flush=True)
        print(f"[daily-ml]   latest_alert_signal_counts={alert_counts}", flush=True)
        print(f"[daily-ml]   latest_risk_score_avg={avg_risk:.4f}, max={max_risk:.4f}", flush=True)


def main() -> None:
    """Train the daily-bar ML pipeline from daily stock and index bars."""
    args = parse_args()
    selected_model_names = parse_model_names(args.models)
    selected_horizon = max(1, int(args.prediction_horizon))
    experiment_horizons = parse_int_list(args.horizon_experiments)
    print(f"[daily-ml] selected models: {sorted(selected_model_names)}", flush=True)
    stock_ml.MIN_DIRECTION_RETURN = float(args.direction_threshold if args.direction_threshold is not None else stock_ml.settings.ml_direction_threshold)
    stock_ml.DIRECTION_FIXED_THRESHOLD = args.direction_threshold
    stock_ml.PREDICTION_HORIZON = selected_horizon
    stock_ml.LSTM_WINDOW_SIZE = max(5, int(stock_ml.settings.ml_lstm_window_size))
    print(
        f"[daily-ml] target_mode={stock_ml.ML_TARGET_MODE}, prediction_horizon={selected_horizon}, horizon_experiments={experiment_horizons}",
        flush=True,
    )
    if args.direction_threshold is not None:
        print(f"[daily-ml] override all model direction_threshold={args.direction_threshold}", flush=True)
    else:
        print(f"[daily-ml] using searched per-model direction thresholds: {stock_ml.OPTIMAL_MODEL_CONFIGS}", flush=True)

    with log_stage("load daily_stock_bars"):
        ticks = load_price_ticks(source="akshare_cold_start")
    log_dataset("loaded daily ticks", ticks)
    if ticks.empty:
        raise SystemExit("[daily-ml] no daily stock bars found; run: python -m python.ml.cold_start --days 900")

    with log_stage("load daily_index_bars"):
        index_ticks = load_price_ticks(source="akshare_index")
    log_dataset("loaded index ticks", index_ticks)
    assert_daily_data_freshness(ticks, index_ticks, args.allow_stale_data)

    with log_stage("prepare model datasets"):
        if args.direction_threshold is None:
            model_datasets = prepare_model_datasets(ticks, index_ticks, selected_model_names, prediction_horizon=selected_horizon)
        else:
            dataset = stock_ml.prepare_dataset(ticks, index_ticks, direction_threshold=args.direction_threshold, prediction_horizon=selected_horizon)
            before_limit_rows = len(dataset)
            dataset = stock_ml.limit_training_dataset(dataset)
            dataset.attrs["direction_threshold"] = float(args.direction_threshold)
            dataset.attrs["prediction_horizon"] = selected_horizon
            print(f"[daily-ml] dataset limit summary: {before_limit_rows} -> {len(dataset)}", flush=True)
            model_datasets = {name: dataset for name in stock_ml.OPTIMAL_MODEL_CONFIGS}
        model_datasets = {name: data for name, data in model_datasets.items() if name in selected_model_names}
    for model_name, model_dataset in model_datasets.items():
        log_dataset(f"{model_name} prepared dataset", model_dataset)

    if args.direction_threshold is not None:
        threshold_label = f"-fixed{int(round(args.direction_threshold * 10000)):04d}bp"
    else:
        threshold_label = "-bestparams"
    horizon_label = f"-h{selected_horizon}"
    version = f"{args.version_label}{threshold_label}{horizon_label}-" + datetime.now().strftime("%Y%m%d%H%M%S")

    with log_stage("train all models"):
        model_results = train_models(model_datasets, selected_model_names)
    print("[daily-ml] model training summary:", flush=True)
    for result in model_results:
        print(f"[daily-ml]   model={result.name}", flush=True)

    operational_candidates = [result for result in model_results if result.name != "random_forest"] or model_results
    best_model = select_best_model(operational_candidates)
    print(f"[daily-ml] selected best_non_baseline_model={best_model.name}", flush=True)

    with log_stage("predict latest daily rows"):
        predictions = predict_latest_ensemble(ticks, model_results, version, index_ticks)
    log_dataset("latest predictions", predictions)

    with log_stage("collect metrics"):
        metrics = collect_metrics(model_results, best_model.name)
        experiment_dataset = model_datasets["lightgbm"] if "lightgbm" in model_datasets else next(iter(model_datasets.values()))
        metrics.extend(data_quality_metrics(experiment_dataset))
        metrics.extend(threshold_experiment_metrics(experiment_dataset))
        experiment_threshold = float(args.direction_threshold) if args.direction_threshold is not None else float(stock_ml.OPTIMAL_MODEL_CONFIGS["lightgbm"]["direction_threshold"])
        metrics.extend(horizon_experiment_metrics(ticks, index_ticks, experiment_threshold, experiment_horizons))
        append_training_quality_gate(metrics)
    print(f"[daily-ml] collected metrics count={len(metrics)}", flush=True)
    print_training_quality_summary(metrics, predictions)

    if args.no_write:
        drift_result = {"skipped": True, "reason": "no-write"}
    else:
        with log_stage("save models"):
            save_models(model_results, version)
        with log_stage("write results"):
            write_results(predictions, metrics, version)
        with log_stage("check model drift"):
            drift_result = check_model_drift(
                window=50,
                threshold=0.55,
                horizon=selected_horizon,
                model_version=f"ensemble-{version}",
                price_source="daily",
            )

    sample_rows = {name: len(model_dataset) for name, model_dataset in model_datasets.items()}
    print(f"trained {len(model_results)} daily stock ML models with samples={sample_rows}, version={version}")
    print("prediction_model=ensemble" if len(model_results) >= 2 else f"prediction_model={best_model.name}")
    print(f"best_non_baseline_model={best_model.name}")
    print(metrics)
    print(f"drift_check={drift_result}")


if __name__ == "__main__":
    main()
