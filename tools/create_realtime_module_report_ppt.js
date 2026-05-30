const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const sharp = require("sharp");

const projectRoot = path.resolve(__dirname, "..");
const outDir = path.join(projectRoot, "docs", "ppt");
const previewDir = path.join(outDir, "realtime_module_report_preview");
fs.mkdirSync(previewDir, { recursive: true });
for (const file of fs.readdirSync(previewDir)) {
  if (file.endsWith(".png")) fs.unlinkSync(path.join(previewDir, file));
}

const pptx = new pptxgen();
pptx.defineLayout({ name: "WIDE", width: 13.333, height: 7.5 });
pptx.layout = "WIDE";
pptx.author = "Comprehensive Practice";
pptx.company = "Quant Stream";
pptx.subject = "股票实时流分析平台实时数据分析模块汇报";
pptx.title = "股票实时流分析平台实时数据分析模块汇报";
pptx.lang = "zh-CN";
pptx.theme = {
  headFontFace: "Microsoft YaHei",
  bodyFontFace: "Microsoft YaHei",
  lang: "zh-CN",
};

const C = {
  bg: "F7FAFC",
  ink: "102033",
  muted: "5E7185",
  line: "D7E0EA",
  navy: "0B1F36",
  blue: "1D7CF2",
  green: "18A058",
  amber: "F59E0B",
  red: "DC2626",
  cyan: "00A8FF",
  white: "FFFFFF",
  lightBlue: "E8F2FF",
  lightGreen: "E9F8F0",
  lightAmber: "FFF7E6",
};

const previews = [];

function esc(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function addBg(slide, dark = false) {
  slide.background = { color: dark ? C.navy : C.bg };
}

function addFooter(slide, pageNo, dark = false) {
  slide.addText("股票实时流分析平台 · 实时数据分析模块", {
    x: 0.55,
    y: 7.06,
    w: 5.8,
    h: 0.18,
    fontFace: "Microsoft YaHei",
    fontSize: 7.5,
    color: dark ? "9FB2C8" : "718096",
    margin: 0,
  });
  slide.addText(String(pageNo).padStart(2, "0"), {
    x: 12.15,
    y: 7.03,
    w: 0.55,
    h: 0.2,
    fontFace: "Aptos",
    fontSize: 8,
    bold: true,
    color: dark ? "9FB2C8" : "718096",
    align: "right",
    margin: 0,
  });
}

function addTitle(slide, title, subtitle, dark = false) {
  slide.addText(title, {
    x: 0.7,
    y: 0.42,
    w: 11.6,
    h: 0.5,
    fontFace: "Microsoft YaHei",
    fontSize: 24,
    bold: true,
    color: dark ? C.white : C.ink,
    margin: 0,
    fit: "shrink",
  });
  if (subtitle) {
    slide.addText(subtitle, {
      x: 0.72,
      y: 0.98,
      w: 11.0,
      h: 0.26,
      fontFace: "Microsoft YaHei",
      fontSize: 9.5,
      color: dark ? "B8C7D9" : C.muted,
      margin: 0,
      fit: "shrink",
    });
  }
}

function addBullet(slide, text, x, y, w, opts = {}) {
  const color = opts.color || C.ink;
  slide.addShape(pptx.ShapeType.ellipse, {
    x,
    y: y + 0.09,
    w: 0.08,
    h: 0.08,
    fill: { color: opts.dot || C.blue },
    line: { color: opts.dot || C.blue },
  });
  slide.addText(text, {
    x: x + 0.18,
    y,
    w,
    h: opts.h || 0.34,
    fontFace: "Microsoft YaHei",
    fontSize: opts.size || 10.4,
    bold: !!opts.bold,
    color,
    margin: 0,
    fit: "shrink",
  });
}

function addCode(slide, lines, x, y, w, h, fontSize = 8.2) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: 0.08,
    fill: { color: "0F172A" },
    line: { color: "1E293B" },
  });
  slide.addText(lines.join("\n"), {
    x: x + 0.16,
    y: y + 0.16,
    w: w - 0.32,
    h: h - 0.28,
    fontFace: "Consolas",
    fontSize,
    color: "D8EAFE",
    margin: 0,
    fit: "shrink",
    breakLine: false,
  });
}

function addSimpleTable(slide, rows, x, y, colW, rowH = 0.48) {
  const totalW = colW.reduce((a, b) => a + b, 0);
  rows.forEach((row, r) => {
    const yy = y + r * rowH;
    const fill = r === 0 ? C.navy : r % 2 ? C.white : "EEF5FC";
    slide.addShape(pptx.ShapeType.rect, {
      x,
      y: yy,
      w: totalW,
      h: rowH,
      fill: { color: fill },
      line: { color: C.line, transparency: r === 0 ? 100 : 25 },
    });
    let xx = x;
    row.forEach((cell, c) => {
      slide.addText(cell, {
        x: xx + 0.08,
        y: yy + 0.11,
        w: colW[c] - 0.16,
        h: rowH - 0.14,
        fontFace: "Microsoft YaHei",
        fontSize: r === 0 ? 8.6 : 8.1,
        bold: r === 0,
        color: r === 0 ? C.white : C.ink,
        margin: 0,
        fit: "shrink",
      });
      xx += colW[c];
    });
  });
}

function addCallout(slide, text, x, y, w, color = C.blue, dark = false) {
  slide.addShape(pptx.ShapeType.line, { x, y, w, h: 0, line: { color, width: 2 } });
  slide.addText(text, {
    x,
    y: y + 0.18,
    w,
    h: 0.46,
    fontFace: "Microsoft YaHei",
    fontSize: 11.4,
    bold: true,
    color: dark ? C.white : C.ink,
    margin: 0,
    fit: "shrink",
  });
}

