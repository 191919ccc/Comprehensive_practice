package com.recruitment.backend.service;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class DashboardServiceTest {

    @Mock
    private JdbcTemplate jdbcTemplate;

    private DashboardService dashboardService;

    @org.junit.jupiter.api.BeforeEach
    void setUp() {
        dashboardService = new DashboardService(jdbcTemplate, "/tmp/stock_output", "/tmp/stock_checkpoint");
    }

    @Test
    void updateAlertStatusNormalizesAndWritesAction() {
        Map<String, Object> response = dashboardService.updateAlertStatus(
                42L,
                Map.of("status", "resolved", "note", "done", "handled_by", "tester")
        );

        assertThat(response)
                .containsEntry("alert_id", 42L)
                .containsEntry("status", "RESOLVED")
                .containsEntry("note", "done")
                .containsEntry("handled_by", "tester");
        verify(jdbcTemplate).update(
                contains("INSERT INTO alert_actions"),
                eq(42L),
                eq("RESOLVED"),
                eq("done"),
                eq("tester")
        );
    }

    @Test
    void exportHistoryCsvEscapesCommaAndQuoteFields() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("symbol", "000001");
        row.put("company_name", "Ping An, Bank");
        row.put("category", "A");
        row.put("sector", "Finance \"Bank\"");
        row.put("market", "SZ");
        row.put("last_price", "11.23");
        row.put("change_pct", "1.25");
        row.put("volume", 1000);
        row.put("turnover", "12345.67");
        row.put("event_time", "2026-05-29 09:30:00");
        row.put("source", "sina");
        doReturn(List.of(row)).when(jdbcTemplate).queryForList(anyString(), any(Object[].class));

        String csv = dashboardService.exportHistoryCsv("000001", 1440, 200);

        assertThat(csv).startsWith("\uFEFFsymbol,company_name");
        assertThat(csv).contains("\"Ping An, Bank\"");
        assertThat(csv).contains("\"Finance \"\"Bank\"\"\"");
        assertThat(csv).contains("000001");
    }

    @Test
    void fetchAlertStatsReturnsExpectedChartSections() {
        List<Map<String, Object>> typeRows = List.of(Map.of("alert_type", "price_volatility", "cnt", 3));
        List<Map<String, Object>> sectorRows = List.of(Map.of("sector", "金融", "cnt", 2, "high_cnt", 1));
        List<Map<String, Object>> topRows = List.of(Map.of("symbol", "000001", "company_name", "平安银行", "cnt", 4, "high_cnt", 2, "avg_change", 1.23));
        when(jdbcTemplate.queryForList(contains("GROUP BY alert_type"))).thenReturn(typeRows);
        when(jdbcTemplate.queryForList(contains("GROUP BY COALESCE(NULLIF(sector"))).thenReturn(sectorRows);
        when(jdbcTemplate.queryForList(contains("GROUP BY symbol, company_name"))).thenReturn(topRows);

        Map<String, Object> stats = dashboardService.fetchAlertStats();

        assertThat(stats)
                .containsEntry("type_dist", typeRows)
                .containsEntry("sector_heat", sectorRows)
                .containsEntry("top_symbols", topRows);
    }
}
