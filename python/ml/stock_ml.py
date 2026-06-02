"""Machine-learning feature engineering, training, prediction and persistence.

The module supports two data granularities:
- daily bars through `python -m python.ml.train_daily_predict`
- real-time/minute ticks through `python -m python.ml.train_predict`

Both paths share the same feature builder and model training functions. The
models predict future return, UP/DOWN/WATCH direction and a reference next
price. Direction and alert quality are more important than exact price points.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Any

import joblib
import numpy as np
import pandas as pd
import pymysql
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.base import clone
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score, mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from python.common.config import settings
from python.common.stock_utils import market_change_limit
from python.ml.daily_bar_store import DAILY_BAR_SELECT_COLUMNS, daily_table_for_source, ensure_daily_bar_tables


RAW_NUMERIC_COLUMNS = ["open_price", "high_price", "low_price", "last_price", "previous_close", "change_pct", "volume", "turnover"]
TRAINING_SOURCE_PRIORITY = ["akshare_cold_start", "sina", "tencent", "eastmoney"]
LSTM_HIDDEN_SIZE = max(16, int(settings.ml_lstm_hidden_size))
LSTM_HEAD_SIZE = max(8, int(settings.ml_lstm_head_size))
LSTM_NUM_LAYERS = max(1, int(settings.ml_lstm_num_layers))
LSTM_DROPOUT = max(0.0, min(0.8, float(settings.ml_lstm_dropout)))
LSTM_RECURRENT_DROPOUT = LSTM_DROPOUT if LSTM_NUM_LAYERS > 1 else 0.0
LSTM_LEARNING_RATE = max(1e-6, float(settings.ml_lstm_learning_rate))
LSTM_WEIGHT_DECAY = max(0.0, float(settings.ml_lstm_weight_decay))
LSTM_BATCH_SIZE = max(16, int(settings.ml_lstm_batch_size))
SEQUENCE_FEATURES = [
    "change_pct_scaled",
    "return_1",
    "return_3",
    "momentum_5",
    "momentum_10",
    "momentum_20",
    "volume_change",
    "turnover_change",
    "ma_5_gap",
    "ma_10_gap",
    "ma_20_gap",
    "volume_ratio",
    "volume_ratio_20_raw",
    "turnover_ratio",
    "volatility_5",
    "volatility_10",
    "volatility_20",
    "max_drawdown_5",
    "max_drawdown_10",
    "max_drawdown_20",
    "high_low_range",
    "price_vs_ma20",
    "relative_sector_change_pct",
    "relative_market_change_pct",
    "current_vs_market_index_return",
    "relative_sh_index_return_1",
    "relative_cyb_index_return_1",
    "sector_relative_change",
    "market_relative_change",
    "sector_avg_change_pct",
    "market_avg_change_pct",
    "sector_momentum_5",
    "market_momentum_5",
    "market_up_ratio",
    "sector_up_ratio",
    "sector_return_1",
    "sector_return_3",
    "sector_momentum_3",
    "sector_relative_return_1",
    "sector_relative_return_3",
    "sector_relative_return_5",
    "sector_relative_return_10",
    "sector_relative_return_20",
    "sector_return_rank_5",
    "sector_return_rank_10",
    "sector_return_rank_20",
    "sector_strength_rank",
    "sector_volatility_5",
    "sector_up_ratio_3",
    "index_sh_return_1",
    "index_sh_return_3",
    "index_sh_volatility_5",
    "index_sh_volatility_10",
    "index_cyb_return_1",
    "index_cyb_return_3",
    "index_cyb_volatility_5",
    "index_cyb_volatility_10",
    "index_hs300_return_1",
    "index_hs300_return_3",
    "index_hs300_volatility_5",
    "index_hs300_volatility_10",
    "market_index_return_1",
    "market_index_return_3",
    "market_index_return_5",
    "market_index_volatility_5",
    "market_index_volatility_10",
    "relative_hs300_return_1",
    "relative_hs300_return_3",
    "relative_hs300_return_5",
    "relative_market_index_return_1",
    "relative_market_index_return_3",
    "relative_market_index_return_5",
    "index_up_3d",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "volume_price_corr",
    "money_flow_ratio",
    "vol_regime",
    "price_position_20",
    "up_streak_3",
    "down_streak_3",
    "volume_spike_20",
    "volume_up_breakout",
    "volume_down_breakout",
    "volume_expansion_streak_3",
    "volume_expansion_streak_5",
    "return_3_x_volume_ratio_20",
    "momentum_5_x_volume_ratio_20",
]
CATEGORICAL_FEATURES = ["symbol", "category", "sector"]
TABULAR_FEATURES = [*CATEGORICAL_FEATURES, *SEQUENCE_FEATURES]
LSTM_WINDOW_SIZE = max(5, int(settings.ml_lstm_window_size))
TIME_SPLIT_RATIO = 0.8
MIN_DIRECTION_RETURN = float(settings.ml_direction_threshold)
PREDICTION_RETURN_SIGNAL_THRESHOLD = max(0.0, float(settings.ml_prediction_return_signal_threshold))
DIRECTION_FIXED_THRESHOLD: float | None = None
PREDICTION_HORIZON = max(1, int(settings.ml_prediction_horizon))
PREDICTION_HORIZON_EXPERIMENTS = [1, 3, 5]
ML_TARGET_MODE = settings.ml_target_mode if settings.ml_target_mode in {"direction", "downside_risk"} else "downside_risk"
RISK_TARGET_ENABLED = ML_TARGET_MODE == "downside_risk"
RISK_DOWNSIDE_THRESHOLD = max(0.0, float(settings.ml_risk_downside_threshold))
RISK_VOLATILITY_THRESHOLD = max(0.0, float(settings.ml_risk_volatility_threshold))
RISK_ALERT_MIN_RETURN = max(0.0, float(settings.ml_risk_alert_min_return))
DOWN_ALERT_RISK_SCORE_THRESHOLD = max(0.0, float(settings.ml_down_alert_risk_score_threshold))
LSTM_AUX_MAX_WEIGHT = min(0.30, max(0.0, float(settings.ml_lstm_aux_max_weight)))
LIGHTGBM_MIN_WEIGHT = min(1.0, max(0.0, float(settings.ml_lightgbm_min_weight)))
DIRECTION_VOLATILITY_WINDOW = 20
DIRECTION_THRESHOLD_MULTIPLIER = 1.0
THRESHOLD_EXPERIMENTS = [0.003, 0.005, 0.01, 0.015, 0.02]
WALK_FORWARD_FOLDS = 3
WALK_FORWARD_INITIAL_TRAIN_RATIO = 0.5
WALK_FORWARD_VALIDATION_RATIO = 0.1
DIRECTION_DOWN = 0
DIRECTION_UP = 1
DIRECTION_FLAT = 2
DIRECTION_LABELS = [DIRECTION_DOWN, DIRECTION_UP, DIRECTION_FLAT]
DIRECTION_SIGNAL_MAP = {DIRECTION_UP: "UP", DIRECTION_DOWN: "DOWN", DIRECTION_FLAT: "WATCH"}
TRAINING_PROGRESS_INTERVAL_SECONDS = 30.0
BASELINE_GUARD_LIFT_FLOOR = -0.02
# Production defaults from the latest parameter search.
OPTIMAL_MODEL_CONFIGS: dict[str, dict[str, Any]] = {
    "random_forest": {
        "direction_threshold": 0.015,
        "n_estimators_reg": 80,
        "n_estimators_cls": 120,
        "max_depth": 12,
        "min_samples_leaf": 10,
        "max_features": 0.6,
        "calibration": "sigmoid",
    },
    "lightgbm": {
        "direction_threshold": 0.02,
        "n_estimators": 500,
        "learning_rate": 0.02,
        "num_leaves": 31,
        "min_child_samples": 80,
        "subsample": 0.8,
        "colsample_bytree": 0.85,
        "reg_lambda": 5.0,
    },
    "lstm": {
        "direction_threshold": 0.02,
        "window": 30,
        "hidden": 48,
        "head": 32,
        "layers": 1,
        "dropout": 0.40,
        "lr": 0.0003,
        "weight_decay": 0.002,
        "batch_size": 128,
    },
}
INDEX_FEATURE_COLUMNS = [
    "index_sh_return_1",
    "index_sh_return_3",
    "index_sh_return_5",
    "index_sh_volatility_5",
    "index_sh_volatility_10",
    "index_cyb_return_1",
    "index_cyb_return_3",
    "index_cyb_return_5",
    "index_cyb_volatility_5",
    "index_cyb_volatility_10",
    "index_hs300_return_1",
    "index_hs300_return_3",
    "index_hs300_return_5",
    "index_hs300_volatility_5",
    "index_hs300_volatility_10",
]
INDEX_SYMBOL_FEATURE_PREFIX = {
    "INDEX_SH000001": "index_sh",
    "INDEX_SZ399006": "index_cyb",
    "INDEX_SH000300": "index_hs300",
}
DIRECTION_METRIC_NAMES = {
    DIRECTION_DOWN: "down",
    DIRECTION_UP: "up",
    DIRECTION_FLAT: "watch",
}
DOWN_RISK_EVIDENCE_COLUMNS = [
    "return_1",
    "return_3",
    "momentum_5",
    "volume_ratio_20_raw",
    "volume_down_breakout",
    "relative_market_index_return_3",
    "relative_market_index_return_5",
    "sector_relative_return_5",
    "current_vs_market_index_return",
]


def direction_eval_metrics(prefix: str, y_true: np.ndarray | pd.Series, y_pred: np.ndarray | pd.Series) -> dict[str, float]:
    """Report direction quality beyond raw accuracy, which can be misleading on one-class samples."""
    true_values = np.asarray(y_true, dtype=int)
    pred_values = np.asarray(y_pred, dtype=int)
    if true_values.size == 0:
        return {
            f"{prefix}_direction_accuracy": 0.0,
            f"{prefix}_balanced_direction_accuracy": 0.0,
            f"{prefix}_direction_macro_f1": 0.0,
            f"{prefix}_majority_baseline_accuracy": 0.0,
            f"{prefix}_validation_samples": 0.0,
        }
    counts = np.bincount(true_values, minlength=len(DIRECTION_LABELS))
    pred_counts = np.bincount(pred_values, minlength=len(DIRECTION_LABELS))
    total = float(true_values.size)
    direction_accuracy = float(accuracy_score(true_values, pred_values))
    majority_baseline = float(counts.max() / total)
    metrics = {
        f"{prefix}_direction_accuracy": direction_accuracy,
        f"{prefix}_balanced_direction_accuracy": float(balanced_accuracy_score(true_values, pred_values)),
        f"{prefix}_direction_macro_f1": float(f1_score(true_values, pred_values, labels=DIRECTION_LABELS, average="macro", zero_division=0)),
        f"{prefix}_majority_baseline_accuracy": majority_baseline,
        f"{prefix}_direction_lift_over_baseline": direction_accuracy - majority_baseline,
        f"{prefix}_validation_samples": total,
        f"{prefix}_validation_down_ratio": float(counts[DIRECTION_DOWN] / total),
        f"{prefix}_validation_up_ratio": float(counts[DIRECTION_UP] / total),
        f"{prefix}_validation_flat_ratio": float(counts[DIRECTION_FLAT] / total),
    }
    matrix = confusion_matrix(true_values, pred_values, labels=DIRECTION_LABELS)
    for label_index, label in enumerate(DIRECTION_LABELS):
        name = DIRECTION_METRIC_NAMES[label]
        true_positive = float(matrix[label_index, label_index])
        actual_total = float(matrix[label_index, :].sum())
        predicted_total = float(matrix[:, label_index].sum())
        metrics[f"{prefix}_{name}_recall"] = true_positive / actual_total if actual_total else 0.0
        metrics[f"{prefix}_{name}_precision"] = true_positive / predicted_total if predicted_total else 0.0
        metrics[f"{prefix}_predicted_{name}_ratio"] = float(pred_counts[label] / total)
    metrics[f"{prefix}_risk_recall"] = metrics[f"{prefix}_down_recall"]
    metrics[f"{prefix}_risk_precision"] = metrics[f"{prefix}_down_precision"]
    metrics[f"{prefix}_predicted_risk_ratio"] = metrics[f"{prefix}_predicted_down_ratio"]
    return metrics


def numeric_series(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(default)


def clean_price_frame(df: pd.DataFrame, context: str = "training") -> pd.DataFrame:
    """Clean quote/daily-bar rows before feature engineering.

    Storage keeps market snapshots for display, but model training needs a
    stricter OHLC-consistent view. The report is attached to ``attrs`` so the
    training script can persist quality metrics with the model version.
    """
    if df.empty:
        result = df.copy()
        result.attrs["quality_report"] = {"input_rows": 0.0, "output_rows": 0.0, "dropped_rows": 0.0}
        return result

    frame = df.copy()
    input_rows = len(frame)
    for text_column, default in (("symbol", ""), ("company_name", ""), ("category", "Unknown"), ("sector", "Other"), ("market", "UNKNOWN"), ("source", "")):
        if text_column not in frame.columns:
            frame[text_column] = default
        frame[text_column] = frame[text_column].fillna(default).astype(str).str.strip()
    frame["symbol"] = frame["symbol"].str.upper()
    frame["company_name"] = frame["company_name"].where(frame["company_name"] != "", frame["symbol"])
    frame["category"] = frame["category"].where(frame["category"] != "", "Unknown")
    frame["sector"] = frame["sector"].where(frame["sector"] != "", "Other")
    frame["market"] = frame["market"].str.upper().where(frame["market"] != "", "UNKNOWN")
    if "event_time" not in frame.columns:
        frame["event_time"] = pd.NaT
    frame["event_time"] = pd.to_datetime(frame["event_time"], errors="coerce")

    for column in RAW_NUMERIC_COLUMNS:
        if column not in frame.columns:
            frame[column] = 0.0
        frame[column] = pd.to_numeric(frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan)

    invalid_time = frame["event_time"].isna()
    invalid_identity = frame["symbol"].eq("")
    invalid_price = (
        frame[["open_price", "high_price", "low_price", "last_price", "previous_close"]].isna().any(axis=1)
        | (frame[["open_price", "high_price", "low_price", "last_price", "previous_close"]] <= 0).any(axis=1)
    )
    invalid_volume = frame["volume"].isna() | (frame["volume"] <= 0)
    invalid_ohlc = (
        (frame["high_price"] < frame["low_price"])
        | (frame["open_price"] > frame["high_price"])
        | (frame["open_price"] < frame["low_price"])
        | (frame["last_price"] > frame["high_price"])
        | (frame["last_price"] < frame["low_price"])
    )
    limits = frame.apply(lambda row: market_change_limit(str(row["symbol"]), str(row["market"])), axis=1)
    limits = pd.to_numeric(limits, errors="coerce")
    invalid_change = limits.isna() | frame["change_pct"].isna() | (frame["change_pct"].abs() >= limits)

    valid_mask = ~(invalid_time | invalid_identity | invalid_price | invalid_volume | invalid_ohlc | invalid_change)
    cleaned = frame[valid_mask].sort_values(["symbol", "event_time"]).copy()
    before_dedup = len(cleaned)
    cleaned = cleaned.drop_duplicates(["symbol", "event_time", "source"], keep="last").copy()
    report = {
        "input_rows": float(input_rows),
        "output_rows": float(len(cleaned)),
        "dropped_rows": float(input_rows - len(cleaned)),
        "invalid_time_rows": float(invalid_time.sum()),
        "invalid_identity_rows": float(invalid_identity.sum()),
        "invalid_price_rows": float(invalid_price.sum()),
        "invalid_volume_rows": float(invalid_volume.sum()),
        "invalid_ohlc_rows": float(invalid_ohlc.sum()),
        "invalid_change_rows": float(invalid_change.sum()),
        "duplicate_rows": float(before_dedup - len(cleaned)),
    }
    cleaned.attrs["quality_report"] = report
    if report["dropped_rows"] > 0:
        print(
            "[ml] data quality "
            f"{context}: rows {input_rows} -> {len(cleaned)}, "
            f"drop={int(report['dropped_rows'])}, "
            f"ohlc={int(report['invalid_ohlc_rows'])}, "
            f"volume={int(report['invalid_volume_rows'])}, "
            f"change={int(report['invalid_change_rows'])}, "
            f"dup={int(report['duplicate_rows'])}",
            flush=True,
        )
    return cleaned


def downside_risk_score(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Score whether a DOWN model signal has real weak-price evidence behind it."""
    if frame.empty:
        empty = pd.Series(dtype=float, index=frame.index)
        return empty, pd.Series(dtype=int, index=frame.index)

    prob_down = numeric_series(frame, "prob_down")
    prob_flat = numeric_series(frame, "prob_flat")
    return_1 = numeric_series(frame, "return_1")
    return_3 = numeric_series(frame, "return_3")
    momentum_5 = numeric_series(frame, "momentum_5")
    volume_ratio = numeric_series(frame, "volume_ratio_20_raw", 1.0)
    volume_down_breakout = numeric_series(frame, "volume_down_breakout")
    relative_market_3 = numeric_series(frame, "relative_market_index_return_3")
    relative_market_5 = numeric_series(frame, "relative_market_index_return_5")
    relative_sector_5 = numeric_series(frame, "sector_relative_return_5")
    current_vs_market = numeric_series(frame, "current_vs_market_index_return")

    probability_score = prob_down.clip(0, 1)
    margin_score = (prob_down - prob_flat).clip(lower=0, upper=1)
    recent_weakness = pd.concat(
        [
            (-return_1 / 0.015).clip(lower=0, upper=1),
            (-return_3 / 0.030).clip(lower=0, upper=1),
            (-momentum_5 / 0.050).clip(lower=0, upper=1),
        ],
        axis=1,
    ).max(axis=1)
    volume_score = pd.concat(
        [
            volume_down_breakout.clip(lower=0, upper=1),
            (((volume_ratio - 1.0) / 1.0).clip(lower=0, upper=1) * (return_1 < 0).astype(float)),
        ],
        axis=1,
    ).max(axis=1)
    relative_weakness = pd.concat(
        [
            (-relative_market_3 / 0.030).clip(lower=0, upper=1),
            (-relative_market_5 / 0.050).clip(lower=0, upper=1),
            (-relative_sector_5 / 0.050).clip(lower=0, upper=1),
            (-current_vs_market / 0.020).clip(lower=0, upper=1),
        ],
        axis=1,
    ).max(axis=1)
    evidence_count = (
        (recent_weakness >= 0.20).astype(int)
        + (volume_score >= 0.25).astype(int)
        + (relative_weakness >= 0.20).astype(int)
    )
    score = (
        probability_score * 0.34
        + margin_score * 0.18
        + recent_weakness * 0.18
        + volume_score * 0.12
        + relative_weakness * 0.18
    ).clip(0, 1)
    return score, evidence_count


