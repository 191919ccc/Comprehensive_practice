# 本地前端依赖

页面会优先加载本目录下的库文件，缺失时才回退到 CDN。

需要放置的文件：

- `chart.umd.js`：Chart.js 4.x
- `echarts.min.js`：ECharts 5.x
- `marked.min.js`：marked 9.x

这样答辩环境断网时，首页和子页面图表仍能正常渲染。