function svgPreview(idx, name, title, body, dark = false) {
  const bg = dark ? `#${C.navy}` : `#${C.bg}`;
  const ink = dark ? "#FFFFFF" : `#${C.ink}`;
  const safeBody = body.replace(/&(?!amp;|lt;|gt;|quot;|apos;)/g, "&amp;");
  previews.push({
    idx,
    name,
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900">
      <rect width="1600" height="900" fill="${bg}"/>
      <text x="82" y="90" font-family="Microsoft YaHei, Arial" font-size="42" font-weight="700" fill="${ink}">${esc(title)}</text>
      ${safeBody}
      <text x="1460" y="860" font-family="Arial" font-size="22" font-weight="700" fill="${dark ? "#9FB2C8" : "#718096"}">${String(idx).padStart(2, "0")}</text>
    </svg>`,
  });
}

function slideCover() {
  const slide = pptx.addSlide();
  addBg(slide, true);
  slide.addText("股票实时流分析平台", {
    x: 0.75,
    y: 0.72,
    w: 4.2,
    h: 0.28,
    fontFace: "Microsoft YaHei",
    fontSize: 12,
    bold: true,
    color: "7DD3FC",
    margin: 0,
  });
  slide.addText("实时数据分析模块设计与实现", {
    x: 0.75,
    y: 1.45,
    w: 8.7,
    h: 0.75,
    fontFace: "Microsoft YaHei",
    fontSize: 34,
    bold: true,
    color: C.white,
    margin: 0,
    fit: "shrink",
  });
  slide.addText("基于 Kafka + Spark Streaming + MySQL/HDFS 的股票行情实时分析链路", {
    x: 0.78,
    y: 2.34,
    w: 9.4,
    h: 0.32,
    fontFace: "Microsoft YaHei",
    fontSize: 12.5,
    color: "B8C7D9",
    margin: 0,
    fit: "shrink",
  });
  slide.addShape(pptx.ShapeType.line, { x: 0.78, y: 4.55, w: 10.8, h: 0, line: { color: "3DD6C6", width: 2 } });
  slide.addText("股票行情采集  →  消息传输  →  流式计算  →  异常告警  →  前端展示", {
    x: 0.78,
    y: 4.92,
    w: 8.8,
    h: 0.25,
    fontFace: "Microsoft YaHei",
    fontSize: 11.4,
    color: "D8EAF8",
    margin: 0,
    fit: "shrink",
  });
  slide.addText("本模块实现了从股票行情采集、消息传输、流式计算、异常告警到前端展示的完整实时数据分析流程。", {
    x: 0.78,
    y: 6.15,
    w: 10.2,
    h: 0.32,
    fontFace: "Microsoft YaHei",
    fontSize: 12.2,
    bold: true,
    color: "CFFAFE",
    margin: 0,
    fit: "shrink",
  });
  svgPreview(1, "cover", "实时数据分析模块设计与实现", `<text x="82" y="190" font-family="Microsoft YaHei" font-size="28" fill="#B8C7D9">基于 Kafka + Spark Streaming + MySQL/HDFS 的股票行情实时分析链路</text><line x1="90" y1="560" x2="1380" y2="560" stroke="#3DD6C6" stroke-width="4"/><text x="90" y="630" font-family="Microsoft YaHei" font-size="26" fill="#D8EAF8">采集 → 消息传输 → 流式计算 → 异常告警 → 前端展示</text>`, true);
}

function slidePosition() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "实时数据分析模块在系统中的位置", "模块定位：把不断变化的行情转化为可分析、可存储、可展示、可告警的实时结果");
  addBullet(slide, "本项目不是只展示静态股票数据，而是通过实时流处理不断更新行情、统计指标和风险告警。", 0.9, 1.7, 10.5, { bold: true });
  addBullet(slide, "实时数据分析模块连接采集端、Kafka、Spark、MySQL/HDFS 和前端可视化页面。", 0.9, 2.35, 10.5);
  addBullet(slide, "它是平台中“动态展示”和“风险监控”的核心支撑模块。", 0.9, 2.95, 10.5);
  const lanes = [
    ["数据采集端", C.blue],
    ["Kafka 消息队列", C.amber],
    ["Spark 流式计算", C.green],
    ["MySQL/HDFS 存储", C.cyan],
    ["前端可视化", C.red],
  ];
  lanes.forEach((lane, i) => {
    const x = 0.95 + i * 2.36;
    slide.addShape(pptx.ShapeType.roundRect, { x, y: 4.4, w: 1.82, h: 0.62, rectRadius: 0.07, fill: { color: lane[1] }, line: { color: lane[1] } });
    slide.addText(lane[0], { x: x + 0.06, y: 4.62, w: 1.7, h: 0.16, fontFace: "Microsoft YaHei", fontSize: 8.6, bold: true, color: C.white, align: "center", margin: 0, fit: "shrink" });
  });
  addCallout(slide, "讲解句：这个模块的作用是把不断变化的行情数据转化为实时分析结果。", 0.95, 6.05, 10.8);
  addFooter(slide, 2);
  svgPreview(2, "position", "实时数据分析模块在系统中的位置", `<text x="100" y="230" font-family="Microsoft YaHei" font-size="27" fill="#102033">动态更新行情、统计指标和风险告警</text><text x="100" y="520" font-family="Microsoft YaHei" font-size="26" fill="#102033">采集端 → Kafka → Spark → MySQL/HDFS → 前端</text><text x="100" y="710" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#1D7CF2">核心支撑：动态展示 + 风险监控</text>`);
}

function slideFlow() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "实时数据分析整体流程", "从行情源到前端大屏的完整实时链路");
  const nodes = [
    ["股票行情源", "多行情源输入", C.blue],
    ["Python Producer", "实时采集与标准化", C.blue],
    ["Kafka", "消息队列缓冲", C.amber],
    ["Spark Streaming", "解析、清洗、聚合、告警", C.green],
    ["MySQL / HDFS", "快速查询与归档", C.cyan],
    ["Java 后端接口", "封装看板数据", C.red],
    ["前端实时大屏", "周期刷新展示", C.navy],
  ];
  nodes.forEach((n, i) => {
    const y = 1.35 + i * 0.62;
    slide.addShape(pptx.ShapeType.roundRect, { x: 0.95, y, w: 3.15, h: 0.38, rectRadius: 0.05, fill: { color: n[2] }, line: { color: n[2] } });
    slide.addText(n[0], { x: 1.08, y: y + 0.105, w: 2.9, h: 0.12, fontFace: "Microsoft YaHei", fontSize: 8.8, bold: true, color: C.white, margin: 0, align: "center", fit: "shrink" });
    if (i < nodes.length - 1) slide.addShape(pptx.ShapeType.downArrow, { x: 2.18, y: y + 0.42, w: 0.22, h: 0.18, fill: { color: C.line }, line: { color: C.line } });
    slide.addText(n[1], { x: 4.55, y: y + 0.08, w: 4.4, h: 0.18, fontFace: "Microsoft YaHei", fontSize: 9, color: C.ink, margin: 0, fit: "shrink" });
  });
  addBullet(slide, "Producer 负责采集并标准化行情数据。", 9.35, 1.45, 3.0, { size: 8.8 });
  addBullet(slide, "Kafka 负责缓冲实时消息。", 9.35, 2.02, 3.0, { size: 8.8, dot: C.amber });
  addBullet(slide, "Spark 负责实时解析、清洗、聚合、告警。", 9.35, 2.59, 3.0, { size: 8.8, dot: C.green });
  addBullet(slide, "MySQL 负责前端快速查询，HDFS 负责归档。", 9.35, 3.16, 3.0, { size: 8.8, dot: C.cyan });
  addBullet(slide, "前端每隔几秒刷新展示最新状态。", 9.35, 3.73, 3.0, { size: 8.8, dot: C.red });
  addFooter(slide, 3);
  svgPreview(3, "flow", "实时数据分析整体流程", `<text x="100" y="190" font-family="Microsoft YaHei" font-size="28" fill="#102033">股票行情源 ↓ Python Producer ↓ Kafka ↓ Spark Structured Streaming</text><text x="100" y="300" font-family="Microsoft YaHei" font-size="28" fill="#102033">MySQL 明细表 / 聚合表 / 告警表 ↓ Java 后端接口 ↓ 前端实时大屏</text><text x="100" y="690" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#102033">核心：采集、缓冲、计算、存储、展示分层解耦</text>`);
}

