"""Spark Structured Streaming job for stock quote analytics.

Input:
    Kafka topic configured by `settings.kafka_topic`.

Output:
    - `price_ticks`: raw but de-duplicated quote records for detail pages.
    - `metric_snapshots`: market-wide minute snapshots for dashboard cards.
    - `symbol_stats`: per-stock aggregates for focus lists.
    - `sector_stats` and `category_stats`: heat-map data.
    - `alert_events`: price and volume anomaly alerts.
    - HDFS/parquet quote archive when HDFS is available.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyspark.sql import SparkSession, functions as F, types as T

from python.common.config import settings


def build_spark() -> SparkSession:
    """Create the SparkSession used by the streaming analytics job."""

    return (
        SparkSession.builder.appName("StockStreamingAnalytics")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate()
    )


def event_schema() -> T.StructType:
    """Kafka value JSON schema.

    The fields must match `python.producer.stock_sources.normalize_quote`.
    If the producer changes a field name, this schema must be changed too.
    """

    return T.StructType(
        [
            T.StructField("event_id", T.StringType()),
            T.StructField("symbol", T.StringType()),
            T.StructField("company_name", T.StringType()),
            T.StructField("category", T.StringType()),
            T.StructField("sector", T.StringType()),
            T.StructField("market", T.StringType()),
            T.StructField("open_price", T.DoubleType()),
            T.StructField("high_price", T.DoubleType()),
            T.StructField("low_price", T.DoubleType()),
            T.StructField("last_price", T.DoubleType()),
            T.StructField("previous_close", T.DoubleType()),
            T.StructField("change_pct", T.DoubleType()),
            T.StructField("volume", T.LongType()),
            T.StructField("turnover", T.DoubleType()),
            T.StructField("event_time", T.StringType()),
            T.StructField("source", T.StringType()),
        ]
    )


def parse_stream(spark: SparkSession):
    """Subscribe to Kafka and parse quote JSON into typed Spark columns."""

    # Kafka 中的 value 是生产者写入的 JSON 字符串，先按固定 schema 转成强类型列，后续才能做窗口聚合。
    raw = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", settings.kafka_bootstrap_servers)
        .option("subscribe", settings.kafka_topic)
        .option("startingOffsets", "latest")
        .option("failOnDataLoss", "false")
        .load()
    )
    parsed = raw.select(F.from_json(F.col("value").cast("string"), event_schema()).alias("data")).select("data.*")
    parsed = parsed.withColumn("event_time", F.to_timestamp("event_time", "yyyy-MM-dd HH:mm:ss"))
    market = F.upper(F.coalesce(F.col("market"), F.lit("")))

    # Keep only plausible domestic-market quotes. These sanity filters prevent
    # broken source responses from entering MySQL and skewing the dashboard.
    return parsed.filter(
        (F.col("last_price") > 0)
        & (F.col("volume") > 0)
        & (
            (market.isin("SH", "SZ", "BJ") & (F.abs(F.col("change_pct")) < F.lit(11.0)))
            | ((market == "HK") & (F.abs(F.col("change_pct")) < F.lit(50.0)))
        )
    )


def write_jdbc(df, table: str) -> None:
    """Append one micro-batch result DataFrame to a MySQL table."""

    options = {"user": settings.mysql_user, "password": settings.mysql_password, "driver": "com.mysql.cj.jdbc.Driver"}
    df.write.mode("append").jdbc(url=settings.mysql_jdbc_url, table=table, properties=options)


def read_history_baseline(batch_df):
    """Read recent ticks as dynamic alert baselines."""

    # 告警阈值不是纯固定值，而是参考近 1 天同股票的平均波动和平均成交量，让不同股票有各自基线。
    options = {"user": settings.mysql_user, "password": settings.mysql_password, "driver": "com.mysql.cj.jdbc.Driver"}
    try:
        history = batch_df.sparkSession.read.jdbc(
            url=settings.mysql_jdbc_url,
            table="(SELECT symbol, change_pct, volume FROM price_ticks WHERE created_at >= NOW() - INTERVAL 1 DAY) recent_price_ticks",
            properties=options,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] history baseline unavailable, fallback to fixed rules: {exc}")
        return batch_df.select("symbol").distinct().withColumn("avg_abs_change_pct", F.lit(0.0)).withColumn("avg_volume", F.lit(0.0))

    return (
        history.groupBy("symbol")
        .agg(
            F.avg(F.abs(F.col("change_pct"))).alias("avg_abs_change_pct"),
            F.avg("volume").alias("avg_volume"),
        )
        .fillna({"avg_abs_change_pct": 0.0, "avg_volume": 0.0})
    )


def read_latest_quote_state(batch_df):
    """Read the latest stored quote per symbol/source for duplicate filtering."""

    options = {"user": settings.mysql_user, "password": settings.mysql_password, "driver": "com.mysql.cj.jdbc.Driver"}
    try:
        return batch_df.sparkSession.read.jdbc(
            url=settings.mysql_jdbc_url,
            table="""
            (
                SELECT p.symbol, p.source, p.last_price, p.change_pct, p.volume
                FROM price_ticks p
                INNER JOIN (
                    SELECT symbol, source, MAX(id) AS id
                    FROM price_ticks
                    GROUP BY symbol, source
                ) latest ON p.id = latest.id
            ) latest_quotes
            """,
            properties=options,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] latest quote state unavailable, skip unchanged filter: {exc}")
        return None


def keep_changed_quotes(batch_df):
    """Drop repeated snapshots that have the same price, change and volume."""

    # 多数据源可能连续推送完全相同的快照；去掉重复点可以减少 MySQL 写入和后续训练标签噪声。
    compact_batch = batch_df.dropDuplicates(["symbol", "source", "last_price", "change_pct", "volume"])
    latest_state = read_latest_quote_state(compact_batch)
    if latest_state is None:
        return compact_batch

    current = compact_batch.alias("current")
    previous = latest_state.alias("previous")
    return (
        current.join(previous, on=["symbol", "source"], how="left")
        .filter(
            F.col("previous.last_price").isNull()
            | (~F.col("current.last_price").eqNullSafe(F.col("previous.last_price")))
            | (~F.col("current.change_pct").eqNullSafe(F.col("previous.change_pct")))
            | (~F.col("current.volume").eqNullSafe(F.col("previous.volume")))
        )
        .select("current.*")
    )


def write_dashboard_aggregates(raw_batch, batch_id: int) -> None:
    """Write dashboard aggregation tables for one micro-batch."""

    # 即使个股价格没有变化，也写入聚合心跳，首页可以据此判断实时流是否还在工作。
    with_window = raw_batch.withColumn("window_bucket", F.date_format("event_time", "yyyy-MM-dd HH:mm:00"))

    metrics = (
        with_window.groupBy("window_bucket")
        .agg(
            F.countDistinct("symbol").alias("symbol_count"),
            F.round(F.avg("last_price"), 2).alias("avg_price"),
            F.round(F.avg("change_pct"), 4).alias("avg_change_pct"),
            F.sum("volume").alias("total_volume"),
            F.round(F.sum("turnover"), 2).alias("total_turnover"),
        )
        .withColumn("batch_id", F.lit(batch_id))
        .withColumn("created_at", F.current_timestamp())
    )

    symbol_stats = (
        raw_batch.groupBy("symbol", "company_name", "category", "sector")
        .agg(
            F.round(F.max("last_price"), 2).alias("last_price"),
            F.round(F.avg("change_pct"), 4).alias("change_pct"),
            F.sum("volume").alias("volume"),
            F.round(F.sum("turnover"), 2).alias("turnover"),
        )
        .withColumn("batch_id", F.lit(batch_id))
        .withColumn("created_at", F.current_timestamp())
    )

    category_stats = (
        raw_batch.groupBy("category")
        .agg(
            F.countDistinct("symbol").alias("symbol_count"),
            F.round(F.avg("change_pct"), 4).alias("avg_change_pct"),
            F.round(F.sum("turnover"), 2).alias("turnover"),
        )
        .withColumn("batch_id", F.lit(batch_id))
        .withColumn("created_at", F.current_timestamp())
    )

    sector_stats = (
        raw_batch.groupBy("sector")
        .agg(
            F.countDistinct("symbol").alias("symbol_count"),
            F.round(F.avg("change_pct"), 4).alias("avg_change_pct"),
            F.round(F.sum("turnover"), 2).alias("turnover"),
        )
        .withColumn("batch_id", F.lit(batch_id))
        .withColumn("created_at", F.current_timestamp())
    )

    write_jdbc(metrics, "metric_snapshots")
    write_jdbc(symbol_stats, "symbol_stats")
    write_jdbc(sector_stats, "sector_stats")
    write_jdbc(category_stats, "category_stats")


def build_alerts(changed_batch):
    """Apply price/volume anomaly rules and return alert rows."""

    history_baseline = read_history_baseline(changed_batch)
    # Spark 告警规则核心：价格阈值取“固定最低阈值”和“历史平均波动倍数”的较大值；
    # 成交量阈值同理，并额外设置市场最低成交量，避免冷门股票小量波动误报。
    enriched_batch = (
        changed_batch.join(history_baseline, on="symbol", how="left")
        .fillna({"avg_abs_change_pct": 0.0, "avg_volume": 0.0})
        .withColumn(
            "volume_min_threshold",
            F.when(F.upper(F.col("market")).isin("SH", "SZ", "BJ"), F.lit(5_000_000.0))
            .when(F.upper(F.col("market")) == "HK", F.lit(1_000_000.0))
            .otherwise(F.lit(1_000_000.0)),
        )
        .withColumn("price_alert_threshold", F.greatest(F.lit(2.0), F.col("avg_abs_change_pct") * F.lit(2.5)))
        .withColumn("volume_alert_threshold", F.greatest(F.col("volume_min_threshold"), F.col("avg_volume") * F.lit(2.0)))
        .withColumn("price_high_threshold", F.greatest(F.lit(4.0), F.col("avg_abs_change_pct") * F.lit(4.0)))
        .withColumn("volume_high_threshold", F.greatest(F.col("volume_min_threshold") * F.lit(2.0), F.col("avg_volume") * F.lit(4.0)))
        .withColumn("price_trigger", F.abs(F.col("change_pct")) >= F.col("price_alert_threshold"))
        .withColumn("volume_trigger", F.col("volume") >= F.col("volume_alert_threshold"))
        .withColumn("price_high_trigger", F.abs(F.col("change_pct")) >= F.col("price_high_threshold"))
        .withColumn("volume_high_trigger", (F.col("avg_volume") > F.lit(0.0)) & (F.col("volume") >= F.col("volume_high_threshold")))
    )

    return (
        enriched_batch.filter(F.col("price_trigger") | F.col("volume_trigger"))
        .withColumn(
            "alert_type",
            F.when(
                F.col("price_trigger") & F.col("volume_trigger"),
                F.lit("price_and_volume")  # 两者都触发
            ).when(
                F.col("price_trigger"),
                F.lit("price_volatility")  # 只有价格触发
            ).otherwise(
                F.lit("volume_spike")  # 只有成交量触发
            )
        )
        .withColumn(
            "alert_level",
            F.when(
                F.col("price_high_trigger")
                | (F.col("price_trigger") & F.col("volume_trigger"))
                | F.col("volume_high_trigger"),
                F.lit("HIGH"),
            ).otherwise(F.lit("MEDIUM")),
        )
        .withColumn("created_at", F.current_timestamp())
        .select(
            "event_id",
            "symbol",
            "company_name",
            "category",
            "sector",
            "market",
            "open_price",
            "high_price",
            "low_price",
            "last_price",
            "previous_close",
            "change_pct",
            "volume",
            "turnover",
            "event_time",
            "source",
            "alert_type",
            "alert_level",
            "created_at",
            F.round("price_alert_threshold", 2).alias("price_threshold"),
            F.round("volume_alert_threshold", 0).cast("long").alias("volume_threshold"),
        )
    )


def suppress_recent_duplicate_alerts(alerts_df):
    """Suppress same-symbol same-rule alerts within a short cooldown window."""

    # 同一股票同一规则在冷却窗口内只保留一次，减少满屏重复高危告警。
    cooldown = max(0, int(settings.alert_duplicate_cooldown_minutes))
    if cooldown <= 0:
        return alerts_df

    options = {"user": settings.mysql_user, "password": settings.mysql_password, "driver": "com.mysql.cj.jdbc.Driver"}
    try:
        recent_alerts = alerts_df.sparkSession.read.jdbc(
            url=settings.mysql_jdbc_url,
            table=f"""
            (
                SELECT symbol, alert_type
                FROM alert_events
                WHERE created_at >= NOW() - INTERVAL {cooldown} MINUTE
            ) recent_alerts
            """,
            properties=options,
        ).dropDuplicates(["symbol", "alert_type"])
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] recent alert cooldown unavailable, write all alerts: {exc}", flush=True)
        return alerts_df

    return alerts_df.join(recent_alerts, on=["symbol", "alert_type"], how="left_anti")


def write_batch(batch_df, batch_id: int) -> None:
    """Process one Spark micro-batch.

    The batch first updates dashboard aggregates. Then it writes only changed
    quote snapshots and generated alerts, which keeps `price_ticks` smaller.
    """

    if batch_df.isEmpty():
        return

    # 每个微批次先按 event_id 去重，再分别写 HDFS 归档、仪表盘聚合、告警和明细行情。
    raw_batch = batch_df.dropDuplicates(["event_id"])
    try:
        raw_batch.write.mode("append").parquet(f"{settings.hdfs_output_path.rstrip('/')}/quotes")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] HDFS write failed for batch {batch_id}, continue MySQL writes: {exc}", flush=True)

    write_dashboard_aggregates(raw_batch, batch_id)

    changed_batch = keep_changed_quotes(raw_batch)
    if changed_batch.isEmpty():
        print(f"[info] batch {batch_id}: all quotes unchanged, wrote metric heartbeat only")
        return

    latest_quotes = changed_batch.withColumn("created_at", F.current_timestamp())
    write_jdbc(suppress_recent_duplicate_alerts(build_alerts(changed_batch)), "alert_events")
    write_jdbc(latest_quotes, "price_ticks")


def main() -> None:
    """Start the streaming query and keep it running."""

    spark = build_spark()
    stream_df = parse_stream(spark)
    query = (
        stream_df.writeStream.outputMode("append")
        .foreachBatch(write_batch)
        .option("checkpointLocation", settings.hdfs_checkpoint_path)
        .start()
    )
    query.awaitTermination()


if __name__ == "__main__":
    main()