def baseline_guarded_direction_metrics(prefix: str, y_true: np.ndarray | pd.Series, y_pred: np.ndarray | pd.Series) -> dict[str, float]:
    """Report an operational baseline guard for cases where a model underperforms.

    The raw model metrics stay untouched. These extra metrics answer a stricter
    operational question: if the model is below the validation majority baseline,
    what is the safe fallback accuracy? The fallback is explicitly marked so it
    cannot be mistaken for genuine model lift.
    """
    true_values = np.asarray(y_true, dtype=int)
    pred_values = np.asarray(y_pred, dtype=int)
    if true_values.size == 0:
        return direction_eval_metrics(f"{prefix}_guarded", true_values, pred_values)
    raw_metrics = direction_eval_metrics(prefix, true_values, pred_values)
    raw_lift = raw_metrics.get(f"{prefix}_direction_lift_over_baseline", -1.0)
    if raw_lift >= BASELINE_GUARD_LIFT_FLOOR:
        guarded_predictions = pred_values
        used_baseline = 0.0
    else:
        counts = np.bincount(true_values, minlength=len(DIRECTION_LABELS))
        guarded_predictions = np.full_like(true_values, int(counts.argmax()))
        used_baseline = 1.0
    guarded = direction_eval_metrics(f"{prefix}_guarded", true_values, guarded_predictions)
    guarded[f"{prefix}_guarded_used_majority_baseline"] = used_baseline
    guarded[f"{prefix}_guarded_raw_lift_over_baseline"] = float(raw_lift)
    return guarded


def validation_baseline_guard(
    prefix: str,
    y_true: np.ndarray | pd.Series,
    y_pred: np.ndarray | pd.Series,
    decision_params: dict[str, Any] | None = None,
) -> tuple[np.ndarray, dict[str, Any], dict[str, float]]:
    """Force final validation decisions to meet the majority-class baseline.

    The raw model predictions are still reported under ``*_raw_*`` metrics. If
    the model is below the validation majority baseline, the deployed decision
    rule becomes an explicit majority-class fallback instead of pretending that
    the weak model is useful.
    """
    true_values = np.asarray(y_true, dtype=int)
    pred_values = np.asarray(y_pred, dtype=int)
    params: dict[str, Any] = dict(decision_params or {"mode": "argmax"})
    if true_values.size == 0:
        return pred_values, params, {}

    raw_metrics = direction_eval_metrics(f"{prefix}_raw", true_values, pred_values)
    comparison_metrics = direction_eval_metrics(prefix, true_values, pred_values)
    raw_lift = float(comparison_metrics.get(f"{prefix}_direction_lift_over_baseline", -1.0))
    raw_down_recall = float(comparison_metrics.get(f"{prefix}_down_recall", 0.0))
    raw_down_precision = float(comparison_metrics.get(f"{prefix}_down_precision", 0.0))
    preserves_risk_signal = RISK_TARGET_ENABLED and raw_down_recall > 0 and raw_down_precision >= 0.10
    if raw_lift >= BASELINE_GUARD_LIFT_FLOOR or preserves_risk_signal:
        final_predictions = pred_values
        guard_used = 0.0
        guard_label = -1
        params.setdefault("validation_guard_used", 0.0)
        if preserves_risk_signal and raw_lift < BASELINE_GUARD_LIFT_FLOOR:
            params.setdefault("validation_guard_reason", "kept_downside_risk_recall")
    else:
        counts = np.bincount(true_values, minlength=len(DIRECTION_LABELS))
        guard_label = int(counts.argmax())
        final_predictions = np.full_like(true_values, guard_label)
        guard_used = 1.0
        params = {
            "mode": "majority_class",
            "label": guard_label,
            "fallback_reason": "validation_accuracy_below_guard_floor",
            "fallback_from_mode": str(params.get("mode", "argmax")),
            "validation_guard_used": 1.0,
        }

    final_metrics = direction_eval_metrics(prefix, true_values, final_predictions)
    guarded_metrics = direction_eval_metrics(f"{prefix}_guarded", true_values, final_predictions)
    guard_metrics = {
        **raw_metrics,
        **guarded_metrics,
        f"{prefix}_validation_guard_used": guard_used,
        f"{prefix}_validation_guard_label": float(guard_label),
        f"{prefix}_validation_guard_raw_lift_over_baseline": raw_lift,
        f"{prefix}_guarded_used_majority_baseline": guard_used,
        f"{prefix}_guarded_raw_lift_over_baseline": raw_lift,
    }
    params["validation_guard_accuracy"] = float(final_metrics.get(f"{prefix}_direction_accuracy", 0.0))
    params["validation_guard_majority_baseline"] = float(final_metrics.get(f"{prefix}_majority_baseline_accuracy", 0.0))
    params["validation_guard_lift_over_baseline"] = float(final_metrics.get(f"{prefix}_direction_lift_over_baseline", 0.0))
    return final_predictions, params, guard_metrics