function slideFileMap() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "实时分析模块核心代码结构", "实时分析按采集、传输、计算、存储、展示分层实现");
  addSimpleTable(slide, [
    ["文件", "作用"],
    ["python/producer/stock_producer.py", "实时采集行情并写入 Kafka"],
    ["python/producer/stock_sources.py", "封装不同行情源的抓取逻辑"],
    ["python/common/stock_utils.py", "行情数据校验与标准化工具"],
    ["python/spark/stock_streaming_job.py", "Spark 实时分析核心代码"],
    ["java-backend/.../DashboardService.java", "查询实时结果并提供前端接口"],
    ["frontend/index.html / dash-pages.js", "展示实时行情、告警和系统状态"],
  ], 0.85, 1.45, [4.55, 6.55], 0.55);
  addCallout(slide, "讲解重点：实时分析不是写在一个文件里，而是通过分层代码完成完整链路。", 0.9, 5.95, 10.7);
  addFooter(slide, 4);
  svgPreview(4, "files", "实时分析模块核心代码结构", `<text x="100" y="210" font-family="Microsoft YaHei" font-size="25" fill="#102033">stock_producer.py / stock_sources.py / stock_utils.py</text><text x="100" y="290" font-family="Microsoft YaHei" font-size="25" fill="#102033">stock_streaming_job.py / DashboardService.java / frontend</text><text x="100" y="690" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#1D7CF2">分层实现：采集、传输、计算、存储、展示</text>`);
}

function slideProducer() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "Producer 如何生成实时行情事件", "对应文件：python/producer/stock_producer.py");
  addBullet(slide, "从股票池读取监控股票。", 0.85, 1.46, 5.4);
  addBullet(slide, "使用多线程并发抓取行情。", 0.85, 1.92, 5.4);
  addBullet(slide, "调用多个行情源进行兜底。", 0.85, 2.38, 5.4);
  addBullet(slide, "使用 is_valid_tick 过滤无效数据。", 0.85, 2.84, 5.4);
  addBullet(slide, "将合法行情写入 Kafka。", 0.85, 3.3, 5.4);
  addCode(slide, [
    "quotes = [quote for quote in fetch_quotes() if is_valid_tick(quote)]",
    "",
    "for quote in quotes:",
    "    producer.send(",
    "        settings.kafka_topic,",
    "        key=quote['symbol'],",
    "        value=quote",
    "    )",
    "producer.flush()",
  ], 6.6, 1.45, 5.65, 3.05, 8.0);
  addSimpleTable(slide, [
    ["函数/参数", "说明"],
    ["fetch_quotes()", "采集一轮股票行情"],
    ["is_valid_tick()", "过滤价格、成交量异常数据"],
    ["producer.send()", "发送到 Kafka topic"],
    ["key=symbol", "用股票代码作为消息 key，便于追踪"],
  ], 0.9, 4.42, [2.5, 4.1], 0.38);
  addFooter(slide, 5);
  svgPreview(5, "producer", "Producer 如何生成实时行情事件", `<text x="100" y="200" font-family="Microsoft YaHei" font-size="26" fill="#102033">股票池 → 多线程采集 → 多源兜底 → is_valid_tick → Kafka</text><rect x="850" y="180" width="620" height="320" rx="18" fill="#0F172A"/><text x="890" y="250" font-family="Consolas" font-size="22" fill="#D8EAFE">producer.send(topic, key=symbol, value=quote)</text>`);
}

