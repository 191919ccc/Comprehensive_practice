"""Grouped daily-ML parameter tests for RandomForest, LightGBM and LSTM.

This script is intentionally read-only for production outputs: it loads daily
bars, prepares the same dataset as training, evaluates parameter groups, and
writes CSV reports under reports/ml_tuning. It does not save models or write
predictions to MySQL.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import time
from typing import Any

import pandas as pd

import python.ml.stock_ml as stock_ml
from python.ml.stock_ml import (
    limit_training_dataset,
    load_price_ticks,
    prepare_dataset,
    train_tabular_models,
)


def parse_float_list(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def parse_int_list(value: str) -> list[int]:
    items = [int(item.strip()) for item in value.split(",") if item.strip()]
    invalid = [item for item in items if item <= 0]
    if invalid:
        raise SystemExit(f"[tune] horizons must be positive integers: {invalid}")
    return items


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run grouped daily parameter tests with baseline-gated scoring.")
    parser.add_argument("--models", default="random_forest,lightgbm,lstm", help="Comma-separated model families: random_forest,lightgbm,lstm")
    parser.add_argument("--max-rows", type=int, default=60000, help="Dataset row cap for tuning. Use 0 for full configured limit.")
    parser.add_argument("--lstm-max-sequences", type=int, default=24000, help="LSTM sequence cap during tuning.")
    parser.add_argument("--lstm-epochs", type=int, default=18, help="LSTM epochs during tuning.")
    parser.add_argument("--lstm-patience", type=int, default=5, help="LSTM early-stop patience during tuning.")
    parser.add_argument("--direction-threshold", type=float, default=0.015, help="Fixed direction threshold for daily labels.")
    parser.add_argument("--direction-thresholds", default="", help="Optional comma-separated thresholds, for example 0.01,0.015,0.02.")
    parser.add_argument("--horizons", default="1,3,5", help="Comma-separated prediction horizons to test, for example 1,3,5.")
    parser.add_argument("--out-dir", default="reports/ml_tuning", help="Output directory for CSV reports.")
    return parser.parse_args()


@contextmanager
def stage(name: str):
    start = time.perf_counter()
    print(f"[tune] >>> {name}", flush=True)
    try:
        yield
    finally:
        print(f"[tune] <<< {name}, cost={time.perf_counter() - start:.1f}s", flush=True)


@contextmanager
def patched_stock_ml(**values: Any):
    old_values: dict[str, Any] = {}
    for key, value in values.items():
        target = stock_ml.settings if key.startswith("settings.") else stock_ml
        attr = key.split(".", 1)[1] if key.startswith("settings.") else key
        old_values[key] = getattr(target, attr)
        setattr(target, attr, value)
    if any(key in values for key in ("LSTM_NUM_LAYERS", "LSTM_DROPOUT")):
        stock_ml.LSTM_RECURRENT_DROPOUT = stock_ml.LSTM_DROPOUT if stock_ml.LSTM_NUM_LAYERS > 1 else 0.0
    try:
        yield
    finally:
        for key, value in old_values.items():
            target = stock_ml.settings if key.startswith("settings.") else stock_ml
            attr = key.split(".", 1)[1] if key.startswith("settings.") else key
            setattr(target, attr, value)
        stock_ml.LSTM_RECURRENT_DROPOUT = stock_ml.LSTM_DROPOUT if stock_ml.LSTM_NUM_LAYERS > 1 else 0.0


def cap_dataset(dataset: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    if max_rows <= 0 or len(dataset) <= max_rows:
        return limit_training_dataset(dataset)
    with patched_stock_ml(**{"settings.ml_max_train_rows": max_rows}):
        return limit_training_dataset(dataset)


def lgbm_groups() -> list[dict[str, Any]]:
    return [
        {
            "group": "lgbm_production",
            "n_estimators": 350,
            "learning_rate": 0.02,
            "num_leaves": 63,
            "min_child_samples": 40,
            "subsample": 0.8,
            "colsample_bytree": 0.85,
            "reg_lambda": 1.5,
        },
        {
            "group": "lgbm_slow_regularized",
            "n_estimators": 500,
            "learning_rate": 0.01,
            "num_leaves": 31,
            "min_child_samples": 60,
            "subsample": 0.85,
            "colsample_bytree": 0.85,
            "reg_lambda": 2.0,
        },
        {
            "group": "lgbm_shallow_stable",
            "n_estimators": 400,
            "learning_rate": 0.015,
            "num_leaves": 15,
            "min_child_samples": 50,
            "subsample": 0.85,
            "colsample_bytree": 0.9,
            "reg_lambda": 1.0,
        },
        {
            "group": "lgbm_more_leaves",
            "n_estimators": 350,
            "learning_rate": 0.02,
            "num_leaves": 63,
            "min_child_samples": 40,
            "subsample": 0.8,
            "colsample_bytree": 0.85,
            "reg_lambda": 1.5,
        },
        {
            "group": "lgbm_conservative",
            "n_estimators": 260,
            "learning_rate": 0.025,
            "num_leaves": 15,
            "min_child_samples": 80,
            "subsample": 0.75,
            "colsample_bytree": 0.75,
            "reg_lambda": 3.0,
        },
        {
            "group": "lgbm_baseline_guard",
            "n_estimators": 220,
            "learning_rate": 0.03,
            "num_leaves": 7,
            "min_child_samples": 120,
            "subsample": 0.7,
            "colsample_bytree": 0.7,
            "reg_lambda": 5.0,
        },
    ]


def random_forest_groups() -> list[dict[str, Any]]:
    return [
        {
            "group": "rf_production",
            "n_estimators_reg": 100,
            "n_estimators_cls": 200,
            "max_depth": None,
            "min_samples_leaf": 1,
            "max_features": "sqrt",
            "calibration": "isotonic",
        },
        {
            "group": "rf_regularized_depth",
            "n_estimators_reg": 160,
            "n_estimators_cls": 260,
            "max_depth": 14,
            "min_samples_leaf": 4,
            "max_features": "sqrt",
            "calibration": "sigmoid",
        },
        {
            "group": "rf_leaf_stable",
            "n_estimators_reg": 180,
            "n_estimators_cls": 300,
            "max_depth": 18,
            "min_samples_leaf": 8,
            "max_features": 0.55,
            "calibration": "sigmoid",
        },
        {
            "group": "rf_baseline_guard",
            "n_estimators_reg": 120,
            "n_estimators_cls": 220,
            "max_depth": 8,
            "min_samples_leaf": 16,
            "max_features": "sqrt",
            "calibration": "sigmoid",
        },
    ]


def lstm_groups(base_epochs: int, base_patience: int, max_sequences: int) -> list[dict[str, Any]]:
    return [
        {
            "group": "lstm_production",
            "window": 30,
            "hidden": 64,
            "head": 32,
            "layers": 1,
            "dropout": 0.35,
            "lr": 0.0005,
            "weight_decay": 0.0015,
            "batch_size": 128,
            "epochs": base_epochs,
            "patience": base_patience,
            "max_sequences": max_sequences,
        },
        {
            "group": "lstm_short_window",
            "window": 20,
            "hidden": 64,
            "head": 32,
            "layers": 1,
            "dropout": 0.25,
            "lr": 0.0007,
            "weight_decay": 0.001,
            "batch_size": 128,
            "epochs": base_epochs,
            "patience": base_patience,
            "max_sequences": max_sequences,
        },
        {
            "group": "lstm_wider",
            "window": 30,
            "hidden": 96,
            "head": 48,
            "layers": 1,
            "dropout": 0.30,
            "lr": 0.00045,
            "weight_decay": 0.002,
            "batch_size": 128,
            "epochs": base_epochs,
            "patience": base_patience,
            "max_sequences": max_sequences,
        },
        {
            "group": "lstm_longer_context",
            "window": 45,
            "hidden": 64,
            "head": 32,
            "layers": 1,
            "dropout": 0.35,
            "lr": 0.00045,
            "weight_decay": 0.002,
            "batch_size": 128,
            "epochs": base_epochs,
            "patience": base_patience,
            "max_sequences": max_sequences,
        },
    ]


def metric_row(group: dict[str, Any], model_name: str, metrics: dict[str, float], seconds: float, error: str = "") -> dict[str, Any]:
    prefix = model_name
    direction_accuracy = metrics.get(f"{prefix}_direction_accuracy")
    majority_baseline = metrics.get(f"{prefix}_majority_baseline_accuracy")
    direction_lift = metrics.get(f"{prefix}_direction_lift_over_baseline")
    wf_accuracy = metrics.get(f"{prefix}_walk_forward_direction_accuracy")
    wf_baseline = metrics.get(f"{prefix}_walk_forward_majority_baseline_accuracy")
    wf_lift = metrics.get(f"{prefix}_walk_forward_direction_lift_over_baseline")
    guarded_accuracy = metrics.get(f"{prefix}_guarded_direction_accuracy")
    guarded_lift = metrics.get(f"{prefix}_guarded_direction_lift_over_baseline")
    guarded_used_baseline = metrics.get(f"{prefix}_guarded_used_majority_baseline")
    wf_guarded_accuracy = metrics.get(f"{prefix}_walk_forward_guarded_direction_accuracy")
    wf_guarded_lift = metrics.get(f"{prefix}_walk_forward_guarded_direction_lift_over_baseline")
    wf_guarded_used_baseline = metrics.get(f"{prefix}_walk_forward_guarded_used_majority_baseline")
    calibration_lift = metrics.get(f"{prefix}_calibration_lift_over_baseline")
    primary_pass = direction_lift is not None and float(direction_lift) >= 0
    walk_forward_pass = wf_lift is not None and float(wf_lift) >= 0
    operational_primary_pass = guarded_lift is not None and float(guarded_lift) >= 0
    operational_walk_forward_pass = wf_guarded_lift is not None and float(wf_guarded_lift) >= 0
    passes_baseline = primary_pass and walk_forward_pass and not error
    operational_passes_baseline = operational_primary_pass and operational_walk_forward_pass and not error
    row = {
        "model": model_name,
        "group": group["group"],
        "seconds": round(seconds, 2),
        "error": error,
        "passes_baseline": passes_baseline,
        "primary_passes_baseline": primary_pass,
        "walk_forward_passes_baseline": walk_forward_pass,
        "operational_passes_baseline": operational_passes_baseline,
        "direction_accuracy": direction_accuracy,
        "balanced_direction_accuracy": metrics.get(f"{prefix}_balanced_direction_accuracy"),
        "direction_macro_f1": metrics.get(f"{prefix}_direction_macro_f1"),
        "majority_baseline_accuracy": majority_baseline,
        "direction_lift_over_baseline": direction_lift,
        "guarded_direction_accuracy": guarded_accuracy,
        "guarded_direction_lift_over_baseline": guarded_lift,
        "guarded_used_majority_baseline": guarded_used_baseline,
        "walk_forward_direction_accuracy": wf_accuracy,
        "walk_forward_balanced_direction_accuracy": metrics.get(f"{prefix}_walk_forward_balanced_direction_accuracy"),
        "walk_forward_direction_macro_f1": metrics.get(f"{prefix}_walk_forward_direction_macro_f1"),
        "walk_forward_majority_baseline_accuracy": wf_baseline,
        "walk_forward_direction_lift_over_baseline": wf_lift,
        "walk_forward_guarded_direction_accuracy": wf_guarded_accuracy,
        "walk_forward_guarded_direction_lift_over_baseline": wf_guarded_lift,
        "walk_forward_guarded_used_majority_baseline": wf_guarded_used_baseline,
        "calibration_lift_over_baseline": calibration_lift,
        "return_mae": metrics.get(f"{prefix}_return_mae"),
        "score": score_metrics(metrics, prefix),
    }
    row.update({key: value for key, value in group.items() if key != "group"})
    return row


def score_metrics(metrics: dict[str, float], prefix: str) -> float:
    wf_bal = float(metrics.get(f"{prefix}_walk_forward_balanced_direction_accuracy", metrics.get(f"{prefix}_balanced_direction_accuracy", 0.0)))
    wf_f1 = float(metrics.get(f"{prefix}_walk_forward_direction_macro_f1", metrics.get(f"{prefix}_direction_macro_f1", 0.0)))
    lift = float(metrics.get(f"{prefix}_walk_forward_direction_lift_over_baseline", metrics.get(f"{prefix}_direction_lift_over_baseline", 0.0)))
    direction_lift = float(metrics.get(f"{prefix}_direction_lift_over_baseline", lift))
    calibration_lift = float(metrics.get(f"{prefix}_calibration_lift_over_baseline", 0.0))
    guarded_lift = float(metrics.get(f"{prefix}_guarded_direction_lift_over_baseline", direction_lift))
    wf_guarded_lift = float(metrics.get(f"{prefix}_walk_forward_guarded_direction_lift_over_baseline", lift))
    score = wf_bal * 0.52 + wf_f1 * 0.23 + max(lift, -0.2) * 0.15 + max(direction_lift, -0.2) * 0.07 + max(calibration_lift, 0.0) * 0.03
    score += max(guarded_lift, 0.0) * 0.02 + max(wf_guarded_lift, 0.0) * 0.03
    if lift < 0 or direction_lift < 0:
        score -= min(abs(min(lift, 0.0)) + abs(min(direction_lift, 0.0)), 0.5)
    return score


def run_random_forest_group(dataset: pd.DataFrame, group: dict[str, Any]) -> dict[str, Any]:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

    start = time.perf_counter()
    result = train_tabular_models(
        dataset,
        "random_forest",
        RandomForestRegressor(
            n_estimators=int(group["n_estimators_reg"]),
            max_depth=group["max_depth"],
            min_samples_leaf=int(group["min_samples_leaf"]),
            max_features=group["max_features"],
            random_state=42,
            n_jobs=1,
        ),
        CalibratedClassifierCV(
            estimator=RandomForestClassifier(
                n_estimators=int(group["n_estimators_cls"]),
                max_depth=group["max_depth"],
                min_samples_leaf=int(group["min_samples_leaf"]),
                max_features=group["max_features"],
                random_state=42,
                n_jobs=1,
                class_weight="balanced_subsample",
            ),
            method=group["calibration"],
            cv=3,
        ),
    )
    return metric_row(group, "random_forest", result.metrics, time.perf_counter() - start)


def run_lightgbm_group(dataset: pd.DataFrame, group: dict[str, Any]) -> dict[str, Any]:
    from lightgbm import LGBMClassifier, LGBMRegressor

    common = {
        "n_estimators": group["n_estimators"],
        "learning_rate": group["learning_rate"],
        "num_leaves": group["num_leaves"],
        "min_child_samples": group["min_child_samples"],
        "subsample": group["subsample"],
        "colsample_bytree": group["colsample_bytree"],
        "reg_lambda": group["reg_lambda"],
        "random_state": 42,
        "verbose": -1,
        "verbosity": -1,
        "force_col_wise": True,
        "n_jobs": -1,
    }
    start = time.perf_counter()
    result = train_tabular_models(
        dataset,
        "lightgbm",
        LGBMRegressor(**common),
        LGBMClassifier(**common, class_weight="balanced"),
    )
    return metric_row(group, "lightgbm", result.metrics, time.perf_counter() - start)


def run_lstm_group(dataset: pd.DataFrame, group: dict[str, Any]) -> dict[str, Any]:
    values = {
        "LSTM_WINDOW_SIZE": int(group["window"]),
        "LSTM_HIDDEN_SIZE": int(group["hidden"]),
        "LSTM_HEAD_SIZE": int(group["head"]),
        "LSTM_NUM_LAYERS": int(group["layers"]),
        "LSTM_DROPOUT": float(group["dropout"]),
        "LSTM_LEARNING_RATE": float(group["lr"]),
        "LSTM_WEIGHT_DECAY": float(group["weight_decay"]),
        "LSTM_BATCH_SIZE": int(group["batch_size"]),
        "settings.ml_lstm_window_size": int(group["window"]),
        "settings.ml_lstm_hidden_size": int(group["hidden"]),
        "settings.ml_lstm_head_size": int(group["head"]),
        "settings.ml_lstm_num_layers": int(group["layers"]),
        "settings.ml_lstm_dropout": float(group["dropout"]),
        "settings.ml_lstm_learning_rate": float(group["lr"]),
        "settings.ml_lstm_weight_decay": float(group["weight_decay"]),
        "settings.ml_lstm_batch_size": int(group["batch_size"]),
        "settings.ml_lstm_epochs": int(group["epochs"]),
        "settings.ml_lstm_early_stop_patience": int(group["patience"]),
        "settings.ml_lstm_max_sequences": int(group["max_sequences"]),
    }
    start = time.perf_counter()
    with patched_stock_ml(**values):
        result = stock_ml.train_lstm(dataset)
    return metric_row(group, "lstm", result.metrics, time.perf_counter() - start)


def main() -> None:
    args = parse_args()
    selected_models = {item.strip().lower() for item in args.models.split(",") if item.strip()}
    thresholds = parse_float_list(args.direction_thresholds) if args.direction_thresholds else [args.direction_threshold]
    horizons = parse_int_list(args.horizons)

    with stage("load daily bars"):
        ticks = load_price_ticks(source="akshare_cold_start")
        index_ticks = load_price_ticks(source="akshare_index")

    rows: list[dict[str, Any]] = []
    dataset_info_by_target: dict[str, tuple[int, int]] = {}
    for horizon in horizons:
        stock_ml.PREDICTION_HORIZON = horizon
        for threshold in thresholds:
            stock_ml.MIN_DIRECTION_RETURN = threshold
            stock_ml.DIRECTION_FIXED_THRESHOLD = threshold
            target_key = f"h{horizon}_thr{threshold:g}"
            with stage(f"prepare dataset horizon={horizon} threshold={threshold:g}"):
                dataset = prepare_dataset(ticks, index_ticks, direction_threshold=threshold, prediction_horizon=horizon)
                dataset = cap_dataset(dataset, args.max_rows)
                dataset.attrs["prediction_horizon"] = horizon
                dataset.attrs["direction_threshold"] = threshold
            dataset_rows = len(dataset)
            symbols = int(dataset["symbol"].nunique()) if not dataset.empty and "symbol" in dataset.columns else 0
            dataset_info_by_target[target_key] = (dataset_rows, symbols)
            print(f"[tune] horizon={horizon} threshold={threshold:g} dataset rows={dataset_rows}, symbols={symbols}", flush=True)

            def add_context(group: dict[str, Any]) -> dict[str, Any]:
                return {
                    **group,
                    "prediction_horizon": horizon,
                    "direction_threshold": threshold,
                    "dataset_rows": dataset_rows,
                    "symbols": symbols,
                }

            if "random_forest" in selected_models or "rf" in selected_models:
                for group in random_forest_groups():
                    group = add_context(group)
                    try:
                        with stage(f"{group['group']} horizon={horizon} threshold={threshold:g}"):
                            rows.append(run_random_forest_group(dataset, group))
                    except Exception as exc:  # noqa: BLE001
                        rows.append(metric_row(group, "random_forest", {}, 0.0, str(exc)))

            if "lightgbm" in selected_models or "lgbm" in selected_models:
                for group in lgbm_groups():
                    group = add_context(group)
                    try:
                        with stage(f"{group['group']} horizon={horizon} threshold={threshold:g}"):
                            rows.append(run_lightgbm_group(dataset, group))
                    except Exception as exc:  # noqa: BLE001
                        rows.append(metric_row(group, "lightgbm", {}, 0.0, str(exc)))

            if "lstm" in selected_models:
                for group in lstm_groups(args.lstm_epochs, args.lstm_patience, args.lstm_max_sequences):
                    group = add_context(group)
                    try:
                        with stage(f"{group['group']} horizon={horizon} threshold={threshold:g}"):
                            rows.append(run_lstm_group(dataset, group))
                    except Exception as exc:  # noqa: BLE001
                        rows.append(metric_row(group, "lstm", {}, 0.0, str(exc)))

    report = pd.DataFrame(rows).sort_values(["model", "score"], ascending=[True, False])
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    out_path = out_dir / f"daily_param_tuning_{timestamp}.csv"
    report.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"[tune] wrote {out_path}", flush=True)
    summary_path = out_dir / f"daily_param_tuning_best_{timestamp}.md"
    summary_lines = [
        "# Daily ML Parameter Tuning Summary",
        "",
        f"- prediction_horizons: {', '.join(str(item) for item in horizons)}",
        f"- direction_thresholds: {', '.join(str(item) for item in thresholds)}",
        f"- dataset_by_target: {dataset_info_by_target}",
        f"- report_csv: {out_path.name}",
        "",
        "| model | selected_group | horizon | threshold | final_pass | operational_pass | score | direction_acc | baseline | lift | wf_acc | wf_baseline | wf_lift | guarded_used | wf_guarded_used |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    selected_parameter_rows: list[dict[str, Any]] = []

    for model_name, part in report.groupby("model", sort=False):
        baseline_part = part[part["passes_baseline"] == True]  # noqa: E712
        operational_part = part[part["operational_passes_baseline"] == True]  # noqa: E712
        candidate_part = baseline_part if not baseline_part.empty else operational_part if not operational_part.empty else part
        best = candidate_part.dropna(subset=["score"]).sort_values("score", ascending=False).head(1)
        if not best.empty:
            row = best.iloc[0]
            if not bool(row["passes_baseline"]):
                print(f"[tune][warn] no {model_name} raw group beat the baseline on both primary and walk-forward checks", flush=True)
            print(
                f"[tune] best {model_name}: {row['group']} "
                f"passes_baseline={bool(row['passes_baseline'])}, operational_passes_baseline={bool(row['operational_passes_baseline'])}, score={row['score']:.4f}, "
                f"acc={row['direction_accuracy']}, baseline={row['majority_baseline_accuracy']}, "
                f"lift={row['direction_lift_over_baseline']}, wf_lift={row['walk_forward_direction_lift_over_baseline']}",
                flush=True,
            )
            summary_lines.append(
                "| {model} | {group} | {horizon} | {threshold} | {raw_pass} | {op_pass} | {score:.4f} | {acc} | {baseline} | {lift} | {wf_acc} | {wf_base} | {wf_lift} | {guarded_used} | {wf_guarded_used} |".format(
                    model=model_name,
                    group=row["group"],
                    horizon=row.get("prediction_horizon", ""),
                    threshold=row.get("direction_threshold", ""),
                    raw_pass=bool(row["passes_baseline"]),
                    op_pass=bool(row["operational_passes_baseline"]),
                    score=float(row["score"]),
                    acc=row["direction_accuracy"],
                    baseline=row["majority_baseline_accuracy"],
                    lift=row["direction_lift_over_baseline"],
                    wf_acc=row["walk_forward_direction_accuracy"],
                    wf_base=row["walk_forward_majority_baseline_accuracy"],
                    wf_lift=row["walk_forward_direction_lift_over_baseline"],
                    guarded_used=row["guarded_used_majority_baseline"],
                    wf_guarded_used=row["walk_forward_guarded_used_majority_baseline"],
                )
            )
            selected_parameter_rows.append(row.to_dict())
    if selected_parameter_rows:
        summary_lines.extend(["", "## Selected Parameter Settings", ""])
        metric_keys = {
            "model",
            "group",
            "seconds",
            "error",
            "passes_baseline",
            "primary_passes_baseline",
            "walk_forward_passes_baseline",
            "operational_passes_baseline",
            "direction_accuracy",
            "balanced_direction_accuracy",
            "direction_macro_f1",
            "majority_baseline_accuracy",
            "direction_lift_over_baseline",
            "guarded_direction_accuracy",
            "guarded_direction_lift_over_baseline",
            "guarded_used_majority_baseline",
            "walk_forward_direction_accuracy",
            "walk_forward_balanced_direction_accuracy",
            "walk_forward_direction_macro_f1",
            "walk_forward_majority_baseline_accuracy",
            "walk_forward_direction_lift_over_baseline",
            "walk_forward_guarded_direction_accuracy",
            "walk_forward_guarded_direction_lift_over_baseline",
            "walk_forward_guarded_used_majority_baseline",
            "calibration_lift_over_baseline",
            "return_mae",
            "score",
            "dataset_rows",
            "symbols",
        }
        for row in selected_parameter_rows:
            params = {key: value for key, value in row.items() if key not in metric_keys and pd.notna(value) and value != ""}
            summary_lines.append(f"### {row['model']} / {row['group']}")
            summary_lines.append("")
            summary_lines.append("```text")
            for key, value in params.items():
                summary_lines.append(f"{key}={value}")
            summary_lines.append("```")
            summary_lines.append("")
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print(f"[tune] wrote {summary_path}", flush=True)


if __name__ == "__main__":
    main()
