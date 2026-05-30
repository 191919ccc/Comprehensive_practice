# 前端入口说明

当前运行入口：

- `index.html`：首页大屏，只负责页面结构和样式。
- `dashboard-home.js`：首页大屏业务逻辑。
- `dash-pages.js`：风险告警、模型分析、市场图表、系统状态等子页面逻辑。
- `shared-ui.js`：API 请求、指标口径、告警原因、Markdown 安全渲染、历史/导出 URL 等共用逻辑。
- `vendor/`：Chart.js、ECharts、marked 的本地离线依赖。

早期首页脚本 `app.js` 和旧样式 `style.css` 已删除。后续新增功能应优先放到 `shared-ui.js` 或对应页面脚本，避免再把业务逻辑写回 HTML。