function slideKafka() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "为什么中间要使用 Kafka", "Kafka 作为实时数据缓冲层，解耦采集端和计算端");
  addBullet(slide, "Producer 只负责写消息，不直接操作数据库和复杂分析逻辑。", 0.9, 1.55, 6.2, { bold: true });
  addBullet(slide, "Spark 可以持续消费 Kafka 中的行情事件。", 0.9, 2.13, 6.2);
  addBullet(slide, "采集速度和计算速度不完全一致时，Kafka 起到削峰和缓冲作用。", 0.9, 2.71, 6.2);
  addBullet(slide, "实时行情被转换为持续流动的消息，后续计算更稳定。", 0.9, 3.29, 6.2);
  addCode(slide, [
    "KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:9092",
    "KAFKA_TOPIC=stock_realtime_topic",
  ], 7.6, 1.6, 4.4, 1.0, 10.5);
  slide.addShape(pptx.ShapeType.line, { x: 7.6, y: 3.5, w: 3.7, h: 0, line: { color: C.amber, width: 3 } });
  slide.addText("讲解重点", { x: 7.6, y: 3.88, w: 1.3, h: 0.2, fontFace: "Microsoft YaHei", fontSize: 9.3, bold: true, color: C.amber, margin: 0 });
  slide.addText("Kafka 的作用是把实时行情变成持续流动的消息，让后面的 Spark 可以稳定消费。", {
    x: 7.6,
    y: 4.25,
    w: 4.2,
    h: 0.72,
    fontFace: "Microsoft YaHei",
    fontSize: 12.3,
    bold: true,
    color: C.ink,
    margin: 0,
    fit: "shrink",
  });
  addFooter(slide, 6);
  svgPreview(6, "kafka", "为什么中间要使用 Kafka", `<text x="100" y="230" font-family="Microsoft YaHei" font-size="28" fill="#102033">解耦采集端和计算端，承担实时消息缓冲</text><text x="900" y="260" font-family="Consolas" font-size="25" fill="#F59E0B">stock_realtime_topic</text><text x="100" y="680" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#102033">把实时行情变成持续流动的消息</text>`);
}

function slideSparkRead() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "Spark 如何读取实时行情流", "对应文件：python/spark/stock_streaming_job.py");
  addCode(slide, [
    "raw = (",
    "    spark.readStream.format('kafka')",
    "    .option('kafka.bootstrap.servers', settings.kafka_bootstrap_servers)",
    "    .option('subscribe', settings.kafka_topic)",
    "    .option('startingOffsets', 'latest')",
    "    .option('failOnDataLoss', 'false')",
    "    .load()",
    ")",
  ], 0.85, 1.42, 6.15, 3.55, 8.1);
  addBullet(slide, "readStream 表示持续读取数据流。", 7.4, 1.55, 4.5, { size: 9.4 });
  addBullet(slide, "format('kafka') 表示数据来源是 Kafka。", 7.4, 2.07, 4.5, { size: 9.4 });
  addBullet(slide, "subscribe 指定消费哪个 topic。", 7.4, 2.59, 4.5, { size: 9.4 });
  addBullet(slide, "startingOffsets='latest' 适合实时演示。", 7.4, 3.11, 4.5, { size: 9.4 });
  addBullet(slide, "failOnDataLoss=false 增强容错性。", 7.4, 3.63, 4.5, { size: 9.4 });
  addCallout(slide, "这一页重点讲：Spark 读取的是一条持续流，不是一次性静态文件。", 0.9, 5.75, 10.7, C.green);
  addFooter(slide, 7);
  svgPreview(7, "spark_read", "Spark 如何读取实时行情流", `<rect x="100" y="170" width="720" height="420" rx="18" fill="#0F172A"/><text x="130" y="250" font-family="Consolas" font-size="22" fill="#D8EAFE">spark.readStream.format('kafka')</text><text x="910" y="240" font-family="Microsoft YaHei" font-size="26" fill="#102033">持续读取 Kafka topic</text><text x="910" y="330" font-family="Microsoft YaHei" font-size="24" fill="#102033">latest / failOnDataLoss=false</text>`);
}

function slideJson() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "Kafka 消息如何变成结构化行情表", "JSON 解析与字段标准化");
  addCode(slide, [
    "parsed = raw.select(",
    "    F.from_json(",
    "        F.col('value').cast('string'),",
    "        event_schema()",
    "    ).alias('data')",
    ").select('data.*')",
    "",
    "parsed = parsed.withColumn(",
    "    'event_time',",
    "    F.to_timestamp('event_time', 'yyyy-MM-dd HH:mm:ss')",
    ")",
  ], 0.85, 1.35, 6.2, 4.1, 7.4);
  addBullet(slide, "Kafka 中的 value 是 JSON 字符串。", 7.4, 1.45, 4.4, { size: 9.2 });
  addBullet(slide, "event_schema() 定义字段结构。", 7.4, 1.95, 4.4, { size: 9.2 });
  addBullet(slide, "from_json() 将 JSON 转成 Spark DataFrame。", 7.4, 2.45, 4.4, { size: 9.2 });
  addBullet(slide, "event_time 转为时间类型，用于窗口统计和排序。", 7.4, 2.95, 4.4, { size: 9.2 });
  slide.addText("字段：symbol / company_name / market / last_price / change_pct / volume / turnover / event_time / source", {
    x: 7.42,
    y: 4.18,
    w: 4.35,
    h: 0.56,
    fontFace: "Consolas",
    fontSize: 8.2,
    color: C.blue,
    bold: true,
    margin: 0,
    fit: "shrink",
  });
  addFooter(slide, 8);
  svgPreview(8, "json", "Kafka 消息如何变成结构化行情表", `<text x="100" y="220" font-family="Consolas" font-size="24" fill="#1D7CF2">from_json(col('value').cast('string'), event_schema())</text><text x="100" y="330" font-family="Microsoft YaHei" font-size="26" fill="#102033">JSON 字符串 → Spark DataFrame → event_time 时间字段</text><text x="100" y="650" font-family="Consolas" font-size="22" fill="#102033">symbol / last_price / change_pct / volume / turnover / source</text>`);
}

