CREATE TABLE IF NOT EXISTS metric_snapshots (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    window_bucket VARCHAR(32) NOT NULL COMMENT '统计时间窗口，例如 2026-04-20 10:35:00',
    symbol_count INT NOT NULL DEFAULT 0 COMMENT '当前窗口内覆盖的股票数量',
    avg_price DECIMAL(18, 2) NOT NULL DEFAULT 0 COMMENT '当前窗口平均价格',
    avg_change_pct DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '当前窗口平均涨跌幅百分比',
    total_volume BIGINT NOT NULL DEFAULT 0 COMMENT '当前窗口总成交量',
    total_turnover DECIMAL(20, 2) NOT NULL DEFAULT 0 COMMENT '当前窗口总成交额',
    batch_id BIGINT NOT NULL COMMENT 'Spark foreachBatch 批次号',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    KEY idx_metric_snapshots_window_bucket (window_bucket),
    KEY idx_metric_snapshots_created_at (created_at)
) COMMENT='实时指标快照表';

CREATE TABLE IF NOT EXISTS price_ticks (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    event_id VARCHAR(64) NOT NULL COMMENT '行情事件唯一标识',
    symbol VARCHAR(32) NOT NULL COMMENT '股票代码，例如 AAPL、600519、00700',
    company_name VARCHAR(255) NOT NULL COMMENT '公司名称',
    category VARCHAR(64) NOT NULL COMMENT '股票池分类，例如 美股科技、A股新能源',
    sector VARCHAR(64) NOT NULL COMMENT '行业分类',
    market VARCHAR(32) NOT NULL COMMENT '市场标识，例如 NASDAQ、SH、SZ、HK',
    open_price DECIMAL(18, 2) NOT NULL COMMENT '开盘价',
    high_price DECIMAL(18, 2) NOT NULL COMMENT '最高价',
    low_price DECIMAL(18, 2) NOT NULL COMMENT '最低价',
    last_price DECIMAL(18, 2) NOT NULL COMMENT '最新价',
    previous_close DECIMAL(18, 2) NOT NULL COMMENT '昨收价',
    change_pct DECIMAL(18, 4) NOT NULL COMMENT '涨跌幅百分比',
    volume BIGINT NOT NULL COMMENT '成交量',
    turnover DECIMAL(20, 2) NOT NULL COMMENT '成交额',
    event_time DATETIME NOT NULL COMMENT '行情事件时间',
    source VARCHAR(32) NOT NULL COMMENT '数据来源，例如 yahoo、eastmoney、sina、tencent、stooq、replay_yahoo',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '记录入库时间',
    KEY idx_price_ticks_symbol_created_at (symbol, created_at),
    KEY idx_price_ticks_symbol_event_time (symbol, event_time),
    KEY idx_price_ticks_source_created_at (source, created_at),
    KEY idx_price_ticks_event_time (event_time),
    KEY idx_price_ticks_created_at (created_at)
) COMMENT='原始行情明细表';

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

CREATE TABLE IF NOT EXISTS symbol_stats (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    symbol VARCHAR(32) NOT NULL COMMENT '股票代码',
    company_name VARCHAR(255) NOT NULL COMMENT '公司名称',
    category VARCHAR(64) NOT NULL COMMENT '股票池分类',
    sector VARCHAR(64) NOT NULL COMMENT '行业分类',
    last_price DECIMAL(18, 2) NOT NULL COMMENT '最新价',
    change_pct DECIMAL(18, 4) NOT NULL COMMENT '窗口平均涨跌幅百分比',
    volume BIGINT NOT NULL COMMENT '窗口累计成交量',
    turnover DECIMAL(20, 2) NOT NULL COMMENT '窗口累计成交额',
    batch_id BIGINT NOT NULL COMMENT 'Spark foreachBatch 批次号',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    KEY idx_symbol_stats_symbol_created_at (symbol, created_at)
) COMMENT='个股聚合统计表';

CREATE TABLE IF NOT EXISTS sector_stats (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    sector VARCHAR(64) NOT NULL COMMENT '行业名称',
    symbol_count INT NOT NULL DEFAULT 0 COMMENT '行业内股票数量',
    avg_change_pct DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '行业平均涨跌幅百分比',
    turnover DECIMAL(20, 2) NOT NULL DEFAULT 0 COMMENT '行业总成交额',
    batch_id BIGINT NOT NULL COMMENT 'Spark foreachBatch 批次号',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    KEY idx_sector_stats_sector_created_at (sector, created_at)
) COMMENT='行业维度统计表';

