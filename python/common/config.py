"""Central runtime configuration.

Values are read from `python/.env` first and then from operating-system
environment variables. Defaults are kept local-demo friendly so the project can
start on a Windows development machine without extra parameters.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file() -> None:
    """Load `python/.env` into environment variables if the file exists."""

    # 本地演示经常在不同终端启动 Python、Spark 和后端，优先读取 python/.env
    # 可以减少手动设置环境变量的步骤；系统环境变量仍然拥有更高优先级。
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env_file()


class Settings:
    """Typed access to Kafka, MySQL, HDFS, crawler and ML settings."""

    # Kafka receives quote events from the Python producer and feeds Spark.
    kafka_bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092")
    kafka_topic = os.getenv("KAFKA_TOPIC", "stock_realtime_topic")

    # MySQL stores raw ticks, aggregates, alerts and ML outputs for the backend.
    mysql_host = os.getenv("MYSQL_HOST", "127.0.0.1")
    mysql_port = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_user = os.getenv("MYSQL_USER", "root")
    mysql_password = os.getenv("MYSQL_PASSWORD", "root")
    mysql_database = os.getenv("MYSQL_DATABASE", "stock_stream")

    # HDFS paths are used by Spark for archive output and streaming checkpoint.
    hdfs_output_path = os.getenv("HDFS_OUTPUT_PATH", "/user/fqy/stock_output")
    hdfs_checkpoint_path = os.getenv("HDFS_CHECKPOINT_PATH", "/user/fqy/stock_checkpoint")

    # The normal stock pool comes from python/data/stock_symbols.json. This
    # fallback only applies if that JSON file is missing or invalid.
    # 行情采集与告警去重参数：冷却窗口用于避免同一股票同一规则在短时间内刷屏。
    stock_symbols = [item.strip() for item in os.getenv("STOCK_SYMBOLS", "600519,000001,00700").split(",") if item.strip()]
    quote_interval_seconds = float(os.getenv("QUOTE_INTERVAL_SECONDS", "5"))
    quote_source = os.getenv("QUOTE_SOURCE", "sina")
    quote_sources = [item.strip().lower() for item in os.getenv("QUOTE_SOURCES", "sina,tencent,eastmoney").split(",") if item.strip()]
    quote_output = os.getenv("QUOTE_OUTPUT", "data/stock_symbols.json")
    alert_duplicate_cooldown_minutes = int(os.getenv("ALERT_DUPLICATE_COOLDOWN_MINUTES", "10"))
    stock_producer_max_workers = int(os.getenv("STOCK_PRODUCER_MAX_WORKERS", "12"))
    http_timeout_seconds = int(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))
    http_user_agent = os.getenv(
        "HTTP_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    )

    # Machine-learning settings are intentionally environment-driven so the
    # user can run longer local training without changing code.
    ml_model_dir = os.getenv("ML_MODEL_DIR", "models")
    ml_min_train_size = int(os.getenv("ML_MIN_TRAIN_SIZE", "12"))
    ml_max_train_rows = int(os.getenv("ML_MAX_TRAIN_ROWS", "120000"))
    ml_require_gpu = os.getenv("ML_REQUIRE_GPU", "false").strip().lower() in {"1", "true", "yes", "on"}
    ml_lstm_epochs = int(os.getenv("ML_LSTM_EPOCHS", "60"))
    ml_lstm_fine_tune_epochs = int(os.getenv("ML_LSTM_FINE_TUNE_EPOCHS", "2"))
    ml_lstm_early_stop_patience = int(os.getenv("ML_LSTM_EARLY_STOP_PATIENCE", "8"))
    ml_lstm_max_sequences = int(os.getenv("ML_LSTM_MAX_SEQUENCES", "80000"))
    ml_lstm_window_size = int(os.getenv("ML_LSTM_WINDOW_SIZE", "30"))
    ml_lstm_hidden_size = int(os.getenv("ML_LSTM_HIDDEN_SIZE", "48"))
    ml_lstm_head_size = int(os.getenv("ML_LSTM_HEAD_SIZE", "32"))
    ml_lstm_num_layers = int(os.getenv("ML_LSTM_NUM_LAYERS", "1"))
    ml_lstm_dropout = float(os.getenv("ML_LSTM_DROPOUT", "0.40"))
    ml_lstm_learning_rate = float(os.getenv("ML_LSTM_LEARNING_RATE", "0.0003"))
    ml_lstm_weight_decay = float(os.getenv("ML_LSTM_WEIGHT_DECAY", "0.002"))
    ml_lstm_batch_size = int(os.getenv("ML_LSTM_BATCH_SIZE", "128"))
    ml_rf_full_calibration = os.getenv("ML_RF_FULL_CALIBRATION", "true").strip().lower() in {"1", "true", "yes", "on"}
    ml_rf_walk_forward = os.getenv("ML_RF_WALK_FORWARD", "true").strip().lower() in {"1", "true", "yes", "on"}
    ml_rf_n_jobs = int(os.getenv("ML_RF_N_JOBS", "4"))
    ml_training_lookback_days = int(os.getenv("ML_TRAINING_LOOKBACK_DAYS", "1500"))
    ml_direction_threshold = float(os.getenv("ML_DIRECTION_THRESHOLD", "0.020"))
    ml_prediction_horizon = int(os.getenv("ML_PREDICTION_HORIZON", "5"))
    ml_horizon_experiments = os.getenv("ML_HORIZON_EXPERIMENTS", "1,3,5")
    ml_prediction_return_signal_threshold = float(os.getenv("ML_PREDICTION_RETURN_SIGNAL_THRESHOLD", "0.003"))
    # 日线训练数据时效阈值。训练入口会在数据过旧时中止，避免前端展示“新预测、旧数据”的状态。
    ml_max_daily_data_age_days = int(os.getenv("ML_MAX_DAILY_DATA_AGE_DAYS", "10"))
    ml_allow_stale_daily_data = os.getenv("ML_ALLOW_STALE_DAILY_DATA", "false").strip().lower() in {"1", "true", "yes", "on"}
    # 告警侧置信度过滤只影响 alert_signal，不覆盖 predicted_signal，保证漂移检测评估真实模型方向。
    ml_alert_confidence_threshold = float(os.getenv("ML_ALERT_CONFIDENCE_THRESHOLD", "0.64"))
    ml_alert_up_confidence_threshold = float(os.getenv("ML_ALERT_UP_CONFIDENCE_THRESHOLD", os.getenv("ML_ALERT_CONFIDENCE_THRESHOLD", "0.64")))
    ml_alert_down_confidence_threshold = float(os.getenv("ML_ALERT_DOWN_CONFIDENCE_THRESHOLD", "0.75"))

    @property
    def mysql_jdbc_url(self) -> str:
        """JDBC URL used by Spark to write MySQL tables."""

        return (
            f"jdbc:mysql://{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            "?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai"
        )


settings = Settings()