function slideQuality() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "进入实时分析前的数据清洗", "实时系统最怕脏数据直接进入分析，因此 Spark 入口先做基础质量过滤");
  addCode(slide, [
    "return parsed.filter(",
    "    (F.col('last_price') > 0)",
    "    & (F.col('volume') > 0)",
    "    & (",
    "        (market.isin('SH', 'SZ', 'BJ')",
    "         & (F.abs(F.col('change_pct')) < 11.0))",
    "        | ((market == 'HK')",
    "           & (F.abs(F.col('change_pct')) < 50.0))",
    "    )",
    ")",
  ], 0.85, 1.35, 6.3, 3.95, 7.6);
  addSimpleTable(slide, [
    ["规则", "作用"],
    ["last_price > 0", "过滤价格异常数据"],
    ["volume > 0", "过滤无成交量数据"],
    ["A 股 < 11%", "A 股涨跌幅限制更严格"],
    ["港股 < 50%", "港股允许更大波动范围"],
  ], 7.55, 1.55, [2.0, 2.9], 0.52);
  addCallout(slide, "这样可以防止错误行情污染实时统计和告警结果。", 7.55, 5.25, 4.6, C.amber);
  addFooter(slide, 9);
  svgPreview(9, "quality", "进入实时分析前的数据清洗", `<text x="100" y="230" font-family="Consolas" font-size="25" fill="#102033">last_price > 0  &  volume > 0</text><text x="100" y="330" font-family="Consolas" font-size="25" fill="#102033">A股 abs(change_pct) &lt; 11.0 / 港股 &lt; 50.0</text><text x="100" y="680" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#F59E0B">防止错误行情污染实时统计和告警结果</text>`);
}

function slideMicroBatch() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "Spark 使用 foreachBatch 处理每个实时批次", "Structured Streaming 将实时流切成微批统一处理");
  addCode(slide, [
    "query = (",
    "    stream_df.writeStream.outputMode('append')",
    "    .foreachBatch(write_batch)",
    "    .option('checkpointLocation', settings.hdfs_checkpoint_path)",
    "    .start()",
    ")",
  ], 0.9, 1.45, 5.75, 2.25, 9.5);
  addBullet(slide, "Spark Structured Streaming 会把实时流切成一个个微批。", 7.0, 1.55, 4.8);
  addBullet(slide, "每个微批调用 write_batch() 处理。", 7.0, 2.08, 4.8);
  addBullet(slide, "checkpointLocation 用于保存流式计算状态，支持恢复。", 7.0, 2.61, 4.8);
  addBullet(slide, "outputMode('append') 表示追加写入。", 7.0, 3.14, 4.8);
  addCallout(slide, "讲解重点：本项目不是一条数据单独处理，而是按微批统一完成聚合、告警和写库。", 0.9, 5.4, 10.9, C.green);
  addFooter(slide, 10);
  svgPreview(10, "micro_batch", "Spark 使用 foreachBatch 处理每个实时批次", `<text x="110" y="260" font-family="Consolas" font-size="27" fill="#1D7CF2">writeStream.outputMode('append').foreachBatch(write_batch)</text><text x="110" y="650" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#102033">按微批统一完成聚合、告警和写库</text>`);
}

function slideWriteBatch() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "一个微批中完成哪些实时分析任务", "write_batch 同时负责去重、归档、聚合、告警和写库");
  addCode(slide, [
    "raw_batch = batch_df.dropDuplicates(['event_id'])",
    "",
    "raw_batch.write.mode('append').parquet(",
    "    f'{settings.hdfs_output_path.rstrip('/')}/quotes'",
    ")",
    "",
    "write_dashboard_aggregates(raw_batch, batch_id)",
    "changed_batch = keep_changed_quotes(raw_batch)",
    "write_jdbc(build_alerts(changed_batch), 'alert_events')",
    "write_jdbc(latest_quotes, 'price_ticks')",
  ], 0.85, 1.27, 6.55, 4.5, 7.2);
  const steps = ["按 event_id 去重", "原始行情归档到 HDFS", "生成看板聚合指标", "过滤重复行情快照", "生成告警事件", "写入 MySQL 明细表"];
  steps.forEach((s, i) => addBullet(slide, s, 7.75, 1.45 + i * 0.49, 4.2, { size: 9.2, dot: i < 2 ? C.blue : i < 4 ? C.green : C.red }));
  addCallout(slide, "一个微批不只是写原始数据，还同时生成前端展示需要的统计结果和风险告警。", 7.75, 5.25, 4.4, C.red);
  addFooter(slide, 11);
  svgPreview(11, "write_batch", "一个微批中完成哪些实时分析任务", `<text x="100" y="230" font-family="Microsoft YaHei" font-size="26" fill="#102033">去重 → HDFS 归档 → 聚合快照 → 重复过滤 → 告警 → MySQL 明细</text><text x="100" y="680" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#DC2626">同时生成前端统计结果和风险告警</text>`);
}

