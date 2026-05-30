package com.recruitment.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

@Service
public class AiChatService {

    @FunctionalInterface
    public interface ChunkWriter {
        void write(String content) throws IOException;
    }

    private enum AiIntent {
        DATA,
        REPORT,
        WEB,
        WEB_STATUS,
        CASUAL
    }

    private record ChatInput(
            String question,
            String symbol,
            String mode,
            AiIntent intent,
            Map<String, Object> context,
            List<Map<String, String>> history
    ) {
    }

    private final DashboardService dashboardService;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;
    private final String apiKey;
    private final String model;
    private final String apiUrl;
    private final boolean webEnabled;
    private final String webSearchUrl;
    private final String serperKey;

    public AiChatService(
            DashboardService dashboardService,
            ObjectMapper objectMapper,
            @Value("${app.ai.deepseek-api-key:${DEEPSEEK_API_KEY:}}") String apiKey,
            @Value("${app.ai.model:deepseek-v4-flash}") String model,
            @Value("${app.ai.api-url:https://api.deepseek.com/v1/chat/completions}") String apiUrl,
            @Value("${app.ai.web-enabled:${AI_WEB_ENABLED:true}}") boolean webEnabled,
            @Value("${app.ai.web-search-url:https://rsshub.rssforever.com/eastmoney/search/%s}") String webSearchUrl,
            @Value("${app.ai.serper-key:${SERPER_API_KEY:}}") String serperKey
    ) {
        this.dashboardService = dashboardService;
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .followRedirects(HttpClient.Redirect.ALWAYS)
                .build();
        this.apiKey = apiKey == null ? "" : apiKey.trim();
        this.model = model == null || model.isBlank() ? "deepseek-v4-flash" : model.trim();
        this.apiUrl = apiUrl;
        this.webEnabled = webEnabled;
        this.webSearchUrl = webSearchUrl;
        this.serperKey = serperKey == null ? "" : serperKey.trim();
    }

    public Map<String, Object> chat(Map<String, Object> payload) {
        ChatInput input = buildInput(payload);
        Map<String, Object> response = baseResponse(input);

        if (apiKey.isBlank()) {
            response.put("reply", buildLocalReply(input.question(), input.intent(), input.context()));
            response.put("warning", "DEEPSEEK_API_KEY is not configured; returned local data fallback.");
            return response;
        }

        try {
            response.put("reply", callDeepSeek(buildMessages(input), false));
        } catch (Exception ex) {
            response.put("reply", buildLocalReply(input.question(), input.intent(), input.context()));
            response.put("warning", "DeepSeek request failed; returned local data fallback: " + ex.getMessage());
        }
        return response;
    }

    public void streamChat(Map<String, Object> payload, ChunkWriter writer) throws IOException {
        ChatInput input = buildInput(payload);
        if (apiKey.isBlank()) {
            writer.write(buildLocalReply(input.question(), input.intent(), input.context()));
            return;
        }

        try {
            streamDeepSeek(buildMessages(input), writer);
        } catch (Exception ex) {
            writer.write(buildLocalReply(input.question(), input.intent(), input.context()));
        }
    }

    public String modelName() {
        return apiKey.isBlank() ? "local-rule-fallback" : model;
    }

    public boolean apiKeyConfigured() {
        return !apiKey.isBlank();
    }

    public boolean webEnabled() {
        return webEnabled && (!serperKey.isBlank() || (webSearchUrl != null && !webSearchUrl.isBlank()));
    }

    private Map<String, Object> baseResponse(ChatInput input) {
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("symbol", input.symbol());
        response.put("mode", input.mode());
        response.put("intent", input.intent().name().toLowerCase(Locale.ROOT));
        response.put("model", modelName());
        response.put("web_enabled", webEnabled());
        return response;
    }

    private ChatInput buildInput(Map<String, Object> payload) {
        List<Map<String, String>> history = normalizeHistory(payload.get("messages"));
        String latestQuestion = latestUserQuestion(history);
        String question = latestQuestion.isBlank()
                ? stringValue(payload.get("question"), "请分析当前系统风险")
                : latestQuestion;
        String mode = stringValue(payload.get("mode"), "chat");
        String symbol = normalizeSymbol(stringValue(payload.get("symbol"), ""));

        Map<String, Object> globalContext = buildMarketContext(question, AiIntent.DATA);
        if (symbol.isBlank()) {
            symbol = resolveMentionedSymbol(question, globalContext);
        }

        AiIntent intent = classifyIntent(question, mode, symbol);
        Map<String, Object> context = symbol.isBlank()
                ? buildMarketContext(question, intent)
                : buildStockContext(symbol, question, intent);

        if (history.isEmpty()) {
            history = List.of(Map.of("role", "user", "content", question));
        }
        return new ChatInput(question, symbol, mode, intent, context, history);
    }

    private List<Map<String, String>> buildMessages(ChatInput input) {
        List<Map<String, String>> messages = new ArrayList<>();
        messages.add(Map.of("role", "system", "content", buildSystemPrompt(input)));
        messages.addAll(input.history());
        return messages;
    }

