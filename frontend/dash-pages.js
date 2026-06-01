const API_BASE = window.StockShared.API_BASE;
const page = document.body.dataset.page || "";
/*
 * 子页面通用脚本。
 *
 * alerts、models、market、system 等页面共用这一份逻辑，通过 body[data-page]
 * 判断当前页面并渲染对应模块。共用能力尽量从 shared-ui.js 读取，保持首页和子页面口径一致。
 */
// 页面状态：图表实例缓存、告警筛选状态和依据数据缓存，避免重复初始化 ECharts 和重复请求趋势数据。
let charts = {};
let aiChatHistory = [];
let isRefreshing = false;
let consecutiveRefreshErrors = 0;
let alertQuickFilter = "all";
let alertVisualSymbol = "";
let pageMessageTimer = null;
const alertTrendCache = new Map();
const alertRowCache = new Map();


const labels = {
    LIVE: "真实采集",
    REPLAY: "历史回放",
    OFFLINE: "离线",
    FLOWING: "流动中",
    DELAYED: "延迟",
    STOPPED: "停止",
    UP: "看多",
    DOWN: "看空",
    WATCH: "观望",
    HIGH: "高危",
    MEDIUM: "中危",
    LOW: "低危",
    price_volatility: "价格波动",
    volume_spike: "成交量异动",
    price_and_volume: "价格+成交量双异动",
    direction_accuracy: "方向准确率",
    balanced_direction_accuracy: "平衡准确率",
    direction_macro_f1: "宏平均 F1",
    majority_baseline_accuracy: "多数类基线",
    validation_samples: "验证样本数",
    validation_down_ratio: "下跌样本占比",
    validation_up_ratio: "上涨样本占比",
    validation_flat_ratio: "观望样本占比",
    return_mae: "收益率误差",
    price_mae: "价格误差"
};

function $(id) {
    return document.getElementById(id);
}

function setText(id, value) {
    const el = $(id);
    if (el) el.textContent = value;
}

// 部分历史数据曾经出现编码错位，这里只在检测到明显乱码特征时尝试恢复，避免误伤正常中文。
function repairText(value) {
    const text = String(value ?? "");
    if (!/[ÃÂäåèéæç]/.test(text)) return text;
    try {
        const bytes = Array.from(text, ch => ch.charCodeAt(0));
        if (bytes.some(code => code > 255)) return text;
        return decodeURIComponent(bytes.map(code => "%" + code.toString(16).padStart(2, "0")).join(""));
    } catch {
        return text;
    }
}

function escapeHtml(value) {
    return repairText(value).replace(/[&<>"']/g, ch => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "\"": "&quot;",
        "'": "&#39;"
    }[ch]));
}

function num(value, fallback = 0) {
    if (typeof value === "string") {
        const parsed = Number(value.replace(/[%+,，\s]/g, ""));
        if (Number.isFinite(parsed)) return parsed;
    }
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
}