function slideAggregates() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "Spark 计算了哪些实时分析指标", "对应函数：write_dashboard_aggregates(raw_batch, batch_id)");
  addSimpleTable(slide, [
    ["表名", "内容", "前端用途"],
    ["metric_snapshots", "分钟级市场快照", "首页趋势、流量状态"],
    ["symbol_stats", "个股聚合统计", "个股排行、关注列表"],
    ["sector_stats", "行业统计", "行业热力图"],
    ["category_stats", "分类统计", "市场结构分析"],
  ], 0.85, 1.45, [2.75, 3.8, 3.8], 0.62);
  const metrics = ["股票数量", "平均价格", "平均涨跌幅", "总成交量", "总成交额", "行业平均涨跌幅", "行业成交额"];
  metrics.forEach((m, i) => {
    const x = 0.95 + (i % 4) * 2.6;
    const y = 4.78 + Math.floor(i / 4) * 0.55;
    slide.addShape(pptx.ShapeType.roundRect, { x, y, w: 2.1, h: 0.32, rectRadius: 0.04, fill: { color: i % 2 ? C.lightGreen : C.lightBlue }, line: { color: C.line } });
    slide.addText(m, { x: x + 0.08, y: y + 0.095, w: 1.95, h: 0.1, fontFace: "Microsoft YaHei", fontSize: 7.8, bold: true, color: C.ink, align: "center", margin: 0, fit: "shrink" });
  });
  addFooter(slide, 12);
  svgPreview(12, "aggregates", "Spark 计算了哪些实时分析指标", `<text x="100" y="220" font-family="Microsoft YaHei" font-size="27" fill="#102033">metric_snapshots / symbol_stats / sector_stats / category_stats</text><text x="100" y="620" font-family="Microsoft YaHei" font-size="26" fill="#102033">股票数量、平均价格、平均涨跌幅、总成交量、总成交额、行业统计</text>`);
}

function slideAlertRules() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "实时风险告警如何生成", "对应函数：build_alerts(changed_batch)");
  slide.addText("规则一：价格波动告警", { x: 0.9, y: 1.48, w: 2.4, h: 0.25, fontFace: "Microsoft YaHei", fontSize: 12.2, bold: true, color: C.blue, margin: 0 });
  addCode(slide, ["price_alert_threshold = greatest(", "    2.0,", "    avg_abs_change_pct * 2.5", ")"], 0.9, 1.95, 5.0, 1.45, 10);
  slide.addText("规则二：成交量异动告警", { x: 0.9, y: 3.82, w: 2.6, h: 0.25, fontFace: "Microsoft YaHei", fontSize: 12.2, bold: true, color: C.green, margin: 0 });
  addCode(slide, ["volume_alert_threshold = greatest(", "    volume_min_threshold,", "    avg_volume * 2.0", ")"], 0.9, 4.28, 5.0, 1.45, 10);
  addBullet(slide, "读取最近一天历史行情作为动态基线。", 6.55, 1.62, 5.0, { size: 9.6 });
  addBullet(slide, "当前涨跌幅超过历史平均波动，触发价格波动告警。", 6.55, 2.15, 5.0, { size: 9.6 });
  addBullet(slide, "当前成交量超过历史平均成交量，触发成交量异动告警。", 6.55, 2.68, 5.0, { size: 9.6 });
  addBullet(slide, "告警等级分为 MEDIUM 和 HIGH。", 6.55, 3.21, 5.0, { size: 9.6 });
  addCallout(slide, "讲解重点：告警不是简单写死固定值，而是结合历史基线动态判断当前行情是否异常。", 6.55, 4.65, 4.8, C.amber);
  addFooter(slide, 13);
  svgPreview(13, "alerts", "实时风险告警如何生成", `<text x="110" y="250" font-family="Consolas" font-size="28" fill="#102033">price_alert_threshold = greatest(2.0, avg_abs_change_pct * 2.5)</text><text x="110" y="390" font-family="Consolas" font-size="28" fill="#102033">volume_alert_threshold = greatest(volume_min_threshold, avg_volume * 2.0)</text><text x="110" y="690" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#F59E0B">结合历史基线动态判断异常</text>`);
}

function slideStorage() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "实时分析结果如何落库", "MySQL 用于快速查询，HDFS 用于离线归档");
  addSimpleTable(slide, [
    ["表名", "作用"],
    ["price_ticks", "保存去重后的实时行情明细"],
    ["metric_snapshots", "保存分钟级市场快照"],
    ["symbol_stats", "保存个股聚合指标"],
    ["sector_stats", "保存行业统计"],
    ["category_stats", "保存市场分类统计"],
    ["alert_events", "保存实时风险告警"],
    ["HDFS parquet", "保存原始行情归档"],
  ], 0.85, 1.35, [3.1, 6.6], 0.5);
  addBullet(slide, "MySQL 面向前端快速查询。", 0.95, 5.58, 4.5, { bold: true });
  addBullet(slide, "HDFS 面向后续离线分析和归档。", 0.95, 6.08, 4.5, { bold: true, dot: C.green });
  addBullet(slide, "明细表和聚合表分开，减少前端查询压力。", 6.6, 5.82, 5.4, { bold: true, dot: C.amber });
  addFooter(slide, 14);
  svgPreview(14, "storage", "实时分析结果如何落库", `<text x="110" y="220" font-family="Microsoft YaHei" font-size="27" fill="#102033">price_ticks / metric_snapshots / symbol_stats / sector_stats / category_stats / alert_events</text><text x="110" y="680" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#102033">MySQL 快速查询，HDFS 离线归档</text>`);
}

