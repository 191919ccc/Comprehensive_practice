package com.recruitment.backend.controller;

import com.recruitment.backend.service.DashboardService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class DashboardController {

    private final DashboardService dashboardService;

    public DashboardController(DashboardService dashboardService) {
        this.dashboardService = dashboardService;
    }

    @GetMapping("/dashboard")
    public Map<String, Object> dashboard() {
        return dashboardService.fetchDashboard();
    }

    @GetMapping("/health")
    public Map<String, Object> health() {
        return dashboardService.fetchHealth();
    }

    @GetMapping("/stocks")
    public List<Map<String, Object>> stocks(
            @RequestParam(defaultValue = "") String keyword,
            @RequestParam(defaultValue = "20") int limit
    ) {
        return dashboardService.searchStocks(keyword, limit);
    }

    @GetMapping("/stocks/{symbol}")
    public Map<String, Object> stockDetail(@PathVariable String symbol) {
        return dashboardService.fetchStockDetail(symbol);
    }

    @GetMapping("/stocks/{symbol}/trend")
    public List<Map<String, Object>> stockTrend(
            @PathVariable String symbol,
            @RequestParam(defaultValue = "30") int minutes
    ) {
        return dashboardService.fetchStockTrend(symbol, minutes);
    }

    @GetMapping("/stocks/{symbol}/daily")
    public Map<String, Object> stockDaily(
            @PathVariable String symbol,
            @RequestParam(defaultValue = "120") int days
    ) {
        return dashboardService.fetchStockDaily(symbol, days);
    }

    @GetMapping("/stocks/ranking")
    public List<Map<String, Object>> stockRanking(
            @RequestParam(defaultValue = "optimal") String type,
            @RequestParam(defaultValue = "10") int limit
    ) {
        return dashboardService.fetchStockRanking(type, limit);
    }

    @GetMapping("/alerts")
    public List<Map<String, Object>> alerts(
            @RequestParam(required = false) String symbol,
            @RequestParam(required = false) String level,
            @RequestParam(required = false) String type,
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "20") int limit
    ) {
        return dashboardService.searchAlerts(symbol, level, type, status, limit);
    }

    @GetMapping("/alerts/trend")
    public List<Map<String, Object>> alertTrend(@RequestParam(defaultValue = "24") int hours) {
        return dashboardService.fetchAlertTrend(hours);
    }

    @GetMapping("/alerts/stats")
    public Map<String, Object> alertStats() {
        return dashboardService.fetchAlertStats();
    }

    @PostMapping("/alerts/{id}/status")
    public Map<String, Object> updateAlertStatus(@PathVariable long id, @RequestBody Map<String, Object> payload) {
        return dashboardService.updateAlertStatus(id, payload);
    }

    @PostMapping("/alerts/{id}/action")
    public Map<String, Object> updateAlertAction(@PathVariable long id, @RequestBody Map<String, Object> payload) {
        return dashboardService.updateAlertStatus(id, payload);
    }

    @GetMapping("/ml/models")
    public List<Map<String, Object>> modelComparison() {
        return dashboardService.fetchModelComparison();
    }

    @GetMapping("/history")
    public List<Map<String, Object>> history(
            @RequestParam(required = false) String symbol,
            @RequestParam(defaultValue = "1440") int minutes,
            @RequestParam(defaultValue = "200") int limit
    ) {
        return dashboardService.fetchHistory(symbol, minutes, limit);
    }

    @GetMapping(value = "/history/export", produces = "text/csv; charset=UTF-8")
    public String exportHistory(
            @RequestParam(required = false) String symbol,
            @RequestParam(defaultValue = "1440") int minutes,
            @RequestParam(defaultValue = "1000") int limit
    ) {
        return dashboardService.exportHistoryCsv(symbol, minutes, limit);
    }
}