CREATE TABLE IF NOT EXISTS category_stats (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    category VARCHAR(64) NOT NULL COMMENT '股票池分类名称',
    symbol_count INT NOT NULL DEFAULT 0 COMMENT '分类内股票数量',
    avg_change_pct DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '分类平均涨跌幅百分比',
    turnover DECIMAL(20, 2) NOT NULL DEFAULT 0 COMMENT '分类总成交额',
    batch_id BIGINT NOT NULL COMMENT 'Spark foreachBatch 批次号',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    KEY idx_category_stats_category_created_at (category, created_at)
) COMMENT='股票池分类统计表';

CREATE TABLE IF NOT EXISTS alert_events (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    event_id VARCHAR(64) NOT NULL COMMENT '触发预警的行情事件ID',
    symbol VARCHAR(32) NOT NULL COMMENT '股票代码',
    company_name VARCHAR(255) NOT NULL COMMENT '公司名称',
    category VARCHAR(64) NOT NULL COMMENT '股票池分类',
    sector VARCHAR(64) NOT NULL COMMENT '行业分类',
    market VARCHAR(32) NOT NULL COMMENT '市场标识',
    open_price DECIMAL(18, 2) NOT NULL COMMENT '开盘价',
    high_price DECIMAL(18, 2) NOT NULL COMMENT '最高价',
    low_price DECIMAL(18, 2) NOT NULL COMMENT '最低价',
    last_price DECIMAL(18, 2) NOT NULL COMMENT '最新价',
    previous_close DECIMAL(18, 2) NOT NULL COMMENT '昨收价',
    change_pct DECIMAL(18, 4) NOT NULL COMMENT '涨跌幅百分比',
    volume BIGINT NOT NULL COMMENT '成交量',
    turnover DECIMAL(20, 2) NOT NULL COMMENT '成交额',
    event_time DATETIME NOT NULL COMMENT '行情事件时间',
    source VARCHAR(32) NOT NULL COMMENT '数据来源',
    alert_type VARCHAR(64) NOT NULL COMMENT '预警类型，例如 price_volatility、volume_spike',
    alert_level VARCHAR(16) NOT NULL COMMENT '预警等级，例如 MEDIUM、HIGH',
    price_threshold DECIMAL(8, 2) NOT NULL DEFAULT 0 COMMENT '价格波动告警阈值百分比',
    volume_threshold BIGINT NOT NULL DEFAULT 0 COMMENT '成交量告警阈值',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    KEY idx_alert_events_symbol_created_at (symbol, created_at),
    KEY idx_alert_events_type_created_at (alert_type, created_at),
    KEY idx_alert_events_level_created_at (alert_level, created_at)
) COMMENT='异常预警事件表';

CREATE TABLE IF NOT EXISTS ml_predictions (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    symbol VARCHAR(32) NOT NULL COMMENT '股票代码',
    company_name VARCHAR(255) NOT NULL COMMENT '公司名称',
    category VARCHAR(64) NOT NULL COMMENT '股票池分类',
    sector VARCHAR(64) NOT NULL COMMENT '行业分类',
    current_price DECIMAL(18, 2) NOT NULL COMMENT '当前价格',
    predicted_next_price DECIMAL(18, 2) NOT NULL COMMENT '预测下一时刻价格',
    predicted_signal VARCHAR(16) NOT NULL COMMENT '模型原始预测方向信号，例如 UP、DOWN、WATCH',
    alert_signal VARCHAR(16) NOT NULL DEFAULT 'WATCH' COMMENT '经过置信度过滤后的告警侧信号',
    confidence DECIMAL(8, 4) NOT NULL DEFAULT 0 COMMENT '融合预测置信度，范围0到1',
    model_risk_score DECIMAL(8, 4) NOT NULL DEFAULT 0 COMMENT '模型下跌风险概率分数',
    technical_risk_score DECIMAL(8, 4) NOT NULL DEFAULT 0 COMMENT '价格量能和相对弱势证据分数',
    sequence_risk_score DECIMAL(8, 4) NOT NULL DEFAULT 0 COMMENT 'LSTM序列辅助风险分数',
    final_risk_score DECIMAL(8, 4) NOT NULL DEFAULT 0 COMMENT '最终下跌风险评分',
    model_version VARCHAR(64) NOT NULL COMMENT '模型版本号',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    KEY idx_ml_predictions_symbol_created_at (symbol, created_at),
    KEY idx_ml_predictions_signal_created_at (predicted_signal, created_at),
    KEY idx_ml_predictions_alert_signal_created_at (alert_signal, created_at),
    KEY idx_ml_predictions_final_risk_score (final_risk_score)
) COMMENT='机器学习预测结果表';

