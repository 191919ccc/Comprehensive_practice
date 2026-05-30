/**
 * 前端公共工具模块。
 *
 * 首页和子页面都通过 window.StockShared 复用这里的函数，避免 API 前缀、
 * 模型指标基线、告警触发原因、Markdown 安全渲染和历史导出 URL 在多个页面
 * 各写一套，后续修改口径时只需要改这一处。
 */
(function () {
    // 后端 Spring Boot 统一暴露 /api 前缀，前端所有请求都从这里拼接。
    const API_BASE = window.STOCK_API_BASE || window.API_BASE || "http://127.0.0.1:8080/api";

    // 把后端、表格或输入框里的字符串安全转换成数字，处理百分号、逗号和空值。
    function num(value, fallback = 0) {
        if (typeof value === "string") {
            const parsed = Number(value.replace(/[%+,，\s]/g, ""));
            if (Number.isFinite(parsed)) return parsed;
        }
        const number = Number(value);
        return Number.isFinite(number) ? number : fallback;
    }

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, ch => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            "\"": "&quot;",
            "'": "&#39;"
        }[ch]));
    }

    // AI 回复会被 Markdown 转成 HTML 后写入 DOM，这里统一移除危险标签和事件属性，降低 XSS 风险。
    function sanitizeHtml(html) {
        const template = document.createElement("template");
        template.innerHTML = String(html || "");
        template.content.querySelectorAll("script,style,iframe,object,embed,link,meta").forEach(node => node.remove());
        template.content.querySelectorAll("*").forEach(node => {
            [...node.attributes].forEach(attr => {
                const name = attr.name.toLowerCase();
                const value = String(attr.value || "").trim().toLowerCase();
                if (name.startsWith("on")) {
                    node.removeAttribute(attr.name);
                    return;
                }
                if ((name === "href" || name === "src") && /^(javascript:|data:text\/html)/i.test(value)) {
                    node.removeAttribute(attr.name);
                }
            });
            if (node.tagName === "A") {
                node.setAttribute("target", "_blank");
                node.setAttribute("rel", "noopener noreferrer");
            }
        });
        return template.innerHTML;
    }

    // 所有页面渲染 AI Markdown 都走同一套 sanitize 逻辑，marked 不存在时降级为纯文本换行。
    function renderMarkdown(text) {
        const source = String(text || "");
        if (window.marked?.parse) {
            if (window.marked.setOptions) {
                window.marked.setOptions({ breaks: true, gfm: true });
            }
            return sanitizeHtml(window.marked.parse(source));
        }
        return escapeHtml(source).replace(/\n/g, "<br>");
    }

    // 统一封装 fetch，保证不读取浏览器缓存，并在 HTTP 非 2xx 时直接抛错给页面提示。
    async function requestJson(path, options = {}) {
        const response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...options });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
    }

    async function postJson(path, payload = {}) {
        return requestJson(path, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
            cache: "no-store"
        });
    }

    function metricFor(rows = [], modelName = "", metricName = "") {
        return rows.find(row => row.model_name === modelName && row.metric_name === metricName);
    }

    // 给模型指标找合适的对照基线，避免只展示 accuracy 造成“看起来高但没有超过基线”的误导。
    function modelBenchmark(rows = [], row = null) {
        if (!row) return null;
        const metricName = String(row.metric_name || "");
        if (metricName.includes("balanced_direction_accuracy")) {
            return { value: 1 / 3, label: "随机三分类基线", kind: "balanced" };
        }
        if (metricName.includes("direction_macro_f1")) {
            return { value: 1 / 3, label: "随机宏 F1 参考", kind: "macro" };
        }
        const baselineMetric = metricName.startsWith("walk_forward_")
            ? "walk_forward_majority_baseline_accuracy"
            : "majority_baseline_accuracy";
        const baseline = metricFor(rows, row.model_name, baselineMetric);
        return baseline ? { value: num(baseline.metric_value), label: "多数类基线", kind: "accuracy" } : null;
    }

    function metricLabel(metricName = "") {
        const labels = {
            walk_forward_balanced_direction_accuracy: "walk-forward balanced",
            balanced_direction_accuracy: "balanced accuracy",
            direction_macro_f1: "macro F1",
            direction_accuracy: "direction accuracy",
            majority_baseline_accuracy: "多数类基线",
            return_mae: "收益率误差"
        };
        return labels[metricName] || metricName || "metric";
    }

    function formatNumber(value, digits = 2) {
        return num(value).toLocaleString("zh-CN", { maximumFractionDigits: digits });
    }

    function signedPercent(value) {
        const number = num(value);
        return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
    }

    // 根据 alert_events 中的类型、涨跌幅、成交量和阈值生成“为什么告警”的说明。
    function buildAlertReason(row = {}) {
        const type = String(row.alert_type || "");
        const changePct = num(row.change_pct);
        const volume = num(row.volume);
        const priceThreshold = num(row.price_threshold);
        const volumeThreshold = num(row.volume_threshold);
        const changeText = `<b>${signedPercent(changePct)}</b>`;
        const priceText = `${priceThreshold.toFixed(2)}%`;
        const volumeText = `<b>${formatNumber(volume, 0)}</b> 手`;
        const volumeThresholdText = `${formatNumber(volumeThreshold, 0)} 手`;

        if (type === "price_and_volume") {
            return `涨跌幅 ${changeText} 超过阈值 ${priceText}，且成交量 ${volumeText} 超过阈值 ${volumeThresholdText}`;
        }
        if (type === "price_volatility") {
            return `涨跌幅 ${changeText} 超过阈值 ${priceText}`;
        }
        if (type === "volume_spike") {
            return `成交量 ${volumeText} 超过阈值 ${volumeThresholdText}`;
        }
        if (type.startsWith("model_")) {
            const confidence = row.confidence == null ? "" : `，置信度 ${formatNumber(num(row.confidence) * 100, 1)}%`;
            return `模型类风险信号${confidence}`;
        }
        return "";
    }

    // 股票历史查询只属于行情数据能力，告警页和首页复用同一套 URL 构造规则。
    function historyPath({ symbol = "", minutes = 1440, limit = 80 } = {}) {
        const params = new URLSearchParams();
        if (symbol) params.set("symbol", symbol);
        params.set("minutes", String(minutes));
        params.set("limit", String(limit));
        return `/history?${params.toString()}`;
    }

    function historyExportUrl({ symbol = "", minutes = 1440, limit = 1000 } = {}) {
        const params = new URLSearchParams();
        if (symbol) params.set("symbol", symbol);
        params.set("minutes", String(minutes));
        params.set("limit", String(limit));
        return `${API_BASE}/history/export?${params.toString()}`;
    }

    // 挂到 window，避免各页面脚本互相 import 的同时兼容直接静态页面运行。
    window.StockShared = {
        API_BASE,
        num,
        escapeHtml,
        sanitizeHtml,
        renderMarkdown,
        requestJson,
        postJson,
        metricFor,
        modelBenchmark,
        metricLabel,
        buildAlertReason,
        historyPath,
        historyExportUrl
    };
})();