def alert_backtest_metrics(
    prefix: str,
    next_return: np.ndarray | pd.Series,
    predicted_direction: np.ndarray | pd.Series,
    confidence: np.ndarray | pd.Series | None = None,
    predicted_return: np.ndarray | pd.Series | None = None,
    movement_threshold: float | None = None,
    evidence_frame: pd.DataFrame | None = None,
) -> dict[str, float]:
    """Evaluate UP/DOWN alerts as trading signals after the production gates."""
    returns = pd.to_numeric(pd.Series(next_return), errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0).to_numpy(dtype=float)
    predictions = np.asarray(predicted_direction, dtype=int)
    if returns.size == 0 or predictions.size == 0:
        return {
            f"{prefix}_alert_backtest_samples": 0.0,
            f"{prefix}_alert_backtest_coverage": 0.0,
            f"{prefix}_alert_backtest_hit_rate": 0.0,
        }
    if confidence is None:
        confidence_values = np.ones_like(returns, dtype=float)
    else:
        confidence_values = (
            pd.to_numeric(pd.Series(confidence), errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0)
            .to_numpy(dtype=float)
        )
    if predicted_return is None:
        predicted_return_values = np.full_like(returns, np.nan, dtype=float)
    else:
        predicted_return_values = (
            pd.to_numeric(pd.Series(predicted_return), errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .to_numpy(dtype=float)
        )
    usable_size = min(returns.size, predictions.size, confidence_values.size, predicted_return_values.size)
    returns = returns[:usable_size]
    predictions = predictions[:usable_size]
    confidence_values = confidence_values[:usable_size]
    predicted_return_values = predicted_return_values[:usable_size]

    up_confidence_threshold = float(settings.ml_alert_up_confidence_threshold)
    down_confidence_threshold = float(settings.ml_alert_down_confidence_threshold)
    if RISK_TARGET_ENABLED:
        down_confidence_threshold = min(down_confidence_threshold, 0.68)
    movement_threshold = float(
        movement_threshold if movement_threshold is not None else DIRECTION_FIXED_THRESHOLD if DIRECTION_FIXED_THRESHOLD is not None else MIN_DIRECTION_RETURN
    )
    raw_alert_mask = np.isin(predictions, [DIRECTION_UP, DIRECTION_DOWN])
    down_return_floor = -RISK_ALERT_MIN_RETURN if RISK_TARGET_ENABLED else -movement_threshold
    weak_down_return = (predictions == DIRECTION_DOWN) & np.isfinite(predicted_return_values) & (predicted_return_values > down_return_floor)
    weak_down_evidence = np.zeros_like(weak_down_return, dtype=bool)
    down_score_values = np.zeros_like(returns, dtype=float)
    evidence_count_values = np.zeros_like(returns, dtype=float)
    if RISK_TARGET_ENABLED and evidence_frame is not None and not evidence_frame.empty:
        evidence = evidence_frame.iloc[:usable_size].copy()
        if "prob_down" not in evidence.columns:
            evidence["prob_down"] = 0.0
        if "prob_flat" not in evidence.columns:
            evidence["prob_flat"] = 0.0
        score, evidence_count = downside_risk_score(evidence)
        down_score_values = score.to_numpy(dtype=float)[:usable_size]
        evidence_count_values = evidence_count.to_numpy(dtype=float)[:usable_size]
        weak_down_evidence = (predictions == DIRECTION_DOWN) & (
            (down_score_values < DOWN_ALERT_RISK_SCORE_THRESHOLD) | (evidence_count_values < 1)
        )
    filtered_mask = ((predictions == DIRECTION_UP) & (confidence_values < up_confidence_threshold)) | (
        (predictions == DIRECTION_DOWN) & (confidence_values < down_confidence_threshold)
    ) | weak_down_return | weak_down_evidence
    final_predictions = predictions.copy()
    final_predictions[filtered_mask] = DIRECTION_FLAT

    up_mask = final_predictions == DIRECTION_UP
    down_mask = final_predictions == DIRECTION_DOWN
    alert_mask = up_mask | down_mask
    up_hit = up_mask & (returns > movement_threshold)
    down_hit = down_mask & (returns < -movement_threshold)
    alert_hits = up_hit | down_hit
    total = float(usable_size)
    alert_count = float(alert_mask.sum())
    up_count = float(up_mask.sum())
    down_count = float(down_mask.sum())

    metrics = {
        f"{prefix}_alert_backtest_samples": total,
        f"{prefix}_alert_confidence_threshold": up_confidence_threshold,
        f"{prefix}_alert_up_confidence_threshold": up_confidence_threshold,
        f"{prefix}_alert_down_confidence_threshold": down_confidence_threshold,
        f"{prefix}_alert_backtest_movement_threshold": movement_threshold,
        f"{prefix}_alert_down_risk_score_threshold": DOWN_ALERT_RISK_SCORE_THRESHOLD if RISK_TARGET_ENABLED else 0.0,
        f"{prefix}_alert_backtest_raw_coverage": float(raw_alert_mask.mean()),
        f"{prefix}_alert_backtest_coverage": float(alert_mask.mean()),
        f"{prefix}_alert_backtest_filtered_ratio": float(filtered_mask.mean()),
        f"{prefix}_alert_backtest_weak_down_evidence_ratio": float(weak_down_evidence.mean()) if usable_size else 0.0,
        f"{prefix}_alert_backtest_watch_ratio": float((final_predictions == DIRECTION_FLAT).mean()),
        f"{prefix}_alert_backtest_hit_rate": float(alert_hits.sum() / alert_count) if alert_count else 0.0,
        f"{prefix}_alert_backtest_up_count": up_count,
        f"{prefix}_alert_backtest_down_count": down_count,
        f"{prefix}_alert_backtest_up_hit_rate": float(up_hit.sum() / up_count) if up_count else 0.0,
        f"{prefix}_alert_backtest_down_hit_rate": float(down_hit.sum() / down_count) if down_count else 0.0,
        f"{prefix}_alert_backtest_avg_confidence": float(confidence_values[alert_mask].mean()) if alert_count else 0.0,
        f"{prefix}_alert_backtest_down_avg_risk_score": float(down_score_values[down_mask].mean()) if down_count else 0.0,
        f"{prefix}_alert_backtest_up_avg_return": float(returns[up_mask].mean()) if up_count else 0.0,
        f"{prefix}_alert_backtest_down_avg_return": float(returns[down_mask].mean()) if down_count else 0.0,
        f"{prefix}_alert_backtest_down_avg_inverse_return": float((-returns[down_mask]).mean()) if down_count else 0.0,
    }
    return metrics


def direction_class_weights(labels: np.ndarray | pd.Series) -> np.ndarray:
    """Inverse-frequency class weights for DOWN / UP / WATCH labels."""
    values = np.asarray(labels, dtype=int)
    counts = np.bincount(values, minlength=len(DIRECTION_LABELS)).astype(float)
    total = counts.sum()
    weights = np.ones(len(DIRECTION_LABELS), dtype=float)
    for index, count in enumerate(counts):
        if count > 0:
            weights[index] = total / (len(DIRECTION_LABELS) * count)
    present = counts > 0
    if present.any():
        weights[present] = weights[present] / weights[present].mean()
    if RISK_TARGET_ENABLED and counts[DIRECTION_DOWN] > 0:
        weights[DIRECTION_DOWN] *= 1.35
    return weights


def direction_sample_weights(labels: np.ndarray | pd.Series) -> np.ndarray:
    values = np.asarray(labels, dtype=int)
    weights = direction_class_weights(values)
    return weights[np.clip(values, 0, len(weights) - 1)]


class PriceLstmModel(nn.Module):
    """PyTorch LSTM regression model for next-price prediction."""

    def __init__(self, feature_size: int) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=feature_size,
            hidden_size=LSTM_HIDDEN_SIZE,
            num_layers=LSTM_NUM_LAYERS,
            batch_first=True,
            dropout=LSTM_RECURRENT_DROPOUT,
        )
        self.head = nn.Sequential(
            nn.Linear(LSTM_HIDDEN_SIZE, LSTM_HEAD_SIZE),
            nn.ReLU(),
            nn.Dropout(LSTM_DROPOUT),
            nn.Linear(LSTM_HEAD_SIZE, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.head(out[:, -1, :]).squeeze(1)


class DirectionLstmModel(nn.Module):
    """PyTorch LSTM multi-class classifier for UP / DOWN / FLAT prediction."""

    def __init__(self, feature_size: int) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=feature_size,
            hidden_size=LSTM_HIDDEN_SIZE,
            num_layers=LSTM_NUM_LAYERS,
            batch_first=True,
            dropout=LSTM_RECURRENT_DROPOUT,
        )
        self.head = nn.Sequential(
            nn.Linear(LSTM_HIDDEN_SIZE, LSTM_HEAD_SIZE),
            nn.ReLU(),
            nn.Dropout(LSTM_DROPOUT),
            nn.Linear(LSTM_HEAD_SIZE, len(DIRECTION_LABELS)),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.head(out[:, -1, :])


@dataclass
class ModelResult:
    name: str
    model_type: str
    price_model: Any
    direction_model: Any
    metrics: dict[str, float]
    extra: dict[str, Any] | None = None


def model_dir() -> Path:
    """Internal ML pipeline helper."""
    path = Path(__file__).resolve().parents[1] / settings.ml_model_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def training_cutoff_time() -> pd.Timestamp | None:
    """Return the earliest event_time used for ML training, or None for full history."""
    lookback_days = int(settings.ml_training_lookback_days)
    if lookback_days <= 0:
        return None
    return pd.Timestamp.now().normalize() - pd.Timedelta(days=lookback_days)


def load_price_ticks(source: str | None = None) -> pd.DataFrame:
    """Read quote rows from MySQL. AKShare daily sources use dedicated daily bar tables."""
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cursor:
            ensure_daily_bar_tables(cursor)

        daily_table = daily_table_for_source(source)
        cutoff_time = training_cutoff_time()
        if daily_table is not None:
            select_columns = ", ".join(DAILY_BAR_SELECT_COLUMNS)
            date_filter = "AND event_time >= %s" if cutoff_time is not None else ""
            daily_params = (source, cutoff_time.to_pydatetime()) if cutoff_time is not None else (source,)
            df = pd.read_sql(
                f"""
                SELECT {select_columns}
                FROM {daily_table}
                WHERE source = %s
                {date_filter}
                ORDER BY event_time ASC
                """,
                conn,
                params=daily_params,
            )
            if not df.empty:
                return df
            print(f"[ml] {daily_table} is empty; fallback to price_ticks source={source}", flush=True)

        where_clause = "WHERE source = %s" if source else "WHERE (source IS NULL OR source NOT LIKE 'replay%')"
        params = [source] if source else []
        if cutoff_time is not None:
            where_clause += " AND event_time >= %s"
            params.append(cutoff_time.to_pydatetime())
        df = pd.read_sql(
            f"""
            SELECT symbol, company_name, category, sector, market, open_price, high_price, low_price,
                   last_price, previous_close, change_pct, volume, turnover, event_time, source
            FROM price_ticks
            {where_clause}
            ORDER BY event_time ASC
            """,
            conn,
            params=tuple(params) if params else None,
        )
    finally:
        conn.close()
    return df


def build_index_feature_frame(index_df: pd.DataFrame | None) -> pd.DataFrame:
    """Build same-day broad-market index return features keyed by trade date."""
    if index_df is None or index_df.empty:
        return pd.DataFrame(columns=["trade_date", *INDEX_FEATURE_COLUMNS])
    frame = index_df.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame = frame[frame["symbol"].isin(INDEX_SYMBOL_FEATURE_PREFIX)].copy()
    if frame.empty:
        return pd.DataFrame(columns=["trade_date", *INDEX_FEATURE_COLUMNS])
    frame["event_time"] = pd.to_datetime(frame["event_time"], errors="coerce")
    frame = frame.dropna(subset=["event_time"]).sort_values(["symbol", "event_time"]).copy()
    frame["last_price"] = pd.to_numeric(frame["last_price"], errors="coerce").fillna(0)
    frame["trade_date"] = frame["event_time"].dt.strftime("%Y-%m-%d")
    grouped = frame.groupby("symbol", group_keys=False)
    frame["index_return_1"] = grouped["last_price"].pct_change().replace([np.inf, -np.inf], 0).fillna(0)
    frame["index_return_3"] = grouped["last_price"].pct_change(3).replace([np.inf, -np.inf], 0).fillna(0)
    frame["index_return_5"] = grouped["last_price"].pct_change(5).replace([np.inf, -np.inf], 0).fillna(0)
    frame["index_volatility_5"] = grouped["index_return_1"].transform(lambda item: item.rolling(5, min_periods=2).std()).fillna(0)
    frame["index_volatility_10"] = grouped["index_return_1"].transform(lambda item: item.rolling(10, min_periods=3).std()).fillna(0)
    parts: list[pd.DataFrame] = []
    for symbol, prefix in INDEX_SYMBOL_FEATURE_PREFIX.items():
        selected = frame[frame["symbol"] == symbol][
            ["trade_date", "index_return_1", "index_return_3", "index_return_5", "index_volatility_5", "index_volatility_10"]
        ].copy()
        if selected.empty:
            continue
        selected = selected.groupby("trade_date", as_index=False).last()
        selected = selected.rename(
            columns={
                "index_return_1": f"{prefix}_return_1",
                "index_return_3": f"{prefix}_return_3",
                "index_return_5": f"{prefix}_return_5",
                "index_volatility_5": f"{prefix}_volatility_5",
                "index_volatility_10": f"{prefix}_volatility_10",
            }
        )
        parts.append(selected)
    if not parts:
        return pd.DataFrame(columns=["trade_date", *INDEX_FEATURE_COLUMNS])
    result = parts[0]
    for part in parts[1:]:
        result = result.merge(part, on="trade_date", how="outer")
    for column in INDEX_FEATURE_COLUMNS:
        if column not in result.columns:
            result[column] = 0.0
    return result[["trade_date", *INDEX_FEATURE_COLUMNS]].sort_values("trade_date")


def merge_index_features(df: pd.DataFrame, index_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Attach external index features without adding index rows as training samples."""
    result = df.copy()
    result["trade_date"] = pd.to_datetime(result["event_time"], errors="coerce").dt.strftime("%Y-%m-%d")
    index_features = build_index_feature_frame(index_df)
    if not index_features.empty:
        result = result.merge(index_features, on="trade_date", how="left")
    for column in INDEX_FEATURE_COLUMNS:
        if column not in result.columns:
            result[column] = 0.0
        result[column] = pd.to_numeric(result[column], errors="coerce").replace([np.inf, -np.inf], 0).fillna(0)
    result = result.drop(columns=["trade_date"])
    return result


def add_technical_features(df: pd.DataFrame, index_df: pd.DataFrame | None = None, *, already_clean: bool = False) -> pd.DataFrame:
    """Add trend features used by the LSTM branch."""
    cleaned_df = df.copy() if already_clean else clean_price_frame(df, context="feature_engineering")
    quality_report = dict(cleaned_df.attrs.get("quality_report", {}))
    sorted_df = cleaned_df.sort_values(["symbol", "event_time"]).copy()
    for price_column in ("open_price", "high_price", "low_price"):
        if price_column not in sorted_df.columns:
            sorted_df[price_column] = sorted_df.get("last_price", 0)
    for column in RAW_NUMERIC_COLUMNS:
        sorted_df[column] = pd.to_numeric(sorted_df[column], errors="coerce").fillna(0)
    grouped = sorted_df.groupby("symbol", group_keys=False)
    sorted_df["change_pct_scaled"] = sorted_df["change_pct"] / 100.0
    sorted_df["return_1"] = grouped["last_price"].pct_change().replace([np.inf, -np.inf], 0).fillna(0)
    sorted_df["return_3"] = grouped["last_price"].pct_change(3).replace([np.inf, -np.inf], 0).fillna(0)
    sorted_df["momentum_5"] = grouped["last_price"].pct_change(5).replace([np.inf, -np.inf], 0).fillna(0)
    sorted_df["momentum_10"] = grouped["last_price"].pct_change(10).replace([np.inf, -np.inf], 0).fillna(0)
    sorted_df["momentum_20"] = grouped["last_price"].pct_change(20).replace([np.inf, -np.inf], 0).fillna(0)
    sorted_df["volume_change"] = grouped["volume"].pct_change().replace([np.inf, -np.inf], 0).fillna(0)
    sorted_df["turnover_change"] = grouped["turnover"].pct_change().replace([np.inf, -np.inf], 0).fillna(0)
    ma_5 = grouped["last_price"].transform(lambda item: item.rolling(5, min_periods=1).mean())
    ma_10 = grouped["last_price"].transform(lambda item: item.rolling(10, min_periods=1).mean())
    ma_20 = grouped["last_price"].transform(lambda item: item.rolling(20, min_periods=1).mean())
    sorted_df["ma_5_gap"] = np.where(ma_5.abs() > 1e-8, (sorted_df["last_price"] - ma_5) / ma_5, 0)
    sorted_df["ma_10_gap"] = np.where(ma_10.abs() > 1e-8, (sorted_df["last_price"] - ma_10) / ma_10, 0)
    sorted_df["ma_20_gap"] = np.where(ma_20.abs() > 1e-8, (sorted_df["last_price"] - ma_20) / ma_20, 0)
    sorted_df["price_vs_ma20"] = sorted_df["ma_20_gap"]
    volume_ma20 = grouped["volume"].transform(lambda item: item.rolling(20, min_periods=5).mean())
    turnover_ma20 = grouped["turnover"].transform(lambda item: item.rolling(20, min_periods=5).mean())
    sorted_df["volume_ratio_20_raw"] = np.where(volume_ma20.abs() > 1e-8, sorted_df["volume"] / volume_ma20, 1)
    sorted_df["volume_ratio"] = sorted_df["volume_ratio_20_raw"] - 1
    sorted_df["turnover_ratio"] = np.where(turnover_ma20.abs() > 1e-8, sorted_df["turnover"] / turnover_ma20 - 1, 0)
    sorted_df["volatility_5"] = grouped["return_1"].transform(lambda item: item.rolling(5, min_periods=2).std()).fillna(0)
    sorted_df["volatility_10"] = grouped["return_1"].transform(lambda item: item.rolling(10, min_periods=3).std()).fillna(0)
    sorted_df["volatility_20"] = grouped["return_1"].transform(lambda item: item.rolling(20, min_periods=5).std()).fillna(0)
    def rolling_max_drawdown(item: pd.Series, window: int) -> pd.Series:
        return item.rolling(window, min_periods=2).apply(
            lambda values: float(np.min(values / np.maximum.accumulate(values) - 1.0)),
            raw=True,
        )

    sorted_df["max_drawdown_5"] = grouped["last_price"].transform(lambda item: rolling_max_drawdown(item, 5)).fillna(0)
    sorted_df["max_drawdown_10"] = grouped["last_price"].transform(lambda item: rolling_max_drawdown(item, 10)).fillna(0)
    sorted_df["max_drawdown_20"] = grouped["last_price"].transform(lambda item: rolling_max_drawdown(item, 20)).fillna(0)
    sorted_df["high_low_range"] = np.where(
        sorted_df["last_price"].abs() > 1e-8,
        (sorted_df["high_price"] - sorted_df["low_price"]) / sorted_df["last_price"],
        0,
    )
    sector_avg_change = sorted_df.groupby(["sector", "event_time"])["change_pct"].transform("mean")
    sorted_df["sector_avg_change_pct"] = sector_avg_change.fillna(0) / 100.0
    sorted_df["sector_relative_change"] = (sorted_df["change_pct"] - sector_avg_change).fillna(0) / 100.0
    sorted_df["relative_sector_change_pct"] = sorted_df["sector_relative_change"]
    market_avg_change = sorted_df.groupby(["market", "event_time"])["change_pct"].transform("mean")
    sorted_df["market_avg_change_pct"] = market_avg_change.fillna(0) / 100.0
    sorted_df["market_relative_change"] = (sorted_df["change_pct"] - market_avg_change).fillna(0) / 100.0
    sorted_df["relative_market_change_pct"] = sorted_df["market_relative_change"]
    sorted_df["market_up_ratio"] = sorted_df.groupby(["market", "event_time"])["change_pct"].transform(lambda item: (item > 0).mean()).fillna(0.5) - 0.5
    sorted_df["sector_up_ratio"] = sorted_df.groupby(["sector", "event_time"])["change_pct"].transform(lambda item: (item > 0).mean()).fillna(0.5) - 0.5
    sorted_df["sector_return_1"] = sorted_df.groupby(["sector", "event_time"])["return_1"].transform("mean").fillna(0)
    sorted_df["sector_return_3"] = sorted_df.groupby(["sector", "event_time"])["return_3"].transform("mean").fillna(0)
    sorted_df["sector_momentum_3"] = sorted_df["sector_return_3"]
    sorted_df["sector_momentum_5"] = sorted_df.groupby(["sector", "event_time"])["momentum_5"].transform("mean").fillna(0)
    sorted_df["sector_momentum_10"] = sorted_df.groupby(["sector", "event_time"])["momentum_10"].transform("mean").fillna(0)
    sorted_df["sector_momentum_20"] = sorted_df.groupby(["sector", "event_time"])["momentum_20"].transform("mean").fillna(0)
    sorted_df["market_momentum_5"] = sorted_df.groupby(["market", "event_time"])["momentum_5"].transform("mean").fillna(0)
    sorted_df["sector_relative_return_1"] = (sorted_df["return_1"] - sorted_df["sector_return_1"]).fillna(0)
    sorted_df["sector_relative_return_3"] = (sorted_df["return_3"] - sorted_df["sector_return_3"]).fillna(0)
    sorted_df["sector_relative_return_5"] = (sorted_df["momentum_5"] - sorted_df["sector_momentum_5"]).fillna(0)
    sorted_df["sector_relative_return_10"] = (sorted_df["momentum_10"] - sorted_df["sector_momentum_10"]).fillna(0)
    sorted_df["sector_relative_return_20"] = (sorted_df["momentum_20"] - sorted_df["sector_momentum_20"]).fillna(0)
    sorted_df["sector_return_rank_5"] = sorted_df.groupby(["sector", "event_time"])["momentum_5"].rank(pct=True).fillna(0.5) - 0.5
    sorted_df["sector_return_rank_10"] = sorted_df.groupby(["sector", "event_time"])["momentum_10"].rank(pct=True).fillna(0.5) - 0.5
    sorted_df["sector_return_rank_20"] = sorted_df.groupby(["sector", "event_time"])["momentum_20"].rank(pct=True).fillna(0.5) - 0.5
    sector_strength = (
        sorted_df[["sector", "event_time", "sector_return_1"]]
        .drop_duplicates()
        .assign(sector_strength_rank=lambda item: item.groupby("event_time")["sector_return_1"].rank(pct=True) - 0.5)
    )
    sorted_df = sorted_df.merge(sector_strength[["sector", "event_time", "sector_strength_rank"]], on=["sector", "event_time"], how="left")
    sorted_df["sector_volatility_5"] = sorted_df.groupby(["sector", "event_time"])["volatility_5"].transform("mean").fillna(0)
    sorted_df["sector_up_ratio_3"] = sorted_df.groupby(["sector", "event_time"])["return_3"].transform(lambda item: (item > 0).mean()).fillna(0.5) - 0.5
    sorted_df = merge_index_features(sorted_df, index_df)
    is_chinext = sorted_df["symbol"].astype(str).str.startswith("300")
    sorted_df["market_index_return_1"] = np.select(
        [sorted_df["market"] == "SH", is_chinext],
        [sorted_df["index_sh_return_1"], sorted_df["index_cyb_return_1"]],
        default=sorted_df["index_hs300_return_1"],
    )
    sorted_df["market_index_return_3"] = np.select(
        [sorted_df["market"] == "SH", is_chinext],
        [sorted_df["index_sh_return_3"], sorted_df["index_cyb_return_3"]],
        default=sorted_df["index_hs300_return_3"],
    )
    sorted_df["market_index_return_5"] = np.select(
        [sorted_df["market"] == "SH", is_chinext],
        [sorted_df["index_sh_return_5"], sorted_df["index_cyb_return_5"]],
        default=sorted_df["index_hs300_return_5"],
    )
    sorted_df["market_index_volatility_5"] = np.select(
        [sorted_df["market"] == "SH", is_chinext],
        [sorted_df["index_sh_volatility_5"], sorted_df["index_cyb_volatility_5"]],
        default=sorted_df["index_hs300_volatility_5"],
    )
    sorted_df["market_index_volatility_10"] = np.select(
        [sorted_df["market"] == "SH", is_chinext],
        [sorted_df["index_sh_volatility_10"], sorted_df["index_cyb_volatility_10"]],
        default=sorted_df["index_hs300_volatility_10"],
    )
    sorted_df["current_vs_market_index_return"] = (sorted_df["change_pct_scaled"] - sorted_df["market_index_return_1"]).fillna(0)
    sorted_df["relative_sh_index_return_1"] = (sorted_df["return_1"] - sorted_df["index_sh_return_1"]).fillna(0)
    sorted_df["relative_cyb_index_return_1"] = (sorted_df["return_1"] - sorted_df["index_cyb_return_1"]).fillna(0)
    sorted_df["relative_hs300_return_1"] = (sorted_df["return_1"] - sorted_df["index_hs300_return_1"]).fillna(0)
    sorted_df["relative_hs300_return_3"] = (sorted_df["return_3"] - sorted_df["index_hs300_return_3"]).fillna(0)
    sorted_df["relative_hs300_return_5"] = (sorted_df["momentum_5"] - sorted_df["index_hs300_return_5"]).fillna(0)
    sorted_df["relative_market_index_return_1"] = (sorted_df["return_1"] - sorted_df["market_index_return_1"]).fillna(0)
    sorted_df["relative_market_index_return_3"] = (sorted_df["return_3"] - sorted_df["market_index_return_3"]).fillna(0)
    sorted_df["relative_market_index_return_5"] = (sorted_df["momentum_5"] - sorted_df["market_index_return_5"]).fillna(0)
    grouped = sorted_df.groupby("symbol", group_keys=False)
    sorted_df["index_up_3d"] = grouped["market_index_return_1"].transform(lambda item: (item.rolling(3, min_periods=1).sum() > 0).astype(float))
    delta = grouped["last_price"].diff().fillna(0)
    gain = delta.clip(lower=0)
    loss = (-delta.clip(upper=0))
    avg_gain = gain.groupby(sorted_df["symbol"]).transform(lambda item: item.rolling(14, min_periods=1).mean())
    avg_loss = loss.groupby(sorted_df["symbol"]).transform(lambda item: item.rolling(14, min_periods=1).mean())
    rs = avg_gain / avg_loss.replace(0, np.nan)
    sorted_df["rsi_14"] = ((100 - (100 / (1 + rs))).fillna(50) - 50) / 50
    ema_12 = grouped["last_price"].transform(lambda item: item.ewm(span=12, adjust=False).mean())
    ema_26 = grouped["last_price"].transform(lambda item: item.ewm(span=26, adjust=False).mean())
    macd_raw = ema_12 - ema_26
    macd_signal_raw = macd_raw.groupby(sorted_df["symbol"]).transform(lambda item: item.ewm(span=9, adjust=False).mean())
    price_base = sorted_df["last_price"].abs().replace(0, np.nan)
    sorted_df["macd"] = (macd_raw / price_base).fillna(0)
    sorted_df["macd_signal"] = (macd_signal_raw / price_base).fillna(0)
    sorted_df["macd_hist"] = ((macd_raw - macd_signal_raw) / price_base).fillna(0)
    money_flow = (sorted_df["last_price"] * sorted_df["volume"]).replace([np.inf, -np.inf], 0).fillna(0)
    money_flow_5 = money_flow.groupby(sorted_df["symbol"]).transform(lambda item: item.rolling(5, min_periods=1).mean())
    money_flow_20 = money_flow.groupby(sorted_df["symbol"]).transform(lambda item: item.rolling(20, min_periods=5).mean())
    sorted_df["money_flow_ratio"] = np.where(money_flow_20.abs() > 1e-8, money_flow_5 / money_flow_20 - 1, 0)
    rolling_min_20 = grouped["last_price"].transform(lambda item: item.rolling(20, min_periods=2).min())
    rolling_max_20 = grouped["last_price"].transform(lambda item: item.rolling(20, min_periods=2).max())
    sorted_df["price_position_20"] = np.where(
        (rolling_max_20 - rolling_min_20).abs() > 1e-8,
        (sorted_df["last_price"] - rolling_min_20) / (rolling_max_20 - rolling_min_20) - 0.5,
        0,
    )
    sorted_df["vol_regime"] = (sorted_df["volatility_5"] > sorted_df["volatility_20"].replace(0, np.nan)).astype(float).fillna(0)
    positive_return = (sorted_df["return_1"] > 0).astype(float)
    negative_return = (sorted_df["return_1"] < 0).astype(float)
    sorted_df["up_streak_3"] = positive_return.groupby(sorted_df["symbol"]).transform(lambda item: item.rolling(3, min_periods=3).sum()).fillna(0) / 3.0
    sorted_df["down_streak_3"] = negative_return.groupby(sorted_df["symbol"]).transform(lambda item: item.rolling(3, min_periods=3).sum()).fillna(0) / 3.0
    sorted_df["volume_spike_20"] = (sorted_df["volume_ratio_20_raw"] >= 2.0).astype(float)
    sorted_df["volume_up_breakout"] = ((sorted_df["return_1"] > 0) & (sorted_df["volume_ratio_20_raw"] >= 1.5)).astype(float)
    sorted_df["volume_down_breakout"] = ((sorted_df["return_1"] < 0) & (sorted_df["volume_ratio_20_raw"] >= 1.5)).astype(float)
    volume_expanding = (sorted_df["volume_ratio_20_raw"] >= 1.2).astype(float)
    sorted_df["volume_expansion_streak_3"] = volume_expanding.groupby(sorted_df["symbol"]).transform(lambda item: item.rolling(3, min_periods=1).sum()) / 3.0
    sorted_df["volume_expansion_streak_5"] = volume_expanding.groupby(sorted_df["symbol"]).transform(lambda item: item.rolling(5, min_periods=1).sum()) / 5.0
    sorted_df["return_3_x_volume_ratio_20"] = sorted_df["return_3"] * sorted_df["volume_ratio_20_raw"]
    sorted_df["momentum_5_x_volume_ratio_20"] = sorted_df["momentum_5"] * sorted_df["volume_ratio_20_raw"]
    sorted_df["volume_price_corr"] = 0.0
    for _, index in sorted_df.groupby("symbol", sort=False).groups.items():
        group = sorted_df.loc[index]
        sorted_df.loc[index, "volume_price_corr"] = group["volume"].rolling(5, min_periods=3).corr(group["last_price"]).fillna(0)
    for column in SEQUENCE_FEATURES:
        sorted_df[column] = pd.to_numeric(sorted_df[column], errors="coerce").replace([np.inf, -np.inf], 0).fillna(0).clip(-5, 5)
    sorted_df.attrs["quality_report"] = quality_report
    return sorted_df


def collapse_repeated_price_ticks(df: pd.DataFrame) -> pd.DataFrame:
    """Remove consecutive unchanged-price ticks before building supervised labels.

    Realtime/replay feeds can emit many rows with the same price. If every repeated
    row is used as a training sample, the validation target becomes almost all
    FLAT/WATCH and raw accuracy is meaningless.
    """
    sorted_df = df.sort_values(["symbol", "event_time"]).copy()
    sorted_df["last_price"] = pd.to_numeric(sorted_df["last_price"], errors="coerce").fillna(0)
    previous_price = sorted_df.groupby("symbol")["last_price"].shift(1)
    keep_first = previous_price.isna()
    price_changed = (sorted_df["last_price"] - previous_price).abs() > 1e-8
    collapsed = sorted_df[keep_first | price_changed].copy()
    if len(collapsed) < len(sorted_df):
        print(f"[ml] collapse repeated price ticks {len(sorted_df)} -> {len(collapsed)}", flush=True)
    return collapsed


def select_training_sources(df: pd.DataFrame) -> pd.DataFrame:
    """Use one coherent price source per symbol to avoid cross-source label noise."""
    if "source" not in df.columns:
        return df
    priority = {source: index for index, source in enumerate(TRAINING_SOURCE_PRIORITY)}
    selected_parts: list[pd.DataFrame] = []
    for symbol, group in df.groupby("symbol", sort=False):
        source_counts = group.groupby("source").size().reset_index(name="count")
        source_counts["priority"] = source_counts["source"].map(priority).fillna(len(priority)).astype(int)
        source_counts = source_counts.sort_values(["priority", "count"], ascending=[True, False])
        selected_source = source_counts.iloc[0]["source"]
        selected = group[group["source"] == selected_source].copy()
        selected_parts.append(selected)
    result = pd.concat(selected_parts, ignore_index=True) if selected_parts else df
    print(f"[ml] selected one training source per symbol {len(df)} -> {len(result)}", flush=True)
    return result


def prepare_dataset(
    df: pd.DataFrame,
    index_df: pd.DataFrame | None = None,
    direction_threshold: float | None = None,
    prediction_horizon: int | None = None,
) -> pd.DataFrame:
    """Build supervised-learning labels from sorted price rows.

    For each symbol, `next_price` is shifted by the selected prediction horizon.
    With daily bars this means T+N trading days. With real-time ticks this
    means the third future stored tick for the same symbol, not necessarily
    exactly three wall-clock minutes.
    """
    horizon = max(1, int(prediction_horizon if prediction_horizon is not None else PREDICTION_HORIZON))
    cleaned_input = clean_price_frame(df, context="training_input")
    sorted_df = add_technical_features(collapse_repeated_price_ticks(select_training_sources(cleaned_input)), index_df, already_clean=True)
    sorted_df.attrs["quality_report"] = dict(cleaned_input.attrs.get("quality_report", {}))
    sorted_df["next_price"] = sorted_df.groupby("symbol")["last_price"].shift(-horizon)
    sorted_df["next_return"] = np.where(
        sorted_df["last_price"].abs() > 1e-8,
        (sorted_df["next_price"] - sorted_df["last_price"]) / sorted_df["last_price"],
        0,
    )
    future_price_frame = pd.concat(
        [sorted_df.groupby("symbol")["last_price"].shift(-step) for step in range(1, horizon + 1)],
        axis=1,
    )
    sorted_df["future_min_price"] = future_price_frame.min(axis=1)
    sorted_df["future_max_price"] = future_price_frame.max(axis=1)
    sorted_df["future_min_return"] = np.where(
        sorted_df["last_price"].abs() > 1e-8,
        (sorted_df["future_min_price"] - sorted_df["last_price"]) / sorted_df["last_price"],
        0,
    )
    sorted_df["future_range_return"] = np.where(
        sorted_df["last_price"].abs() > 1e-8,
        (sorted_df["future_max_price"] - sorted_df["future_min_price"]) / sorted_df["last_price"],
        0,
    )
    adaptive_threshold = sorted_df.groupby("symbol")["return_1"].transform(
        lambda item: item.rolling(DIRECTION_VOLATILITY_WINDOW, min_periods=5).std()
    )
    adaptive_threshold = (adaptive_threshold * DIRECTION_THRESHOLD_MULTIPLIER).replace([np.inf, -np.inf], np.nan)
    fixed_threshold = direction_threshold if direction_threshold is not None else DIRECTION_FIXED_THRESHOLD
    if fixed_threshold is not None:
        sorted_df["direction_threshold"] = float(fixed_threshold)
    else:
        sorted_df["direction_threshold"] = adaptive_threshold.fillna(MIN_DIRECTION_RETURN).clip(lower=MIN_DIRECTION_RETURN)
    if RISK_TARGET_ENABLED:
        risk_threshold = np.maximum(sorted_df["direction_threshold"], RISK_DOWNSIDE_THRESHOLD)
        downside_risk = (
            (sorted_df["next_return"] <= -risk_threshold)
            | (sorted_df["future_min_return"] <= -risk_threshold)
            | (
                (sorted_df["future_range_return"] >= RISK_VOLATILITY_THRESHOLD)
                & (sorted_df["future_min_return"] <= -(risk_threshold * 0.7))
            )
        )
        sorted_df["next_direction"] = np.where(downside_risk, DIRECTION_DOWN, DIRECTION_FLAT)
        sorted_df["target_mode"] = ML_TARGET_MODE
    else:
        sorted_df["next_direction"] = np.select(
            [
                sorted_df["next_return"] > sorted_df["direction_threshold"],
                sorted_df["next_return"] < -sorted_df["direction_threshold"],
            ],
            [DIRECTION_UP, DIRECTION_DOWN],
            default=DIRECTION_FLAT,
        )
        sorted_df["target_mode"] = ML_TARGET_MODE
    sorted_df = sorted_df.dropna(subset=["next_price"])
    sorted_df["next_direction"] = sorted_df["next_direction"].astype(int)
    sorted_df.attrs["direction_threshold"] = float(sorted_df["direction_threshold"].iloc[0]) if not sorted_df.empty else None
    sorted_df.attrs["prediction_horizon"] = horizon
    sorted_df.attrs["target_mode"] = ML_TARGET_MODE
    return sorted_df


def prepare_model_datasets(
    df: pd.DataFrame,
    index_df: pd.DataFrame | None = None,
    model_names: set[str] | None = None,
    prediction_horizon: int | None = None,
) -> dict[str, pd.DataFrame]:
    """Prepare per-model training datasets using the selected best thresholds."""
    datasets: dict[str, pd.DataFrame] = {}
    dataset_by_key: dict[tuple[float, int], pd.DataFrame] = {}
    horizon = max(1, int(prediction_horizon if prediction_horizon is not None else PREDICTION_HORIZON))
    for model_name, config in OPTIMAL_MODEL_CONFIGS.items():
        if model_names is not None and model_name not in model_names:
            continue
        threshold = float(config["direction_threshold"])
        key = (threshold, horizon)
        if key not in dataset_by_key:
            prepared = prepare_dataset(df, index_df, direction_threshold=threshold, prediction_horizon=horizon)
            before_limit = len(prepared)
            limited = limit_training_dataset(prepared)
            limited.attrs["direction_threshold"] = threshold
            limited.attrs["prediction_horizon"] = horizon
            limited.attrs["target_mode"] = prepared.attrs.get("target_mode", ML_TARGET_MODE)
            print(
                f"[ml] prepared target={ML_TARGET_MODE} horizon={horizon} threshold={threshold:g} rows {before_limit} -> {len(limited)}, symbols={limited['symbol'].nunique() if not limited.empty else 0}",
                flush=True,
            )
            dataset_by_key[key] = limited
        datasets[model_name] = dataset_by_key[key]
    return datasets


def threshold_experiment_metrics(dataset: pd.DataFrame) -> list[tuple[str, str, float]]:
    """Report how fixed UP/DOWN/WATCH thresholds reshape labels before training."""
    metrics: list[tuple[str, str, float]] = []
    if dataset.empty or "next_return" not in dataset.columns:
        return metrics
    returns = pd.to_numeric(dataset["next_return"], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if returns.empty:
        return metrics
    for threshold in THRESHOLD_EXPERIMENTS:
        labels = np.select(
            [returns > threshold, returns < -threshold],
            [DIRECTION_UP, DIRECTION_DOWN],
            default=DIRECTION_FLAT,
        )
        counts = np.bincount(labels.astype(int), minlength=len(DIRECTION_LABELS)).astype(float)
        total = float(counts.sum())
        tag = f"{int(round(threshold * 10000)):04d}bp"
        metrics.extend(
            [
                ("threshold_experiment", f"{tag}_threshold", threshold),
                ("threshold_experiment", f"{tag}_down_ratio", counts[DIRECTION_DOWN] / total),
                ("threshold_experiment", f"{tag}_up_ratio", counts[DIRECTION_UP] / total),
                ("threshold_experiment", f"{tag}_watch_ratio", counts[DIRECTION_FLAT] / total),
                ("threshold_experiment", f"{tag}_majority_baseline_accuracy", counts.max() / total),
            ]
        )
    return metrics


def data_quality_metrics(dataset: pd.DataFrame, prefix: str = "training_data") -> list[tuple[str, str, float]]:
    """Expose training data cleaning results as model metrics."""
    report = dataset.attrs.get("quality_report", {}) if hasattr(dataset, "attrs") else {}
    metrics: list[tuple[str, str, float]] = []
    for key in (
        "input_rows",
        "output_rows",
        "dropped_rows",
        "invalid_time_rows",
        "invalid_identity_rows",
        "invalid_price_rows",
        "invalid_volume_rows",
        "invalid_ohlc_rows",
        "invalid_change_rows",
        "duplicate_rows",
    ):
        if key in report:
            metrics.append((prefix, key, float(report[key])))
    if report.get("input_rows"):
        metrics.append((prefix, "drop_ratio", float(report.get("dropped_rows", 0.0)) / float(report["input_rows"])))
    return metrics


def horizon_experiment_metrics(
    df: pd.DataFrame,
    index_df: pd.DataFrame | None,
    direction_threshold: float,
    horizons: list[int] | tuple[int, ...] | None = None,
) -> list[tuple[str, str, float]]:
    """Compare label balance for T+1/T+3/T+5 style daily targets."""
    metrics: list[tuple[str, str, float]] = []
    selected_horizons = horizons or PREDICTION_HORIZON_EXPERIMENTS
    for horizon in selected_horizons:
        horizon_value = max(1, int(horizon))
        dataset = prepare_dataset(df, index_df, direction_threshold=direction_threshold, prediction_horizon=horizon_value)
        if dataset.empty or "next_direction" not in dataset.columns:
            continue
        labels = dataset["next_direction"].astype(int).to_numpy()
        counts = np.bincount(labels, minlength=len(DIRECTION_LABELS)).astype(float)
        total = float(counts.sum())
        tag = f"h{horizon_value}"
        metrics.extend(
            [
                ("horizon_experiment", f"{tag}_prediction_horizon", float(horizon_value)),
                ("horizon_experiment", f"{tag}_samples", total),
                ("horizon_experiment", f"{tag}_symbols", float(dataset["symbol"].nunique() if "symbol" in dataset.columns else 0)),
                ("horizon_experiment", f"{tag}_down_ratio", counts[DIRECTION_DOWN] / total if total else 0.0),
                ("horizon_experiment", f"{tag}_up_ratio", counts[DIRECTION_UP] / total if total else 0.0),
                ("horizon_experiment", f"{tag}_watch_ratio", counts[DIRECTION_FLAT] / total if total else 0.0),
                ("horizon_experiment", f"{tag}_majority_baseline_accuracy", counts.max() / total if total else 0.0),
            ]
        )
    return metrics


def dataset_direction_threshold(dataset: pd.DataFrame, model_name: str | None = None) -> float:
    threshold = dataset.attrs.get("direction_threshold") if hasattr(dataset, "attrs") else None
    if threshold is None and model_name in OPTIMAL_MODEL_CONFIGS:
        threshold = OPTIMAL_MODEL_CONFIGS[model_name]["direction_threshold"]
    if threshold is None:
        threshold = DIRECTION_FIXED_THRESHOLD if DIRECTION_FIXED_THRESHOLD is not None else MIN_DIRECTION_RETURN
    return float(threshold)


def dataset_prediction_horizon(dataset: pd.DataFrame) -> int:
    horizon = dataset.attrs.get("prediction_horizon") if hasattr(dataset, "attrs") else None
    return max(1, int(horizon if horizon is not None else PREDICTION_HORIZON))


def limit_training_dataset(dataset: pd.DataFrame) -> pd.DataFrame:
    """Limit samples for local demo training by taking each symbol's latest time window."""
    max_rows = settings.ml_max_train_rows
    if max_rows <= 0 or len(dataset) <= max_rows:
        return dataset

    symbol_count = max(dataset["symbol"].nunique(), 1)
    rows_per_symbol = max(max_rows // symbol_count, LSTM_WINDOW_SIZE + 2)
    limited_parts: list[pd.DataFrame] = []
    for _, group in dataset.sort_values(["symbol", "event_time"]).groupby("symbol", sort=False):
        limited_parts.append(group.tail(rows_per_symbol))

    limited = pd.concat(limited_parts).sort_values(["symbol", "event_time"]).copy()
    if len(limited) > max_rows:
        limited = limited.sort_values("event_time").tail(max_rows).copy()
    limited.attrs.update(dataset.attrs)
    print(f"[ml] limit training rows {len(dataset)} -> {len(limited)}", flush=True)
    return limited


def tabular_category_values(dataset: pd.DataFrame) -> list[list[str]]:
    """Keep one-hot feature dimensions stable across train/calibration/folds."""
    values: list[list[str]] = []
    for column in CATEGORICAL_FEATURES:
        if column in dataset:
            categories = sorted(dataset[column].fillna("").astype(str).unique().tolist())
        else:
            categories = [""]
        if "" not in categories:
            categories.insert(0, "")
        values.append(categories)
    return values


def build_preprocessor(category_values: list[list[str]] | None = None) -> ColumnTransformer:
    """Internal ML pipeline helper."""
    encoder = OneHotEncoder(handle_unknown="ignore", categories=category_values) if category_values else OneHotEncoder(handle_unknown="ignore")
    return ColumnTransformer(
        transformers=[
            ("cat", encoder, CATEGORICAL_FEATURES),
        ],
        remainder="passthrough",
    )


def time_split_dataframe_by_symbol(dataset: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split every symbol by time so validation never uses older rows than training."""
    train_parts: list[pd.DataFrame] = []
    test_parts: list[pd.DataFrame] = []
    for _, group in dataset.sort_values(["symbol", "event_time"]).groupby("symbol", sort=False):
        if len(group) < 2:
            continue
        split = max(1, min(len(group) - 1, int(len(group) * TIME_SPLIT_RATIO)))
        train_parts.append(group.iloc[:split])
        test_parts.append(group.iloc[split:])

    if not train_parts or not test_parts:
        sorted_dataset = dataset.sort_values(["event_time", "symbol"]).reset_index(drop=True)
        split = max(1, min(len(sorted_dataset) - 1, int(len(sorted_dataset) * TIME_SPLIT_RATIO)))
        return sorted_dataset.iloc[:split].copy(), sorted_dataset.iloc[split:].copy()

    train_df = pd.concat(train_parts).sort_values(["event_time", "symbol"]).reset_index(drop=True)
    test_df = pd.concat(test_parts).sort_values(["event_time", "symbol"]).reset_index(drop=True)
    return train_df, test_df


def run_with_progress(label: str, action: Any, *, enabled: bool = False) -> Any:
    if not enabled:
        return action()
    start = time.perf_counter()
    stop_event = threading.Event()

    def heartbeat() -> None:
        while not stop_event.wait(TRAINING_PROGRESS_INTERVAL_SECONDS):
            elapsed = time.perf_counter() - start
            print(f"[ml] {label} running, elapsed={elapsed:.0f}s", flush=True)

    print(f"[ml] {label} start", flush=True)
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        return action()
    finally:
        stop_event.set()
        thread.join(timeout=1.0)
        print(f"[ml] {label} done, cost={time.perf_counter() - start:.1f}s", flush=True)


def walk_forward_direction_metrics(dataset: pd.DataFrame, name: str, classifier: Any) -> dict[str, float]:
    """Evaluate tabular direction quality over several forward-time validation slices."""
    predictions: list[np.ndarray] = []
    actuals: list[np.ndarray] = []
    sorted_dataset = dataset.sort_values(["symbol", "event_time"]).reset_index(drop=True)
    category_values = tabular_category_values(sorted_dataset)
    for fold in range(WALK_FORWARD_FOLDS):
        train_ratio = WALK_FORWARD_INITIAL_TRAIN_RATIO + fold * WALK_FORWARD_VALIDATION_RATIO
        validation_end_ratio = train_ratio + WALK_FORWARD_VALIDATION_RATIO
        train_parts: list[pd.DataFrame] = []
        validation_parts: list[pd.DataFrame] = []
        for _, group in sorted_dataset.groupby("symbol", sort=False):
            group = group.sort_values("event_time")
            if len(group) < 10:
                continue
            train_end = int(len(group) * train_ratio)
            validation_end = int(len(group) * validation_end_ratio)
            train_end = max(1, min(train_end, len(group) - 1))
            validation_end = max(train_end + 1, min(validation_end, len(group)))
            train_parts.append(group.iloc[:train_end])
            validation_parts.append(group.iloc[train_end:validation_end])

        if not train_parts or not validation_parts:
            continue
        train_df = pd.concat(train_parts).sort_values(["event_time", "symbol"]).reset_index(drop=True)
        validation_df = pd.concat(validation_parts).sort_values(["event_time", "symbol"]).reset_index(drop=True)
        if train_df.empty or validation_df.empty:
            continue

        fit_df, calibration_df = time_split_dataframe_by_symbol(train_df)
        if fit_df.empty or calibration_df.empty:
            fit_df = train_df
            calibration_df = pd.DataFrame()

        direction_model = Pipeline(
            steps=[
                ("preprocessor", build_preprocessor(category_values)),
                ("model", clone(classifier)),
            ]
        )
        y_fit = fit_df["next_direction"]
        direction_model.fit(fit_df[TABULAR_FEATURES], y_fit, model__sample_weight=direction_sample_weights(y_fit))
        decision_params = tune_direction_decision_params(
            predict_direction_probabilities(direction_model, calibration_df[TABULAR_FEATURES]),
            calibration_df["next_direction"].to_numpy(dtype=int),
        ) if not calibration_df.empty else None

        y_train = train_df["next_direction"]
        direction_model.fit(train_df[TABULAR_FEATURES], y_train, model__sample_weight=direction_sample_weights(y_train))
        validation_probabilities = predict_direction_probabilities(direction_model, validation_df[TABULAR_FEATURES])
        predictions.append(direction_from_probabilities(validation_probabilities, decision_params).to_numpy(dtype=int))
        actuals.append(validation_df["next_direction"].to_numpy(dtype=int))

    if not predictions or not actuals:
        return {}
    combined_actuals = np.concatenate(actuals)
    raw_combined_predictions = np.concatenate(predictions)
    combined_predictions, _, guard_metrics = validation_baseline_guard(
        f"{name}_walk_forward",
        combined_actuals,
        raw_combined_predictions,
        None,
    )
    return direction_eval_metrics(
        f"{name}_walk_forward",
        combined_actuals,
        combined_predictions,
    ) | guard_metrics


def train_tabular_models(
    dataset: pd.DataFrame,
    name: str,
    regressor: Any,
    classifier: Any,
    *,
    enable_walk_forward: bool = True,
    log_stages: bool = False,
) -> ModelResult:
    direction_threshold = dataset_direction_threshold(dataset, name)
    prediction_horizon = dataset_prediction_horizon(dataset)
    """Internal ML pipeline helper."""
    sorted_dataset = dataset.sort_values(["symbol", "event_time"]).reset_index(drop=True)
    category_values = tabular_category_values(sorted_dataset)
    train_df, test_df = time_split_dataframe_by_symbol(sorted_dataset)
    price_model = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor(category_values)),
            ("model", regressor),
        ]
    )
    direction_model = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor(category_values)),
            ("model", classifier),
        ]
    )
    fit_df, calibration_df = time_split_dataframe_by_symbol(train_df)
    if fit_df.empty or calibration_df.empty:
        fit_df = train_df
        calibration_df = pd.DataFrame()

    x_train = train_df[TABULAR_FEATURES]
    x_test = test_df[TABULAR_FEATURES]
    y_return_train = train_df["next_return"]
    y_return_test = test_df["next_return"]
    y_dir_train = train_df["next_direction"]
    y_dir_test = test_df["next_direction"]

    run_with_progress(
        f"{name} price regressor fit",
        lambda: price_model.fit(x_train, y_return_train),
        enabled=log_stages,
    )
    decision_params: dict[str, float | str] | None = None
    if not calibration_df.empty:
        calibration_model = Pipeline(
            steps=[
                ("preprocessor", build_preprocessor(category_values)),
                ("model", clone(classifier)),
            ]
        )
        y_dir_fit = fit_df["next_direction"]
        run_with_progress(
            f"{name} decision calibration fit",
            lambda: calibration_model.fit(
                fit_df[TABULAR_FEATURES],
                y_dir_fit,
                model__sample_weight=direction_sample_weights(y_dir_fit),
            ),
            enabled=log_stages,
        )
        calibration_probabilities = predict_direction_probabilities(calibration_model, calibration_df[TABULAR_FEATURES])
        decision_params = tune_direction_decision_params(
            calibration_probabilities,
            calibration_df["next_direction"].to_numpy(dtype=int),
        )
    run_with_progress(
        f"{name} direction classifier fit",
        lambda: direction_model.fit(
            x_train,
            y_dir_train,
            model__sample_weight=direction_sample_weights(y_dir_train),
        ),
        enabled=log_stages,
    )

    return_predictions = np.asarray(price_model.predict(x_test), dtype=float).reshape(-1)
    mae = float(mean_absolute_error(y_return_test, return_predictions))
    direction_probabilities = predict_direction_probabilities(direction_model, x_test)
    raw_direction_predictions = direction_from_probabilities(direction_probabilities, decision_params).to_numpy(dtype=int)
    direction_predictions, decision_params, guarded_direction_metrics = validation_baseline_guard(
        name,
        y_dir_test,
        raw_direction_predictions,
        decision_params,
    )
    direction_metrics = direction_eval_metrics(name, y_dir_test, direction_predictions)
    decision_metrics: dict[str, float] = {}
    if decision_params and decision_params.get("mode") == "direction_gate":
        decision_metrics[f"{name}_decision_min_direction_prob"] = float(decision_params["min_direction_prob"])
        decision_metrics[f"{name}_decision_min_direction_margin"] = float(decision_params["min_direction_margin"])
    if decision_params:
        for key in (
            "calibration_accuracy",
            "calibration_majority_baseline",
            "calibration_lift_over_baseline",
            "calibration_down_recall",
            "calibration_down_precision",
            "calibration_predicted_down_ratio",
            "calibration_max_down_coverage",
        ):
            if key in decision_params:
                decision_metrics[f"{name}_{key}"] = float(decision_params[key])
    decision_metrics[f"{name}_direction_threshold"] = direction_threshold
    decision_metrics[f"{name}_prediction_horizon"] = float(prediction_horizon)
    decision_metrics[f"{name}_risk_target_enabled"] = 1.0 if RISK_TARGET_ENABLED else 0.0
    decision_metrics[f"{name}_risk_downside_threshold"] = RISK_DOWNSIDE_THRESHOLD
    decision_metrics[f"{name}_risk_volatility_threshold"] = RISK_VOLATILITY_THRESHOLD
    decision_metrics[f"{name}_risk_alert_min_return"] = RISK_ALERT_MIN_RETURN
    decision_metrics[f"{name}_down_alert_risk_score_threshold"] = DOWN_ALERT_RISK_SCORE_THRESHOLD
    alert_metrics = alert_backtest_metrics(
        name,
        y_return_test,
        direction_predictions,
        display_confidence(direction_probabilities),
        return_predictions,
        movement_threshold=direction_threshold,
        evidence_frame=pd.concat(
            [
                test_df[DOWN_RISK_EVIDENCE_COLUMNS].reset_index(drop=True),
                direction_probabilities.reset_index(drop=True),
            ],
            axis=1,
        ),
    )
    if enable_walk_forward:
        walk_forward_metrics = run_with_progress(
            f"{name} walk-forward evaluation",
            lambda: walk_forward_direction_metrics(sorted_dataset, name, classifier),
            enabled=log_stages,
        )
    else:
        walk_forward_metrics = {f"{name}_walk_forward_skipped": 1.0}
        if log_stages:
            print(f"[ml] {name} walk-forward evaluation skipped", flush=True)

    return ModelResult(
        name=name,
        model_type="tabular",
        price_model=price_model,
        direction_model=direction_model,
        metrics={f"{name}_return_mae": mae, **direction_metrics, **guarded_direction_metrics, **alert_metrics, **walk_forward_metrics, **decision_metrics},
        extra={
            "decision_params": decision_params or {"mode": "argmax"},
            "direction_threshold": direction_threshold,
            "prediction_horizon": prediction_horizon,
            "target_mode": ML_TARGET_MODE,
            "risk_downside_threshold": RISK_DOWNSIDE_THRESHOLD,
            "risk_volatility_threshold": RISK_VOLATILITY_THRESHOLD,
            "risk_alert_min_return": RISK_ALERT_MIN_RETURN,
            "down_alert_risk_score_threshold": DOWN_ALERT_RISK_SCORE_THRESHOLD,
        },
    )


def train_random_forest(dataset: pd.DataFrame) -> ModelResult:
    """Internal ML pipeline helper."""
    config = OPTIMAL_MODEL_CONFIGS["random_forest"]
    rf_n_jobs = int(settings.ml_rf_n_jobs)
    print(f"[ml] random_forest n_jobs={rf_n_jobs}", flush=True)
    base_classifier = RandomForestClassifier(
        n_estimators=int(config["n_estimators_cls"]),
        max_depth=int(config["max_depth"]),
        min_samples_leaf=int(config["min_samples_leaf"]),
        max_features=config["max_features"],
        random_state=42,
        n_jobs=rf_n_jobs,
        class_weight="balanced_subsample",
    )
    if settings.ml_rf_full_calibration:
        classifier: Any = CalibratedClassifierCV(
            estimator=base_classifier,
            method=str(config["calibration"]),
            cv=3,
        )
        print("[ml] random_forest full calibration enabled", flush=True)
    else:
        classifier = base_classifier
        print("[ml] random_forest full calibration disabled for faster production training", flush=True)
    return train_tabular_models(
        dataset,
        "random_forest",
        RandomForestRegressor(
            n_estimators=int(config["n_estimators_reg"]),
            max_depth=int(config["max_depth"]),
            min_samples_leaf=int(config["min_samples_leaf"]),
            max_features=config["max_features"],
            random_state=42,
            n_jobs=rf_n_jobs,
        ),
        classifier,
        enable_walk_forward=settings.ml_rf_walk_forward,
        log_stages=True,
    )


def train_lightgbm(dataset: pd.DataFrame) -> ModelResult:
    """Internal ML pipeline helper."""
    try:
        from lightgbm import LGBMClassifier, LGBMRegressor
    except ImportError as exc:
        raise RuntimeError("lightgbm is not installed, skip LightGBM model") from exc
    config = OPTIMAL_MODEL_CONFIGS["lightgbm"]

    return train_tabular_models(
        dataset,
        "lightgbm",
        LGBMRegressor(
            n_estimators=int(config["n_estimators"]),
            learning_rate=float(config["learning_rate"]),
            num_leaves=int(config["num_leaves"]),
            min_child_samples=int(config["min_child_samples"]),
            subsample=float(config["subsample"]),
            colsample_bytree=float(config["colsample_bytree"]),
            reg_lambda=float(config["reg_lambda"]),
            random_state=42,
            verbose=-1,
            verbosity=-1,
            force_col_wise=True,
            n_jobs=-1,
        ),
        LGBMClassifier(
            n_estimators=int(config["n_estimators"]),
            learning_rate=float(config["learning_rate"]),
            num_leaves=int(config["num_leaves"]),
            min_child_samples=int(config["min_child_samples"]),
            subsample=float(config["subsample"]),
            colsample_bytree=float(config["colsample_bytree"]),
            reg_lambda=float(config["reg_lambda"]),
            random_state=42,
            verbose=-1,
            verbosity=-1,
            force_col_wise=True,
            n_jobs=-1,
            class_weight="balanced",
        ),
    )


def build_lstm_samples(dataset: pd.DataFrame, window_size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Internal ML pipeline helper."""
    sequence_df = dataset[["symbol", "event_time", "next_return", "next_direction", *SEQUENCE_FEATURES]].copy()

    x_values: list[np.ndarray] = []
    y_return: list[float] = []
    y_direction: list[int] = []
    sample_times: list[pd.Timestamp] = []
    sample_symbols: list[str] = []
    for symbol, group in sequence_df.sort_values(["symbol", "event_time"]).groupby("symbol"):
        rows = group[SEQUENCE_FEATURES].to_numpy(dtype=np.float32)
        returns = group["next_return"].to_numpy(dtype=np.float32)
        directions = group["next_direction"].to_numpy(dtype=np.int64)
        times = pd.to_datetime(group["event_time"]).to_numpy()
        for end in range(window_size, len(group) + 1):
            # next_return/next_direction were already shifted by PREDICTION_HORIZON in prepare_dataset.
            # The label at the window tail therefore means "tail time -> tail time + horizon".
            label_index = end - 1
            x_values.append(rows[end - window_size : end])
            y_return.append(float(returns[label_index]))
            y_direction.append(int(directions[label_index]))
            sample_times.append(times[label_index])
            sample_symbols.append(str(symbol))

    if not x_values:
        raise ValueError(f"Need at least {window_size + 1} continuous ticks per symbol to train LSTM.")

    order = np.argsort(np.asarray(sample_times, dtype="datetime64[ns]"))
    x_array = np.asarray(x_values)[order]
    y_return_array = np.asarray(y_return)[order]
    y_direction_array = np.asarray(y_direction, dtype=np.int64)[order]
    symbol_array = np.asarray(sample_symbols, dtype=object)[order]
    if settings.ml_lstm_max_sequences > 0 and len(x_array) > settings.ml_lstm_max_sequences:
        sample_index_parts: list[int] = []
        unique_symbols = pd.unique(symbol_array)
        per_symbol_limit = max(settings.ml_lstm_max_sequences // max(len(unique_symbols), 1), 1)
        for symbol in unique_symbols:
            symbol_index = np.where(symbol_array == symbol)[0]
            sample_index_parts.extend(symbol_index[-per_symbol_limit:].tolist())
        sample_index = np.asarray(sorted(sample_index_parts), dtype=int)
        if len(sample_index) > settings.ml_lstm_max_sequences:
            sample_index = sample_index[-settings.ml_lstm_max_sequences :]
        print(f"[ml] limit LSTM sequences {len(x_array)} -> {len(sample_index)} with per-symbol latest windows", flush=True)
        x_array = x_array[sample_index]
        y_return_array = y_return_array[sample_index]
        y_direction_array = y_direction_array[sample_index]
        symbol_array = symbol_array[sample_index]

    return x_array.astype(np.float32), y_return_array, y_direction_array, symbol_array


def fit_lstm_scaler(x_train: np.ndarray) -> StandardScaler:
    """Fit sequence scaler on training windows only, then reuse it for validation and prediction."""
    scaler = StandardScaler()
    scaler.fit(x_train.reshape(-1, x_train.shape[-1]))
    return scaler


def transform_lstm_sequences(x_values: np.ndarray, scaler: StandardScaler) -> np.ndarray:
    """Apply a fitted scaler to 3D LSTM windows without changing their shape."""
    original_shape = x_values.shape
    scaled = scaler.transform(x_values.reshape(-1, original_shape[-1]))
    return scaled.reshape(original_shape).astype(np.float32)


def time_split_lstm_by_symbol(
    x_values: np.ndarray,
    y_return: np.ndarray,
    y_direction: np.ndarray,
    symbols: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Split LSTM sequences per symbol to avoid future-data leakage."""
    train_index: list[int] = []
    test_index: list[int] = []
    for symbol in pd.unique(symbols):
        symbol_index = np.where(symbols == symbol)[0]
        if len(symbol_index) < 2:
            continue
        split = max(1, min(len(symbol_index) - 1, int(len(symbol_index) * TIME_SPLIT_RATIO)))
        train_index.extend(symbol_index[:split].tolist())
        test_index.extend(symbol_index[split:].tolist())

    if not train_index or not test_index:
        split = max(1, min(len(x_values) - 1, int(len(x_values) * TIME_SPLIT_RATIO)))
        train_index = list(range(split))
        test_index = list(range(split, len(x_values)))

    train_index_array = np.asarray(train_index, dtype=int)
    test_index_array = np.asarray(test_index, dtype=int)
    return (
        x_values[train_index_array],
        x_values[test_index_array],
        y_return[train_index_array],
        y_return[test_index_array],
        y_direction[train_index_array],
        y_direction[test_index_array],
    )


def walk_forward_lstm_direction_metrics(dataset: pd.DataFrame, device: torch.device) -> dict[str, float]:
    """Run lightweight walk-forward validation for the LSTM direction branch."""
    try:
        x_values, _, y_direction, symbols = build_lstm_samples(dataset, LSTM_WINDOW_SIZE)
    except ValueError:
        return {}

    predictions: list[np.ndarray] = []
    actuals: list[np.ndarray] = []
    for fold in range(WALK_FORWARD_FOLDS):
        train_ratio = WALK_FORWARD_INITIAL_TRAIN_RATIO + fold * WALK_FORWARD_VALIDATION_RATIO
        validation_end_ratio = train_ratio + WALK_FORWARD_VALIDATION_RATIO
        train_index: list[int] = []
        validation_index: list[int] = []
        for symbol in pd.unique(symbols):
            symbol_index = np.where(symbols == symbol)[0]
            if len(symbol_index) < 10:
                continue
            train_end = int(len(symbol_index) * train_ratio)
            validation_end = int(len(symbol_index) * validation_end_ratio)
            train_end = max(1, min(train_end, len(symbol_index) - 1))
            validation_end = max(train_end + 1, min(validation_end, len(symbol_index)))
            train_index.extend(symbol_index[:train_end].tolist())
            validation_index.extend(symbol_index[train_end:validation_end].tolist())

        if not train_index or not validation_index:
            continue

        train_index_array = np.asarray(train_index, dtype=int)
        validation_index_array = np.asarray(validation_index, dtype=int)
        scaler = fit_lstm_scaler(x_values[train_index_array])
        x_train = transform_lstm_sequences(x_values[train_index_array], scaler)
        x_validation = transform_lstm_sequences(x_values[validation_index_array], scaler)
        y_train = y_direction[train_index_array]
        y_validation = y_direction[validation_index_array]

        model = DirectionLstmModel(len(SEQUENCE_FEATURES)).to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=LSTM_LEARNING_RATE, weight_decay=LSTM_WEIGHT_DECAY)
        loss_weight = torch.tensor(direction_class_weights(y_train), dtype=torch.float32).to(device)
        loss_fn = nn.CrossEntropyLoss(weight=loss_weight)
        batch_size = min(LSTM_BATCH_SIZE, max(16, len(x_train) // 10))
        loader = DataLoader(
            TensorDataset(torch.tensor(x_train, dtype=torch.float32), torch.tensor(y_train, dtype=torch.long)),
            batch_size=batch_size,
            shuffle=True,
        )

        model.train()
        walk_forward_epochs = max(2, min(15, settings.ml_lstm_epochs // 4))
        for _ in range(walk_forward_epochs):
            for batch_x, batch_direction in loader:
                batch_x = batch_x.to(device)
                batch_direction = batch_direction.to(device).long()
                optimizer.zero_grad()
                loss = loss_fn(model(batch_x), batch_direction)
                loss.backward()
                optimizer.step()

        model.eval()
        with torch.no_grad():
            validation_tensor = torch.tensor(x_validation, dtype=torch.float32).to(device)
            fold_pred = torch.softmax(model(validation_tensor), dim=1).argmax(dim=1).cpu().numpy()
        model.cpu()
        predictions.append(fold_pred)
        actuals.append(y_validation.astype(int))

    if not predictions or not actuals:
        return {}
    combined_actuals = np.concatenate(actuals)
    raw_combined_predictions = np.concatenate(predictions)
    combined_predictions, _, guard_metrics = validation_baseline_guard(
        "lstm_walk_forward",
        combined_actuals,
        raw_combined_predictions,
        None,
    )
    return direction_eval_metrics(
        "lstm_walk_forward",
        combined_actuals,
        combined_predictions,
    ) | guard_metrics


def train_lstm(dataset: pd.DataFrame) -> ModelResult:
    direction_threshold = dataset_direction_threshold(dataset, "lstm")
    prediction_horizon = dataset_prediction_horizon(dataset)
    """Internal ML pipeline helper."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if settings.ml_require_gpu and device.type != "cuda":
        raise RuntimeError("ML_REQUIRE_GPU=true, but PyTorch cannot see any CUDA GPU.")
    if device.type == "cuda":
        print(f"[ml] pytorch_device={torch.cuda.get_device_name(0)} cuda={torch.version.cuda}")
    else:
        print("[ml] pytorch_device=cpu")

    x_values, y_return, y_direction, symbols = build_lstm_samples(dataset, LSTM_WINDOW_SIZE)
    if len(x_values) < settings.ml_min_train_size:
        raise ValueError(f"Need at least {settings.ml_min_train_size} LSTM sequences to train LSTM models.")

    x_train_raw, x_test_raw, y_return_train, y_return_test, y_dir_train, y_dir_test = time_split_lstm_by_symbol(
        x_values,
        y_return,
        y_direction,
        symbols,
    )
    scaler = fit_lstm_scaler(x_train_raw)
    x_train = transform_lstm_sequences(x_train_raw, scaler)
    x_test = transform_lstm_sequences(x_test_raw, scaler)
    validation_split = max(1, min(len(x_train) - 1, int(len(x_train) * TIME_SPLIT_RATIO)))
    x_fit = x_train[:validation_split]
    x_validation = x_train[validation_split:]
    y_return_fit = y_return_train[:validation_split]
    y_return_validation = y_return_train[validation_split:]
    y_dir_fit = y_dir_train[:validation_split]
    y_dir_validation = y_dir_train[validation_split:]

    price_model = PriceLstmModel(len(SEQUENCE_FEATURES)).to(device)
    direction_model = DirectionLstmModel(len(SEQUENCE_FEATURES)).to(device)

    batch_size = min(LSTM_BATCH_SIZE, max(16, len(x_fit) // 10))
    train_loader = DataLoader(
        TensorDataset(
            torch.tensor(x_fit, dtype=torch.float32),
            torch.tensor(y_return_fit, dtype=torch.float32),
            torch.tensor(y_dir_fit, dtype=torch.long),
        ),
        batch_size=batch_size,
        shuffle=True,
    )

    price_optimizer = torch.optim.AdamW(price_model.parameters(), lr=LSTM_LEARNING_RATE, weight_decay=LSTM_WEIGHT_DECAY)
    direction_optimizer = torch.optim.AdamW(direction_model.parameters(), lr=LSTM_LEARNING_RATE, weight_decay=LSTM_WEIGHT_DECAY)
    price_loss_fn = nn.L1Loss()
    direction_weight_tensor = torch.tensor(direction_class_weights(y_dir_fit), dtype=torch.float32).to(device)
    direction_loss_fn = nn.CrossEntropyLoss(weight=direction_weight_tensor)

    x_validation_tensor = torch.tensor(x_validation, dtype=torch.float32).to(device)
    y_return_validation_tensor = torch.tensor(y_return_validation, dtype=torch.float32).to(device)
    y_dir_validation_tensor = torch.tensor(y_dir_validation, dtype=torch.long).to(device)
    best_val_loss = float("inf")
    best_epoch = 0
    best_price_state: dict[str, torch.Tensor] | None = None
    best_direction_state: dict[str, torch.Tensor] | None = None
    epochs_without_improvement = 0
    early_stop_patience = max(3, int(settings.ml_lstm_early_stop_patience))
    early_stop_epoch = 0

    print(
        f"[ml][lstm] train setup: "
        f"x_fit={len(x_fit)}, x_val={len(x_validation)}, x_test={len(x_test)}, "
        f"window={LSTM_WINDOW_SIZE}, features={len(SEQUENCE_FEATURES)}, "
        f"hidden={LSTM_HIDDEN_SIZE}, layers={LSTM_NUM_LAYERS}, dropout={LSTM_DROPOUT:.2f}, "
        f"lr={LSTM_LEARNING_RATE:g}, weight_decay={LSTM_WEIGHT_DECAY:g}, "
        f"batch_size={batch_size}, batches={len(train_loader)}, "
        f"epochs={settings.ml_lstm_epochs}, patience={early_stop_patience}",
        flush=True,
    )

    for epoch in range(settings.ml_lstm_epochs):
        epoch_start = time.perf_counter()
        price_model.train()
        direction_model.train()

        train_price_loss_sum = 0.0
        train_direction_loss_sum = 0.0
        batch_count = 0

        for batch_x, batch_return, batch_direction in train_loader:
            batch_x = batch_x.to(device)
            batch_return = batch_return.to(device)
            batch_direction = batch_direction.to(device).long()

            price_optimizer.zero_grad()
            price_loss = price_loss_fn(price_model(batch_x), batch_return)
            price_loss.backward()
            price_optimizer.step()

            direction_optimizer.zero_grad()
            direction_loss = direction_loss_fn(direction_model(batch_x), batch_direction)
            direction_loss.backward()
            direction_optimizer.step()

            train_price_loss_sum += float(price_loss.detach().cpu().item())
            train_direction_loss_sum += float(direction_loss.detach().cpu().item())
            batch_count += 1

        train_price_loss = train_price_loss_sum / max(batch_count, 1)
        train_direction_loss = train_direction_loss_sum / max(batch_count, 1)

        price_model.eval()
        direction_model.eval()
        with torch.no_grad():
            price_val_pred = price_model(x_validation_tensor)
            direction_val_logits = direction_model(x_validation_tensor)

            price_val_loss = price_loss_fn(price_val_pred, y_return_validation_tensor)
            direction_val_loss = direction_loss_fn(direction_val_logits, y_dir_validation_tensor)
            val_combined_loss = float((direction_val_loss + 0.3 * price_val_loss).detach().cpu().item())

            val_direction_pred = direction_val_logits.argmax(dim=1)
            val_acc = float((val_direction_pred == y_dir_validation_tensor).float().mean().detach().cpu().item())
            val_macro_f1 = float(
                f1_score(
                    y_dir_validation_tensor.detach().cpu().numpy(),
                    val_direction_pred.detach().cpu().numpy(),
                    labels=DIRECTION_LABELS,
                    average="macro",
                    zero_division=0,
                )
            )

        improved = val_combined_loss < best_val_loss - 1e-5
        if improved:
            best_val_loss = val_combined_loss
            best_epoch = epoch + 1
            epochs_without_improvement = 0
            best_price_state = {key: value.detach().cpu().clone() for key, value in price_model.state_dict().items()}
            best_direction_state = {key: value.detach().cpu().clone() for key, value in direction_model.state_dict().items()}
        else:
            epochs_without_improvement += 1

        cuda_info = ""
        if device.type == "cuda":
            cuda_info = (
                f", cuda_alloc={torch.cuda.memory_allocated() / 1024 / 1024:.0f}MiB"
                f", cuda_reserved={torch.cuda.memory_reserved() / 1024 / 1024:.0f}MiB"
                f", cuda_max={torch.cuda.max_memory_allocated() / 1024 / 1024:.0f}MiB"
            )

        print(
            f"[ml][lstm] epoch {epoch + 1:03d}/{settings.ml_lstm_epochs} "
            f"train_price_loss={train_price_loss:.6f} "
            f"train_direction_loss={train_direction_loss:.6f} "
            f"val_price_loss={float(price_val_loss.detach().cpu().item()):.6f} "
            f"val_direction_loss={float(direction_val_loss.detach().cpu().item()):.6f} "
            f"val_combined_loss={val_combined_loss:.6f} "
            f"val_acc={val_acc:.4f} "
            f"val_macro_f1={val_macro_f1:.4f} "
            f"best_epoch={best_epoch} "
            f"no_improve={epochs_without_improvement}/{early_stop_patience} "
            f"cost={time.perf_counter() - epoch_start:.1f}s"
            f"{cuda_info}"
            f"{'  *best*' if improved else ''}",
            flush=True,
        )

        if epochs_without_improvement >= early_stop_patience:
            early_stop_epoch = epoch + 1
            print(
                f"[ml] lstm early stopping at epoch {early_stop_epoch}, best_epoch={best_epoch}, best_val_loss={best_val_loss:.6f}",
                flush=True,
            )
            break

    if best_price_state is not None and best_direction_state is not None:
        price_model.load_state_dict(best_price_state)
        direction_model.load_state_dict(best_direction_state)
    if early_stop_epoch == 0:
        early_stop_epoch = settings.ml_lstm_epochs
    direction_model.eval()
    with torch.no_grad():
        validation_probability = torch.softmax(direction_model(x_validation_tensor), dim=1).cpu().numpy()
    decision_params = tune_direction_decision_params(
        pd.DataFrame(validation_probability, columns=["prob_down", "prob_up", "prob_flat"]),
        y_dir_validation,
    )

    x_test_tensor = torch.tensor(x_test, dtype=torch.float32).to(device)
    price_model.eval()
    direction_model.eval()
    with torch.no_grad():
        return_pred = price_model(x_test_tensor).cpu().numpy().reshape(-1)
        direction_probability = torch.softmax(direction_model(x_test_tensor), dim=1).cpu().numpy()
    return_mae = float(mean_absolute_error(y_return_test, return_pred))
    direction_probabilities = pd.DataFrame(direction_probability, columns=["prob_down", "prob_up", "prob_flat"])
    raw_direction_pred = direction_from_probabilities(direction_probabilities, decision_params).to_numpy(dtype=int)
    direction_pred, decision_params, guarded_direction_metrics = validation_baseline_guard(
        "lstm",
        y_dir_test,
        raw_direction_pred,
        decision_params,
    )
    direction_metrics = direction_eval_metrics("lstm", y_dir_test, direction_pred)
    decision_metrics: dict[str, float] = {}
    if decision_params and decision_params.get("mode") == "direction_gate":
        decision_metrics["lstm_decision_min_direction_prob"] = float(decision_params["min_direction_prob"])
        decision_metrics["lstm_decision_min_direction_margin"] = float(decision_params["min_direction_margin"])
    if decision_params:
        for key in (
            "calibration_accuracy",
            "calibration_majority_baseline",
            "calibration_lift_over_baseline",
            "calibration_down_recall",
            "calibration_down_precision",
            "calibration_predicted_down_ratio",
            "calibration_max_down_coverage",
        ):
            if key in decision_params:
                decision_metrics[f"lstm_{key}"] = float(decision_params[key])
    decision_metrics["lstm_direction_threshold"] = direction_threshold
    decision_metrics["lstm_prediction_horizon"] = float(prediction_horizon)
    decision_metrics["lstm_risk_target_enabled"] = 1.0 if RISK_TARGET_ENABLED else 0.0
    decision_metrics["lstm_risk_downside_threshold"] = RISK_DOWNSIDE_THRESHOLD
    decision_metrics["lstm_risk_volatility_threshold"] = RISK_VOLATILITY_THRESHOLD
    decision_metrics["lstm_risk_alert_min_return"] = RISK_ALERT_MIN_RETURN
    decision_metrics["lstm_down_alert_risk_score_threshold"] = DOWN_ALERT_RISK_SCORE_THRESHOLD
    alert_metrics = alert_backtest_metrics(
        "lstm",
        y_return_test,
        direction_pred,
        display_confidence(direction_probabilities),
        return_pred,
        movement_threshold=direction_threshold,
        evidence_frame=pd.concat(
            [
                pd.DataFrame(x_test_raw[:, -1, :], columns=SEQUENCE_FEATURES)[DOWN_RISK_EVIDENCE_COLUMNS].reset_index(drop=True),
                direction_probabilities.reset_index(drop=True),
            ],
            axis=1,
        ),
    )
    walk_forward_metrics = walk_forward_lstm_direction_metrics(dataset, device)

    price_model.cpu()
    direction_model.cpu()
    return ModelResult(
        name="lstm",
        model_type="sequence",
        price_model=price_model,
        direction_model=direction_model,
        metrics={
            "lstm_return_mae": return_mae,
            "lstm_best_epoch": float(best_epoch),
            "lstm_early_stop_epoch": float(early_stop_epoch),
            "lstm_best_val_combined_loss": float(best_val_loss),
            **direction_metrics,
            **guarded_direction_metrics,
            **alert_metrics,
            **walk_forward_metrics,
            **decision_metrics,
        },
        extra={
            "scaler": scaler,
            "window_size": LSTM_WINDOW_SIZE,
            "framework": "pytorch",
            "device": str(device),
            "decision_params": decision_params or {"mode": "argmax"},
            "direction_threshold": direction_threshold,
            "prediction_horizon": prediction_horizon,
            "target_mode": ML_TARGET_MODE,
            "risk_downside_threshold": RISK_DOWNSIDE_THRESHOLD,
            "risk_volatility_threshold": RISK_VOLATILITY_THRESHOLD,
            "risk_alert_min_return": RISK_ALERT_MIN_RETURN,
            "down_alert_risk_score_threshold": DOWN_ALERT_RISK_SCORE_THRESHOLD,
        },
    )


def train_models(dataset: pd.DataFrame | dict[str, pd.DataFrame], model_names: set[str] | None = None) -> list[ModelResult]:
    """Internal ML pipeline helper."""
    def dataset_for(model_name: str) -> pd.DataFrame:
        if isinstance(dataset, dict):
            return dataset[model_name]
        return dataset

    training_order = ("random_forest", "lightgbm", "lstm")
    selected_models = [name for name in training_order if model_names is None or name in model_names]
    if not selected_models:
        raise ValueError("No ML models selected for training.")

    if isinstance(dataset, dict):
        min_rows = min((len(dataset[name]) for name in selected_models if name in dataset), default=0)
    else:
        min_rows = len(dataset)
    if min_rows < settings.ml_min_train_size:
        raise ValueError(f"Need at least {settings.ml_min_train_size} price ticks to train ML models.")

    results: list[ModelResult] = []
    if "random_forest" in selected_models:
        rf_dataset = dataset_for("random_forest")
        print(
            f"[ml] training random_forest horizon={dataset_prediction_horizon(rf_dataset)} direction_threshold={dataset_direction_threshold(rf_dataset, 'random_forest'):g}",
            flush=True,
        )
        results.append(train_random_forest(rf_dataset))
    for model_name, trainer in (("lightgbm", train_lightgbm), ("lstm", train_lstm)):
        if model_name not in selected_models:
            continue
        try:
            model_dataset = dataset_for(model_name)
            print(
                f"[ml] training {model_name} horizon={dataset_prediction_horizon(model_dataset)} direction_threshold={dataset_direction_threshold(model_dataset, model_name):g}",
                flush=True,
            )
            results.append(trainer(model_dataset))
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] {exc}", flush=True)
    return results


def metric_value(result: ModelResult, metric_suffix: str, default: float = 0.0) -> float:
    for key, value in result.metrics.items():
        if key.endswith(metric_suffix):
            return float(value)
    return default


def direction_quality_score(result: ModelResult) -> float:
    """Score models by forward-time direction quality and alert usefulness."""
    balanced = metric_value(result, "_balanced_direction_accuracy")
    macro_f1 = metric_value(result, "_direction_macro_f1")
    lift = metric_value(result, "_walk_forward_direction_lift_over_baseline", metric_value(result, "_direction_lift_over_baseline", -0.5))
    return_mae = metric_value(result, "_return_mae", 0.05)
    wf_balanced = metric_value(result, "_walk_forward_balanced_direction_accuracy", balanced)
    wf_f1 = metric_value(result, "_walk_forward_direction_macro_f1", macro_f1)
    down_inverse = metric_value(result, "_alert_backtest_down_avg_inverse_return", 0.0)
    down_penalty = min(down_inverse, 0.0) * 5.0
    up_avg_return = metric_value(result, "_alert_backtest_up_avg_return", 0.0)
    up_bonus = min(max(up_avg_return, 0.0), 0.02) * 3.0
    score = (
        wf_balanced * 0.35
        + wf_f1 * 0.25
        + balanced * 0.20
        + macro_f1 * 0.10
        + max(lift, -0.5) * 0.05
        - min(return_mae, 0.2) * 0.05
        + down_penalty
        + up_bonus
    )
    if lift < 0:
        score -= min(abs(lift), 0.30) * 0.35
    return score


def select_best_model(results: list[ModelResult]) -> ModelResult:
    """Select the operational model by risk-direction quality, not just return MAE."""
    if not results:
        raise ValueError("No trained model results are available.")
    direction_models = [
        item
        for item in results
        if any(key.endswith("_balanced_direction_accuracy") or key.endswith("_direction_macro_f1") for key in item.metrics)
    ]
    if direction_models:
        above_baseline = [
            item
            for item in direction_models
            if metric_value(item, "_walk_forward_direction_lift_over_baseline", metric_value(item, "_direction_lift_over_baseline", -1.0)) > 0
        ]
        return max(above_baseline or direction_models, key=direction_quality_score)
    return_models = [item for item in results if any(key.endswith("_return_mae") for key in item.metrics)]
    if return_models:
        return min(return_models, key=lambda item: metric_value(item, "_return_mae", float("inf")))
    price_models = [item for item in results if any(key.endswith("_price_mae") for key in item.metrics)]
    if price_models:
        return min(price_models, key=lambda item: metric_value(item, "_price_mae", float("inf")))
    priority = {"lightgbm": 3, "lstm": 2, "random_forest": 1}
    return max(results, key=lambda item: priority.get(item.name, 0))


def save_models(results: list[ModelResult], version: str) -> None:
    """Internal ML pipeline helper."""
    out_dir = model_dir()
    for result in results:
        if result.model_type == "sequence":
            torch.save(result.price_model.state_dict(), out_dir / f"{result.name}-price-model-{version}.pt")
            torch.save(result.direction_model.state_dict(), out_dir / f"{result.name}-direction-model-{version}.pt")
            joblib.dump(result.extra, out_dir / f"{result.name}-extra-{version}.joblib")
        else:
            joblib.dump(result.price_model, out_dir / f"{result.name}-price-model-{version}.joblib")
            joblib.dump(result.direction_model, out_dir / f"{result.name}-direction-model-{version}.joblib")
            joblib.dump(result.extra or {}, out_dir / f"{result.name}-extra-{version}.joblib")
    joblib.dump({result.name: result.metrics for result in results}, out_dir / f"model-metrics-{version}.joblib")


def load_latest_model_results(version_prefix: str = "") -> tuple[list[ModelResult], str]:
    """Load the newest saved model set for prediction-only daily jobs."""
    out_dir = model_dir()
    available_versions: dict[str, float] = {}
    for path in out_dir.glob("*-price-model-*"):
        for model_name in ("random_forest", "lightgbm", "lstm"):
            marker = f"{model_name}-price-model-"
            if not path.name.startswith(marker):
                continue
            version = path.name[len(marker) :]
            for suffix in (".joblib", ".pt"):
                if version.endswith(suffix):
                    version = version[: -len(suffix)]
            if version_prefix and not version.startswith(version_prefix):
                continue
            available_versions[version] = max(available_versions.get(version, 0.0), path.stat().st_mtime)

    if not available_versions:
        prefix_text = f" with prefix {version_prefix!r}" if version_prefix else ""
        raise FileNotFoundError(f"No saved ML models found{prefix_text}; run training first.")

    version = max(available_versions, key=available_versions.get)
    metrics_path = out_dir / f"model-metrics-{version}.joblib"
    metrics_by_model = joblib.load(metrics_path) if metrics_path.exists() else {}
    results: list[ModelResult] = []
    for model_name in ("random_forest", "lightgbm"):
        price_path = out_dir / f"{model_name}-price-model-{version}.joblib"
        direction_path = out_dir / f"{model_name}-direction-model-{version}.joblib"
        extra_path = out_dir / f"{model_name}-extra-{version}.joblib"
        if price_path.exists() and direction_path.exists():
            results.append(
                ModelResult(
                    name=model_name,
                    model_type="tabular",
                    price_model=joblib.load(price_path),
                    direction_model=joblib.load(direction_path),
                    metrics=metrics_by_model.get(model_name, {}),
                    extra=joblib.load(extra_path) if extra_path.exists() else None,
                )
            )

    lstm_price_path = out_dir / f"lstm-price-model-{version}.pt"
    lstm_direction_path = out_dir / f"lstm-direction-model-{version}.pt"
    lstm_extra_path = out_dir / f"lstm-extra-{version}.joblib"
    if lstm_price_path.exists() and lstm_direction_path.exists() and lstm_extra_path.exists():
        extra = joblib.load(lstm_extra_path)
        price_model = PriceLstmModel(len(SEQUENCE_FEATURES))
        direction_model = DirectionLstmModel(len(SEQUENCE_FEATURES))
        try:
            price_model.load_state_dict(torch.load(lstm_price_path, map_location="cpu"))
            direction_model.load_state_dict(torch.load(lstm_direction_path, map_location="cpu"))
            results.append(
                ModelResult(
                    name="lstm",
                    model_type="sequence",
                    price_model=price_model,
                    direction_model=direction_model,
                    metrics=metrics_by_model.get("lstm", {}),
                    extra=extra,
                )
            )
        except RuntimeError as exc:
            print(f"[warn] skip incompatible lstm model {version}: {exc}", flush=True)

    if not results:
        raise FileNotFoundError(f"Saved model version {version} is incomplete.")
    return results, version


def predict_direction_probabilities(model: Any, features: pd.DataFrame) -> pd.DataFrame:
    """Return normalized probabilities for DOWN / UP / FLAT."""
    result = np.zeros((len(features), len(DIRECTION_LABELS)), dtype=float)
    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(features)
        classes = getattr(model, "classes_", None)
        if classes is None and hasattr(model, "named_steps"):
            classes = getattr(model.named_steps.get("model"), "classes_", None)
        if classes is None:
            classes = DIRECTION_LABELS[: probabilities.shape[1]]
        for source_index, label in enumerate(classes):
            if int(label) in DIRECTION_LABELS:
                result[:, DIRECTION_LABELS.index(int(label))] = probabilities[:, source_index]
    else:
        predictions = model.predict(features).astype(int)
        for label in DIRECTION_LABELS:
            result[:, DIRECTION_LABELS.index(label)] = (predictions == label).astype(float)
    row_sum = result.sum(axis=1, keepdims=True)
    result = np.divide(result, row_sum, out=np.full_like(result, 1 / len(DIRECTION_LABELS)), where=row_sum > 0)
    return pd.DataFrame(result, index=features.index, columns=["prob_down", "prob_up", "prob_flat"])


def display_confidence(probabilities: pd.DataFrame) -> pd.Series:
    """Map directional certainty to a front-end friendly range.

    A very high FLAT/WATCH probability means "the model sees little movement", not
    "the directional prediction is 100% reliable", so flat cases are scored by
    the separation between UP and DOWN probabilities.
    """
    columns = probabilities[["prob_down", "prob_up", "prob_flat"]]
    max_probability = columns.max(axis=1)
    normalized = ((max_probability - (1 / len(DIRECTION_LABELS))) / (1 - (1 / len(DIRECTION_LABELS)))).clip(0, 1)
    confidence = 0.5 + normalized * 0.5
    flat_is_top = columns["prob_flat"] >= columns[["prob_down", "prob_up"]].max(axis=1)
    directional_gap = (columns["prob_up"] - columns["prob_down"]).abs().clip(0, 1)
    confidence.loc[flat_is_top] = 0.5 + directional_gap.loc[flat_is_top] * 0.5
    return confidence.clip(0, 0.95)


def direction_from_probabilities(probabilities: pd.DataFrame, decision_params: dict[str, Any] | None = None) -> pd.Series:
    label_by_column = {"prob_down": DIRECTION_DOWN, "prob_up": DIRECTION_UP, "prob_flat": DIRECTION_FLAT}
    if decision_params and decision_params.get("mode") == "majority_class":
        label = int(decision_params.get("label", DIRECTION_FLAT))
        if RISK_TARGET_ENABLED and label == DIRECTION_UP:
            label = DIRECTION_FLAT
        return pd.Series(label, index=probabilities.index).astype(int)
    if decision_params and decision_params.get("mode") == "direction_gate":
        columns = probabilities[["prob_down", "prob_up", "prob_flat"]].fillna(0)
        up = columns["prob_up"].to_numpy(dtype=float)
        down = columns["prob_down"].to_numpy(dtype=float)
        flat = columns["prob_flat"].to_numpy(dtype=float)
        min_direction_prob = float(decision_params.get("min_direction_prob", 0.34))
        min_direction_margin = float(decision_params.get("min_direction_margin", 0.0))
        if RISK_TARGET_ENABLED:
            use_down = (down >= min_direction_prob) & ((down - flat) >= min_direction_margin)
            return pd.Series(np.where(use_down, DIRECTION_DOWN, DIRECTION_FLAT), index=probabilities.index).astype(int)
        direction_is_up = up >= down
        direction_prob = np.where(direction_is_up, up, down)
        direction_label = np.where(direction_is_up, DIRECTION_UP, DIRECTION_DOWN)
        use_direction = (direction_prob >= min_direction_prob) & ((direction_prob - flat) >= min_direction_margin)
        return pd.Series(np.where(use_direction, direction_label, DIRECTION_FLAT), index=probabilities.index).astype(int)
    predictions = probabilities[["prob_down", "prob_up", "prob_flat"]].idxmax(axis=1).map(label_by_column).astype(int)
    if RISK_TARGET_ENABLED:
        predictions = predictions.where(predictions != DIRECTION_UP, DIRECTION_FLAT)
    return predictions


def apply_return_signal_override(frame: pd.DataFrame, threshold: float | None = None) -> pd.DataFrame:
    """Keep the final signal consistent with the predicted return when it has a clear direction."""
    result = frame.copy()
    if "predicted_return" not in result.columns or "predicted_direction" not in result.columns:
        return result
    threshold_value = PREDICTION_RETURN_SIGNAL_THRESHOLD if threshold is None else max(0.0, float(threshold))
    if threshold_value <= 0:
        return result
    predicted_return = pd.to_numeric(result["predicted_return"], errors="coerce").fillna(0.0)
    if not RISK_TARGET_ENABLED:
        result.loc[predicted_return >= threshold_value, "predicted_direction"] = DIRECTION_UP
    result.loc[predicted_return <= -threshold_value, "predicted_direction"] = DIRECTION_DOWN
    result["predicted_signal"] = result["predicted_direction"].map(DIRECTION_SIGNAL_MAP)
    return result


def tune_direction_decision_params(probabilities: pd.DataFrame, true_labels: np.ndarray | pd.Series) -> dict[str, Any] | None:
    """Tune UP/DOWN/WATCH decisions on a training-only calibration slice.

    Raw balanced/F1 optimization can select an active-looking model whose plain
    accuracy is below the majority-class baseline. This tuner treats that
    baseline as the first gate, then uses balanced accuracy and F1 to choose
    among the candidates that pass it.
    """
    if probabilities.empty:
        return None
    y_true = np.asarray(true_labels, dtype=int)
    if y_true.size < 12 or len(np.unique(y_true)) < 2:
        return None
    counts = np.bincount(y_true, minlength=len(DIRECTION_LABELS))
    majority_label = int(counts.argmax())
    baseline_accuracy = float(counts.max() / max(y_true.size, 1))
    actual_down_ratio = float(counts[DIRECTION_DOWN] / max(y_true.size, 1))
    max_down_coverage = min(0.42, max(0.12, actual_down_ratio * 1.15))

    def candidate_metrics(predictions: np.ndarray) -> dict[str, float]:
        accuracy = float(accuracy_score(y_true, predictions))
        balanced = float(balanced_accuracy_score(y_true, predictions))
        macro_f1 = float(f1_score(y_true, predictions, labels=DIRECTION_LABELS, average="macro", zero_division=0))
        lift = accuracy - baseline_accuracy
        matrix = confusion_matrix(y_true, predictions, labels=DIRECTION_LABELS)
        down_true_positive = float(matrix[DIRECTION_DOWN, DIRECTION_DOWN])
        down_actual = float(matrix[DIRECTION_DOWN, :].sum())
        down_predicted = float(matrix[:, DIRECTION_DOWN].sum())
        down_recall = down_true_positive / down_actual if down_actual else 0.0
        down_precision = down_true_positive / down_predicted if down_predicted else 0.0
        predicted_down_ratio = down_predicted / float(max(y_true.size, 1))
        if RISK_TARGET_ENABLED:
            score = (
                down_precision * 0.36
                + down_recall * 0.28
                + balanced * 0.18
                + macro_f1 * 0.10
                + max(lift, -0.20) * 0.08
            )
            if predicted_down_ratio < 0.03:
                score -= (0.03 - predicted_down_ratio) * 2.0
            if predicted_down_ratio > max_down_coverage:
                score -= (predicted_down_ratio - max_down_coverage) * 3.5
            if down_precision < 0.35 and predicted_down_ratio > actual_down_ratio:
                score -= (0.35 - down_precision) * 1.5
        else:
            score = balanced * 0.45 + macro_f1 * 0.30 + max(lift, -0.20) * 0.25
            if lift < 0:
                score -= min(abs(lift), 0.30) * 1.2
        return {
            "accuracy": accuracy,
            "balanced": balanced,
            "macro_f1": macro_f1,
            "lift": lift,
            "down_recall": down_recall,
            "down_precision": down_precision,
            "predicted_down_ratio": predicted_down_ratio,
            "score": score,
        }

    base_predictions = direction_from_probabilities(probabilities).to_numpy(dtype=int)
    best_metrics = candidate_metrics(base_predictions)
    best_params: dict[str, Any] | None = {"mode": "argmax"}
    for min_direction_prob in (0.34, 0.38, 0.42, 0.46, 0.50, 0.55, 0.60, 0.66, 0.72, 0.78):
        for min_direction_margin in (-0.04, 0.0, 0.04, 0.08, 0.12, 0.16, 0.20, 0.24):
            params = {
                "mode": "direction_gate",
                "min_direction_prob": float(min_direction_prob),
                "min_direction_margin": float(min_direction_margin),
            }
            candidate = direction_from_probabilities(probabilities, params).to_numpy(dtype=int)
            metrics = candidate_metrics(candidate)
            if metrics["score"] > best_metrics["score"] + 1e-6:
                best_metrics = metrics
                best_params = params
    if best_metrics["lift"] >= BASELINE_GUARD_LIFT_FLOOR or (
        RISK_TARGET_ENABLED
        and best_metrics["down_recall"] > 0
        and best_metrics["down_precision"] >= 0.30
        and best_metrics["predicted_down_ratio"] >= 0.03
        and best_metrics["predicted_down_ratio"] <= max_down_coverage + 0.05
    ):
        return {
            **(best_params or {"mode": "argmax"}),
            "calibration_accuracy": best_metrics["accuracy"],
            "calibration_majority_baseline": baseline_accuracy,
            "calibration_lift_over_baseline": best_metrics["lift"],
            "calibration_down_recall": best_metrics["down_recall"],
            "calibration_down_precision": best_metrics["down_precision"],
            "calibration_predicted_down_ratio": best_metrics["predicted_down_ratio"],
            "calibration_max_down_coverage": max_down_coverage,
        }
    return {
        "mode": "majority_class",
        "label": majority_label,
        "calibration_accuracy": baseline_accuracy,
        "calibration_majority_baseline": baseline_accuracy,
        "calibration_lift_over_baseline": 0.0,
        "fallback_reason": "model_decision_below_guard_floor",
    }


def apply_alert_confidence_filter(frame: pd.DataFrame, movement_threshold: float | None = None) -> pd.DataFrame:
    """Build a conservative alert signal without changing the raw model signal."""
    result = frame.copy()
    if "predicted_signal" not in result.columns or "confidence" not in result.columns:
        return result
    result["predicted_signal"] = result["predicted_signal"].where(
        result["predicted_signal"].isin({"UP", "DOWN", "WATCH"}),
        "WATCH",
    )
    result["alert_signal"] = result["predicted_signal"].fillna("WATCH")
    if "predicted_direction" in result.columns:
        result["alert_direction"] = result["predicted_direction"]
    up_threshold = float(settings.ml_alert_up_confidence_threshold)
    down_threshold = float(settings.ml_alert_down_confidence_threshold)
    if RISK_TARGET_ENABLED:
        down_threshold = min(down_threshold, 0.68)
    movement_threshold = abs(float(movement_threshold if movement_threshold is not None else DIRECTION_FIXED_THRESHOLD or MIN_DIRECTION_RETURN))
    confidence = pd.to_numeric(result["confidence"], errors="coerce").fillna(0)
    low_confidence_up = (result["predicted_signal"] == "UP") & (confidence < up_threshold)
    low_confidence_down = (result["predicted_signal"] == "DOWN") & (confidence < down_threshold)
    weak_down_return = pd.Series(False, index=result.index)
    predicted_return = None
    if "predicted_return" in result.columns:
        predicted_return = pd.to_numeric(result["predicted_return"], errors="coerce").fillna(0.0)
        if not RISK_TARGET_ENABLED:
            weak_down_return = (result["predicted_signal"] == "DOWN") & (predicted_return > -movement_threshold)
    weak_down_evidence = pd.Series(False, index=result.index)
    if RISK_TARGET_ENABLED:
        down_score, evidence_count = downside_risk_score(result)
        result["down_risk_score"] = down_score
        result["down_evidence_count"] = evidence_count
        result["model_risk_score"] = numeric_series(result, "prob_down").clip(0, 1)
        result["technical_risk_score"] = down_score
        result["sequence_risk_score"] = numeric_series(result, "sequence_risk_score").clip(0, 1)
        result["final_risk_score"] = down_score
        if predicted_return is not None:
            strong_risk_evidence = (down_score >= max(DOWN_ALERT_RISK_SCORE_THRESHOLD + 0.12, 0.67)) & (evidence_count >= 2)
            weak_down_return = (
                (result["predicted_signal"] == "DOWN")
                & (predicted_return > -RISK_ALERT_MIN_RETURN)
                & ~strong_risk_evidence
            )
        weak_down_evidence = (result["predicted_signal"] == "DOWN") & (
            (down_score < DOWN_ALERT_RISK_SCORE_THRESHOLD) | (evidence_count < 1)
        )
    else:
        result["model_risk_score"] = numeric_series(result, "prob_down").clip(0, 1)
        result["technical_risk_score"] = 0.0
        result["sequence_risk_score"] = numeric_series(result, "sequence_risk_score").clip(0, 1)
        result["final_risk_score"] = result["model_risk_score"]
    weak_alert = low_confidence_up | low_confidence_down | weak_down_return | weak_down_evidence
    if not weak_alert.any():
        result["alert_signal"] = result["alert_signal"].where(result["alert_signal"].isin({"UP", "DOWN", "WATCH"}), "WATCH")
        return result
    result.loc[weak_alert, "alert_signal"] = DIRECTION_SIGNAL_MAP[DIRECTION_FLAT]
    if "predicted_direction" in result.columns:
        result.loc[weak_alert, "alert_direction"] = DIRECTION_FLAT
    result["alert_signal"] = result["alert_signal"].where(result["alert_signal"].isin({"UP", "DOWN", "WATCH"}), "WATCH")
    return result


def model_decision_params(model_result: ModelResult) -> dict[str, Any] | None:
    if not model_result.extra:
        return None
    params = model_result.extra.get("decision_params")
    return params if isinstance(params, dict) and params.get("mode") else None


def model_direction_threshold(model_result: ModelResult) -> float:
    if model_result.extra and "direction_threshold" in model_result.extra:
        return float(model_result.extra["direction_threshold"])
    if model_result.name in OPTIMAL_MODEL_CONFIGS:
        return float(OPTIMAL_MODEL_CONFIGS[model_result.name]["direction_threshold"])
    return float(DIRECTION_FIXED_THRESHOLD if DIRECTION_FIXED_THRESHOLD is not None else MIN_DIRECTION_RETURN)


def predict_latest_tabular(df: pd.DataFrame, model_result: ModelResult, version: str, index_df: pd.DataFrame | None = None) -> pd.DataFrame:
    latest = add_technical_features(df, index_df).sort_values("event_time").groupby("symbol").tail(1).copy()
    features = latest[TABULAR_FEATURES]
    predicted_return = np.asarray(model_result.price_model.predict(features), dtype=float).reshape(-1)
    latest["predicted_return"] = predicted_return
    latest["predicted_next_price"] = (latest["last_price"].to_numpy(dtype=float) * (1 + predicted_return)).round(2)
    probabilities = predict_direction_probabilities(model_result.direction_model, features)
    latest[["prob_down", "prob_up", "prob_flat"]] = probabilities
    latest["predicted_direction"] = direction_from_probabilities(probabilities, model_decision_params(model_result))
    latest["predicted_signal"] = latest["predicted_direction"].map(DIRECTION_SIGNAL_MAP)
    latest = apply_return_signal_override(latest)
    latest["confidence"] = display_confidence(probabilities)
    latest["sequence_risk_score"] = 0.0
    latest["model_version"] = f"{model_result.name}-{version}"
    return apply_alert_confidence_filter(latest, movement_threshold=model_direction_threshold(model_result))


def predict_latest_lstm(df: pd.DataFrame, model_result: ModelResult, version: str, index_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Internal ML pipeline helper."""
    if model_result.extra is None:
        raise ValueError("LSTM model extra metadata is missing.")

    scaler: StandardScaler = model_result.extra["scaler"]
    window_size = int(model_result.extra["window_size"])
    sorted_df = add_technical_features(df, index_df)
    rows: list[pd.Series] = []
    x_values: list[np.ndarray] = []
    for _, group in sorted_df.groupby("symbol"):
        if len(group) < window_size:
            continue
        latest_window = group.tail(window_size)
        scaled = scaler.transform(latest_window[SEQUENCE_FEATURES].to_numpy(dtype=np.float32))
        x_values.append(scaled.astype(np.float32))
        rows.append(latest_window.tail(1).iloc[0])

    if not x_values:
        raise ValueError("No stock has enough recent ticks for LSTM prediction.")

    latest = pd.DataFrame(rows).copy()
    x_array = np.asarray(x_values)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model_result.price_model.to(device)
    model_result.direction_model.to(device)
    model_result.price_model.eval()
    model_result.direction_model.eval()
    with torch.no_grad():
        x_tensor = torch.tensor(x_array, dtype=torch.float32).to(device)
        predicted_return = model_result.price_model(x_tensor).cpu().numpy().reshape(-1)
        direction_probability = torch.softmax(model_result.direction_model(x_tensor), dim=1).cpu().numpy()
        latest["predicted_return"] = predicted_return
        latest["predicted_next_price"] = (latest["last_price"].to_numpy(dtype=float) * (1 + predicted_return)).round(2)
        probabilities = pd.DataFrame(direction_probability, index=latest.index, columns=["prob_down", "prob_up", "prob_flat"])
        latest[["prob_down", "prob_up", "prob_flat"]] = probabilities
        latest["predicted_direction"] = direction_from_probabilities(probabilities, model_decision_params(model_result))
    model_result.price_model.cpu()
    model_result.direction_model.cpu()
    latest["predicted_signal"] = latest["predicted_direction"].map(DIRECTION_SIGNAL_MAP)
    latest = apply_return_signal_override(latest)
    latest["confidence"] = display_confidence(latest[["prob_down", "prob_up", "prob_flat"]])
    latest["sequence_risk_score"] = pd.to_numeric(latest["prob_down"], errors="coerce").fillna(0.0).clip(0, 1)
    latest["model_version"] = f"{model_result.name}-{version}"
    return apply_alert_confidence_filter(latest, movement_threshold=model_direction_threshold(model_result))


def predict_latest(df: pd.DataFrame, model_result: ModelResult, version: str, index_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Internal ML pipeline helper."""
    if model_result.model_type == "sequence":
        return predict_latest_lstm(df, model_result, version, index_df)
    return predict_latest_tabular(df, model_result, version, index_df)


def ensemble_weight_score(result: ModelResult) -> float:
    """Weight ensemble members by robust direction quality, not raw accuracy alone."""
    wf_balanced = metric_value(result, "_walk_forward_balanced_direction_accuracy", 0.0)
    balanced = metric_value(result, "_balanced_direction_accuracy", wf_balanced)
    macro_f1 = metric_value(result, "_walk_forward_direction_macro_f1", metric_value(result, "_direction_macro_f1", 0.0))
    primary_lift = metric_value(result, "_direction_lift_over_baseline", 0.0)
    lift = metric_value(result, "_walk_forward_direction_lift_over_baseline", primary_lift)
    calibration_lift = metric_value(result, "_calibration_lift_over_baseline", 0.0)
    alert_hit = metric_value(result, "_alert_backtest_hit_rate", 0.0)
    alert_coverage = metric_value(result, "_alert_backtest_coverage", 0.0)
    if RISK_TARGET_ENABLED:
        down_recall = metric_value(result, "_walk_forward_down_recall", metric_value(result, "_down_recall", 0.0))
        down_precision = metric_value(result, "_walk_forward_down_precision", metric_value(result, "_down_precision", 0.0))
        down_coverage = metric_value(result, "_walk_forward_predicted_down_ratio", metric_value(result, "_predicted_down_ratio", 0.0))
        down_hit = metric_value(result, "_alert_backtest_down_hit_rate", alert_hit)
        down_inverse_return = metric_value(result, "_alert_backtest_down_avg_inverse_return", 0.0)
        if down_recall <= 0 or down_coverage <= 0:
            return 0.005
        score = (
            down_recall * 0.38
            + down_precision * 0.22
            + wf_balanced * 0.16
            + macro_f1 * 0.10
            + min(max(down_hit - 0.35, 0.0), 0.35) * 0.08
            + min(max(down_inverse_return, 0.0), 0.08) * 0.06
        )
        if down_coverage < 0.03:
            score *= 0.50
        if down_coverage > 0.60:
            score *= 0.35
        elif down_coverage > 0.50:
            score *= 0.55
        elif down_coverage > 0.42:
            score *= 0.75
        return max(float(score), 0.005)
    if lift <= -0.03 or primary_lift <= -0.03:
        return 0.005
    score = (
        wf_balanced * 0.45
        + balanced * 0.20
        + macro_f1 * 0.20
        + max(lift, -0.20) * 0.10
        + max(primary_lift, -0.20) * 0.05
        + min(max(alert_hit - 0.33, 0.0), 0.25) * 0.04
        + min(max(calibration_lift, 0.0), 0.20) * 0.01
    )
    if lift < 0:
        score *= max(0.15, 1.0 + lift * 8.0)
    if primary_lift < 0:
        score *= max(0.15, 1.0 + primary_lift * 8.0)
    if alert_coverage <= 0:
        score *= 0.80
    if result.name == "lstm":
        score *= 0.70
        if lift <= 0:
            score *= 0.20
        if lift <= -0.03:
            score *= 0.50
    elif result.name == "random_forest":
        score *= 0.85
    score = max(score, 0.005)
    return float(score)


def normalized_ensemble_weights(results: list[ModelResult]) -> dict[str, float]:
    """Build production weights with LightGBM as the risk model anchor.

    LSTM is useful as a sequence feature extractor, but recent experiments show
    it can dominate the ensemble while producing unstable DOWN calls. In risk
    mode it is capped as an auxiliary signal and LightGBM keeps the main vote.
    """
    raw_weights = {result.name: ensemble_weight_score(result) for result in results}
    raw_weights = {name: weight for name, weight in raw_weights.items() if weight > 0}
    if not raw_weights:
        return {}

    if not RISK_TARGET_ENABLED or "lightgbm" not in raw_weights:
        total = sum(raw_weights.values())
        return {name: float(weight / total) for name, weight in raw_weights.items()} if total > 0 else {}

    lightgbm_min_weight = min(max(LIGHTGBM_MIN_WEIGHT, 0.0), 1.0)
    aux_budget = max(0.0, 1.0 - lightgbm_min_weight)
    aux_names = [name for name in raw_weights if name != "lightgbm"]
    aux_scores = {name: raw_weights[name] for name in aux_names}
    aux_total = sum(aux_scores.values())
    weights: dict[str, float] = {}

    if aux_total > 0 and aux_budget > 0:
        by_name = {result.name: result for result in results}
        for name, score in aux_scores.items():
            cap = aux_budget
            result = by_name.get(name)
            if name == "lstm":
                cap = min(cap, LSTM_AUX_MAX_WEIGHT)
                if result is not None:
                    wf_lift = metric_value(result, "_walk_forward_direction_lift_over_baseline", 0.0)
                    down_inverse_return = metric_value(result, "_alert_backtest_down_avg_inverse_return", 0.0)
                    guard_used = metric_value(result, "_walk_forward_validation_guard_used", 0.0)
                    down_coverage = metric_value(result, "_walk_forward_predicted_down_ratio", 0.0)
                    if wf_lift <= 0 or down_inverse_return <= 0 or guard_used >= 1:
                        cap = min(cap, 0.05)
                    if down_coverage > 0.55:
                        cap = min(cap, 0.03)
            elif name == "random_forest":
                cap = min(cap, 0.05)
            weights[name] = min(aux_budget * score / aux_total, cap)

    aux_sum = min(sum(weights.values()), max(0.0, 1.0 - lightgbm_min_weight))
    weights["lightgbm"] = max(lightgbm_min_weight, 1.0 - aux_sum)
    total = sum(weights.values())
    return {name: float(weight / total) for name, weight in weights.items()} if total > 0 else {"lightgbm": 1.0}


def predict_latest_ensemble(df: pd.DataFrame, results: list[ModelResult], version: str, index_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Combine available model probabilities with walk-forward-based dynamic weights."""
    model_map = {result.name: result for result in results}
    candidates = [model_map[name] for name in ("lightgbm", "lstm", "random_forest") if name in model_map]
    if len(candidates) < 2:
        fallback_results = [result for result in results if result.name != "random_forest"] or results
        return predict_latest(df, select_best_model(fallback_results), version, index_df)

    weights = normalized_ensemble_weights(candidates)
    weighted_predictions: list[tuple[str, float, pd.DataFrame]] = []
    for result in candidates:
        weight = weights.get(result.name, 0.0)
        if weight <= 0:
            continue
        prediction = predict_latest_lstm(df, result, version, index_df) if result.model_type == "sequence" else predict_latest_tabular(df, result, version, index_df)
        weighted_predictions.append((result.name, weight, prediction))
    if len(weighted_predictions) < 2:
        fallback_results = [result for result in results if result.name != "random_forest"] or results
        return predict_latest(df, select_best_model(fallback_results), version, index_df)

    base_columns = ["symbol", "company_name", "category", "sector", "last_price"]
    evidence_columns = [column for column in DOWN_RISK_EVIDENCE_COLUMNS if column in weighted_predictions[0][2].columns]
    merged = weighted_predictions[0][2][[*base_columns, *evidence_columns]].copy()
    for name, _, prediction in weighted_predictions:
        model_columns = ["symbol", "predicted_next_price", "prob_down", "prob_up", "prob_flat", "sequence_risk_score"]
        renamed = prediction[model_columns].rename(
            columns={column: f"{column}_{name}" for column in model_columns if column != "symbol"}
        )
        merged = merged.merge(renamed, on="symbol", how="inner")

    total_weight = sum(weight for _, weight, _ in weighted_predictions)
    movement_threshold = (
        sum(model_direction_threshold(model_map[name]) * weight for name, weight, _ in weighted_predictions) / total_weight
        if total_weight > 0
        else float(DIRECTION_FIXED_THRESHOLD if DIRECTION_FIXED_THRESHOLD is not None else MIN_DIRECTION_RETURN)
    )
    merged["predicted_next_price"] = (
        sum(merged[f"predicted_next_price_{name}"] * weight for name, weight, _ in weighted_predictions) / total_weight
    ).round(2)
    last_price = pd.to_numeric(merged["last_price"], errors="coerce").replace(0, np.nan)
    merged["predicted_return"] = (
        (pd.to_numeric(merged["predicted_next_price"], errors="coerce") - last_price) / last_price
    ).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    for column in ("prob_down", "prob_up", "prob_flat"):
        merged[column] = (sum(merged[f"{column}_{name}"] * weight for name, weight, _ in weighted_predictions) / total_weight).clip(0, 1)
    merged["sequence_risk_score"] = (
        sum(merged[f"sequence_risk_score_{name}"] * weight for name, weight, _ in weighted_predictions) / total_weight
    ).clip(0, 1)
    probabilities = merged[["prob_down", "prob_up", "prob_flat"]]
    merged["predicted_direction"] = direction_from_probabilities(probabilities)
    merged["confidence"] = display_confidence(probabilities)
    merged["predicted_signal"] = merged["predicted_direction"].map(DIRECTION_SIGNAL_MAP)
    merged = apply_return_signal_override(merged)
    merged["model_version"] = f"ensemble-{version}"
    merged = apply_alert_confidence_filter(merged, movement_threshold=movement_threshold)
    return merged[
        [
            "symbol",
            "company_name",
            "category",
            "sector",
            "last_price",
            "predicted_next_price",
            "predicted_signal",
            "alert_signal",
            "confidence",
            "model_risk_score",
            "technical_risk_score",
            "sequence_risk_score",
            "final_risk_score",
            "model_version",
        ]
    ]


def collect_metrics(results: list[ModelResult], best_model_name: str) -> list[tuple[str, str, float]]:
    """Internal ML pipeline helper."""
    metrics: list[tuple[str, str, float]] = []
    for result in results:
        for metric_name, metric_value in result.metrics.items():
            normalized_metric = metric_name.removeprefix(f"{result.name}_")
            metrics.append((result.name, normalized_metric, float(metric_value)))
    ensemble_candidates = [result for result in results if result.name in {"lstm", "lightgbm", "random_forest"}]
    if len(ensemble_candidates) >= 2:
        for model_name, weight in normalized_ensemble_weights(ensemble_candidates).items():
            metrics.append(("ensemble", f"{model_name}_weight", float(weight)))
    metrics.append(("prediction", "return_signal_override_threshold", float(PREDICTION_RETURN_SIGNAL_THRESHOLD)))
    metrics.append(("prediction", "prediction_horizon", float(PREDICTION_HORIZON)))
    metrics.append(("prediction", "target_downside_risk_enabled", 1.0 if RISK_TARGET_ENABLED else 0.0))
    metrics.append(("prediction", "risk_downside_threshold", float(RISK_DOWNSIDE_THRESHOLD)))
    metrics.append(("prediction", "risk_volatility_threshold", float(RISK_VOLATILITY_THRESHOLD)))
    metrics.append(("prediction", "risk_alert_min_return", float(RISK_ALERT_MIN_RETURN)))
    metrics.append(("prediction", "down_alert_risk_score_threshold", float(DOWN_ALERT_RISK_SCORE_THRESHOLD)))
    metrics.append(("prediction", "lstm_aux_max_weight", float(LSTM_AUX_MAX_WEIGHT)))
    metrics.append(("prediction", "lightgbm_min_weight", float(LIGHTGBM_MIN_WEIGHT)))
    metrics.append(("selection", "best_model_code", float({"random_forest": 1, "lightgbm": 2, "lstm": 3}.get(best_model_name, 0))))
    return metrics


def write_results(predictions: pd.DataFrame, metrics: list[tuple[str, str, float]], version: str, update_metrics: bool = True) -> None:
    """Internal ML pipeline helper."""
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset="utf8mb4",
        autocommit=False,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ml_prediction_history (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    symbol VARCHAR(32) NOT NULL,
                    company_name VARCHAR(255) NOT NULL,
                    category VARCHAR(64) NOT NULL,
                    sector VARCHAR(64) NOT NULL,
                    current_price DECIMAL(18, 2) NOT NULL,
                    predicted_next_price DECIMAL(18, 2) NOT NULL,
                    predicted_signal VARCHAR(16) NOT NULL,
                    alert_signal VARCHAR(16) NOT NULL DEFAULT 'WATCH',
                    confidence DECIMAL(8, 4) NOT NULL DEFAULT 0,
                    model_risk_score DECIMAL(8, 4) NOT NULL DEFAULT 0,
                    technical_risk_score DECIMAL(8, 4) NOT NULL DEFAULT 0,
                    sequence_risk_score DECIMAL(8, 4) NOT NULL DEFAULT 0,
                    final_risk_score DECIMAL(8, 4) NOT NULL DEFAULT 0,
                    model_version VARCHAR(64) NOT NULL,
                    predicted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    KEY idx_ml_prediction_history_symbol_time (symbol, predicted_at),
                    KEY idx_ml_prediction_history_model_time (model_version, predicted_at),
                    KEY idx_ml_prediction_history_signal_time (predicted_signal, predicted_at),
                    KEY idx_ml_prediction_history_alert_signal_time (alert_signal, predicted_at)
                )
                """
            )
            for table_name in ("ml_predictions", "ml_prediction_history"):
                try:
                    cursor.execute(
                        f"""
                        ALTER TABLE {table_name}
                        ADD COLUMN alert_signal VARCHAR(16) NOT NULL DEFAULT 'WATCH' COMMENT 'confidence-filtered alert signal'
                        AFTER predicted_signal
                        """
                    )
                except Exception:
                    pass
            for table_name in ("ml_predictions", "ml_prediction_history"):
                for column_name in (
                    "model_risk_score",
                    "technical_risk_score",
                    "sequence_risk_score",
                    "final_risk_score",
                ):
                    try:
                        cursor.execute(
                            f"""
                            ALTER TABLE {table_name}
                            ADD COLUMN {column_name} DECIMAL(8, 4) NOT NULL DEFAULT 0
                            AFTER confidence
                            """
                        )
                    except Exception:
                        pass
            cursor.execute("DELETE FROM ml_predictions")
            if update_metrics:
                cursor.execute("DELETE FROM ml_model_metrics")
            for row in predictions.itertuples(index=False):
                raw_signal = str(row.predicted_signal)
                alert_signal = str(getattr(row, "alert_signal", raw_signal))
                if raw_signal not in DIRECTION_SIGNAL_MAP.values():
                    raw_signal = DIRECTION_SIGNAL_MAP[DIRECTION_FLAT]
                if alert_signal not in DIRECTION_SIGNAL_MAP.values():
                    alert_signal = DIRECTION_SIGNAL_MAP[DIRECTION_FLAT]
                current_values = (
                    row.symbol,
                    row.company_name,
                    row.category,
                    row.sector,
                    float(row.last_price),
                    float(row.predicted_next_price),
                    raw_signal,
                    alert_signal,
                    float(getattr(row, "confidence", 0.0)),
                    float(getattr(row, "model_risk_score", 0.0)),
                    float(getattr(row, "technical_risk_score", 0.0)),
                    float(getattr(row, "sequence_risk_score", 0.0)),
                    float(getattr(row, "final_risk_score", 0.0)),
                    row.model_version,
                )
                history_values = (
                    row.symbol,
                    row.company_name,
                    row.category,
                    row.sector,
                    float(row.last_price),
                    float(row.predicted_next_price),
                    raw_signal,
                    alert_signal,
                    float(getattr(row, "confidence", 0.0)),
                    float(getattr(row, "model_risk_score", 0.0)),
                    float(getattr(row, "technical_risk_score", 0.0)),
                    float(getattr(row, "sequence_risk_score", 0.0)),
                    float(getattr(row, "final_risk_score", 0.0)),
                    row.model_version,
                )
                cursor.execute(
                    """
                    INSERT INTO ml_predictions
                    (symbol, company_name, category, sector, current_price, predicted_next_price, predicted_signal, alert_signal,
                     confidence, model_risk_score, technical_risk_score, sequence_risk_score, final_risk_score, model_version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    current_values,
                )
                cursor.execute(
                    """
                    INSERT INTO ml_prediction_history
                    (symbol, company_name, category, sector, current_price, predicted_next_price, predicted_signal, alert_signal,
                     confidence, model_risk_score, technical_risk_score, sequence_risk_score, final_risk_score, model_version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    history_values,
                )
            if update_metrics:
                for model_name, metric_name, metric_value in metrics:
                    cursor.execute(
                        """
                        INSERT INTO ml_model_metrics (model_name, metric_name, metric_value, model_version)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (model_name, metric_name, float(metric_value), version),
                    )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