CREATE TABLE IF NOT EXISTS ml_prediction_history (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '预测历史主键ID',
    symbol VARCHAR(32) NOT NULL COMMENT '股票代码',
    company_name VARCHAR(255) NOT NULL COMMENT '公司名称',
    category VARCHAR(64) NOT NULL COMMENT '股票池分类',
    sector VARCHAR(64) NOT NULL COMMENT '行业分类',
    current_price DECIMAL(18, 2) NOT NULL COMMENT '预测发生时的当前价格',
    predicted_next_price DECIMAL(18, 2) NOT NULL COMMENT '预测下一时刻价格',
    predicted_signal VARCHAR(16) NOT NULL COMMENT '模型原始预测方向信号，例如 UP、DOWN、WATCH',
    alert_signal VARCHAR(16) NOT NULL DEFAULT 'WATCH' COMMENT '经过置信度过滤后的告警侧信号',
    confidence DECIMAL(8, 4) NOT NULL DEFAULT 0 COMMENT '预测置信度，范围0到1',
    model_risk_score DECIMAL(8, 4) NOT NULL DEFAULT 0 COMMENT '模型下跌风险概率分数',
    technical_risk_score DECIMAL(8, 4) NOT NULL DEFAULT 0 COMMENT '价格量能和相对弱势证据分数',
    sequence_risk_score DECIMAL(8, 4) NOT NULL DEFAULT 0 COMMENT 'LSTM序列辅助风险分数',
    final_risk_score DECIMAL(8, 4) NOT NULL DEFAULT 0 COMMENT '最终下跌风险评分',
    model_version VARCHAR(64) NOT NULL COMMENT '模型版本号',
    predicted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '预测生成时间',
    KEY idx_ml_prediction_history_symbol_time (symbol, predicted_at),
    KEY idx_ml_prediction_history_model_time (model_version, predicted_at),
    KEY idx_ml_prediction_history_signal_time (predicted_signal, predicted_at),
    KEY idx_ml_prediction_history_alert_signal_time (alert_signal, predicted_at),
    KEY idx_ml_prediction_history_final_risk_score (final_risk_score)
) COMMENT='机器学习预测历史表，用于模型漂移检测';

CREATE TABLE IF NOT EXISTS ml_model_metrics (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    model_name VARCHAR(64) NOT NULL COMMENT '模型名称，例如 stock_ml',
    metric_name VARCHAR(64) NOT NULL COMMENT '指标名称，例如 price_mae、direction_accuracy',
    metric_value DECIMAL(18, 4) NOT NULL COMMENT '指标值',
    model_version VARCHAR(64) NOT NULL COMMENT '模型版本号',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    KEY idx_ml_model_metrics_model_created_at (model_name, created_at)
) COMMENT='机器学习模型指标表';
CREATE TABLE IF NOT EXISTS alert_actions (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '告警处理记录主键ID',
    alert_id BIGINT NOT NULL COMMENT '对应 alert_events 表中的告警ID',
    status VARCHAR(16) NOT NULL DEFAULT 'OPEN' COMMENT '处理状态：OPEN未处理、ACKED已确认、IGNORED已忽略、RESOLVED已解决',
    note VARCHAR(512) DEFAULT '' COMMENT '处理备注',
    handled_by VARCHAR(64) DEFAULT 'system' COMMENT '处理人',
    handled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '处理时间',
    UNIQUE KEY uk_alert_actions_alert_id (alert_id),
    KEY idx_alert_actions_status (status),
    KEY idx_alert_actions_handled_at (handled_at)
) COMMENT='告警处理闭环记录表';