    private String buildSystemPrompt(ChatInput input) {
        String contextJson;
        try {
            contextJson = objectMapper.writerWithDefaultPrettyPrinter().writeValueAsString(input.context());
        } catch (Exception ex) {
            contextJson = String.valueOf(input.context());
        }

        String taskRule = switch (input.intent()) {
            case REPORT -> "用户要报告时，输出股票分析报告，包含行情表现、告警风险、模型预测、需要观察的指标和系统建议。系统建议可以是偏积极、偏谨慎或继续观察，但不要给出买入、卖出、加仓、清仓等交易指令。";
            case WEB -> "用户问外部信息时，优先使用 external_news 中实际抓到的联网资讯；如果没有抓到足够信息，明确说明联网资料不足，不要编造事实。";
            case WEB_STATUS -> "用户问联网能力时，说明当前是否启用联网增强，以及联网新闻搜索和实时行情价格 API 的区别。";
            case CASUAL -> "用户只是普通聊天时，正常聊天，不要强行输出股票总结。";
            case DATA -> "用户问股票、风险、模型、行情时，必须基于系统实时数据回答，并直接回答用户具体问题。";
        };

        return """
                你是 Quant Stream 股票实时流分析系统里的 AI 数据解读助手。
                你可以做三件事：
                1. 基于系统数据回答：使用下方 JSON 里的行情、告警、模型预测、排行、健康状态和图表数据。
                2. 联网资讯增强：只使用 external_news 里真实抓到的标题、时间和链接，不要假装知道未提供的新闻或价格。
                3. 普通聊天：用户闲聊时自然回答，不要答非所问地套股票模板。

                回答规则：
                - 先回答用户真正问的问题，不要总是返回全局市场摘要。
                - 如果用户点名某只股票或代码，优先围绕该股票回答。
                - 如果 external_news.status=ok，必须阅读 external_news.items 里的 title、source、published_at、summary_content，做跨来源归纳，不允许只罗列链接。
                - 引用新闻时必须使用可点击 Markdown 链接，格式只能是：[新闻标题](https://...)。不要输出裸 URL，不要把 URL 单独放一行。
                - 必须说明新闻对股票的可能影响路径：基本面、资金面、情绪面、风险点；资料不足时明确说不足，不要编造订单金额、业绩数字或政策条款。
                - 投资相关内容只能给风险观察、优先级和需要关注的指标，不能给具体买卖指令。
                - 数据不足或模型异常时要直接说明，不要把演示数据说成确定结论。
                - 中文回答，结构清楚，适合课程答辩展示。
                - 输出格式必须整洁，严格使用以下结构，不要在标题前加多余符号，不要输出代码块：
                  ### 核心结论
                  用 2-3 条短句说明最重要判断。
                  ### 相关新闻
                  用 3-5 条列表输出，每条必须是“来源/时间 + [新闻标题](链接) + 一句话实质内容”，禁止裸链接。
                  ### 影响分析
                  分为“基本面、资金面、风险点”三组短列表。
                  ### 综合建议
                  给出观察重点和风险提示，不给买卖指令。

                当前意图：%s
                前端模式：%s
                股票代码：%s
                当前任务规则：%s

                系统实时数据 JSON：
                %s
                """.formatted(
                input.intent().name(),
                input.mode(),
                input.symbol().isBlank() ? "全局/未指定" : input.symbol(),
                taskRule,
                contextJson
        );
    }