function slideBackendFrontend() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "实时分析结果如何展示到页面", "后端文件：DashboardService.java；前端定时刷新展示实时状态");
  addSimpleTable(slide, [
    ["接口", "作用"],
    ["/dashboard", "获取首页大屏数据"],
    ["/health", "获取系统健康状态"],
    ["/alerts", "查询风险告警"],
    ["/stocks/{symbol}", "查询个股详情"],
    ["/stocks/{symbol}/trend", "查询实时趋势"],
  ], 0.85, 1.42, [2.75, 4.2], 0.52);
  const items = ["实时流状态", "最新行情", "市场涨跌统计", "行业热力", "风险告警", "个股走势", "模型预测结果"];
  items.forEach((item, i) => addBullet(slide, item, 8.0, 1.42 + i * 0.42, 3.8, { size: 8.6, dot: i < 3 ? C.blue : C.green }));
  addCode(slide, ["setInterval(safeRefresh, 5000)"], 0.95, 5.0, 4.9, 0.65, 12);
  addCallout(slide, "前端不是展示静态数据，而是周期性请求后端接口，持续刷新实时分析结果。", 6.9, 5.0, 4.9, C.blue);
  addFooter(slide, 15);
  svgPreview(15, "backend_frontend", "实时分析结果如何展示到页面", `<text x="110" y="220" font-family="Microsoft YaHei" font-size="27" fill="#102033">/dashboard /health /alerts /stocks/{symbol} /stocks/{symbol}/trend</text><text x="110" y="420" font-family="Consolas" font-size="28" fill="#1D7CF2">setInterval(safeRefresh, 5000)</text><text x="110" y="690" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#102033">周期性请求后端接口，持续刷新实时分析结果</text>`);
}

function slideHealth() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "系统如何判断实时流是否正常", "后端根据 metric_snapshots 和 price_ticks 的最新写入时间计算状态");
  const states = [
    ["FLOWING", "最近 30 秒内有新数据", C.green],
    ["DELAYED", "5 分钟内有数据，但不够实时", C.amber],
    ["STOPPED", "较长时间没有新数据", C.red],
    ["LIVE", "真实采集模式", C.blue],
    ["REPLAY", "样本回放模式", C.cyan],
    ["OFFLINE", "离线状态", "64748B"],
  ];
  states.forEach((s, i) => {
    const x = 0.95 + (i % 3) * 3.95;
    const y = 1.55 + Math.floor(i / 3) * 1.35;
    slide.addText(s[0], { x, y, w: 1.5, h: 0.25, fontFace: "Aptos Display", fontSize: 14, bold: true, color: s[2], margin: 0 });
    slide.addText(s[1], { x, y: y + 0.42, w: 3.1, h: 0.25, fontFace: "Microsoft YaHei", fontSize: 9.5, color: C.ink, margin: 0, fit: "shrink" });
  });
  addCode(slide, [
    "CASE",
    "  WHEN latest_created_at >= NOW() - INTERVAL 30 SECOND THEN 'FLOWING'",
    "  WHEN latest_created_at >= NOW() - INTERVAL 5 MINUTE THEN 'DELAYED'",
    "  ELSE 'STOPPED'",
    "END AS stream_state",
  ], 1.0, 4.75, 6.35, 1.6, 8.4);
  addCallout(slide, "讲解重点：这个状态不是前端写死的，而是后端根据最新写入时间计算出来的。", 7.85, 4.92, 4.4, C.green);
  addFooter(slide, 16);
  svgPreview(16, "health", "系统如何判断实时流是否正常", `<text x="110" y="230" font-family="Arial" font-size="36" font-weight="700" fill="#18A058">FLOWING</text><text x="500" y="230" font-family="Arial" font-size="36" font-weight="700" fill="#F59E0B">DELAYED</text><text x="900" y="230" font-family="Arial" font-size="36" font-weight="700" fill="#DC2626">STOPPED</text><text x="110" y="690" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#102033">状态由最新写入时间计算，不是前端写死</text>`);
}

function slideStability() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "实时模块如何保证演示稳定", "针对断流、重复数据和脏数据做保护");
  const guards = [
    "采集端支持多源兜底。",
    "Producer 发送前做数据校验。",
    "Spark 入口做质量过滤。",
    "使用 event_id 去重。",
    "相同行情快照不重复写库。",
    "HDFS 写入失败时不影响 MySQL 写入。",
    "Spark checkpoint 支持流式恢复。",
    "前端支持后端异常时展示离线状态。",
  ];
  guards.forEach((g, i) => {
    const x = i < 4 ? 0.95 : 6.8;
    const y = 1.55 + (i % 4) * 0.67;
    addBullet(slide, g, x, y, 5.3, { size: 9.9, dot: i % 2 ? C.green : C.blue });
  });
  addCallout(slide, "讲解句：这些设计保证系统不是只能在理想情况下运行，而是考虑了实时链路中的常见问题。", 0.95, 5.55, 10.9, C.red);
  addFooter(slide, 17);
  svgPreview(17, "stability", "实时模块如何保证演示稳定", `<text x="110" y="230" font-family="Microsoft YaHei" font-size="27" fill="#102033">多源兜底 / 数据校验 / 质量过滤 / event_id 去重 / checkpoint</text><text x="110" y="690" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#DC2626">考虑断流、重复数据和脏数据问题</text>`);
}

