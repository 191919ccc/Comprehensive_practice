-- Split historical AKShare daily bars out of price_ticks.
-- This script is non-destructive: it creates/fills the new tables and keeps price_ticks unchanged.

CREATE TABLE IF NOT EXISTS daily_stock_bars (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT 'primary key',
    event_id VARCHAR(64) NOT NULL COMMENT 'unique daily bar event id',
    symbol VARCHAR(32) NOT NULL COMMENT 'stock symbol',
    company_name VARCHAR(255) NOT NULL COMMENT 'company name',
    category VARCHAR(64) NOT NULL COMMENT 'stock category',
    sector VARCHAR(64) NOT NULL COMMENT 'sector',
    market VARCHAR(32) NOT NULL COMMENT 'market',
    trade_date DATE NOT NULL COMMENT 'trade date',
    open_price DECIMAL(18, 2) NOT NULL COMMENT 'open price',
    high_price DECIMAL(18, 2) NOT NULL COMMENT 'high price',
    low_price DECIMAL(18, 2) NOT NULL COMMENT 'low price',
    last_price DECIMAL(18, 2) NOT NULL COMMENT 'close price',
    previous_close DECIMAL(18, 2) NOT NULL COMMENT 'previous close',
    change_pct DECIMAL(18, 4) NOT NULL COMMENT 'change percent',
    volume BIGINT NOT NULL COMMENT 'volume',
    turnover DECIMAL(20, 2) NOT NULL COMMENT 'turnover',
    event_time DATETIME NOT NULL COMMENT 'daily bar event time',
    source VARCHAR(32) NOT NULL COMMENT 'data source',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'created time',
    UNIQUE KEY uk_daily_stock_bars_event_id (event_id),
    UNIQUE KEY uk_daily_stock_bars_symbol_date_source (symbol, trade_date, source),
    KEY idx_daily_stock_bars_symbol_time (symbol, event_time),
    KEY idx_daily_stock_bars_event_time (event_time),
    KEY idx_daily_stock_bars_source_time (source, event_time)
) COMMENT='Daily stock bars for ML training';

CREATE TABLE IF NOT EXISTS daily_index_bars (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT 'primary key',
    event_id VARCHAR(64) NOT NULL COMMENT 'unique daily index event id',
    symbol VARCHAR(32) NOT NULL COMMENT 'index symbol',
    company_name VARCHAR(255) NOT NULL COMMENT 'index name',
    category VARCHAR(64) NOT NULL COMMENT 'category',
    sector VARCHAR(64) NOT NULL COMMENT 'sector',
    market VARCHAR(32) NOT NULL COMMENT 'market',
    trade_date DATE NOT NULL COMMENT 'trade date',
    open_price DECIMAL(18, 2) NOT NULL COMMENT 'open price',
    high_price DECIMAL(18, 2) NOT NULL COMMENT 'high price',
    low_price DECIMAL(18, 2) NOT NULL COMMENT 'low price',
    last_price DECIMAL(18, 2) NOT NULL COMMENT 'close price',
    previous_close DECIMAL(18, 2) NOT NULL COMMENT 'previous close',
    change_pct DECIMAL(18, 4) NOT NULL COMMENT 'change percent',
    volume BIGINT NOT NULL COMMENT 'volume',
    turnover DECIMAL(20, 2) NOT NULL COMMENT 'turnover',
    event_time DATETIME NOT NULL COMMENT 'daily index event time',
    source VARCHAR(32) NOT NULL COMMENT 'data source',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'created time',
    UNIQUE KEY uk_daily_index_bars_event_id (event_id),
    UNIQUE KEY uk_daily_index_bars_symbol_date_source (symbol, trade_date, source),
    KEY idx_daily_index_bars_symbol_time (symbol, event_time),
    KEY idx_daily_index_bars_event_time (event_time),
    KEY idx_daily_index_bars_source_time (source, event_time)
) COMMENT='Daily market index bars for ML features';

INSERT IGNORE INTO daily_stock_bars (
    event_id, symbol, company_name, category, sector, market, trade_date,
    open_price, high_price, low_price, last_price, previous_close,
    change_pct, volume, turnover, event_time, source, created_at
)
SELECT
    event_id, symbol, company_name, category, sector, market, DATE(event_time),
    open_price, high_price, low_price, last_price, previous_close,
    change_pct, volume, turnover, event_time, source, created_at
FROM price_ticks
WHERE source = 'akshare_cold_start';

INSERT IGNORE INTO daily_index_bars (
    event_id, symbol, company_name, category, sector, market, trade_date,
    open_price, high_price, low_price, last_price, previous_close,
    change_pct, volume, turnover, event_time, source, created_at
)
SELECT
    event_id, symbol, company_name, category, sector, market, DATE(event_time),
    open_price, high_price, low_price, last_price, previous_close,
    change_pct, volume, turnover, event_time, source, created_at
FROM price_ticks
WHERE source = 'akshare_index';

SELECT 'daily_stock_bars' AS table_name, COUNT(*) AS rows_count FROM daily_stock_bars
UNION ALL
SELECT 'daily_index_bars' AS table_name, COUNT(*) AS rows_count FROM daily_index_bars
UNION ALL
SELECT 'price_ticks_akshare_left' AS table_name, COUNT(*) AS rows_count
FROM price_ticks
WHERE source IN ('akshare_cold_start', 'akshare_index');

-- Optional cleanup after you verify the two new tables:
-- DELETE FROM price_ticks WHERE source IN ('akshare_cold_start', 'akshare_index');