    private String callDeepSeek(List<Map<String, String>> messages, boolean stream) throws Exception {
        Map<String, Object> requestBody = new LinkedHashMap<>();
        requestBody.put("model", model);
        requestBody.put("messages", messages);
        requestBody.put("stream", stream);
        requestBody.put("max_tokens", 4000);
        requestBody.put("temperature", 0.45);

        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(apiUrl))
                .timeout(Duration.ofSeconds(45))
                .header("Authorization", "Bearer " + apiKey)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(requestBody), StandardCharsets.UTF_8))
                .build();

        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IllegalStateException("HTTP " + response.statusCode() + ": " + response.body());
        }
        JsonNode choices = objectMapper.readTree(response.body()).path("choices");
        if (choices.isArray() && !choices.isEmpty()) {
            String content = choices.get(0).path("message").path("content").asText("");
            if (!content.isBlank()) {
                return content;
            }
        }
        return "DeepSeek 已返回结果，但没有解析到文本内容。";
    }

    private void streamDeepSeek(List<Map<String, String>> messages, ChunkWriter writer) throws Exception {
        Map<String, Object> requestBody = new LinkedHashMap<>();
        requestBody.put("model", model);
        requestBody.put("messages", messages);
        requestBody.put("stream", true);
        requestBody.put("max_tokens", 4000);
        requestBody.put("temperature", 0.45);

        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(apiUrl))
                .timeout(Duration.ofSeconds(60))
                .header("Authorization", "Bearer " + apiKey)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(requestBody), StandardCharsets.UTF_8))
                .build();

        HttpResponse<InputStream> response = httpClient.send(request, HttpResponse.BodyHandlers.ofInputStream());
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            String errorBody = new String(response.body().readAllBytes(), StandardCharsets.UTF_8);
            throw new IllegalStateException("HTTP " + response.statusCode() + ": " + errorBody);
        }

        try (BufferedReader reader = new BufferedReader(new InputStreamReader(response.body(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (!line.startsWith("data:")) {
                    continue;
                }
                String data = line.substring(5).trim();
                if (data.isBlank() || "[DONE]".equals(data)) {
                    continue;
                }
                JsonNode root = objectMapper.readTree(data);
                JsonNode choices = root.path("choices");
                if (choices.isArray() && !choices.isEmpty()) {
                    String content = choices.get(0).path("delta").path("content").asText("");
                    if (!content.isEmpty()) {
                        writer.write(content);
                    }
                }
            }
        }
    }

    private AiIntent classifyIntent(String question, String mode, String symbol) {
        String normalized = lower(question);
        if ("report".equalsIgnoreCase(mode) || containsAny(normalized, "报告", "分析报告", "答辩总结")) {
            return AiIntent.REPORT;
        }
        if (containsAny(normalized, "联网状态", "网络状态", "联网能力", "能不能联网", "web status")) {
            return AiIntent.WEB_STATUS;
        }
        if (!symbol.isBlank() || containsAny(normalized, "股票", "a股", "港股", "美股", "行情", "股价", "涨跌", "告警", "风险", "模型", "预测", "置信", "市场", "情绪", "潜力", "优选", "分析", "哪只")) {
            return AiIntent.DATA;
        }
        if (containsAny(normalized, "黄金", "gold", "xau", "原油", "汇率", "美元指数",
                "新闻", "资讯", "昨天", "今日最新", "最新价格",
                "联网", "网络", "外部新闻", "搜索", "查一下", "查询", "查查", "web", "internet",
                "消息", "公告", "政策", "利好", "利空",
                "最近发生", "今天", "怎么了", "为什么")) {
            return AiIntent.WEB;
        }
        return AiIntent.CASUAL;
    }

    private Map<String, Object> buildStockContext(String symbol, String question, AiIntent intent) {
        Map<String, Object> context = new LinkedHashMap<>();
        Map<String, Object> detail = dashboardService.fetchStockDetail(symbol);
        context.put("stock_detail", detail);
        context.put("related_alerts", dashboardService.searchAlerts(symbol, null, null, null, 8));
        context.put("external_news", shouldFetchExternalNews(intent)
                ? buildExternalNewsContext(buildNewsQuery(symbol, detail, question, intent))
                : emptyExternalNewsContext());
        return context;
    }

    private Map<String, Object> buildMarketContext(String question, AiIntent intent) {
        Map<String, Object> dashboard = dashboardService.fetchDashboard();
        Map<String, Object> context = new LinkedHashMap<>();
        context.put("summary", dashboard.get("summary"));
        context.put("stream_status", dashboard.get("stream_status"));
        context.put("focus_stocks", firstRows(dashboard.get("focus_stocks"), 6));
        context.put("optimal_stocks", firstRows(dashboard.get("optimal_stocks"), 8));
        context.put("risk_stocks", firstRows(dashboard.get("risk_stocks"), 8));
        context.put("latest_ticks", firstRows(dashboard.get("latest_ticks"), 12));
        context.put("latest_alerts", firstRows(dashboard.get("latest_alerts"), 8));
        context.put("ml_predictions", firstRows(dashboard.get("ml_predictions"), 8));
        context.put("model_comparison", firstRows(dashboard.get("model_comparison"), 12));
        context.put("market_overview", firstRows(dashboard.get("market_overview"), 6));
        context.put("external_news", shouldFetchExternalNews(intent)
                ? buildExternalNewsContext(buildNewsQuery("", Map.of(), question, intent))
                : emptyExternalNewsContext());
        return context;
    }

    private boolean shouldFetchExternalNews(AiIntent intent) {
        return webEnabled() && (
                intent == AiIntent.WEB
                        || intent == AiIntent.WEB_STATUS
                        || intent == AiIntent.REPORT
                        || intent == AiIntent.DATA
        );
    }

    private Map<String, Object> emptyExternalNewsContext() {
        Map<String, Object> news = new LinkedHashMap<>();
        news.put("enabled", webEnabled());
        news.put("status", "not_requested");
        news.put("items", List.of());
        return news;
    }

    private String buildLocalReply(String question, AiIntent intent, Map<String, Object> context) {
        return switch (intent) {
            case WEB_STATUS -> buildWebStatusReply(context);
            case WEB -> buildWebLocalReply(context);
            case REPORT -> hasValidStockDetail(context) ? buildStockReportReply(context) : buildMarketReply(context);
            case CASUAL -> buildCasualLocalReply(question);
            case DATA -> buildDataLocalReply(question, context);
        };
    }

    private String buildDataLocalReply(String question, Map<String, Object> context) {
        String normalized = lower(question);
        String reply;
        if (hasValidStockDetail(context)) {
            reply = buildStockReply(context);
        } else if (containsAny(normalized, "潜力", "最好", "优选", "最优", "机会")) {
            reply = buildTopOpportunityReply(context);
        } else if (containsAny(normalized, "风险最高", "最高风险", "哪只")) {
            reply = buildTopRiskReply(context);
        } else if (containsAny(normalized, "模型", "预测", "置信")) {
            reply = buildModelReply(context);
        } else {
            reply = buildMarketReply(context);
        }
        return appendNewsBackground(reply, context);
    }

    private String appendNewsBackground(String reply, Map<String, Object> context) {
        List<Map<String, Object>> items = rows(asMap(context.get("external_news")).get("items"));
        if (items.isEmpty()) {
            return reply;
        }
        String titles = items.stream()
                .limit(2)
                .map(item -> stringValue(item.get("title"), ""))
                .filter(title -> !title.isBlank())
                .collect(Collectors.joining("；"));
        if (titles.isBlank()) {
            return reply;
        }
        return reply + " 联网背景：" + titles + "。";
    }

    private String buildStockReportReply(Map<String, Object> context) {
        Map<String, Object> detail = asMap(context.get("stock_detail"));
        Map<String, Object> stock = asMap(detail.get("stock"));
        List<Map<String, Object>> alerts = stockAlerts(context, detail);
        return """
                %s %s 股票分析报告：
                1. 行情表现：当前价 %s，涨跌幅 %s%%，成交量 %s。
                2. 告警风险：近30分钟告警 %s 条，高危 %s 条，重点看价格波动、成交量异常和告警频次。
                3. 模型预测：方向为 %s，展示置信约 %s%%，预测价差 %s。
                4. 需要观察：后续价格是否继续偏离、成交量是否放大、告警等级是否升级、模型信号是否连续。
                5. 系统建议：%s
                """.formatted(
                stringValue(stock.get("symbol"), "--"),
                stringValue(stock.get("company_name"), ""),
                stock.getOrDefault("last_price", "--"),
                stock.getOrDefault("change_pct", 0),
                stock.getOrDefault("volume", 0),
                alerts.size(),
                stock.getOrDefault("high_alert_count", 0),
                signalText(stringValue(stock.get("predicted_signal"), "NONE")),
                confidencePercent(stock.get("confidence")),
                stock.getOrDefault("predicted_gap", "--"),
                buildDataSuggestion(stock, alerts)
        );
    }

    private String buildStockReply(Map<String, Object> context) {
        Map<String, Object> detail = asMap(context.get("stock_detail"));
        Map<String, Object> stock = asMap(detail.get("stock"));
        List<Map<String, Object>> alerts = stockAlerts(context, detail);
        return "%s %s 当前涨跌幅 %s%%，近30分钟告警 %s 条，高危 %s 条。模型方向为 %s，展示置信约 %s%%。主要判断：%s"
                .formatted(
                        stringValue(stock.get("symbol"), "--"),
                        stringValue(stock.get("company_name"), ""),
                        stock.getOrDefault("change_pct", 0),
                        alerts.size(),
                        stock.getOrDefault("high_alert_count", 0),
                        signalText(stringValue(stock.get("predicted_signal"), "NONE")),
                        confidencePercent(stock.get("confidence")),
                        buildDataSuggestion(stock, alerts)
                );
    }

    private String buildTopRiskReply(Map<String, Object> context) {
        List<Map<String, Object>> risks = rows(context.get("risk_stocks"));
        if (risks.isEmpty()) {
            return "当前没有可排序的高风险股票。请先确认行情、告警和模型预测数据是否正常入库。";
        }
        Map<String, Object> top = risks.get(0);
        return "当前风险最高的是 %s %s，涨跌幅 %s%%，近30分钟告警 %s 条，高危 %s 条。主要原因：%s"
                .formatted(
                        stringValue(top.get("symbol"), "--"),
                        stringValue(top.get("company_name"), ""),
                        top.getOrDefault("change_pct", 0),
                        top.getOrDefault("alert_count", 0),
                        top.getOrDefault("high_alert_count", 0),
                        stringValue(top.get("reason"), "告警频次、成交量和价格波动综合较高。")
                );
    }

    private String buildTopOpportunityReply(Map<String, Object> context) {
        List<Map<String, Object>> opportunities = rows(context.get("optimal_stocks"));
        if (opportunities.isEmpty()) {
            return "当前没有可排序的潜力股数据。请确认实时行情、模型预测和优选评分是否已经入库。";
        }
        Map<String, Object> top = opportunities.get(0);
        return "按当前优选评分，潜力相对最高的是 %s %s，涨跌幅 %s%%，优选分 %s，模型方向为 %s，置信约 %s%%。原因：%s 这只是系统排序，不构成买卖建议。"
                .formatted(
                        stringValue(top.get("symbol"), "--"),
                        stringValue(top.get("company_name"), ""),
                        top.getOrDefault("change_pct", 0),
                        top.getOrDefault("optimal_score", "--"),
                        signalText(stringValue(top.get("predicted_signal"), "NONE")),
                        confidencePercent(top.get("confidence")),
                        stringValue(top.get("reason"), "综合评分相对靠前。")
                );
    }

    private String buildMarketReply(Map<String, Object> context) {
        Map<String, Object> summary = asMap(context.get("summary"));
        List<Map<String, Object>> risks = rows(context.get("risk_stocks"));
        List<Map<String, Object>> alerts = rows(context.get("latest_alerts"));
        String topRisk = risks.isEmpty()
                ? "暂无明显高风险股票"
                : stringValue(risks.get(0).get("symbol"), "--") + " " + stringValue(risks.get(0).get("company_name"), "");
        return "当前监控 %s 只股票，平均涨跌幅 %s%%，近30分钟告警 %s 条，最新告警样本 %s 条。风险最高关注 %s。系统判断以告警频次、成交量放大和价格波动为主，模型信号只作辅助参考。"
                .formatted(
                        summary.getOrDefault("symbol_count", 0),
                        summary.getOrDefault("avg_change_pct", 0),
                        summary.getOrDefault("alert_count", alerts.size()),
                        alerts.size(),
                        topRisk
                );
    }

    private String buildModelReply(Map<String, Object> context) {
        List<Map<String, Object>> predictions = rows(context.get("ml_predictions"));
        List<Map<String, Object>> metrics = rows(context.get("model_comparison"));
        long up = predictions.stream().filter(row -> "UP".equals(stringValue(row.get("predicted_signal"), ""))).count();
        long down = predictions.stream().filter(row -> "DOWN".equals(stringValue(row.get("predicted_signal"), ""))).count();
        long watch = predictions.stream().filter(row -> "WATCH".equals(stringValue(row.get("predicted_signal"), ""))).count();
        return "当前模型信号分布：看多 %s、看空 %s、观望 %s。验证指标样本 %s 条。建议同时看方向准确率、平衡准确率、宏平均 F1 和收益率误差，不要只看单一准确率。"
                .formatted(up, down, watch, metrics.size());
    }

    private String buildWebStatusReply(Map<String, Object> context) {
        Map<String, Object> news = asMap(context.get("external_news"));
        if (!webEnabled()) {
            return "联网增强未启用。设置 app.ai.web-enabled=true 或 AI_WEB_ENABLED=true 并重启后端后，AI 可以把外部新闻标题注入上下文。";
        }
        String status = stringValue(news.get("status"), "unknown");
        if ("ok".equals(status)) {
            return "联网增强已启用，本次抓到 " + rows(news.get("items")).size() + " 条外部资讯，可用于背景解释。注意：新闻搜索不是精确行情价格 API。";
        }
        return "联网增强已启用，但本次外部资讯不可用：" + stringValue(news.get("error"), "未知原因") + "。系统会退回本地行情、告警和模型数据回答。";
    }

    private String buildWebLocalReply(Map<String, Object> context) {
        Map<String, Object> news = asMap(context.get("external_news"));
        List<Map<String, Object>> items = rows(news.get("items"));
        if (items.isEmpty()) {
            return webEnabled()
                    ? "联网增强已启用，但本次没有取得可用外部资讯。涉及精确历史价格时，需要接入专门行情价格 API。"
                    : "这个问题需要外部信息，但联网增强未启用。请启用 app.ai.web-enabled=true 后重启后端。";
        }
        String titles = items.stream()
                .limit(4)
                .map(item -> "《" + stringValue(item.get("title"), "") + "》")
                .collect(Collectors.joining("、"));
        return "联网增强检索到这些资讯：" + titles + "。这些新闻可辅助判断背景，但不能替代精确行情 API。";
    }

    private String buildCasualLocalReply(String question) {
        String normalized = lower(question);
        if (containsAny(normalized, "你好", "hello", "hi")) {
            return "你好，我在。你可以和我聊天，也可以问当前股票、告警、模型预测，或让我结合联网资讯解释数据。";
        }
        return "我在。本地模式下我可以陪你简单聊天；配置 DEEPSEEK_API_KEY 后，我会使用 DeepSeek 进行更自然的连续对话，并结合你的系统数据回答。";
    }

    private String buildDataSuggestion(Map<String, Object> stock, List<Map<String, Object>> alerts) {
        String signal = stringValue(stock.get("predicted_signal"), "NONE");
        double changePct = doubleValue(stock.get("change_pct"));
        double confidence = doubleValue(stock.get("confidence"));
        int highAlerts = (int) Math.round(doubleValue(stock.get("high_alert_count")));
        int alertCount = alerts.size();
        if (highAlerts > 0 || alertCount >= 8 || "DOWN".equals(signal) || changePct <= -2.0) {
            return "偏谨慎。告警或下行压力较强，建议降低展示优先级，等待告警回落、成交量稳定或模型信号改善后再评估。";
        }
        if ("UP".equals(signal) && confidence >= 0.60 && changePct >= 0 && alertCount <= 3) {
            return "偏积极。趋势和模型信号相对一致，可列入重点观察，继续确认成交量是否配合、告警是否维持低位。";
        }
        if ("WATCH".equals(signal)) {
            return "继续观察。模型方向不明确，重点看后续价格是否突破、成交量是否放大、告警频次是否下降。";
        }
        return "中性观察。当前信号不够一致，建议结合后续行情、告警变化和模型置信度再判断优先级。";
    }

    private Map<String, Object> buildExternalNewsContext(String query) {
        Map<String, Object> news = new LinkedHashMap<>();
        news.put("enabled", webEnabled());
        news.put("query", query);
        if (!webEnabled()) {
            news.put("status", "disabled");
            news.put("items", List.of());
            return news;
        }
        try {
            news.put("items", fetchNewsItems(query, 8));
            news.put("status", "ok");
            news.put("search_engine_mode", serperKey.isBlank() ? "rss_fallback_single_site" : "serper_full_web");
        } catch (Exception ex) {
            System.err.println("[AI联网] 抓取失败 query=" + query + " error=" + ex.getMessage());
            news.put("status", "unavailable");
            news.put("error", ex.getMessage());
            news.put("items", List.of());
        }
        return news;
    }

    private String buildNewsQuery(String symbol, Map<String, Object> detail, String question, AiIntent intent) {
        if (intent == AiIntent.WEB_STATUS) {
            return "A股 港股 市场 新闻";
        }
        if (!symbol.isBlank()) {
            Map<String, Object> stock = asMap(detail.get("stock"));
            String name = stringValue(stock.get("company_name"), "");
            return (symbol + " " + name + " 股票 最新新闻 公告 研报 资金面").trim();
        }
        if (intent == AiIntent.WEB) {
            return question;
        }
        return "A股 港股 市场 新闻";
    }

    private List<Map<String, Object>> fetchNewsItems(String query, int limit) throws Exception {
        if (!serperKey.isBlank()) {
            return fetchNewsFromSerper(query, limit, serperKey);
        }
        return fetchNewsFromRss(query, limit);
    }

    private List<Map<String, Object>> fetchNewsFromSerper(String query, int limit, String apiKey) throws Exception {
        List<Map<String, Object>> items = new ArrayList<>();
        fetchSerperEndpoint("https://google.serper.dev/news", query, limit, apiKey, "news", items);
        if (items.size() < limit) {
            fetchSerperEndpoint("https://google.serper.dev/search", query, limit - items.size(), apiKey, "organic", items);
        }
        if (items.isEmpty()) {
            throw new IllegalStateException("serper returned 0 news/search items");
        }
        return items.stream().limit(limit).collect(Collectors.toList());
    }

    private void fetchSerperEndpoint(
            String url,
            String query,
            int limit,
            String apiKey,
            String arrayField,
            List<Map<String, Object>> items
    ) throws Exception {
        String body = objectMapper.writeValueAsString(Map.of(
                "q", query,
                "gl", "cn",
                "hl", "zh-cn",
                "num", limit
        ));
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .timeout(Duration.ofSeconds(8))
                .header("X-API-KEY", apiKey)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8))
                .build();
        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IllegalStateException("serper HTTP " + response.statusCode() + ": " + response.body());
        }
        JsonNode root = objectMapper.readTree(response.body());
        int targetSize = items.size() + Math.max(0, limit);
        for (JsonNode node : root.path(arrayField)) {
            String title = node.path("title").asText("");
            if (title.isBlank()) {
                continue;
            }
            String link = node.path("link").asText("");
            if (items.stream().anyMatch(item -> title.equals(item.get("title")) || link.equals(item.get("link")))) {
                continue;
            }
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("title", stripHtml(title));
            item.put("link", link);
            item.put("source", node.path("source").asText(arrayField.equals("news") ? "全网新闻" : "全网网页"));
            item.put("published_at", node.path("date").asText(""));
            item.put("summary_content", stripHtml(node.path("snippet").asText("")));
            items.add(item);
            if (items.size() >= targetSize) {
                break;
            }
        }
    }

    private List<Map<String, Object>> fetchNewsFromRss(String query, int limit) throws Exception {
        String encodedQuery = URLEncoder.encode(query, StandardCharsets.UTF_8);
        String url = webSearchUrl.contains("%s")
                ? webSearchUrl.replace("%s", encodedQuery)
                : webSearchUrl + encodedQuery;
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .timeout(Duration.ofSeconds(6))
                .header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
                .header("Accept", "text/html,application/rss+xml,application/xml;q=0.9,*/*;q=0.8")
                .header("Accept-Language", "zh-CN,zh;q=0.9")
                .GET()
                .build();
        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IllegalStateException("news HTTP " + response.statusCode());
        }
        List<Map<String, Object>> items = parseRssItems(response.body(), limit);
        if (items.isEmpty()) {
            throw new IllegalStateException("news response parsed 0 items from " + url);
        }
        return items;
    }

    private List<Map<String, Object>> parseRssItems(String xml, int limit) {
        List<Map<String, Object>> items = new ArrayList<>();
        Matcher itemMatcher = Pattern.compile("<item>(.*?)</item>", Pattern.CASE_INSENSITIVE | Pattern.DOTALL).matcher(xml);
        while (itemMatcher.find() && items.size() < limit) {
            String itemXml = itemMatcher.group(1);
            String title = extractXmlTag(itemXml, "title");
            String link = extractXmlTag(itemXml, "link");
            String pubDate = extractXmlTag(itemXml, "pubDate");
            String description = extractXmlTag(itemXml, "description");
            if (!title.isBlank()) {
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("title", stripHtml(title));
                item.put("link", htmlDecode(link));
                item.put("source", "RSS降级来源");
                item.put("published_at", htmlDecode(pubDate));
                item.put("summary_content", stripHtml(description));
                items.add(item);
            }
        }
        return items.isEmpty() ? parseSogouHtmlItems(xml, limit) : items;
    }

    private List<Map<String, Object>> parseSogouHtmlItems(String html, int limit) {
        List<Map<String, Object>> items = new ArrayList<>();
        Matcher titleMatcher = Pattern.compile(
                "<h3[^>]*class=\"[^\"]*vr-title[^\"]*\"[^>]*>\\s*<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>",
                Pattern.CASE_INSENSITIVE | Pattern.DOTALL
        ).matcher(html);
        while (titleMatcher.find() && items.size() < limit) {
            addHtmlNewsItem(items, titleMatcher.group(2), titleMatcher.group(1));
        }
        Matcher cardMatcher = Pattern.compile(
                "<div[^>]*class=\"[^\"]*titleWrap[^\"]*\"[^>]*>\\s*<a[^>]*href=\"([^\"]+)\"[^>]*>\\s*<div[^>]*>(.*?)</div>",
                Pattern.CASE_INSENSITIVE | Pattern.DOTALL
        ).matcher(html);
        while (cardMatcher.find() && items.size() < limit) {
            addHtmlNewsItem(items, cardMatcher.group(2), cardMatcher.group(1));
        }
        return items;
    }

    private void addHtmlNewsItem(List<Map<String, Object>> items, String rawTitle, String rawLink) {
        String title = stripHtml(rawTitle);
        if (title.isBlank() || items.stream().anyMatch(item -> title.equals(item.get("title")))) {
            return;
        }
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("title", title);
        item.put("link", htmlDecode(rawLink));
        item.put("source", "HTML降级来源");
        item.put("published_at", "");
        item.put("summary_content", title);
        items.add(item);
    }

    private String extractXmlTag(String xml, String tagName) {
        Matcher matcher = Pattern.compile("<" + tagName + ">(.*?)</" + tagName + ">", Pattern.CASE_INSENSITIVE | Pattern.DOTALL).matcher(xml);
        return matcher.find() ? matcher.group(1).replace("<![CDATA[", "").replace("]]>", "").trim() : "";
    }

    private List<Map<String, String>> normalizeHistory(Object value) {
        List<Map<String, Object>> rawRows = rows(value);
        if (rawRows.isEmpty()) {
            return List.of();
        }
        int start = Math.max(0, rawRows.size() - 30);
        List<Map<String, String>> normalized = new ArrayList<>();
        for (Map<String, Object> row : rawRows.subList(start, rawRows.size())) {
            String role = stringValue(row.get("role"), "user").toLowerCase(Locale.ROOT);
            if (!List.of("user", "assistant").contains(role)) {
                role = "user";
            }
            String content = stringValue(row.get("content"), "").trim();
            if (!content.isBlank()) {
                normalized.add(Map.of("role", role, "content", content));
            }
        }
        return normalized;
    }

    private String latestUserQuestion(List<Map<String, String>> history) {
        for (int i = history.size() - 1; i >= 0; i--) {
            Map<String, String> row = history.get(i);
            if ("user".equals(row.get("role"))) {
                return stringValue(row.get("content"), "");
            }
        }
        return "";
    }

    private String resolveMentionedSymbol(String question, Map<String, Object> context) {
        String normalizedQuestion = normalizeMentionText(question);
        if (normalizedQuestion.isBlank()) {
            return "";
        }
        String aliasSymbol = resolveKnownAlias(normalizedQuestion);
        if (!aliasSymbol.isBlank()) {
            return aliasSymbol;
        }
        for (String key : List.of("optimal_stocks", "risk_stocks", "focus_stocks", "ml_predictions", "latest_ticks", "latest_alerts")) {
            for (Map<String, Object> row : rows(context.get(key))) {
                String symbol = normalizeSymbol(stringValue(row.get("symbol"), ""));
                String name = stringValue(row.get("company_name"), "");
                if (!symbol.isBlank() && matchesMention(normalizedQuestion, symbol, name)) {
                    return symbol;
                }
            }
        }
        return "";
    }

    private String resolveKnownAlias(String normalizedQuestion) {
        Map<String, String> aliases = Map.ofEntries(
                Map.entry("茅台", "600519"),
                Map.entry("贵州茅台", "600519"),
                Map.entry("汾酒", "600809"),
                Map.entry("山西汾酒", "600809"),
                Map.entry("小米", "01810"),
                Map.entry("小米集团", "01810"),
                Map.entry("腾讯", "00700"),
                Map.entry("阿里", "09988"),
                Map.entry("美团", "03690"),
                Map.entry("宁德时代", "300750"),
                Map.entry("比亚迪", "002594"),
                Map.entry("格力", "000651"),
                Map.entry("美的", "000333")
        );
        for (Map.Entry<String, String> entry : aliases.entrySet()) {
            if (normalizedQuestion.contains(normalizeMentionText(entry.getKey()))) {
                return entry.getValue();
            }
        }
        return "";
    }

    private boolean matchesMention(String normalizedQuestion, String symbol, String companyName) {
        String normalizedSymbol = normalizeMentionText(symbol);
        String normalizedName = normalizeMentionText(companyName);
        return (!normalizedSymbol.isBlank() && normalizedQuestion.contains(normalizedSymbol))
                || (!normalizedName.isBlank() && normalizedName.length() >= 2
                && (normalizedQuestion.contains(normalizedName)
                || normalizedName.contains(normalizedQuestion)
                || containsNameFragment(normalizedQuestion, normalizedName)));
    }

    private boolean containsNameFragment(String normalizedQuestion, String normalizedName) {
        for (int start = 0; start < normalizedName.length() - 1; start++) {
            String fragment = normalizedName.substring(start, start + 2);
            if (List.of("中国", "国际", "控股", "股份", "集团").contains(fragment)) {
                continue;
            }
            if (normalizedQuestion.contains(fragment)) {
                return true;
            }
        }
        return false;
    }

    private boolean hasValidStockDetail(Map<String, Object> context) {
        Map<String, Object> detail = asMap(context.get("stock_detail"));
        return "OK".equals(stringValue(detail.get("status"), ""));
    }

    private List<Map<String, Object>> stockAlerts(Map<String, Object> context, Map<String, Object> detail) {
        List<Map<String, Object>> alerts = rows(detail.get("recent_alerts"));
        if (alerts.isEmpty()) {
            alerts = rows(context.get("related_alerts"));
        }
        return alerts;
    }

    private List<Map<String, Object>> firstRows(Object value, int limit) {
        return rows(value).stream().limit(limit).collect(Collectors.toList());
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> rows(Object value) {
        if (value instanceof List<?> list) {
            return list.stream()
                    .filter(Objects::nonNull)
                    .filter(Map.class::isInstance)
                    .map(item -> (Map<String, Object>) item)
                    .collect(Collectors.toList());
        }
        return List.of();
    }

    private Map<String, Object> asMap(Object value) {
        if (value instanceof Map<?, ?> map) {
            Map<String, Object> result = new LinkedHashMap<>();
            map.forEach((key, item) -> result.put(String.valueOf(key), item));
            return result;
        }
        return Map.of();
    }

    private String signalText(String signal) {
        return switch (signal) {
            case "UP" -> "看多";
            case "DOWN" -> "看空";
            case "WATCH" -> "观望";
            default -> "暂无明确方向";
        };
    }

    private String confidencePercent(Object value) {
        double confidence = doubleValue(value);
        if (confidence <= 0) {
            return "0";
        }
        return String.valueOf(Math.round(confidence * 100));
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

    private String normalizeSymbol(String symbol) {
        return symbol == null ? "" : symbol.trim().toUpperCase(Locale.ROOT);
    }

    private String normalizeMentionText(String value) {
        String text = stringValue(value, "").toUpperCase(Locale.ROOT);
        for (String word : List.of("股份", "控股", "集团", "有限公司", "公司", "-W", " ", "·", ".", "_", "-", "(", ")", "（", "）")) {
            text = text.replace(word, "");
        }
        return text;
    }

    private String lower(String value) {
        return stringValue(value, "").toLowerCase(Locale.ROOT);
    }

    private boolean containsAny(String text, String... needles) {
        for (String needle : needles) {
            if (text.contains(needle.toLowerCase(Locale.ROOT))) {
                return true;
            }
        }
        return false;
    }

    private String htmlDecode(String value) {
        return stringValue(value, "")
                .replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&quot;", "\"")
                .replace("&#39;", "'");
    }

    private String stripHtml(String value) {
        return htmlDecode(value)
                .replace("<!--red_beg-->", "")
                .replace("<!--red_end-->", "")
                .replaceAll("<[^>]+>", "")
                .replaceAll("\\s+", " ")
                .trim();
    }

    private String stringValue(Object value, String fallback) {
        if (value == null) {
            return fallback;
        }
        String text = String.valueOf(value);
        return text.isBlank() ? fallback : text;
    }

    private String stringValue(Object value) {
        return stringValue(value, "");
    }
}
