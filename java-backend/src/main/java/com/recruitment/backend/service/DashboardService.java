package com.recruitment.backend.service;

import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.io.File;
import java.net.URI;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

@Service
// 仪表盘聚合服务：把 MySQL 中的实时行情、告警、模型预测和系统状态整理成前端可直接展示的数据结构。
public class DashboardService {

    private final JdbcTemplate jdbcTemplate;
    private final String hdfsOutputPath;
    private final String hdfsCheckpointPath;

    public DashboardService(
            JdbcTemplate jdbcTemplate,
            @Value("${app.hdfs.output-path:}") String hdfsOutputPath,
            @Value("${app.hdfs.checkpoint-path:}") String hdfsCheckpointPath
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.hdfsOutputPath = hdfsOutputPath;
        this.hdfsCheckpointPath = hdfsCheckpointPath;
    }

    @PostConstruct
    public void ensureExtendedTables() {
        // 兼容旧库：启动时补齐演示需要的处理记录、模型置信度、告警阈值等字段。
        // init.sql 仍是新环境的主 schema，这里主要用于已有数据库平滑升级。
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS alert_actions (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
                    alert_id BIGINT NOT NULL COMMENT '告警事件ID',
                    status VARCHAR(16) NOT NULL DEFAULT 'OPEN' COMMENT '处理状态：OPEN、ACKED、IGNORED、RESOLVED',
                    note VARCHAR(512) DEFAULT '' COMMENT '处理备注',
                    handled_by VARCHAR(64) DEFAULT 'system' COMMENT '处理人',
                    handled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '处理时间',
                    UNIQUE KEY uk_alert_actions_alert_id (alert_id),
                    KEY idx_alert_actions_status (status),
                    KEY idx_alert_actions_handled_at (handled_at)
                ) COMMENT='告警处理记录表'
                """);
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE ml_predictions
                    ADD COLUMN confidence DECIMAL(8,4) NOT NULL DEFAULT 0 COMMENT '融合预测置信度，范围0到1'
                    AFTER predicted_signal
                    """);
        } catch (Exception ignored) {
            // Existing deployments may already have the column.
        }
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE ml_predictions
                    ADD COLUMN alert_signal VARCHAR(16) NOT NULL DEFAULT 'WATCH' COMMENT '经过置信度过滤后的告警侧信号'
                    AFTER predicted_signal
                    """);
        } catch (Exception ignored) {
            // Existing deployments may already have the column.
        }
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE ml_prediction_history
                    ADD COLUMN alert_signal VARCHAR(16) NOT NULL DEFAULT 'WATCH' COMMENT '经过置信度过滤后的告警侧信号'
                    AFTER predicted_signal
                    """);
        } catch (Exception ignored) {
            // Existing deployments may already have the column.
        }
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE alert_events
                    ADD COLUMN price_threshold DECIMAL(8,2) NOT NULL DEFAULT 0 COMMENT '价格波动告警阈值百分比'
                    AFTER alert_level
                    """);
        } catch (Exception ignored) {
            // Existing deployments may already have the column.
        }
        try {
            jdbcTemplate.execute("""
                    ALTER TABLE alert_events
                    ADD COLUMN volume_threshold BIGINT NOT NULL DEFAULT 0 COMMENT '成交量告警阈值'
                    AFTER price_threshold
                    """);
        } catch (Exception ignored) {
            // Existing deployments may already have the column.
        }
    }

    public Map<String, Object> fetchDashboard() {
        // 首页大屏只调用这一个聚合接口，后端负责把各类小查询组合好，减少前端多次请求导致的延迟。
        Map<String, Object> response = new LinkedHashMap<>();
        // 首页大屏只调用这一个聚合接口，后端负责把各类小查询组合好，减少前端多次请求导致的延迟。
        // 一个接口返回整张大屏需要的数据，减少前端多次请求造成的展示延迟。
        response.put("system_health", fetchHealth());
        response.put("stream_status", fetchSingleRow("""
                SELECT
                    p.total_events,
                    COALESCE(p.events_last_minute, 0) + COALESCE(m.heartbeats_last_minute, 0) AS events_last_minute,
                    COALESCE(p.events_last_5_minutes, 0) + COALESCE(m.heartbeats_last_5_minutes, 0) AS events_last_5_minutes,
                    p.total_symbols,
                    p.source_count,
                    DATE_FORMAT(p.latest_event_time, '%Y-%m-%d %H:%i:%s') AS latest_event_time,
                    DATE_FORMAT(p.latest_created_at, '%Y-%m-%d %H:%i:%s') AS latest_price_created_at,
                    DATE_FORMAT(m.latest_metric_created_at, '%Y-%m-%d %H:%i:%s') AS latest_metric_created_at,
                    TIMESTAMPDIFF(
                        SECOND,
                        GREATEST(
                            COALESCE(p.latest_created_at, TIMESTAMP('1970-01-01 00:00:00')),
                            COALESCE(m.latest_metric_created_at, TIMESTAMP('1970-01-01 00:00:00'))
                        ),
                        NOW()
                    ) AS seconds_since_last_event,
                    CASE
                        WHEN GREATEST(
                            COALESCE(p.latest_created_at, TIMESTAMP('1970-01-01 00:00:00')),
                            COALESCE(m.latest_metric_created_at, TIMESTAMP('1970-01-01 00:00:00'))
                        ) < NOW() - INTERVAL 10 MINUTE THEN 'OFFLINE'
                        WHEN p.latest_source LIKE 'replay_%'
                             AND COALESCE(p.latest_created_at, TIMESTAMP('1970-01-01 00:00:00')) >= COALESCE(m.latest_metric_created_at, TIMESTAMP('1970-01-01 00:00:00'))
                            THEN 'REPLAY'
                        WHEN p.latest_created_at IS NOT NULL OR m.latest_metric_created_at IS NOT NULL THEN 'LIVE'
                        ELSE 'OFFLINE'
                    END AS current_mode,
                    CASE
                        WHEN GREATEST(
                            COALESCE(p.latest_created_at, TIMESTAMP('1970-01-01 00:00:00')),
                            COALESCE(m.latest_metric_created_at, TIMESTAMP('1970-01-01 00:00:00'))
                        ) >= NOW() - INTERVAL 30 SECOND THEN 'FLOWING'
                        WHEN GREATEST(
                            COALESCE(p.latest_created_at, TIMESTAMP('1970-01-01 00:00:00')),
                            COALESCE(m.latest_metric_created_at, TIMESTAMP('1970-01-01 00:00:00'))
                        ) >= NOW() - INTERVAL 5 MINUTE THEN 'DELAYED'
                        ELSE 'STOPPED'
                    END AS stream_state
                FROM (
                    SELECT
                        COUNT(*) AS total_events,
                        COALESCE(SUM(CASE WHEN created_at >= NOW() - INTERVAL 1 MINUTE THEN 1 ELSE 0 END), 0) AS events_last_minute,
                        COALESCE(SUM(CASE WHEN created_at >= NOW() - INTERVAL 5 MINUTE THEN 1 ELSE 0 END), 0) AS events_last_5_minutes,
                        COUNT(DISTINCT symbol) AS total_symbols,
                        COUNT(DISTINCT source) AS source_count,
                        MAX(event_time) AS latest_event_time,
                        MAX(created_at) AS latest_created_at,
                        (
                            SELECT latest_source.source
                            FROM price_ticks latest_source
                            ORDER BY latest_source.created_at DESC, latest_source.id DESC
                            LIMIT 1
                        ) AS latest_source
                    FROM price_ticks
                ) p
                CROSS JOIN (
                    SELECT
                        COALESCE(SUM(CASE WHEN created_at >= NOW() - INTERVAL 1 MINUTE THEN 1 ELSE 0 END), 0) AS heartbeats_last_minute,
                        COALESCE(SUM(CASE WHEN created_at >= NOW() - INTERVAL 5 MINUTE THEN 1 ELSE 0 END), 0) AS heartbeats_last_5_minutes,
                        MAX(created_at) AS latest_metric_created_at
                    FROM metric_snapshots
                ) m
                """));
        response.put("summary", fetchSingleRow("""
                -- 只取每只股票最新一条行情，避免历史数据重复影响总览指标。
                SELECT
                    COUNT(*) AS symbol_count,
                    COALESCE(SUM(CASE WHEN change_pct > 0 THEN 1 ELSE 0 END), 0) AS up_count,
                    COALESCE(SUM(CASE WHEN change_pct < 0 THEN 1 ELSE 0 END), 0) AS down_count,
                    COALESCE(SUM(CASE WHEN change_pct = 0 THEN 1 ELSE 0 END), 0) AS flat_count,
                    ROUND(COALESCE(AVG(change_pct), 0), 2) AS avg_change_pct,
                    COALESCE(SUM(volume), 0) AS total_volume,
                    ROUND(COALESCE(SUM(turnover), 0), 2) AS total_turnover,
                    COUNT(DISTINCT source) AS source_count,
                    DATE_FORMAT(MAX(event_time), '%Y-%m-%d %H:%i:%s') AS latest_event_time,
                    (
                        SELECT COUNT(*)
                        FROM alert_events
                        WHERE created_at >= NOW() - INTERVAL 30 MINUTE
                    ) AS alert_count,
                    (
                      SELECT COUNT(*)
                      FROM alert_events
                      WHERE created_at >= NOW() - INTERVAL 30 MINUTE
                      AND alert_level = 'HIGH'
                    ) AS alert_high_count,
                    (
                      SELECT COUNT(*)
                      FROM alert_events
                      WHERE created_at >= NOW() - INTERVAL 30 MINUTE
                      AND alert_level = 'MEDIUM'
                    ) AS alert_medium_count
                FROM price_ticks t
                INNER JOIN (
                    SELECT symbol, MAX(id) AS id
                    FROM price_ticks
                    GROUP BY symbol
                ) latest ON t.id = latest.id
                """));
        response.put("trend", fetchRows("""
                SELECT
                    window_bucket,
                    MAX(symbol_count) AS symbol_count,
                    ROUND(AVG(avg_price), 2) AS avg_price,
                    ROUND(AVG(avg_change_pct), 2) AS avg_change_pct,
                    MAX(total_volume) AS total_volume
                FROM metric_snapshots
                GROUP BY window_bucket
                ORDER BY window_bucket DESC
                LIMIT 12
                """));
        response.put("market_overview", fetchRows("""
                SELECT
                    market,
                    COUNT(*) AS symbol_count,
                    COALESCE(SUM(CASE WHEN change_pct > 0 THEN 1 ELSE 0 END), 0) AS up_count,
                    COALESCE(SUM(CASE WHEN change_pct < 0 THEN 1 ELSE 0 END), 0) AS down_count,
                    ROUND(AVG(change_pct), 2) AS avg_change_pct,
                    ROUND(SUM(turnover), 2) AS turnover
                FROM price_ticks t
                INNER JOIN (
                    SELECT symbol, MAX(id) AS id
                    FROM price_ticks
                    GROUP BY symbol
                ) latest ON t.id = latest.id
                GROUP BY market
                ORDER BY turnover DESC
                """));
        response.put("source_status", fetchRows("""
                SELECT
                    source,
                    COUNT(*) AS success_count,
                    COUNT(DISTINCT symbol) AS symbol_count,
                    DATE_FORMAT(MAX(event_time), '%Y-%m-%d %H:%i:%s') AS latest_event_time,
                    TIMESTAMPDIFF(SECOND, MAX(created_at), NOW()) AS seconds_since_last_event,
                    CASE
                        WHEN MAX(created_at) >= NOW() - INTERVAL 10 MINUTE THEN 'OK'
                        WHEN MAX(created_at) >= NOW() - INTERVAL 60 MINUTE THEN 'DELAYED'
                        ELSE 'OFFLINE'
                    END AS status
                FROM price_ticks
                GROUP BY source
                ORDER BY success_count DESC
                """));
        response.put("focus_stocks", fetchRows("""
                -- 关注度由涨跌幅、成交量、预警等级和模型信号共同决定。
                SELECT
                    t.symbol,
                    t.company_name,
                    t.market,
                    t.category,
                    t.sector,
                    ROUND(t.last_price, 2) AS last_price,
                    ROUND(t.change_pct, 2) AS change_pct,
                    t.volume,
                    ROUND(t.turnover, 2) AS turnover,
                    COALESCE(a.alert_count, 0) AS alert_count,
                    CASE COALESCE(a.risk_score, 0)
                        WHEN 3 THEN 'HIGH'
                        WHEN 2 THEN 'MEDIUM'
                        WHEN 1 THEN 'LOW'
                        ELSE 'WATCH'
                    END AS risk_level,
                    COALESCE(m.predicted_signal, 'NONE') AS predicted_signal,
                    ROUND(COALESCE(m.confidence, 0), 4) AS confidence,
                    ROUND(COALESCE(m.predicted_next_price - m.current_price, 0), 2) AS predicted_gap,
                    ROUND(
                        ABS(t.change_pct) * 12
                        + LEAST(LOG10(GREATEST(t.volume, 1)), 10) * 4
                        + COALESCE(a.risk_score, 0) * 18
                        + CASE COALESCE(m.predicted_signal, 'NONE')
                            WHEN 'UP' THEN 8
                            WHEN 'DOWN' THEN 8
                            ELSE 0
                          END,
                        2
                    ) AS attention_score
                FROM price_ticks t
                INNER JOIN (
                    SELECT symbol, MAX(id) AS id
                    FROM price_ticks
                    GROUP BY symbol
                ) latest ON t.id = latest.id
                LEFT JOIN (
                    SELECT
                        symbol,
                        COUNT(*) AS alert_count,
                        MAX(CASE alert_level WHEN 'HIGH' THEN 3 WHEN 'MEDIUM' THEN 2 ELSE 1 END) AS risk_score
                    FROM alert_events
                    WHERE created_at >= NOW() - INTERVAL 30 MINUTE
                    GROUP BY symbol
                ) a ON t.symbol = a.symbol
                LEFT JOIN (
                    SELECT p.*
                    FROM ml_predictions p
                    INNER JOIN (
                        SELECT symbol, MAX(id) AS id
                        FROM ml_predictions
                        GROUP BY symbol
                    ) latest_prediction ON p.id = latest_prediction.id
                ) m ON t.symbol = m.symbol
                ORDER BY attention_score DESC, ABS(t.change_pct) DESC, t.volume DESC
                LIMIT 12
                """));
        response.put("optimal_stocks", fetchStockRanking("optimal", 8));
        response.put("risk_stocks", fetchStockRanking("risk", 8));
        response.put("model_comparison", fetchModelComparison());
        response.put("daily_data_freshness", fetchDailyDataFreshness());
        response.put("sector_heat", fetchRows("""
                -- 行业热力用于说明当前哪些行业波动更明显。
                SELECT
                    sector,
                    COUNT(*) AS symbol_count,
                    COALESCE(SUM(CASE WHEN change_pct > 0 THEN 1 ELSE 0 END), 0) AS up_count,
                    COALESCE(SUM(CASE WHEN change_pct < 0 THEN 1 ELSE 0 END), 0) AS down_count,
                    ROUND(AVG(change_pct), 2) AS avg_change_pct,
                    ROUND(SUM(turnover), 2) AS turnover,
                    COALESCE(SUM(CASE WHEN ABS(change_pct) >= 2 OR volume >= 5000000 THEN 1 ELSE 0 END), 0) AS abnormal_count
                FROM price_ticks t
                INNER JOIN (
                    SELECT symbol, MAX(id) AS id
                    FROM price_ticks
                    GROUP BY symbol
                ) latest ON t.id = latest.id
                GROUP BY sector
                ORDER BY abnormal_count DESC, ABS(avg_change_pct) DESC, turnover DESC
                LIMIT 10
                """));
        response.put("category_heat", fetchRows("""
                SELECT
                    category,
                    COUNT(*) AS symbol_count,
                    ROUND(AVG(change_pct), 2) AS avg_change_pct,
                    ROUND(SUM(turnover), 2) AS turnover,
                    COALESCE(SUM(CASE WHEN ABS(change_pct) >= 2 OR volume >= 5000000 THEN 1 ELSE 0 END), 0) AS abnormal_count
                FROM price_ticks t
                INNER JOIN (
                    SELECT symbol, MAX(id) AS id
                    FROM price_ticks
                    GROUP BY symbol
                ) latest ON t.id = latest.id
                GROUP BY category
                ORDER BY abnormal_count DESC, ABS(avg_change_pct) DESC, turnover DESC
                LIMIT 10
                """));
        response.put("latest_alerts", fetchRows("""
        SELECT
            a.id,
            a.symbol,
            a.company_name,
            a.category,
            a.sector,
            a.market,
            ROUND(a.last_price, 2) AS last_price,
            ROUND(a.change_pct, 4) AS change_pct,
            a.volume,
            ROUND(a.turnover, 2) AS turnover,
            a.alert_type,
            a.alert_level,
            ROUND(a.price_threshold, 2) AS price_threshold,
            a.volume_threshold,
            DATE_FORMAT(a.event_time, '%Y-%m-%d %H:%i:%s') AS event_time,
            DATE_FORMAT(a.created_at, '%Y-%m-%d %H:%i:%s') AS created_at,
            a.source,
            COALESCE(act.status, 'OPEN') AS action_status,
            COALESCE(act.note, '') AS action_note,
            COALESCE(act.handled_by, '') AS handled_by,
            DATE_FORMAT(act.handled_at, '%Y-%m-%d %H:%i:%s') AS handled_at
        FROM alert_events a
        LEFT JOIN alert_actions act ON a.id = act.alert_id
        ORDER BY a.created_at DESC
        LIMIT 20
        """));
        response.put("latest_ticks", fetchRows("""
                SELECT
                    symbol,
                    company_name,
                    category,
                    sector,
                    market,
                    ROUND(last_price, 2) AS last_price,
                    ROUND(change_pct, 2) AS change_pct,
                    volume,
                    ROUND(turnover, 2) AS turnover,
                    DATE_FORMAT(event_time, '%Y-%m-%d %H:%i:%s') AS event_time,
                    source
                FROM price_ticks
                ORDER BY created_at DESC
                LIMIT 20
                """));
        response.put("ml_metrics", fetchRows("""
                SELECT model_name, metric_name, metric_value, model_version
                FROM ml_model_metrics
                ORDER BY created_at DESC
                LIMIT 6
                """));
        response.put("signal_distribution", fetchRows("""
                SELECT
                    COALESCE(NULLIF(alert_signal, ''), 'WATCH') AS predicted_signal,
                    COUNT(*) AS prediction_count
                FROM ml_predictions
                GROUP BY COALESCE(NULLIF(alert_signal, ''), 'WATCH')
                ORDER BY prediction_count DESC
                """));
        response.put("ml_predictions", fetchRows("""
                SELECT
                    symbol,
                    company_name,
                    category,
                    sector,
                    current_price,
                    predicted_next_price,
                    ROUND(predicted_next_price - current_price, 2) AS predicted_gap,
                    predicted_signal,
                    COALESCE(NULLIF(alert_signal, ''), 'WATCH') AS alert_signal,
                    ROUND(COALESCE(confidence, 0), 4) AS confidence,
                    model_version,
                    DATE_FORMAT(created_at, '%Y-%m-%d %H:%i:%s') AS created_at
                FROM ml_predictions
                ORDER BY created_at DESC
                LIMIT 12
        """));
        return response;
    }

    private Map<String, Object> fetchDailyDataFreshness() {
        return fetchSingleRow("""
                SELECT
                    DATE_FORMAT(s.latest_trade_date, '%Y-%m-%d') AS stock_latest_trade_date,
                    DATEDIFF(CURDATE(), s.latest_trade_date) AS stock_age_days,
                    s.stock_rows,
                    s.stock_symbols,
                    DATE_FORMAT(i.latest_trade_date, '%Y-%m-%d') AS index_latest_trade_date,
                    DATEDIFF(CURDATE(), i.latest_trade_date) AS index_age_days,
                    i.index_rows,
                    i.index_symbols,
                    CASE
                        WHEN s.latest_trade_date IS NULL OR i.latest_trade_date IS NULL THEN 'MISSING'
                        WHEN DATEDIFF(CURDATE(), s.latest_trade_date) > 10
                          OR DATEDIFF(CURDATE(), i.latest_trade_date) > 10 THEN 'STALE'
                        ELSE 'OK'
                    END AS status
                FROM (
                    SELECT MAX(trade_date) AS latest_trade_date,
                           COUNT(*) AS stock_rows,
                           COUNT(DISTINCT symbol) AS stock_symbols
                    FROM daily_stock_bars
                ) s
                CROSS JOIN (
                    SELECT MAX(trade_date) AS latest_trade_date,
                           COUNT(*) AS index_rows,
                           COUNT(DISTINCT symbol) AS index_symbols
                    FROM daily_index_bars
                ) i
                """);
    }

    public Map<String, Object> fetchHealth() {
        // 健康信息给前端展示，也方便答辩时证明实时链路是否正在运行。
        Map<String, Object> health = new LinkedHashMap<>();
        health.put("database", fetchDatabaseHealth());
        health.put("stream", fetchSingleRow("""
                SELECT
                    p.total_events,
                    COALESCE(p.events_last_minute, 0) + COALESCE(m.heartbeats_last_minute, 0) AS events_last_minute,
                    DATE_FORMAT(
                        GREATEST(
                            COALESCE(p.latest_created_at, TIMESTAMP('1970-01-01 00:00:00')),
                            COALESCE(m.latest_metric_created_at, TIMESTAMP('1970-01-01 00:00:00'))
                        ),
                        '%Y-%m-%d %H:%i:%s'
                    ) AS latest_created_at,
                    DATE_FORMAT(p.latest_created_at, '%Y-%m-%d %H:%i:%s') AS latest_price_created_at,
                    DATE_FORMAT(m.latest_metric_created_at, '%Y-%m-%d %H:%i:%s') AS latest_metric_created_at,
                    TIMESTAMPDIFF(
                        SECOND,
                        GREATEST(
                            COALESCE(p.latest_created_at, TIMESTAMP('1970-01-01 00:00:00')),
                            COALESCE(m.latest_metric_created_at, TIMESTAMP('1970-01-01 00:00:00'))
                        ),
                        NOW()
                    ) AS seconds_since_last_event,
                    CASE
                        WHEN GREATEST(
                            COALESCE(p.latest_created_at, TIMESTAMP('1970-01-01 00:00:00')),
                            COALESCE(m.latest_metric_created_at, TIMESTAMP('1970-01-01 00:00:00'))
                        ) >= NOW() - INTERVAL 30 SECOND THEN 'OK'
                        WHEN GREATEST(
                            COALESCE(p.latest_created_at, TIMESTAMP('1970-01-01 00:00:00')),
                            COALESCE(m.latest_metric_created_at, TIMESTAMP('1970-01-01 00:00:00'))
                        ) >= NOW() - INTERVAL 5 MINUTE THEN 'DELAYED'
                        ELSE 'STOPPED'
                    END AS status
                FROM (
                    SELECT
                        COUNT(*) AS total_events,
                        COALESCE(SUM(CASE WHEN created_at >= NOW() - INTERVAL 1 MINUTE THEN 1 ELSE 0 END), 0) AS events_last_minute,
                        MAX(created_at) AS latest_created_at
                    FROM price_ticks
                ) p
                CROSS JOIN (
                    SELECT
                        COALESCE(SUM(CASE WHEN created_at >= NOW() - INTERVAL 1 MINUTE THEN 1 ELSE 0 END), 0) AS heartbeats_last_minute,
                        MAX(created_at) AS latest_metric_created_at
                    FROM metric_snapshots
                ) m
                """));
        health.put("storage", Map.of(
                "output", inspectStoragePath(hdfsOutputPath),
                "checkpoint", inspectStoragePath(hdfsCheckpointPath)
        ));
        health.put("sources", fetchRows("""
                SELECT
                    source,
                    COUNT(*) AS total_events,
                    COUNT(DISTINCT symbol) AS symbol_count,
                    DATE_FORMAT(MAX(created_at), '%Y-%m-%d %H:%i:%s') AS latest_created_at,
                    TIMESTAMPDIFF(SECOND, MAX(created_at), NOW()) AS seconds_since_last_event,
                    CASE
                        WHEN MAX(created_at) >= NOW() - INTERVAL 10 MINUTE THEN 'OK'
                        WHEN MAX(created_at) >= NOW() - INTERVAL 60 MINUTE THEN 'DELAYED'
                        ELSE 'OFFLINE'
                    END AS status
                FROM price_ticks
                GROUP BY source
                ORDER BY total_events DESC
                """));
        return health;
    }

    public List<Map<String, Object>> searchStocks(String keyword, int limit) {
        String normalizedKeyword = keyword == null ? "" : keyword.trim();
        String likeKeyword = "%" + normalizedKeyword + "%";
        return fetchRows("""
                SELECT
                    t.symbol,
                    t.company_name,
                    t.market,
                    t.category,
                    t.sector,
                    ROUND(t.last_price, 2) AS last_price,
                    ROUND(t.change_pct, 2) AS change_pct,
                    t.volume,
                    ROUND(t.turnover, 2) AS turnover,
                    DATE_FORMAT(t.event_time, '%Y-%m-%d %H:%i:%s') AS event_time,
                    t.source,
                    COALESCE(a.alert_count, 0) AS alert_count,
                    COALESCE(m.predicted_signal, 'NONE') AS predicted_signal,
                    ROUND(COALESCE(m.confidence, 0), 4) AS confidence,
                    ROUND(COALESCE(m.predicted_next_price - m.current_price, 0), 2) AS predicted_gap
                FROM price_ticks t
                INNER JOIN (
                    SELECT symbol, MAX(id) AS id
                    FROM price_ticks
                    GROUP BY symbol
                ) latest ON t.id = latest.id
                LEFT JOIN (
                    SELECT symbol, COUNT(*) AS alert_count
                    FROM alert_events
                    WHERE created_at >= NOW() - INTERVAL 30 MINUTE
                    GROUP BY symbol
                ) a ON t.symbol = a.symbol
                LEFT JOIN (
                    SELECT p.*
                    FROM ml_predictions p
                    INNER JOIN (
                        SELECT symbol, MAX(id) AS id
                        FROM ml_predictions
                        GROUP BY symbol
                    ) latest_prediction ON p.id = latest_prediction.id
                ) m ON t.symbol = m.symbol
                WHERE (? = ''
                    OR t.symbol LIKE ?
                    OR t.company_name LIKE ?
                    OR t.category LIKE ?
                    OR t.sector LIKE ?)
                ORDER BY ABS(t.change_pct) DESC, COALESCE(a.alert_count, 0) DESC, t.turnover DESC
                LIMIT ?
                """, normalizedKeyword, likeKeyword, likeKeyword, likeKeyword, likeKeyword, normalizeLimit(limit, 20, 100));
    }

    public Map<String, Object> fetchStockDetail(String symbol) {
        String normalizedSymbol = normalizeSymbol(symbol);
        Map<String, Object> detail = new LinkedHashMap<>();
        List<Map<String, Object>> stocks = fetchRows("""
                SELECT
                    t.symbol,
                    t.company_name,
                    t.market,
                    t.category,
                    t.sector,
                    ROUND(t.open_price, 2) AS open_price,
                    ROUND(t.high_price, 2) AS high_price,
                    ROUND(t.low_price, 2) AS low_price,
                    ROUND(t.last_price, 2) AS last_price,
                    ROUND(t.previous_close, 2) AS previous_close,
                    ROUND(t.change_pct, 2) AS change_pct,
                    t.volume,
                    ROUND(t.turnover, 2) AS turnover,
                    DATE_FORMAT(t.event_time, '%Y-%m-%d %H:%i:%s') AS event_time,
                    t.source,
                    COALESCE(a.alert_count, 0) AS alert_count,
                    COALESCE(a.high_alert_count, 0) AS high_alert_count,
                    COALESCE(m.predicted_signal, 'NONE') AS predicted_signal,
                    ROUND(COALESCE(m.predicted_next_price, 0), 2) AS predicted_next_price,
                    ROUND(COALESCE(m.confidence, 0), 4) AS confidence,
                    ROUND(COALESCE(m.predicted_next_price - m.current_price, 0), 2) AS predicted_gap,
                    COALESCE(m.model_version, '') AS model_version
                FROM price_ticks t
                INNER JOIN (
                    SELECT symbol, MAX(id) AS id
                    FROM price_ticks
                    WHERE symbol = ?
                    GROUP BY symbol
                ) latest ON t.id = latest.id
                LEFT JOIN (
                    SELECT
                        symbol,
                        COUNT(*) AS alert_count,
                        SUM(CASE WHEN alert_level = 'HIGH' THEN 1 ELSE 0 END) AS high_alert_count
                    FROM alert_events
                    WHERE symbol = ? AND created_at >= NOW() - INTERVAL 30 MINUTE
                    GROUP BY symbol
                ) a ON t.symbol = a.symbol
                LEFT JOIN (
                    SELECT p.*
                    FROM ml_predictions p
                    INNER JOIN (
                        SELECT symbol, MAX(id) AS id
                        FROM ml_predictions
                        WHERE symbol = ?
                        GROUP BY symbol
                    ) latest_prediction ON p.id = latest_prediction.id
                ) m ON t.symbol = m.symbol
                """, normalizedSymbol, normalizedSymbol, normalizedSymbol);

        if (stocks.isEmpty()) {
            detail.put("status", "NOT_FOUND");
            detail.put("symbol", normalizedSymbol);
            detail.put("message", "No stock data found");
            return detail;
        }

        detail.put("status", "OK");
        detail.put("stock", stocks.get(0));
        detail.put("recent_trend", fetchStockTrend(normalizedSymbol, 30));
        detail.put("recent_alerts", searchAlerts(normalizedSymbol, null, null, null, 10));
        return detail;
    }

    public List<Map<String, Object>> fetchStockTrend(String symbol, int minutes) {
        return fetchRows("""
                SELECT
                    DATE_FORMAT(recent.event_time, '%Y-%m-%d %H:%i:%s') AS event_time,
                    DATE_FORMAT(recent.created_at, '%Y-%m-%d %H:%i:%s') AS created_at,
                    ROUND(recent.open_price, 2) AS open_price,
                    ROUND(recent.last_price, 2) AS last_price,
                    ROUND(recent.change_pct, 2) AS change_pct,
                    recent.volume,
                    ROUND(recent.turnover, 2) AS turnover,
                    recent.source
                FROM (
                    SELECT
                        id,
                        event_time,
                        created_at,
                        open_price,
                        last_price,
                        change_pct,
                        volume,
                        turnover,
                        source
                    FROM price_ticks
                    WHERE symbol = ?
                      AND created_at >= DATE_SUB(NOW(), INTERVAL ? MINUTE)
                    ORDER BY created_at DESC, event_time DESC, id DESC
                    LIMIT 300
                ) recent
                ORDER BY recent.event_time ASC, recent.id ASC
                """, normalizeSymbol(symbol), normalizeMinutes(minutes));
    }

    public Map<String, Object> fetchStockDaily(String symbol, int days) {
        String normalizedSymbol = normalizeSymbol(symbol);
        int normalizedDays = normalizeDays(days);
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("symbol", normalizedSymbol);
        response.put("days", normalizedDays);

        List<Map<String, Object>> dailyRows;
        try {
            dailyRows = fetchRows("""
                    SELECT
                        DATE_FORMAT(trade_date, '%Y-%m-%d') AS trade_date,
                        ROUND(open_price, 2) AS open,
                        ROUND(high_price, 2) AS high,
                        ROUND(low_price, 2) AS low,
                        ROUND(last_price, 2) AS close,
                        ROUND(previous_close, 2) AS previous_close,
                        ROUND(change_pct, 4) AS change_pct,
                        volume,
                        ROUND(turnover, 2) AS turnover,
                        source
                    FROM daily_stock_bars
                    WHERE symbol = ?
                    ORDER BY trade_date DESC, id DESC
                    LIMIT ?
                    """, normalizedSymbol, normalizedDays);
            response.put("daily_source", "daily_stock_bars");
        } catch (RuntimeException ex) {
            dailyRows = List.of();
            response.put("daily_source_error", ex.getMessage());
        }

        if (dailyRows.isEmpty()) {
            dailyRows = fetchRows("""
                    SELECT
                        DATE_FORMAT(DATE(event_time), '%Y-%m-%d') AS trade_date,
                        ROUND(SUBSTRING_INDEX(GROUP_CONCAT(open_price ORDER BY event_time ASC, id ASC), ',', 1), 2) AS open,
                        ROUND(MAX(high_price), 2) AS high,
                        ROUND(MIN(low_price), 2) AS low,
                        ROUND(SUBSTRING_INDEX(GROUP_CONCAT(last_price ORDER BY event_time DESC, id DESC), ',', 1), 2) AS close,
                        ROUND(SUBSTRING_INDEX(GROUP_CONCAT(previous_close ORDER BY event_time ASC, id ASC), ',', 1), 2) AS previous_close,
                        ROUND(SUBSTRING_INDEX(GROUP_CONCAT(change_pct ORDER BY event_time DESC, id DESC), ',', 1), 4) AS change_pct,
                        MAX(volume) AS volume,
                        ROUND(MAX(turnover), 2) AS turnover,
                        'price_ticks_aggregated' AS source
                    FROM price_ticks
                    WHERE symbol = ?
                    GROUP BY DATE(event_time)
                    ORDER BY DATE(event_time) DESC
                    LIMIT ?
                    """, normalizedSymbol, normalizedDays);
            response.put("daily_source", "price_ticks_aggregated");
        }

        List<Map<String, Object>> orderedDaily = new ArrayList<>(dailyRows);
        java.util.Collections.reverse(orderedDaily);
        response.put("daily", orderedDaily);
        response.put("prediction", fetchLatestPrediction(normalizedSymbol));
        response.put("status", orderedDaily.isEmpty() ? "NO_DAILY_DATA" : "OK");
        return response;
    }

    public List<Map<String, Object>> searchAlerts(String symbol, String level, String type, String status, int limit) {
        // 告警查询同时返回阈值字段和处理状态，前端才能解释“为什么触发”和“是否已处理”。
        StringBuilder sql = new StringBuilder("""
                SELECT
                    a.id,
                    a.symbol,
                    a.company_name,
                    a.category,
                    a.sector,
                    a.market,
                    ROUND(a.last_price, 2) AS last_price,
                    ROUND(a.change_pct, 2) AS change_pct,
                    a.volume,
                    ROUND(a.turnover, 2) AS turnover,
                    a.alert_type,
                    a.alert_level,
                    ROUND(a.price_threshold, 2) AS price_threshold,
                    a.volume_threshold,
                    DATE_FORMAT(a.event_time, '%Y-%m-%d %H:%i:%s') AS event_time,
                    DATE_FORMAT(a.created_at, '%Y-%m-%d %H:%i:%s') AS created_at,
                    a.source,
                    COALESCE(act.status, 'OPEN') AS action_status,
                    COALESCE(act.note, '') AS action_note,
                    COALESCE(act.handled_by, '') AS handled_by,
                    DATE_FORMAT(act.handled_at, '%Y-%m-%d %H:%i:%s') AS handled_at
                FROM alert_events a
                LEFT JOIN alert_actions act ON a.id = act.alert_id
                WHERE 1 = 1
                """);
        List<Object> args = new ArrayList<>();
        if (symbol != null && !symbol.isBlank()) {
            sql.append(" AND a.symbol = ?");
            args.add(normalizeSymbol(symbol));
        }
        if (level != null && !level.isBlank()) {
            sql.append(" AND a.alert_level = ?");
            args.add(level.trim().toUpperCase());
        }
        if (type != null && !type.isBlank()) {
            sql.append(" AND a.alert_type = ?");
            args.add(type.trim());
        }
        if (status != null && !status.isBlank()) {
            sql.append(" AND COALESCE(act.status, 'OPEN') = ?");
            args.add(status.trim().toUpperCase());
        }
        sql.append(" ORDER BY a.created_at DESC LIMIT ?");
        args.add(normalizeLimit(limit, 20, 100));
        return fetchRows(sql.toString(), args.toArray());
    }

    public List<Map<String, Object>> fetchAlertTrend(int hours) {
        // 趋势图最多查询 168 小时，防止前端传入过大范围拖慢课堂演示环境。
        int normalizedHours = Math.min(Math.max(hours, 1), 168);
        return fetchRows("""
                SELECT
                    DATE_FORMAT(created_at, '%Y-%m-%d %H:00:00') AS hour_bucket,
                    alert_level,
                    COUNT(*) AS alert_count
                FROM alert_events
                WHERE created_at >= NOW() - INTERVAL ? HOUR
                GROUP BY hour_bucket, alert_level
                ORDER BY hour_bucket ASC
                """, normalizedHours);
    }

    public Map<String, Object> fetchAlertStats() {
        Map<String, Object> result = new LinkedHashMap<>();
        // 告警可信度图表使用三个维度：类型覆盖、行业热度、高频股票，避免只做空洞分类展示。
        result.put("type_dist", fetchRows("""
                SELECT
                    alert_type,
                    COUNT(*) AS cnt
                FROM alert_events
                WHERE created_at >= NOW() - INTERVAL 7 DAY
                GROUP BY alert_type
                ORDER BY cnt DESC
                """));
        result.put("sector_heat", fetchRows("""
                SELECT
                    COALESCE(NULLIF(sector, ''), '未分类') AS sector,
                    COUNT(*) AS cnt,
                    COALESCE(SUM(CASE WHEN alert_level = 'HIGH' THEN 1 ELSE 0 END), 0) AS high_cnt
                FROM alert_events
                WHERE created_at >= NOW() - INTERVAL 7 DAY
                GROUP BY COALESCE(NULLIF(sector, ''), '未分类')
                ORDER BY cnt DESC, high_cnt DESC
                LIMIT 10
                """));
        result.put("top_symbols", fetchRows("""
                SELECT
                    symbol,
                    company_name,
                    COUNT(*) AS cnt,
                    COALESCE(SUM(CASE WHEN alert_level = 'HIGH' THEN 1 ELSE 0 END), 0) AS high_cnt,
                    ROUND(AVG(ABS(change_pct)), 2) AS avg_change
                FROM alert_events
                WHERE created_at >= NOW() - INTERVAL 30 DAY
                GROUP BY symbol, company_name
                ORDER BY cnt DESC, high_cnt DESC
                LIMIT 10
                """));
        return result;
    }

    public Map<String, Object> updateAlertStatus(long alertId, Map<String, Object> payload) {
        String status = String.valueOf(payload.getOrDefault("status", "ACKED")).trim().toUpperCase(Locale.ROOT);
        if (!List.of("OPEN", "ACKED", "IGNORED", "RESOLVED").contains(status)) {
            status = "ACKED";
        }
        String note = String.valueOf(payload.getOrDefault("note", ""));
        String handledBy = String.valueOf(payload.getOrDefault("handled_by", "user"));
        jdbcTemplate.update(
                """
                INSERT INTO alert_actions (alert_id, status, note, handled_by, handled_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    status = VALUES(status),
                    note = VALUES(note),
                    handled_by = VALUES(handled_by),
                    handled_at = CURRENT_TIMESTAMP
                """,
                alertId,
                status,
                note,
                handledBy
        );
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("alert_id", alertId);
        response.put("status", status);
        response.put("note", note);
        response.put("handled_by", handledBy);
        return response;
    }

    public List<Map<String, Object>> fetchStockRanking(String type, int limit) {
        // 股票排行不是简单涨跌幅排序，而是综合价格动量、成交量、模型信号、行业热度和告警次数。
        String orderBy = "risk".equalsIgnoreCase(type) ? "risk_score DESC" : "optimal_score DESC";
        return fetchRows("""
                SELECT
                    t.symbol,
                    t.company_name,
                    t.market,
                    t.category,
                    t.sector,
                    ROUND(t.last_price, 2) AS last_price,
                    ROUND(t.change_pct, 2) AS change_pct,
                    t.volume,
                    ROUND(t.turnover, 2) AS turnover,
                    COALESCE(a.alert_count, 0) AS alert_count,
                    COALESCE(a.high_alert_count, 0) AS high_alert_count,
                    COALESCE(m.predicted_signal, 'NONE') AS predicted_signal,
                    ROUND(COALESCE(m.confidence, 0), 4) AS confidence,
                    ROUND(COALESCE(m.predicted_next_price - m.current_price, 0), 2) AS predicted_gap,
                    ROUND(COALESCE(h.avg_change_pct, 0), 2) AS sector_avg_change_pct,
                    ROUND(
                        50
                        + GREATEST(t.change_pct, 0) * 10
                        + LEAST(LOG10(GREATEST(t.volume, 1)) * 3, 30)
                        + CASE COALESCE(m.predicted_signal, 'NONE')
                            WHEN 'UP' THEN 18
                            WHEN 'DOWN' THEN -12
                            ELSE 0
                          END
                        + GREATEST(COALESCE(h.avg_change_pct, 0), 0) * 6
                        - COALESCE(a.alert_count, 0) * 8
                        - COALESCE(a.high_alert_count, 0) * 12,
                        2
                    ) AS optimal_score,
                    ROUND(
                        ABS(t.change_pct) * 12
                        + COALESCE(a.alert_count, 0) * 20
                        + COALESCE(a.high_alert_count, 0) * 18
                        + LEAST(LOG10(GREATEST(t.volume, 1)) * 4, 40),
                        2
                    ) AS risk_score,
                    CONCAT(
                        CASE WHEN t.change_pct > 0 THEN '价格动量为正；' ELSE '价格动量偏弱；' END,
                        CASE COALESCE(m.predicted_signal, 'NONE')
                            WHEN 'UP' THEN '模型看涨；'
                            WHEN 'DOWN' THEN '模型看跌；'
                            ELSE '模型暂无明显方向；'
                        END,
                        CASE WHEN COALESCE(a.alert_count, 0) > 0 THEN '近期存在异常告警；' ELSE '近期告警较少；' END
                    ) AS reason
                FROM price_ticks t
                INNER JOIN (
                    SELECT symbol, MAX(id) AS id
                    FROM price_ticks
                    GROUP BY symbol
                ) latest ON t.id = latest.id
                LEFT JOIN (
                    SELECT
                        symbol,
                        COUNT(*) AS alert_count,
                        SUM(CASE WHEN alert_level = 'HIGH' THEN 1 ELSE 0 END) AS high_alert_count
                    FROM alert_events
                    WHERE created_at >= NOW() - INTERVAL 30 MINUTE
                    GROUP BY symbol
                ) a ON t.symbol = a.symbol
                LEFT JOIN (
                    SELECT p.*
                    FROM ml_predictions p
                    INNER JOIN (
                        SELECT symbol, MAX(id) AS id
                        FROM ml_predictions
                        GROUP BY symbol
                    ) latest_prediction ON p.id = latest_prediction.id
                ) m ON t.symbol = m.symbol
                LEFT JOIN (
                    SELECT sector, AVG(change_pct) AS avg_change_pct
                    FROM price_ticks ht
                    INNER JOIN (
                        SELECT symbol, MAX(id) AS id
                        FROM price_ticks
                        GROUP BY symbol
                    ) latest_heat ON ht.id = latest_heat.id
                    GROUP BY sector
                ) h ON t.sector = h.sector
                ORDER BY %s
                LIMIT ?
                """.formatted(orderBy), normalizeLimit(limit, 10, 100));
    }

    public List<Map<String, Object>> fetchModelComparison() {
        // 只取最新一版模型指标，并在返回前标记异常指标，前端据此提示“低于基线/谨慎参考”。
        List<Map<String, Object>> rows = fetchRows("""
                SELECT
                    m.model_name,
                    m.metric_name,
                    m.metric_value,
                    m.model_version,
                    DATE_FORMAT(m.created_at, '%Y-%m-%d %H:%i:%s') AS created_at
                FROM ml_model_metrics m
                INNER JOIN (
                    SELECT model_version
                    FROM ml_model_metrics
                    WHERE model_name <> 'drift_monitor'
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                ) latest ON m.model_version = latest.model_version
                ORDER BY
                    CASE m.model_name
                        WHEN 'selection' THEN 0
                        WHEN 'ensemble' THEN 1
                        WHEN 'lstm' THEN 2
                        WHEN 'lightgbm' THEN 3
                        WHEN 'random_forest' THEN 4
                        ELSE 5
                    END,
                    m.model_name ASC,
                    m.metric_name ASC
                LIMIT 200
                """);
        return markAbnormalModelMetrics(rows);
    }

    private List<Map<String, Object>> markAbnormalModelMetrics(List<Map<String, Object>> rows) {
        Map<String, Map<String, Double>> metricsByModel = new LinkedHashMap<>();
        for (Map<String, Object> row : rows) {
            String modelName = String.valueOf(row.getOrDefault("model_name", ""));
            String metricName = String.valueOf(row.getOrDefault("metric_name", ""));
            metricsByModel.computeIfAbsent(modelName, ignored -> new LinkedHashMap<>())
                    .put(metricName, doubleValue(row.get("metric_value")));
        }
        for (Map<String, Object> row : rows) {
            String modelName = String.valueOf(row.getOrDefault("model_name", ""));
            String metricName = String.valueOf(row.getOrDefault("metric_name", ""));
            if (!"direction_accuracy".equals(metricName)) {
                row.put("status", "normal");
                continue;
            }
            Map<String, Double> metrics = metricsByModel.getOrDefault(modelName, Map.of());
            double accuracy = doubleValue(row.get("metric_value"));
            double baseline = metrics.getOrDefault("majority_baseline_accuracy", 0.0);
            double flatRatio = metrics.getOrDefault("validation_flat_ratio", 0.0);
            boolean suspiciousHighAccuracy = accuracy > 0.95 && baseline > 0.80;
            boolean skewedValidation = baseline > 0.85 || flatRatio > 0.90;
            if (accuracy < 0.55 || suspiciousHighAccuracy || skewedValidation) {
                row.put("status", "abnormal");
                row.put("warning", "Validation data may be insufficient or skewed; metric is for reference only.");
            } else {
                row.put("status", "normal");
            }
        }
        return rows;
    }

    private double doubleValue(Object value) {
        if (value instanceof Number number) {
            return number.doubleValue();
        }
        try {
            return Double.parseDouble(String.valueOf(value));
        } catch (RuntimeException ex) {
            return 0.0;
        }
    }

    public List<Map<String, Object>> fetchHistory(String symbol, int minutes, int limit) {
        StringBuilder sql = new StringBuilder("""
                SELECT
                    symbol,
                    company_name,
                    category,
                    sector,
                    market,
                    ROUND(last_price, 2) AS last_price,
                    ROUND(change_pct, 2) AS change_pct,
                    volume,
                    ROUND(turnover, 2) AS turnover,
                    DATE_FORMAT(event_time, '%Y-%m-%d %H:%i:%s') AS event_time,
                    source
                FROM price_ticks
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL ? MINUTE)
                """);
        List<Object> args = new ArrayList<>();
        args.add(normalizeMinutes(minutes));
        if (symbol != null && !symbol.isBlank()) {
            sql.append(" AND symbol = ?");
            args.add(normalizeSymbol(symbol));
        }
        sql.append(" ORDER BY event_time DESC, id DESC LIMIT ?");
        args.add(normalizeLimit(limit, 200, 5000));
        return fetchRows(sql.toString(), args.toArray());
    }

    public String exportHistoryCsv(String symbol, int minutes, int limit) {
        List<Map<String, Object>> rows = fetchHistory(symbol, minutes, limit);
        StringBuilder csv = new StringBuilder("\uFEFFsymbol,company_name,category,sector,market,last_price,change_pct,volume,turnover,event_time,source\n");
        for (Map<String, Object> row : rows) {
            csv.append(csvValue(row.get("symbol"))).append(',')
                    .append(csvValue(row.get("company_name"))).append(',')
                    .append(csvValue(row.get("category"))).append(',')
                    .append(csvValue(row.get("sector"))).append(',')
                    .append(csvValue(row.get("market"))).append(',')
                    .append(csvValue(row.get("last_price"))).append(',')
                    .append(csvValue(row.get("change_pct"))).append(',')
                    .append(csvValue(row.get("volume"))).append(',')
                    .append(csvValue(row.get("turnover"))).append(',')
                    .append(csvValue(row.get("event_time"))).append(',')
                    .append(csvValue(row.get("source"))).append('\n');
        }
        return csv.toString();
    }

    private Map<String, Object> fetchDatabaseHealth() {
        // 用最轻量的 SELECT 1 验证数据库连接是否可用。
        Map<String, Object> database = new LinkedHashMap<>();
        try {
            Integer result = jdbcTemplate.queryForObject("SELECT 1", Integer.class);
            database.put("status", Integer.valueOf(1).equals(result) ? "OK" : "ERROR");
            database.put("message", "MySQL connection is available");
        } catch (RuntimeException ex) {
            database.put("status", "ERROR");
            database.put("message", ex.getMessage());
        }
        return database;
    }

    private Map<String, Object> fetchLatestPrediction(String symbol) {
        List<Map<String, Object>> rows = fetchRows("""
                SELECT
                    symbol,
                    company_name,
                    category,
                    sector,
                    ROUND(current_price, 2) AS current_price,
                    ROUND(predicted_next_price, 2) AS predicted_next_price,
                    ROUND(predicted_next_price - current_price, 2) AS predicted_gap,
                    predicted_signal,
                    ROUND(COALESCE(confidence, 0), 4) AS confidence,
                    model_version,
                    DATE_FORMAT(created_at, '%Y-%m-%d %H:%i:%s') AS created_at
                FROM ml_predictions
                WHERE symbol = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """, symbol);
        return rows.isEmpty() ? new LinkedHashMap<>() : rows.get(0);
    }

    private Map<String, Object> inspectStoragePath(String path) {
        // 本地 file: 路径可以直接检查；HDFS 路径交给 Hadoop 命令或 Spark 实际写入验证。
        Map<String, Object> storage = new LinkedHashMap<>();
        storage.put("path", path);
        if (path == null || path.isBlank()) {
            storage.put("status", "UNKNOWN");
            storage.put("message", "Path is not configured");
            return storage;
        }
        if (!path.startsWith("file:")) {
            storage.put("status", "REMOTE");
            storage.put("message", "Remote HDFS path; check with hdfs dfs command");
            return storage;
        }
        try {
            File file = new File(URI.create(path));
            storage.put("status", file.exists() ? "OK" : "MISSING");
            storage.put("exists", file.exists());
            storage.put("is_directory", file.isDirectory());
            storage.put("absolute_path", file.getAbsolutePath());
        } catch (RuntimeException ex) {
            storage.put("status", "ERROR");
            storage.put("message", ex.getMessage());
        }
        return storage;
    }

    private Map<String, Object> fetchSingleRow(String sql) {
        // 图表总览类 SQL 只需要第一行，空结果时返回空 Map，避免前端报错。
        List<Map<String, Object>> rows = fetchRows(sql);
        return rows.isEmpty() ? new LinkedHashMap<>() : rows.get(0);
    }

    private List<Map<String, Object>> fetchRows(String sql) {
        // JdbcTemplate 会把查询结果转成 Map 列表，字段名直接对应前端 JSON key。
        return jdbcTemplate.queryForList(sql);
    }

    private List<Map<String, Object>> fetchRows(String sql, Object... args) {
        return jdbcTemplate.queryForList(sql, args);
    }

    private String normalizeSymbol(String symbol) {
        return symbol == null ? "" : symbol.trim().toUpperCase();
    }

    private int normalizeLimit(int limit, int defaultValue, int maxValue) {
        if (limit <= 0) {
            return defaultValue;
        }
        return Math.min(limit, maxValue);
    }

    private int normalizeMinutes(int minutes) {
        if (minutes <= 0) {
            return 30;
        }
        return Math.min(minutes, 24 * 60);
    }

    private int normalizeDays(int days) {
        if (days <= 0) {
            return 120;
        }
        return Math.min(days, 500);
    }

    private String csvValue(Object value) {
        String text = value == null ? "" : String.valueOf(value);
        return "\"" + text.replace("\"", "\"\"") + "\"";
    }
}