function slideSummary() {
  const slide = pptx.addSlide();
  addBg(slide, true);
  addTitle(slide, "实时数据分析模块实现效果", "模块总结：完整链路、实时分析、可视化与可监控", true);
  const blocks = [
    ["1. 实现完整实时数据链路", "从行情采集到 Kafka，再到 Spark 分析、MySQL/HDFS 存储和前端展示。"],
    ["2. 实现实时分析能力", "包括行情去重、分钟聚合、个股统计、行业分析和风险告警。"],
    ["3. 实现可视化和可监控", "前端能够展示实时流状态、告警列表、个股走势和市场结构。"],
  ];
  blocks.forEach((b, i) => {
    const y = 1.65 + i * 1.15;
    slide.addText(b[0], { x: 0.9, y, w: 4.2, h: 0.3, fontFace: "Microsoft YaHei", fontSize: 14, bold: true, color: "7DD3FC", margin: 0 });
    slide.addText(b[1], { x: 0.9, y: y + 0.43, w: 9.8, h: 0.32, fontFace: "Microsoft YaHei", fontSize: 11.2, color: C.white, margin: 0, fit: "shrink" });
  });
  slide.addText("实时数据分析模块证明本系统不仅能做静态数据展示，还具备持续采集、持续计算、持续告警和持续展示的能力，是整个平台动态分析能力的核心部分。", {
    x: 0.9,
    y: 6.0,
    w: 11.2,
    h: 0.46,
    fontFace: "Microsoft YaHei",
    fontSize: 12.5,
    bold: true,
    color: "CFFAFE",
    margin: 0,
    fit: "shrink",
  });
  addFooter(slide, 18, true);
  svgPreview(18, "summary", "实时数据分析模块实现效果", `<text x="110" y="220" font-family="Microsoft YaHei" font-size="29" font-weight="700" fill="#7DD3FC">完整实时数据链路</text><text x="110" y="360" font-family="Microsoft YaHei" font-size="29" font-weight="700" fill="#7DD3FC">实时分析能力</text><text x="110" y="500" font-family="Microsoft YaHei" font-size="29" font-weight="700" fill="#7DD3FC">可视化和可监控</text><text x="110" y="700" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#CFFAFE">持续采集、持续计算、持续告警、持续展示</text>`, true);
}

function slideImprovements() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, "后续优化方向", "当前模块已经实现实时链路闭环，后续可以进一步增强可解释性和监控能力");
  const items = [
    ["批次质量统计", "增加输入条数、过滤条数、写库条数。"],
    ["告警原因字段", "记录触发阈值、实际涨跌幅和成交量倍数。"],
    ["链路状态图", "前端展示 Kafka / Spark / MySQL 状态。"],
    ["实时分析日志", "增加批次日志页面，便于答辩展示和排错。"],
    ["接入机器学习", "将实时特征进一步接入预测模型。"],
  ];
  items.forEach((it, i) => {
    const y = 1.55 + i * 0.86;
    slide.addShape(pptx.ShapeType.line, { x: 0.95, y: y + 0.5, w: 10.8, h: 0, line: { color: C.line, width: 1 } });
    slide.addText(it[0], { x: 1.0, y, w: 2.2, h: 0.24, fontFace: "Microsoft YaHei", fontSize: 11, bold: true, color: i % 2 ? C.green : C.blue, margin: 0 });
    slide.addText(it[1], { x: 3.45, y, w: 7.7, h: 0.24, fontFace: "Microsoft YaHei", fontSize: 10.5, color: C.ink, margin: 0, fit: "shrink" });
  });
  addCallout(slide, "讲解重点：后续优化重点不是重新推翻链路，而是在现有闭环上增强解释、监控和预测能力。", 1.0, 6.15, 10.6, C.amber);
  addFooter(slide, 19);
  svgPreview(19, "improvements", "后续优化方向", `<text x="110" y="230" font-family="Microsoft YaHei" font-size="27" fill="#102033">批次质量统计 / 告警原因字段 / 链路状态图 / 实时分析日志 / 接入机器学习</text><text x="110" y="690" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#F59E0B">在现有闭环上增强解释、监控和预测能力</text>`);
}

async function renderPreviews() {
  for (const p of previews) {
    const out = path.join(previewDir, `${String(p.idx).padStart(2, "0")}_${p.name}.png`);
    await sharp(Buffer.from(p.svg)).png().toFile(out);
  }
  const composites = [];
  for (let i = 0; i < previews.length; i += 1) {
    const p = previews[i];
    const file = path.join(previewDir, `${String(p.idx).padStart(2, "0")}_${p.name}.png`);
    const thumb = await sharp(file).resize(480, 270).png().toBuffer();
    const x = 40 + (i % 3) * 520;
    const y = 40 + Math.floor(i / 3) * 560;
    const label = Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="80" height="36"><text x="0" y="25" font-family="Arial" font-size="23" fill="#334155">${String(p.idx).padStart(2, "0")}</text></svg>`);
    composites.push({ input: thumb, left: x, top: y });
    composites.push({ input: label, left: x, top: y + 292 });
  }
  const height = 40 + Math.ceil(previews.length / 3) * 560;
  await sharp({
    create: { width: 1600, height, channels: 4, background: "#EEF2F7" },
  })
    .composite(composites)
    .png()
    .toFile(path.join(previewDir, "montage.png"));
}

async function main() {
  slideCover();
  slidePosition();
  slideFlow();
  slideFileMap();
  slideProducer();
  slideKafka();
  slideSparkRead();
  slideJson();
  slideQuality();
  slideMicroBatch();
  slideWriteBatch();
  slideAggregates();
  slideAlertRules();
  slideStorage();
  slideBackendFrontend();
  slideHealth();
  slideStability();
  slideSummary();
  slideImprovements();

  const pptxPath = path.join(outDir, "股票实时流分析平台实时数据分析模块汇报.pptx");
  await pptx.writeFile({ fileName: pptxPath });
  await renderPreviews();
  const manifest = {
    pptxPath,
    previewDir,
    slideCount: previews.length,
    previews: previews.map((p) => path.join(previewDir, `${String(p.idx).padStart(2, "0")}_${p.name}.png`)),
    montage: path.join(previewDir, "montage.png"),
  };
  fs.writeFileSync(path.join(outDir, "realtime_module_report_manifest.json"), JSON.stringify(manifest, null, 2), "utf8");
  console.log(JSON.stringify(manifest, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