function formatNumber(value, digits = 2) {
    return num(value).toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

function formatPercent(value) {
    return `${num(value).toFixed(2)}%`;
}

function formatPrice(value) {
    return num(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function metricFor(rows = [], modelName = "", metricName = "") {
    return window.StockShared?.metricFor
        ? StockShared.metricFor(rows, modelName, metricName)
        : rows.find(row => row.model_name === modelName && row.metric_name === metricName);
}

function modelBenchmark(rows = [], row = null) {
    if (window.StockShared?.modelBenchmark) return StockShared.modelBenchmark(rows, row);
    if (!row) return null;
    const metricName = String(row.metric_name || "");
    if (metricName.includes("balanced_direction_accuracy")) {
        return { value: 1 / 3, label: "随机三分类基线" };
    }
    if (metricName.includes("direction_macro_f1")) {
        return { value: 1 / 3, label: "随机宏 F1 参考" };
    }
    const baselineMetric = metricName.startsWith("walk_forward_")
        ? "walk_forward_majority_baseline_accuracy"
        : "majority_baseline_accuracy";
    const baseline = metricFor(rows, row.model_name, baselineMetric);
    return baseline ? { value: num(baseline.metric_value), label: "多数类基线" } : null;
}

// 模型页展示训练数据是否过期；数据过期时不只看准确率，避免给用户“模型仍可靠”的错觉。
function dailyFreshnessMessage(freshness = {}) {
    const status = String(freshness.status || "OK").toUpperCase();
    const stockDate = freshness.stock_latest_trade_date || "--";
    const indexDate = freshness.index_latest_trade_date || "--";
    const stockAge = Number.isFinite(Number(freshness.stock_age_days)) ? `${freshness.stock_age_days}天` : "未知";
    const indexAge = Number.isFinite(Number(freshness.index_age_days)) ? `${freshness.index_age_days}天` : "未知";
    return {
        stale: status === "STALE" || status === "MISSING",
        status,
        detail: `日线 ${stockDate}(${stockAge})，指数 ${indexDate}(${indexAge})`
    };
}

function isModelMetricAbnormal(row, rows = []) {
    if (!row) return false;
    const accuracy = num(row.metric_value);
    const baseline = num(metricFor(rows, row.model_name, "majority_baseline_accuracy")?.metric_value);
    const flatRatio = num(metricFor(rows, row.model_name, "validation_flat_ratio")?.metric_value);
    return row.status === "abnormal" || (accuracy > .95 && baseline > .8) || baseline > .85 || flatRatio > .9;
}

function signedClass(value) {
    const number = num(value);
    if (number > 0) return "up";
    if (number < 0) return "down";
    return "warn";
}

function badgeClass(value) {
    if (value === "UP" || value === "OK") return "badge badge-up";
    if (value === "LOW") return "badge badge-neutral";
    if (value === "DOWN" || value === "HIGH" || value === "ERROR") return "badge badge-down";
    return "badge badge-warn";
}

function metricValue(rows = [], modelName = "", metricName = "", fallback = null) {
    const row = rows.find(item => item.model_name === modelName && item.metric_name === metricName);
    return row ? num(row.metric_value) : fallback;
}

function signalText(signal) {
    const value = String(signal || "NONE").toUpperCase();
    if (!value || value === "NONE" || value === "NULL") return "暂无预测";
    return labels[value] || value;
}

function signalTag(signal) {
    const value = String(signal || "NONE").toUpperCase();
    const cls = value === "UP" ? "signal-up" : value === "DOWN" ? "signal-down" : value === "WATCH" ? "signal-watch" : "signal-none";
    const icon = value === "UP" ? "▲" : value === "DOWN" ? "▼" : value === "WATCH" ? "—" : "?";
    const title = value === "NONE" || value === "NULL" ? "当前模型未对该股票生成方向信号" : "";
    return `<span class="signal-tag ${cls}" title="${escapeHtml(title)}">${icon} ${escapeHtml(signalText(value))}</span>`;
}

function deriveAlertLevel(row = {}) {
    const change = num(row.change_pct);
    const type = row.alert_type || "";
    const volumeRatio = num(row.volume_ratio ?? row.volume_change_ratio ?? row.turnover_ratio);
    const hasVolumeSpike = type === "volume_spike" || volumeRatio >= 2;
    if (change <= -3 && hasVolumeSpike) return "HIGH";
    if (hasVolumeSpike || Math.abs(change) >= 1.5 || type === "model_drift") return "MEDIUM";
    return "LOW";
}

// 后端 alert_level 优先；缺失时才按涨跌幅、成交量和模型类型做兜底等级判断。
function normalizeAlertLevel(row = {}) {
    const level = String(row.alert_level || "").toUpperCase();
    if (["HIGH", "MEDIUM", "LOW"].includes(level)) return level;
    return deriveAlertLevel(row);
}

function alertCategory(row = {}) {
    if (row.alert_type === "model_drift" || row.alert_type === "model_signal") return "model";
    if (row.alert_type === "volume_spike") return "volume";
    if (row.alert_type === "price_and_volume") return "volume";
    return "price";
}

function normalizeSymbol(value) {
    return String(value || "").trim().toUpperCase();
}

function showPageMessage(message, type = "info") {
    let box = $("pageMessage");
    if (!box) {
        box = document.createElement("div");
        box.id = "pageMessage";
        box.className = "page-message";
        document.querySelector(".dash")?.prepend(box);
    }
    box.className = `page-message ${type}`;
    box.textContent = message;
    window.clearTimeout(pageMessageTimer);
    pageMessageTimer = window.setTimeout(() => box.remove(), 3200);
}

async function requestJson(path) {
    if (window.StockShared?.requestJson) return StockShared.requestJson(path);
    const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

async function postJson(path, payload) {
    if (window.StockShared?.postJson) return StockShared.postJson(path, payload);
    const res = await fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

function pageAiQuestion(kind) {
    const names = {
        alerts: "风险告警页面",
        models: "模型分析页面",
        market: "市场图表页面",
        system: "系统状态页面"
    };
    if (kind === "risk") return `请基于当前${names[page] || "页面"}数据，说明现在最需要关注的风险是什么。`;
    if (kind === "summary") return `请基于当前${names[page] || "页面"}数据，生成一段适合答辩展示的总结。`;
    if (kind === "reason") return "当前风险最高的是哪只股票？原因是什么？";
    return `请解读当前${names[page] || "页面"}的数据。`;
}

function initAiAssistant() {
    if ($("aiFab")) return;
    const panel = document.createElement("section");
    panel.className = "ai-panel";
    panel.id = "aiPanel";
    panel.innerHTML = `
        <div class="ai-head">
            <div>
                <div class="ai-title">AI 数据解读助手</div>
                <div class="ai-sub" id="aiModelStatus">基于当前页面实时数据回答</div>
            </div>
            <button class="ai-close" type="button" id="aiClose" aria-label="关闭">×</button>
        </div>
        <div class="ai-body" id="aiMessages">
            <div class="ai-msg assistant">我会结合当前页面、实时行情、告警和模型预测解释数据，不会给出直接买卖建议。</div>
        </div>
        <div class="ai-quick">
            <button type="button" data-ai-kind="risk">风险解读</button>
            <button type="button" data-ai-kind="reason">最高风险</button>
            <button type="button" data-ai-kind="summary">答辩总结</button>
        </div>
        <form class="ai-form" id="aiForm">
            <input class="ai-input" id="aiInput" placeholder="问当前页面数据、告警原因或市场状态">
            <button class="ai-send" id="aiSend" type="submit">发送</button>
        </form>
    `;
    const fab = document.createElement("button");
    fab.className = "ai-fab";
    fab.id = "aiFab";
    fab.type = "button";
    fab.textContent = "AI 助手";
    document.body.append(panel, fab);

    fab.addEventListener("click", openAiPanel);
    $("aiClose")?.addEventListener("click", () => panel.classList.remove("open"));
    $("aiForm")?.addEventListener("submit", event => {
        event.preventDefault();
        const input = $("aiInput");
        const question = input?.value || "";
        if (input) input.value = "";
        sendAiQuestion(question);
    });
    document.querySelectorAll("[data-ai-kind]").forEach(button => {
        button.addEventListener("click", () => sendAiQuestion(pageAiQuestion(button.dataset.aiKind), button.dataset.aiKind));
    });
}

function openAiPanel() {
    $("aiPanel")?.classList.add("open");
    setTimeout(() => $("aiInput")?.focus(), 50);
}

// 子页面 AI 结果也必须走 shared-ui 的 Markdown 清洗，防止 marked.parse 后直接 innerHTML 注入。
function setAiMarkdown(element, text) {
    if (!element) return;
    if (window.StockShared?.renderMarkdown) {
        element.innerHTML = StockShared.renderMarkdown(text);
    } else {
        element.textContent = text;
    }
}
function addAiMessage(role, text) {
    const box = $("aiMessages");
    if (!box) return null;
    const item = document.createElement("div");
    item.className = `ai-msg ${role}`;
    if (role === "assistant") {
        setAiMarkdown(item, text);
    } else {
        item.textContent = text;
    }
    box.appendChild(item);
    box.scrollTop = box.scrollHeight;
    return item;
}

function inferSymbolFromQuestion(question) {
    const match = String(question || "").match(/[A-Za-z]{1,6}[0-9]{0,4}|[0-9]{5,6}/);
    return match ? match[0].toUpperCase() : "";
}

async function sendAiQuestion(question, mode = "chat") {
    const text = String(question || "").trim();
    if (!text) return;
    openAiPanel();
    addAiMessage("user", text);
    aiChatHistory.push({ role: "user", content: text });
    aiChatHistory = aiChatHistory.slice(-30);
    const pending = addAiMessage("assistant", "");
    const button = $("aiSend");
    if (button) button.disabled = true;
    setText("aiModelStatus", "正在读取系统数据并连接 DeepSeek...");
    let assistantText = "";
    try {
        const response = await fetch(`${API_BASE}/ai/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                messages: aiChatHistory,
                question: text,
                mode: `${page || "dashboard"}-${mode}`,
                symbol: inferSymbolFromQuestion(text),
                stream: false
            })
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const contentType = response.headers.get("content-type") || "";
        if (response.body && contentType.includes("text/event-stream")) {
            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let buffer = "";
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const parts = buffer.split("\n\n");
                buffer = parts.pop() || "";
                for (const part of parts) {
                    const line = part.split("\n").find(row => row.startsWith("data:"));
                    if (!line) continue;
                    const data = line.slice(5).trim();
                    if (data === "[DONE]") continue;
                    const json = JSON.parse(data);
                    assistantText += json.content || "";
                    setAiMarkdown(pending, assistantText || "正在生成...");
                }
            }
            if (!assistantText) setAiMarkdown(pending, "AI 暂无回复。");
            if (assistantText) aiChatHistory.push({ role: "assistant", content: assistantText });
            setText("aiModelStatus", "模型：deepseek-v4-flash · 流式对话");
        } else {
            const data = await response.json();
            assistantText = data.reply || "AI 暂无回复。";
            setAiMarkdown(pending, assistantText);
            aiChatHistory.push({ role: "assistant", content: assistantText });
            setText("aiModelStatus", data.warning ? "本地数据解读模式" : `模型：${data.model || "AI"}`);
        }
        aiChatHistory = aiChatHistory.slice(-30);
    } catch (error) {
        setAiMarkdown(pending, `AI 接口暂时不可用：${error.message}`);
        setText("aiModelStatus", "接口连接失败");
    } finally {
        if (button) button.disabled = false;
    }
}

function updateClock() {
    const now = new Date();
    const pad = n => String(n).padStart(2, "0");
    setText("clock", `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`);
}

function renderCommon(data) {
    const stream = data.stream_status || {};
    const summary = data.summary || {};
    const mode = stream.current_mode || "OFFLINE";
    const state = stream.stream_state || "STOPPED";
    setText("streamMode", labels[mode] || mode);
    setText("streamState", labels[state] || state);
    setText("eventsLastMinute", formatNumber(stream.events_last_minute, 0));
    setText("symbolCount", formatNumber(summary.symbol_count, 0));
    setText("alertCount", formatNumber(summary.alert_count, 0));
    setText("avgChange", formatPercent(summary.avg_change_pct));
    setText("marketBreadth", `上涨 ${formatNumber(summary.up_count, 0)} / 下跌 ${formatNumber(summary.down_count, 0)}`);
    setText("latestEventTime", stream.latest_event_time || summary.latest_event_time || "--");
    const dot = $("liveDot");
    if (dot) dot.style.background = state === "FLOWING" ? "#00e5a0" : state === "DELAYED" ? "#f0a500" : "#ff4d6a";
}

function alertStatusLabel(status) {
    return {
        OPEN: "待处理",
        ACKED: "已确认",
        IGNORED: "已忽略",
        RESOLVED: "已解决"
    }[status] || status || "待处理";
}

// 单条告警的可信度重点：展示涨跌幅、成交量、阈值和触发规则，而不是只给一个等级标签。
function buildAlertReason(row = {}) {
    if (window.StockShared?.buildAlertReason) return StockShared.buildAlertReason(row);
    const type = row.alert_type || "";
    const changePct = num(row.change_pct);
    const volume = num(row.volume);
    const priceThreshold = num(row.price_threshold);
    const volumeThreshold = num(row.volume_threshold);
    const changeText = `${changePct > 0 ? "+" : ""}${changePct.toFixed(2)}%`;
    const priceText = priceThreshold > 0 ? priceThreshold.toFixed(2) : "--";
    const volumeThresholdText = volumeThreshold > 0 ? formatNumber(volumeThreshold, 0) : "--";
    const volumeMultipleText = volumeThreshold > 0 ? `，约为阈值的 ${(volume / volumeThreshold).toFixed(2)} 倍` : "";

    if (type === "price_and_volume") {
        return `价格+成交量双异动规则：涨跌幅 <b>${changeText}</b> 超过阈值 ${priceText}%，且成交量 <b>${formatNumber(volume, 0)}</b> 手超过阈值 ${volumeThresholdText} 手${volumeMultipleText}`;
    }
    if (type === "price_volatility") {
        return `价格波动规则：涨跌幅 <b>${changeText}</b> 超过阈值 ${priceText}%`;
    }
    if (type === "volume_spike") {
        return `成交量异动规则：成交量 <b>${formatNumber(volume, 0)}</b> 手超过阈值 ${volumeThresholdText} 手${volumeMultipleText}`;
    }
    if (type === "model_drift" || type === "model_signal") {
        return `模型风险信号触发：${escapeHtml(labels[type] || type)}`;
    }
    return `触发规则：${escapeHtml(labels[type] || type || "异常告警")}`;
}

function renderAlertActions(row) {
    if (!row.id) return "";
    const status = row.action_status || "OPEN";
    return `
        <div class="action-buttons">
            <button type="button" data-alert-id="${escapeHtml(row.id)}" data-alert-status="ACKED" ${status === "ACKED" ? "disabled" : ""}>确认</button>
            <button type="button" data-alert-id="${escapeHtml(row.id)}" data-alert-status="IGNORED" ${status === "IGNORED" ? "disabled" : ""}>忽略</button>
            <button type="button" data-alert-id="${escapeHtml(row.id)}" data-alert-status="RESOLVED" ${status === "RESOLVED" ? "disabled" : ""}>解决</button>
        </div>
    `;
}

// 告警卡片渲染保留“触发原因 + 处理按钮”，列表筛选只改变展示集合，不改变原始数据。
function renderAlerts(rows = [], containerId = "alertList", showActions = page === "alerts") {
    const container = $(containerId);
    if (!container) return;
    if (containerId === "alertList" && page === "alerts") renderAlertTabs(rows);
    const displayRows = containerId === "alertList" && page === "alerts" && alertQuickFilter !== "all"
        ? rows.filter(row => alertCategory(row) === alertQuickFilter)
        : rows;
    container.innerHTML = "";
    if (!displayRows.length) {
        container.innerHTML = '<div class="empty">暂无告警数据</div>';
        return;
    }
    displayRows.forEach(row => {
        if (row.id) alertRowCache.set(String(row.id), row);
        const level = normalizeAlertLevel(row);
        const item = document.createElement("article");
        item.className = `alert-card alert-row level-${level.toLowerCase()} ${row.action_status === "IGNORED" ? "is-ignored" : ""}`;
        item.dataset.alertCardId = row.id || "";
       item.innerHTML = `
    <div>
        <strong>${escapeHtml(row.symbol)} ${escapeHtml(row.company_name)}</strong>
        <p class="alert-reason">触发原因：${buildAlertReason(row)}</p>
        <p>
            ${escapeHtml(row.event_time || row.created_at || "")} &nbsp;·&nbsp;
            ${escapeHtml(alertStatusLabel(row.action_status || "OPEN"))}
            ${row.handled_by ? ` / ${escapeHtml(row.handled_by)}` : ""}
        </p>
        </div>
        <div style="text-align:right;flex-shrink:0">
            <span class="${badgeClass(level)}">${labels[level] || level}</span>
            ${showActions ? renderAlertActions(row) : ""}
       </div>
`       ;
        container.appendChild(item);
    });
}

function renderAlertTabs(rows = []) {
    const tabs = $("alertTabs");
    if (!tabs) return;
    const counts = rows.reduce((acc, row) => {
        acc.all += 1;
        acc[alertCategory(row)] += 1;
        return acc;
    }, { all: 0, price: 0, volume: 0, model: 0 });
    const items = [
        ["all", "全部"],
        ["price", "价格异动"],
        ["volume", "成交量"],
        ["model", "模型告警"]
    ];
    tabs.innerHTML = items.map(([key, label]) => `
        <button type="button" class="${alertQuickFilter === key ? "active" : ""}" data-alert-filter="${key}">${label}(${counts[key] || 0})</button>
    `).join("");
}

function collectAlertStocks(rows = []) {
    const map = new Map();
    rows.forEach(row => {
        const symbol = normalizeSymbol(row.symbol);
        if (!symbol || map.has(symbol)) return;
        map.set(symbol, {
            symbol,
            company_name: repairText(row.company_name || ""),
            market: row.market || "",
            alert_level: normalizeAlertLevel(row)
        });
    });
    return Array.from(map.values());
}

function renderAlertStockSelect(rows = []) {
    const select = $("alertStockSelect");
    if (!select) return;
    const stocks = collectAlertStocks(rows);
    const current = alertVisualSymbol || stocks[0]?.symbol || "";
    select.innerHTML = '<option value="">选择告警股票</option>';
    stocks.forEach(row => {
        const option = document.createElement("option");
        option.value = row.symbol;
        option.textContent = `${row.symbol}${row.company_name ? ` · ${row.company_name}` : ""}${row.alert_level ? ` · ${row.alert_level}` : ""}`;
        if (row.symbol === current) option.selected = true;
        select.appendChild(option);
    });
    if (!alertVisualSymbol && current) alertVisualSymbol = current;
}

function selectedAlertHistorySymbol() {
    return normalizeSymbol($("alertChartInput")?.value || alertVisualSymbol || $("alertStockSelect")?.value || $("stockKeyword")?.value);
}

// 告警页上方的单股走势可视化，展示告警相关股票的历史走势和最新预测点。
function renderAlertStockChart(symbol, dailyRows = [], prediction = null) {
    const chart = initChart("alertStockChart");
    if (!chart) return;
    const rows = [...dailyRows].sort((a, b) => String(a.trade_date || a.event_time || "").localeCompare(String(b.trade_date || b.event_time || ""))).slice(-60);
    if (!rows.length) {
        chart.clear();
        setText("alertChartStatus", symbol ? `${symbol} 暂无历史走势` : "等待告警数据");
        return;
    }
    const labelsForAxis = rows.map(row => String(row.trade_date || row.event_time || "").slice(5, 10) || "--");
    const open = rows.map(row => num(row.open ?? row.open_price ?? row.last_price));
    const close = rows.map(row => num(row.close ?? row.last_price));
    const predicted = prediction ? [...close.slice(0, -1), num(prediction.predicted_price || prediction.predicted_return_price || close.at(-1))] : [];
    chart.setOption({
        tooltip: { trigger: "axis" },
        legend: { top: 0, textStyle: { color: "#66736a" } },
        grid: { left: 42, right: 18, top: 42, bottom: 42 },
        xAxis: { type: "category", data: labelsForAxis, axisLabel: { color: "#888780", rotate: 35 } },
        yAxis: { type: "value", axisLabel: { color: "#888780" }, splitLine: { lineStyle: { color: "#f1efe8" } } },
        series: [
            { name: "开盘价", type: "line", smooth: true, symbolSize: 4, data: open, lineStyle: { color: "#0f766e", width: 2 }, itemStyle: { color: "#0f766e" } },
            { name: "收盘/最新价", type: "line", smooth: true, symbolSize: 5, data: close, lineStyle: { color: "#2563eb", width: 2 }, itemStyle: { color: "#2563eb" }, areaStyle: { color: "rgba(37,99,235,.08)" } },
            ...(prediction ? [{ name: "短期预测", type: "line", smooth: true, symbolSize: 6, data: predicted, lineStyle: { color: "#f59e0b", width: 2 }, itemStyle: { color: "#f59e0b" } }] : [])
        ]
    });
    setText("alertChartStatus", `${symbol} · 历史走势 · ${rows.length} 天`);
}

async function loadAlertStockChart(symbol, options = {}) {
    const normalized = normalizeSymbol(symbol);
    if (!normalized) {
        setText("alertChartStatus", "请选择或输入股票代码");
        return;
    }
    alertVisualSymbol = normalized;
    const input = $("alertChartInput");
    if (input && options.syncInput !== false) input.value = "";
    const select = $("alertStockSelect");
    if (select) select.value = normalized;
    setText("alertChartStatus", `${normalized} 读取中...`);
    try {
        const data = await requestJson(`/stocks/${encodeURIComponent(normalized)}/daily?days=60`);
        renderAlertStockChart(normalized, data.daily || [], data.prediction || null);
    } catch (error) {
        showPageMessage(`股票走势读取失败：${error.message}`, "error");
        setText("alertChartStatus", `${normalized} 读取失败`);
    }
}

function renderAlertVisual(data = {}) {
    if (page !== "alerts") return;
    const rows = data.latest_alerts || [];
    renderAlertStockSelect(rows);
    if (alertVisualSymbol) loadAlertStockChart(alertVisualSymbol, { syncInput: false }).catch(console.error);
}

function marketVolumeFloor(row = {}) {
    const market = String(row.market || "").toUpperCase();
    return ["SH", "SZ", "BJ"].includes(market) ? 5000000 : 1000000;
}

// 前端证据面板按 Spark 告警规则估算阈值，用于解释展示；真正等级仍以后端入库字段为准。
function alertThresholds(row = {}, trendRows = []) {
    const history = trendRows.length ? trendRows : [row];
    const avgAbsChange = history.reduce((sum, item) => sum + Math.abs(num(item.change_pct)), 0) / Math.max(history.length, 1);
    const avgVolume = history.reduce((sum, item) => sum + num(item.volume), 0) / Math.max(history.length, 1);
    const volumeFloor = marketVolumeFloor(row);
    return {
        avgAbsChange,
        avgVolume,
        price: Math.max(2.0, avgAbsChange * 2.5),
        priceHigh: Math.max(4.0, avgAbsChange * 4.0),
        volume: Math.max(volumeFloor, avgVolume * 2.0),
        volumeHigh: Math.max(volumeFloor * 2.0, avgVolume * 4.0)
    };
}

function evidenceBar(label, value, threshold, formatter, danger = false) {
    const ratio = threshold > 0 ? Math.min(Math.abs(value) / threshold, 1.4) : 0;
    const width = Math.round(Math.min(ratio, 1) * 100);
    const pass = Math.abs(value) >= threshold;
    return `
        <div class="evidence-rule ${pass ? "is-hit" : ""}">
            <div class="evidence-rule-head">
                <span>${escapeHtml(label)}</span>
                <strong class="${danger || pass ? "down" : "warn"}">${escapeHtml(formatter(value))} / 阈值 ${escapeHtml(formatter(threshold))}</strong>
            </div>
            <div class="evidence-track"><span style="width:${width}%"></span></div>
            <small>${pass ? "已超过触发阈值" : "未超过该项阈值，可能由另一项规则触发"}</small>
        </div>
    `;
}

// 展开“查看依据”时，把该条告警对应的规则、阈值和最近行情摘要拼成证据面板。
function buildAlertEvidence(row = {}, trendRows = []) {
    const type = row.alert_type || "";
    const thresholds = alertThresholds(row, trendRows);
    const isPrice = ["price_volatility", "price_and_volume"].includes(type);
    const isVolume = ["volume_spike", "price_and_volume"].includes(type);
    const isModel = ["model_drift", "model_signal"].includes(type);
    const rules = [];
    if (isPrice || (!isVolume && !isModel)) {
        rules.push(evidenceBar("价格波动", num(row.change_pct), thresholds.price, formatPercent, Math.abs(num(row.change_pct)) >= thresholds.priceHigh));
    }
    if (isVolume) {
        rules.push(evidenceBar("成交量放大", num(row.volume), thresholds.volume, value => `${formatNumber(value, 0)}手`, num(row.volume) >= thresholds.volumeHigh));
    }
    if (isModel) {
        rules.push(`
            <div class="evidence-rule is-hit">
                <div class="evidence-rule-head"><span>模型类风险</span><strong class="warn">${escapeHtml(labels[type] || type)}</strong></div>
                <small>该告警来自模型信号或模型漂移检测，需结合模型页的验证指标一起解释。</small>
            </div>
        `);
    }
    const latest = trendRows.at(-1) || row;
    return `
        <div class="evidence-summary">
            <span>历史平均绝对涨跌幅 ${formatPercent(thresholds.avgAbsChange)}</span>
            <span>历史平均成交量 ${formatNumber(thresholds.avgVolume, 0)}手</span>
            <span>最新点 ${formatPrice(latest.last_price || row.last_price)} / ${formatPercent(latest.change_pct ?? row.change_pct)}</span>
        </div>
        <div class="evidence-rules">${rules.join("")}</div>
    `;
}

function renderAlertEvidenceChart(id, trendRows = [], alertRow = {}) {
    const chart = initChart(id);
    if (!chart) return;
    const rows = trendRows.length ? trendRows : [alertRow];
    chart.setOption({
        tooltip: { trigger: "axis" },
        grid: { left: 38, right: 18, top: 26, bottom: 32 },
        xAxis: {
            type: "category",
            data: rows.map(row => String(row.event_time || row.created_at || "").slice(11, 16) || "--"),
            axisLabel: { color: "#888780", fontSize: 10 }
        },
        yAxis: { type: "value", axisLabel: { color: "#888780", fontSize: 10 }, splitLine: { lineStyle: { color: "#f1efe8" } } },
        series: [{
            name: "价格",
            type: "line",
            smooth: true,
            symbolSize: rows.map((_, index) => index === rows.length - 1 ? 9 : 4),
            data: rows.map(row => num(row.last_price)),
            lineStyle: { color: "#2563eb", width: 2 },
            itemStyle: { color: "#dc2626" },
            markPoint: rows.length ? {
                data: [{ type: "max", name: "触发点" }],
                label: { formatter: "触发点" }
            } : undefined
        }]
    });
}

function renderAlertEvidence(row, container, trendRows = []) {
    const chartId = `alertEvidenceChart-${row.id}`;
    container.innerHTML = `
        <div class="evidence-title">触发依据：${escapeHtml(labels[row.alert_type] || row.alert_type || "异常告警")}</div>
        ${buildAlertEvidence(row, trendRows)}
        <div class="evidence-chart" id="${chartId}"></div>
    `;
    container.hidden = false;
    renderAlertEvidenceChart(chartId, trendRows, row);
}

// 证据面板懒加载最近 30 分钟走势，避免一次性请求所有告警股票导致页面打开变慢。
async function toggleAlertEvidence(alertId, target) {
    const row = alertRowCache.get(String(alertId));
    if (!row) return showPageMessage("未找到该告警的数据，刷新页面后重试。", "error");
    const card = target.closest(".alert-card");
    const container = card?.querySelector(".alert-evidence");
    if (!container) return;
    if (!container.hidden && container.dataset.loaded === "1") {
        container.hidden = true;
        target.textContent = "查看依据";
        return;
    }
    target.disabled = true;
    target.textContent = "读取中";
    container.hidden = false;
    container.innerHTML = '<div class="empty">正在读取该股票最近 30 分钟行情...</div>';
    try {
        const symbol = String(row.symbol || "").trim();
        if (symbol) loadAlertStockChart(symbol, { syncInput: false }).catch(console.error);
        const cacheKey = `${symbol}:30`;
        const trendRows = alertTrendCache.has(cacheKey)
            ? alertTrendCache.get(cacheKey)
            : await requestJson(`/stocks/${encodeURIComponent(symbol)}/trend?minutes=30`);
        alertTrendCache.set(cacheKey, trendRows);
        renderAlertEvidence(row, container, Array.isArray(trendRows) ? trendRows : []);
        container.dataset.loaded = "1";
        target.textContent = "收起依据";
    } catch (error) {
        container.innerHTML = `<div class="empty">依据数据读取失败：${escapeHtml(error.message)}</div>`;
        showPageMessage("告警依据读取失败，请确认后端服务和股票历史数据可用。", "error");
        target.textContent = "查看依据";
    } finally {
        target.disabled = false;
    }
}

function renderSearchResult(rows = []) {
    window.latestAlertSearchRows = rows;
    renderAlerts(rows, "apiResult", page === "alerts");
}

// 模型页同时展示指标和训练数据时效，指标接近基线时给出明确提示，避免过度宣传模型效果。
function renderModels(rows = [], freshness = {}) {
    const container = $("modelList");
    if (!container) return;
    container.innerHTML = "";
    const freshnessInfo = dailyFreshnessMessage(freshness);
    if (freshnessInfo.stale) {
        const note = document.createElement("div");
        note.className = "model-note model-note-bad";
        note.textContent = `训练数据过期：${freshnessInfo.detail}。请更新日线和指数日线后再重新训练。`;
        container.appendChild(note);
    }
    if (!rows.length) {
        container.insertAdjacentHTML("beforeend", '<div class="empty">暂无模型指标</div>');
        return;
    }
    const qualityRows = rows.filter(row => row.metric_name === "balanced_direction_accuracy").slice(0, 6);
    const accuracyRows = rows.filter(row => row.metric_name === "direction_accuracy").slice(0, 6);
    const maeRows = rows.filter(row => row.metric_name === "return_mae").slice(0, 6);
    const detailRows = rows.filter(row => ["direction_macro_f1", "balanced_direction_accuracy", "majority_baseline_accuracy", "validation_samples"].includes(row.metric_name)).slice(0, 12);
    const version = rows.find(row => row.model_version)?.model_version || "";
    const createdAt = rows.find(row => row.created_at)?.created_at || "";

    const headlineRows = qualityRows.length ? qualityRows : accuracyRows;
    if (headlineRows.length) {
        const grid = document.createElement("div");
        grid.className = "metric-grid";
        grid.innerHTML = headlineRows.map(row => `
            <article class="metric-tile">
                <small>${escapeHtml(row.model_name)} ${escapeHtml(labels[row.metric_name] || "方向准确率")}</small>
                <strong class="mono ${isModelMetricAbnormal(row, rows) ? "muted" : "up"}">${isModelMetricAbnormal(row, rows) ? "--" : `${Math.round(num(row.metric_value) * 100)}%`}</strong>
            </article>
        `).join("");
        container.appendChild(grid);
    }

    if (maeRows.length) {
        maeRows.forEach(row => {
            const item = document.createElement("article");
            item.className = "card-row";
            item.innerHTML = `
                <div>
                    <strong>${escapeHtml(row.model_name)} / 收益率误差</strong>
                    <p>${escapeHtml(version)}，训练时间 ${escapeHtml(createdAt)}</p>
                </div>
                <span class="mono warn">${formatNumber(row.metric_value, 4)}</span>
            `;
            container.appendChild(item);
        });
    }

    detailRows.forEach(row => {
        const item = document.createElement("article");
        const isCount = row.metric_name === "validation_samples";
        const value = isCount ? formatNumber(row.metric_value, 0) : `${Math.round(num(row.metric_value) * 100)}%`;
        item.className = "card-row";
        item.innerHTML = `
            <div>
                <strong>${escapeHtml(row.model_name)} / ${escapeHtml(labels[row.metric_name] || row.metric_name)}</strong>
                <p>${escapeHtml(version)}，训练时间 ${escapeHtml(createdAt)}</p>
            </div>
            <span class="mono ${row.metric_name === "majority_baseline_accuracy" ? "warn" : "up"}">${value}</span>
        `;
        container.appendChild(item);
    });

    const primary = headlineRows[0];
    const benchmark = modelBenchmark(rows, primary);
    if (primary && benchmark != null) {
        const current = num(primary.metric_value);
        const note = document.createElement("div");
        note.className = current < benchmark.value ? "model-note model-note-bad" : "model-note model-note-good";
        note.textContent = current < benchmark.value
            ? `当前指标（${Math.round(current * 100)}%）低于${benchmark.label}（${Math.round(benchmark.value * 100)}%），模型仍在持续优化中。`
            : `当前指标（${Math.round(current * 100)}%）高于${benchmark.label}（${Math.round(benchmark.value * 100)}%），但仍需结合 walk-forward 指标判断稳定性。`;
        container.appendChild(note);
    }

    const suspicious = headlineRows.length > 1 && headlineRows.every(row => isModelMetricAbnormal(row, rows));
    if (suspicious) {
        const note = document.createElement("div");
        note.className = "model-note";
        note.textContent = "当前验证指标异常，可能是冷启动数据不足、样本方向单一或模型过拟合。请先导入历史数据并重新训练。";
        container.appendChild(note);
    }
}

function renderRanking(id, rows = [], scoreKey) {
    const container = $(id);
    if (!container) return;
    container.innerHTML = "";
    if (!rows.length) {
        container.innerHTML = '<div class="empty">暂无排行数据</div>';
        return;
    }
    rows.slice(0, 6).forEach((row, index) => {
        const item = document.createElement("article");
        item.className = "card-row";
        const displaySignal = row.alert_signal || row.predicted_signal || "NONE";
        const rawSignal = String(row.predicted_signal || "NONE").toUpperCase();
        const conservativeSignal = String(displaySignal || "NONE").toUpperCase();
        const rawSignalText = rawSignal !== conservativeSignal && rawSignal !== "NONE" ? `，原始模型：${escapeHtml(signalText(rawSignal))}` : "";
        item.innerHTML = `
            <div>
                <strong>${index + 1}. ${escapeHtml(row.symbol)} ${escapeHtml(row.company_name)}</strong>
                <p>${escapeHtml(row.category || "")} / ${escapeHtml(row.sector || "")}，保守信号：${signalTag(displaySignal)}${rawSignalText}</p>
            </div>
            <span class="mono ${scoreKey === "risk_score" ? "warn" : "up"}">${formatNumber(row[scoreKey])}</span>
        `;
        container.appendChild(item);
    });
}

function renderTicks(rows = []) {
    const container = $("tickList");
    if (!container) return;
    container.innerHTML = "";
    if (!rows.length) {
        container.innerHTML = '<div class="empty">暂无最新行情</div>';
        return;
    }
    rows.slice(0, 12).forEach(row => {
        const item = document.createElement("article");
        item.className = "card-row";
        item.innerHTML = `
            <div>
                <strong>${escapeHtml(row.symbol)} ${escapeHtml(row.company_name)}</strong>
                <p>${escapeHtml(row.market)} / ${escapeHtml(row.source)}，${escapeHtml(row.event_time)}</p>
            </div>
            <span class="${signedClass(row.change_pct)}">${formatPrice(row.last_price)} / ${formatPercent(row.change_pct)}</span>
        `;
        container.appendChild(item);
    });
}

function renderHealth(health = {}) {
    const container = $("healthList");
    if (!container) return;
    const database = health.database || {};
    const stream = health.stream || {};
    const storage = health.storage || {};
    const rows = [
        { name: "MySQL", status: database.status || "UNKNOWN", detail: database.message || "--" },
        { name: "实时流", status: stream.status || "UNKNOWN", detail: `近 1 分钟 ${formatNumber(stream.events_last_minute, 0)} 条，累计 ${formatNumber(stream.total_events, 0)} 条` },
        { name: "结果归档", status: storage.output?.status || "UNKNOWN", detail: storage.output?.path || "--" },
        { name: "Checkpoint", status: storage.checkpoint?.status || "UNKNOWN", detail: storage.checkpoint?.path || "--" }
    ];
    container.innerHTML = rows.map(row => `
        <article class="card-row">
            <div><strong>${escapeHtml(row.name)}</strong><p>${escapeHtml(row.detail)}</p></div>
            <span class="${badgeClass(row.status)}">${escapeHtml(row.status)}</span>
        </article>
    `).join("");
}

function renderSources(rows = []) {
    const container = $("sourceList");
    if (!container) return;
    container.innerHTML = "";
    if (!rows.length) {
        container.innerHTML = '<div class="empty">暂无数据源状态</div>';
        return;
    }
    rows.forEach(row => {
        const item = document.createElement("article");
        item.className = "card-row";
        item.innerHTML = `
            <div>
                <strong>${escapeHtml(row.source)}</strong>
                <p>${formatNumber(row.symbol_count, 0)} 只股票，最后入库 ${formatNumber(row.seconds_since_last_event, 0)} 秒前</p>
            </div>
            <span class="${badgeClass(row.status)}">${labels[row.status] || row.status}</span>
        `;
        container.appendChild(item);
    });
}

function initChart(id) {
    const el = $(id);
    if (!el || typeof echarts === "undefined") return null;
    charts[id] = charts[id] || echarts.init(el);
    return charts[id];
}

function showChartEmpty(chart, message = "暂无告警统计数据") {
    chart.clear();
    chart.setOption({
        title: {
            text: message,
            left: "center",
            top: "middle",
            textStyle: { color: "#888780", fontSize: 12, fontWeight: 400 }
        }
    });
}

function alertTypeName(type) {
    return labels[type] || {
        model_drift: "模型漂移",
        model_signal: "模型信号"
    }[type] || type || "未知类型";
}

// 近 24 小时告警趋势证明系统持续在接收和处理风险事件，而不是静态截图。
async function renderAlertTrendChart() {
    const chart = initChart("alertTrendChart");
    if (!chart) return;
    const rows = await requestJson("/alerts/trend?hours=24");
    const hours = [...new Set((rows || []).map(row => row.hour_bucket))].filter(Boolean).sort();
    if (!hours.length) {
        showChartEmpty(chart, "近 24 小时暂无告警");
        return;
    }
    const byKey = new Map((rows || []).map(row => [`${row.hour_bucket}:${row.alert_level}`, num(row.alert_count, 0)]));
    chart.setOption({
        tooltip: { trigger: "axis" },
        legend: { top: 0, textStyle: { color: "#66736a" }, data: ["高危", "中危"] },
        grid: { left: 42, right: 18, top: 42, bottom: 34 },
        xAxis: {
            type: "category",
            data: hours.map(hour => String(hour).slice(11, 16)),
            axisLabel: { color: "#888780", fontSize: 10 },
            axisTick: { alignWithLabel: true }
        },
        yAxis: {
            type: "value",
            minInterval: 1,
            axisLabel: { color: "#888780", fontSize: 10 },
            splitLine: { lineStyle: { color: "#f1efe8" } }
        },
        series: [
            {
                name: "高危",
                type: "line",
                smooth: true,
                symbolSize: 6,
                data: hours.map(hour => byKey.get(`${hour}:HIGH`) || 0),
                lineStyle: { color: "#dc2626", width: 2 },
                itemStyle: { color: "#dc2626" },
                areaStyle: { color: "rgba(220,38,38,.08)" }
            },
            {
                name: "中危",
                type: "line",
                smooth: true,
                symbolSize: 6,
                data: hours.map(hour => byKey.get(`${hour}:MEDIUM`) || 0),
                lineStyle: { color: "#f0a500", width: 2 },
                itemStyle: { color: "#f0a500" },
                areaStyle: { color: "rgba(240,165,0,.08)" }
            }
        ]
    }, true);
}

function renderAlertTypeChart(stats = {}) {
    const chart = initChart("alertTypeChart");
    if (!chart) return;
    const data = (stats.type_dist || []).map(row => ({
        name: alertTypeName(row.alert_type),
        value: num(row.cnt, 0)
    })).filter(row => row.value > 0);
    if (!data.length) {
        showChartEmpty(chart, "近 7 天暂无类型统计");
        return;
    }
    chart.setOption({
        tooltip: { trigger: "item", formatter: "{b}<br/>告警 {c} 次，占比 {d}%" },
        color: ["#dc2626", "#f0a500", "#2563eb", "#00a8ff", "#00e5a0"],
        series: [{
            name: "告警类型",
            type: "pie",
            radius: ["44%", "68%"],
            center: ["50%", "54%"],
            data,
            label: { color: "#444441", fontSize: 11, formatter: "{b}\n{c}次" },
            labelLine: { length: 12, length2: 8 }
        }]
    }, true);
}

function renderAlertSectorChart(stats = {}) {
    const chart = initChart("alertSectorChart");
    if (!chart) return;
    const data = (stats.sector_heat || []).slice(0, 10).reverse();
    if (!data.length) {
        showChartEmpty(chart, "近 7 天暂无行业统计");
        return;
    }
    chart.setOption({
        tooltip: {
            trigger: "axis",
            axisPointer: { type: "shadow" },
            formatter: params => {
                const item = data[params[0].dataIndex] || {};
                return `${escapeHtml(item.sector || "未分类")}<br/>告警 ${formatNumber(item.cnt, 0)} 次<br/>高危 ${formatNumber(item.high_cnt, 0)} 次`;
            }
        },
        grid: { left: 86, right: 26, top: 12, bottom: 28 },
        xAxis: {
            type: "value",
            minInterval: 1,
            axisLabel: { color: "#888780", fontSize: 10 },
            splitLine: { lineStyle: { color: "#f1efe8" } }
        },
        yAxis: {
            type: "category",
            data: data.map(row => repairText(row.sector || "未分类")),
            axisLabel: { color: "#5f5e5a", fontSize: 10, width: 72, overflow: "truncate" }
        },
        series: [
            {
                name: "总告警",
                type: "bar",
                data: data.map(row => num(row.cnt, 0)),
                itemStyle: { color: "#f0a500", borderRadius: [0, 5, 5, 0] },
                label: { show: true, position: "right", color: "#444441", fontSize: 10 }
            },
            {
                name: "高危",
                type: "bar",
                data: data.map(row => num(row.high_cnt, 0)),
                itemStyle: { color: "#dc2626", borderRadius: [0, 5, 5, 0] }
            }
        ]
    }, true);
}

function renderAlertTopChart(stats = {}) {
    const chart = initChart("alertTopChart");
    if (!chart) return;
    const data = (stats.top_symbols || []).slice(0, 10).reverse();
    if (!data.length) {
        showChartEmpty(chart, "近 30 天暂无高频股票");
        return;
    }
    chart.setOption({
        tooltip: {
            trigger: "axis",
            axisPointer: { type: "shadow" },
            formatter: params => {
                const item = data[params[0].dataIndex] || {};
                return `${escapeHtml(item.symbol || "")} ${escapeHtml(item.company_name || "")}<br/>告警 ${formatNumber(item.cnt, 0)} 次<br/>高危 ${formatNumber(item.high_cnt, 0)} 次<br/>平均绝对涨跌幅 ${formatNumber(item.avg_change, 2)}%`;
            }
        },
        grid: { left: 86, right: 26, top: 12, bottom: 28 },
        xAxis: {
            type: "value",
            minInterval: 1,
            axisLabel: { color: "#888780", fontSize: 10 },
            splitLine: { lineStyle: { color: "#f1efe8" } }
        },
        yAxis: {
            type: "category",
            data: data.map(row => repairText(row.symbol || "--")),
            axisLabel: { color: "#5f5e5a", fontSize: 10 }
        },
        series: [{
            name: "告警次数",
            type: "bar",
            data: data.map(row => num(row.cnt, 0)),
            itemStyle: { color: "#2563eb", borderRadius: [0, 5, 5, 0] },
            label: { show: true, position: "right", color: "#444441", fontSize: 10 }
        }]
    }, true);
}

// 告警统计三图复用同一个 /alerts/stats 响应，减少接口请求并保证图表口径一致。
async function renderAlertStatsCharts() {
    if (page !== "alerts") return;
    const stats = await requestJson("/alerts/stats");
    renderAlertTypeChart(stats || {});
    renderAlertSectorChart(stats || {});
    renderAlertTopChart(stats || {});
}

function renderMarketChart(rows = []) {
    const chart = initChart("marketChart");
    if (!chart) return;
    const upCounts = rows.map(row => num(row.up_count));
    const downCounts = rows.map(row => num(row.down_count));
    const upTotal = upCounts.reduce((sum, value) => sum + value, 0);
    const downTotal = downCounts.reduce((sum, value) => sum + value, 0);
    const total = upTotal + downTotal || 1;
    const upName = `上涨 ${formatNumber(upTotal, 0)}只（${Math.round(upTotal / total * 100)}%）`;
    const downName = `下跌 ${formatNumber(downTotal, 0)}只（${Math.round(downTotal / total * 100)}%）`;
    chart.setOption({
        tooltip: { trigger: "axis" },
        legend: { textStyle: { color: "#66736a" } },
        grid: { left: 42, right: 16, top: 38, bottom: 36 },
        xAxis: { type: "category", data: rows.map(row => row.market), axisLabel: { color: "#66736a" } },
        yAxis: { type: "value", axisLabel: { color: "#66736a" }, splitLine: { lineStyle: { color: "#f1efe8" } } },
        series: [
            { name: upName, type: "bar", stack: "count", data: upCounts, itemStyle: { color: "#00C896" } },
            { name: downName, type: "bar", stack: "count", data: downCounts, itemStyle: { color: "#FF4D4D" } }
        ]
    });
}

function renderSectorChart(rows = []) {
    const chart = initChart("sectorChart");
    if (!chart) return;
    const data = rows.slice(0, 10);
    chart.setOption({
        tooltip: { trigger: "axis" },
        grid: { left: 42, right: 16, top: 26, bottom: 70 },
        xAxis: { type: "category", data: data.map(row => repairText(row.sector)), axisLabel: { color: "#66736a", rotate: 28 } },
        yAxis: { type: "value", axisLabel: { color: "#66736a" }, splitLine: { lineStyle: { color: "#f1efe8" } } },
        series: [{ name: "异常数", type: "bar", data: data.map(row => row.abnormal_count), itemStyle: { color: "#f0a500" }, label: { show: true, position: "top", color: "#2c2a27", fontSize: 11 } }]
    });
}

function renderSignalChart(rows = [], rawRows = []) {
    const chart = initChart("signalChart");
    if (!chart) return;
    const buildCounts = sourceRows => sourceRows.reduce((acc, row) => {
        const signal = String(row.predicted_signal || "WATCH").toUpperCase();
        acc[signal] = (acc[signal] || 0) + num(row.prediction_count);
        return acc;
    }, {});
    const conservativeCounts = buildCounts(rows);
    const rawCounts = buildCounts(rawRows.length ? rawRows : rows);
    const signalColors = { UP: "#f0a500", DOWN: "#00C896", WATCH: "#8a8f98" };
    const toChartData = counts => ["UP", "DOWN", "WATCH"].map(signal => ({
        name: labels[signal] || signal,
        value: counts[signal] || 0,
        itemStyle: { color: signalColors[signal] }
    }));
    const finalText = `最终口径\n观望 ${formatNumber(conservativeCounts.WATCH || 0, 0)}\n看多 ${formatNumber(conservativeCounts.UP || 0, 0)} / 看空 ${formatNumber(conservativeCounts.DOWN || 0, 0)}`;
    const rawText = `原始模型\n观望 ${formatNumber(rawCounts.WATCH || 0, 0)}\n看多 ${formatNumber(rawCounts.UP || 0, 0)} / 看空 ${formatNumber(rawCounts.DOWN || 0, 0)}`;
    chart.setOption({
        tooltip: { trigger: "item", formatter: "{a}<br/>{b}: {c}只 ({d}%)" },
        legend: { bottom: 0, textStyle: { color: "#66736a" } },
        graphic: [
            { type: "text", left: "25%", top: "14%", style: { text: "最终保守信号", textAlign: "center", fill: "#2c2a27", fontSize: 13, fontWeight: 700 } },
            { type: "text", left: "68%", top: "14%", style: { text: "原始模型方向", textAlign: "center", fill: "#66736a", fontSize: 13, fontWeight: 700 } },
            { type: "text", left: "25%", top: "38%", style: { text: finalText, textAlign: "center", fill: "#2c2a27", fontSize: 12, lineHeight: 18, fontWeight: 600 } },
            { type: "text", left: "68%", top: "38%", style: { text: rawText, textAlign: "center", fill: "#66736a", fontSize: 12, lineHeight: 18, fontWeight: 600 } }
        ],
        series: [
            { name: "最终保守信号", type: "pie", radius: ["42%", "62%"], center: ["30%", "48%"], data: toChartData(conservativeCounts), label: { fontSize: 11 } },
            { name: "原始模型方向", type: "pie", radius: ["36%", "54%"], center: ["72%", "48%"], data: toChartData(rawCounts), label: { fontSize: 11 } }
        ]
    });
}

async function searchAlerts() {
    const params = new URLSearchParams();
    const keyword = $("stockKeyword")?.value.trim();
    const level = $("alertLevel")?.value;
    const type = $("alertType")?.value;
    if (keyword) params.set("symbol", keyword);
    if (level) params.set("level", level);
    if (type) params.set("type", type);
    params.set("limit", "12");
    renderSearchResult(await requestJson(`/alerts?${params.toString()}`));
}

function renderStockHistory(rows = []) {
    const container = $("apiResult");
    if (!container) return;
    container.innerHTML = "";
    if (!rows.length) {
        container.innerHTML = '<div class="empty">没有查询到股票历史行情</div>';
        return;
    }
    rows.slice(0, 60).forEach(row => {
        const item = document.createElement("article");
        item.className = "card-row";
        item.innerHTML = `
            <div>
                <strong>${escapeHtml(row.symbol)} ${escapeHtml(row.company_name || "")}</strong>
                <p>${escapeHtml(row.market || "")} / ${escapeHtml(row.source || "")}，时间 ${escapeHtml(row.event_time || "")}</p>
            </div>
            <span class="${signedClass(row.change_pct)}">${formatPrice(row.last_price)} / ${formatPercent(row.change_pct)}</span>
        `;
        container.appendChild(item);
    });
}

async function loadStockHistory() {
    const keyword = selectedAlertHistorySymbol();
    const historyPath = window.StockShared?.historyPath
        ? StockShared.historyPath({ symbol: keyword, minutes: 1440, limit: 60 })
        : `/history?${new URLSearchParams({ ...(keyword ? { symbol: keyword } : {}), minutes: "1440", limit: "60" }).toString()}`;
    renderStockHistory(await requestJson(historyPath));
    if (keyword) setText("alertChartStatus", `${keyword} · 已加载历史记录`);
}

function exportStockHistory() {
    const keyword = selectedAlertHistorySymbol();
    const exportUrl = window.StockShared?.historyExportUrl
        ? StockShared.historyExportUrl({ symbol: keyword, minutes: 1440, limit: 1000 })
        : `${API_BASE}/history/export?${new URLSearchParams({ ...(keyword ? { symbol: keyword } : {}), minutes: "1440", limit: "1000" }).toString()}`;
    window.open(exportUrl, "_blank");
}

async function updateAlertAction(alertId, status, target) {
    const item = target?.closest?.(".alert-card");
    const originalText = target?.textContent || "";
    if (target) {
        target.disabled = true;
        target.classList.add("is-loading");
        target.textContent = "处理中";
    }
    try {
        if (status === "IGNORED" && item) item.classList.add("is-ignored");
        await postJson(`/alerts/${encodeURIComponent(alertId)}/status`, {
            status,
            note: `前端标记为 ${status}`,
            handled_by: "dashboard"
        });
        showPageMessage("告警状态已更新。", "success");
        await safeRefresh();
    } catch (error) {
        showPageMessage(`告警状态更新失败：${error.message}`, "error");
        if (status === "IGNORED" && item) item.classList.remove("is-ignored");
    } finally {
        if (target) {
            target.disabled = false;
            target.classList.remove("is-loading");
            target.textContent = originalText;
        }
    }
}

// 子页面刷新入口：先拉大屏聚合数据，再按当前 page 分发给不同模块渲染。
async function refresh() {
    try {
        const data = await requestJson("/dashboard");
        consecutiveRefreshErrors = 0;
        window.latestDashboard = data;
        renderCommon(data);
        if (page === "alerts") {
            renderAlerts(data.latest_alerts || []);
            renderAlertTrendChart().catch(error => console.error("alert trend chart failed", error));
            renderAlertStatsCharts().catch(error => console.error("alert stats charts failed", error));
        }
        if (page === "models") {
            renderModels(data.model_comparison || [], data.daily_data_freshness || {});
            renderRanking("optimalList", data.optimal_stocks || [], "optimal_score");
            renderRanking("riskList", data.risk_stocks || [], "risk_score");
            renderSignalChart(data.signal_distribution || [], data.raw_signal_distribution || []);
        }
        if (page === "market") {
            renderMarketChart(data.market_overview || []);
            renderSectorChart(data.sector_heat || []);
            renderTicks(data.latest_ticks || []);
        }
        if (page === "system") {
            renderHealth(data.system_health || {});
            renderSources(data.source_status || []);
        }
        setText("refreshStatus", `已刷新 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`);
    } catch (error) {
        consecutiveRefreshErrors += 1;
        setText("refreshStatus", `刷新失败 ${consecutiveRefreshErrors}/3`);
        if (consecutiveRefreshErrors >= 3) {
            setText("streamMode", "后端未连接");
            setText("streamState", "离线");
        }
        console.error(error);
    }
}

// 防止定时刷新、筛选操作和按钮操作同时触发多次 refresh，造成旧响应覆盖新页面。
async function safeRefresh() {
    if (isRefreshing) return;
    isRefreshing = true;
    try {
        await refresh();
    } finally {
        isRefreshing = false;
    }
}

$("alertSearchBtn")?.addEventListener("click", () => searchAlerts().catch(console.error));
$("historyBtn")?.addEventListener("click", () => loadStockHistory().catch(error => showPageMessage(`股票历史读取失败：${error.message}`, "error")));
$("exportBtn")?.addEventListener("click", exportStockHistory);
$("alertList")?.addEventListener("click", event => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) return;
    if (target.dataset.alertEvidenceId) return toggleAlertEvidence(target.dataset.alertEvidenceId, target).catch(console.error);
    const alertId = target.dataset.alertId;
    const status = target.dataset.alertStatus;
    if (alertId && status) updateAlertAction(alertId, status, target).catch(console.error);
});
$("alertTabs")?.addEventListener("click", event => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) return;
    if (!target.dataset.alertFilter) return;
    alertQuickFilter = target.dataset.alertFilter;
    renderAlerts(window.latestDashboard?.latest_alerts || []);
});
$("apiResult")?.addEventListener("click", event => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) return;
    if (target.dataset.alertEvidenceId) return toggleAlertEvidence(target.dataset.alertEvidenceId, target).catch(console.error);
    const alertId = target.dataset.alertId;
    const status = target.dataset.alertStatus;
    if (alertId && status) updateAlertAction(alertId, status, target).catch(console.error);
});
window.addEventListener("resize", () => Object.values(charts).forEach(chart => chart.resize()));
initAiAssistant();
updateClock();
setInterval(updateClock, 1000);
safeRefresh();
setInterval(safeRefresh, 5000);
