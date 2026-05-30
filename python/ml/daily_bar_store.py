from __future__ import annotations

from typing import Any


DAILY_STOCK_SOURCE = "akshare_cold_start"
DAILY_INDEX_SOURCE = "akshare_index"
DAILY_STOCK_TABLE = "daily_stock_bars"
DAILY_INDEX_TABLE = "daily_index_bars"
DAILY_SOURCE_TABLES = {
    DAILY_STOCK_SOURCE: DAILY_STOCK_TABLE,
    DAILY_INDEX_SOURCE: DAILY_INDEX_TABLE,
}
DAILY_BAR_COLUMNS = [
    "event_id",
    "symbol",
    "company_name",
    "category",
    "sector",
    "market",
    "trade_date",
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
]
DAILY_BAR_SELECT_COLUMNS = [
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
]


def daily_table_for_source(source: str | None) -> str | None:
    return DAILY_SOURCE_TABLES.get(str(source or "").strip())


def ensure_daily_bar_tables(cursor: Any) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {DAILY_STOCK_TABLE} (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            event_id VARCHAR(64) NOT NULL,
            symbol VARCHAR(32) NOT NULL,
            company_name VARCHAR(255) NOT NULL,
            category VARCHAR(64) NOT NULL,
            sector VARCHAR(64) NOT NULL,
            market VARCHAR(32) NOT NULL,
            trade_date DATE NOT NULL,
            open_price DECIMAL(18, 2) NOT NULL,
            high_price DECIMAL(18, 2) NOT NULL,
            low_price DECIMAL(18, 2) NOT NULL,
            last_price DECIMAL(18, 2) NOT NULL,
            previous_close DECIMAL(18, 2) NOT NULL,
            change_pct DECIMAL(18, 4) NOT NULL,
            volume BIGINT NOT NULL,
            turnover DECIMAL(20, 2) NOT NULL,
            event_time DATETIME NOT NULL,
            source VARCHAR(32) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_daily_stock_bars_event_id (event_id),
            UNIQUE KEY uk_daily_stock_bars_symbol_date_source (symbol, trade_date, source),
            KEY idx_daily_stock_bars_symbol_time (symbol, event_time),
            KEY idx_daily_stock_bars_event_time (event_time),
            KEY idx_daily_stock_bars_source_time (source, event_time)
        ) COMMENT='Daily stock bars for ML training'
        """
    )
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {DAILY_INDEX_TABLE} (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            event_id VARCHAR(64) NOT NULL,
            symbol VARCHAR(32) NOT NULL,
            company_name VARCHAR(255) NOT NULL,
            category VARCHAR(64) NOT NULL,
            sector VARCHAR(64) NOT NULL,
            market VARCHAR(32) NOT NULL,
            trade_date DATE NOT NULL,
            open_price DECIMAL(18, 2) NOT NULL,
            high_price DECIMAL(18, 2) NOT NULL,
            low_price DECIMAL(18, 2) NOT NULL,
            last_price DECIMAL(18, 2) NOT NULL,
            previous_close DECIMAL(18, 2) NOT NULL,
            change_pct DECIMAL(18, 4) NOT NULL,
            volume BIGINT NOT NULL,
            turnover DECIMAL(20, 2) NOT NULL,
            event_time DATETIME NOT NULL,
            source VARCHAR(32) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_daily_index_bars_event_id (event_id),
            UNIQUE KEY uk_daily_index_bars_symbol_date_source (symbol, trade_date, source),
            KEY idx_daily_index_bars_symbol_time (symbol, event_time),
            KEY idx_daily_index_bars_event_time (event_time),
            KEY idx_daily_index_bars_source_time (source, event_time)
        ) COMMENT='Daily market index bars for ML features'
        """
    )


def add_trade_date(quote: dict) -> dict:
    result = dict(quote)
    if "trade_date" not in result:
        result["trade_date"] = str(result["event_time"]).split()[0]
    return result
