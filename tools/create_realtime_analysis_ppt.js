const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const sharp = require("sharp");

const projectRoot = path.resolve(__dirname, "..");
const outDir = path.join(projectRoot, "docs", "ppt");
const previewDir = path.join(outDir, "realtime_analysis_preview");
fs.mkdirSync(previewDir, { recursive: true });
for (const file of fs.readdirSync(previewDir)) {
  if (file.endsWith(".png")) {
    fs.unlinkSync(path.join(previewDir, file));
  }
}

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "Comprehensive Practice";
pptx.subject = "实时数据分析模块演讲汇报";
pptx.title = "股票实时数据分析模块汇报";
pptx.company = "Quant Stream";
pptx.lang = "zh-CN";
pptx.theme = {
  headFontFace: "Microsoft YaHei",
  bodyFontFace: "Microsoft YaHei",
  lang: "zh-CN",
};
pptx.defineLayout({ name: "CUSTOM_WIDE", width: 13.333, height: 7.5 });
pptx.layout = "CUSTOM_WIDE";

const C = {
  bg: "F7FAFC",
  ink: "102033",
  muted: "5E7185",
  faint: "D7E0EA",
  blue: "1D7CF2",
  green: "18A058",
  amber: "F59E0B",
  red: "DC2626",
  navy: "0B1F36",
  cyan: "00A8FF",
  white: "FFFFFF",
  line: "CBD5E1",
};

function addBg(slide, dark = false) {
  slide.background = { color: dark ? C.navy : C.bg };
}

function addFooter(slide, index) {
  slide.addText("股票实时流分析平台 / 实时数据分析模块", {
    x: 0.55,
    y: 7.05,
    w: 6.4,
    h: 0.2,
    fontFace: "Microsoft YaHei",
    fontSize: 7.5,
    color: "718096",
    margin: 0,
  });
  slide.addText(String(index).padStart(2, "0"), {
    x: 12.35,
    y: 7.02,
    w: 0.45,
    h: 0.22,
    fontFace: "Microsoft YaHei",
    fontSize: 8,
    bold: true,
    color: "718096",
    align: "right",
    margin: 0,
  });
}

function title(slide, text, sub, dark = false) {
  slide.addText(text, {
    x: 0.62,
    y: 0.45,
    w: 8.2,
    h: 0.55,
    fontFace: "Microsoft YaHei",
    fontSize: 25,
    bold: true,
    color: dark ? C.white : C.ink,
    margin: 0,
    breakLine: false,
    fit: "shrink",
  });
  if (sub) {
    slide.addText(sub, {
      x: 0.64,
      y: 1.02,
      w: 8.6,
      h: 0.28,
      fontFace: "Microsoft YaHei",
      fontSize: 9.5,
      color: dark ? "B8C7D9" : C.muted,
      margin: 0,
      fit: "shrink",
    });
  }
}

function addPill(slide, text, x, y, color) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w: 1.32,
    h: 0.28,
    rectRadius: 0.06,
    fill: { color },
    line: { color, transparency: 100 },
  });
  slide.addText(text, {
    x: x + 0.08,
    y: y + 0.065,
    w: 1.16,
    h: 0.12,
    fontFace: "Microsoft YaHei",
    fontSize: 6.8,
    bold: true,
    color: C.white,
    align: "center",
    margin: 0,
    fit: "shrink",
  });
}

function addNode(slide, label, desc, x, y, color, idx) {
  slide.addShape(pptx.ShapeType.ellipse, {
    x,
    y,
    w: 0.72,
    h: 0.72,
    fill: { color },
    line: { color, transparency: 100 },
  });
  slide.addText(String(idx), {
    x: x + 0.01,
    y: y + 0.18,
    w: 0.7,
    h: 0.22,
    fontFace: "Aptos Display",
    fontSize: 17,
    bold: true,
    color: C.white,
    align: "center",
    margin: 0,
  });
  slide.addText(label, {
    x: x - 0.35,
    y: y + 0.95,
    w: 1.45,
    h: 0.23,
    fontFace: "Microsoft YaHei",
    fontSize: 10.5,
    bold: true,
    color: C.ink,
    align: "center",
    margin: 0,
    fit: "shrink",
  });
  slide.addText(desc, {
    x: x - 0.55,
    y: y + 1.26,
    w: 1.85,
    h: 0.5,
    fontFace: "Microsoft YaHei",
    fontSize: 7.3,
    color: C.muted,
    align: "center",
    valign: "top",
    margin: 0.02,
    fit: "shrink",
  });
}

function bullet(slide, text, x, y, w, color = C.ink) {
  slide.addShape(pptx.ShapeType.ellipse, {
    x,
    y: y + 0.06,
    w: 0.08,
    h: 0.08,
    fill: { color: C.blue },
    line: { color: C.blue },
  });
  slide.addText(text, {
    x: x + 0.18,
    y,
    w,
    h: 0.34,
    fontFace: "Microsoft YaHei",
    fontSize: 10.2,
    color,
    margin: 0,
    fit: "shrink",
  });
}

function addMiniCode(slide, lines, x, y, w, h) {
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
    x: x + 0.18,
    y: y + 0.18,
    w: w - 0.36,
    h: h - 0.3,
    fontFace: "Consolas",
    fontSize: 8.4,
    color: "D1E7FF",
    margin: 0,
    breakLine: false,
    fit: "shrink",
  });
}

function addTable(slide, rows, x, y, colWidths, rowH = 0.46) {
  const totalW = colWidths.reduce((a, b) => a + b, 0);
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
        y: yy + 0.12,
        w: colWidths[c] - 0.16,
        h: rowH - 0.16,
        fontFace: "Microsoft YaHei",
        fontSize: r === 0 ? 8.4 : 8.0,
        bold: r === 0,
        color: r === 0 ? C.white : C.ink,
        margin: 0,
        fit: "shrink",
      });
      xx += colWidths[c];
    });
  });
}

function addCodeExplainSlide({ slideNo, heading, subheading, codeLines, explainRows, accent = C.blue, dark = false }) {
  const slide = pptx.addSlide();
  addBg(slide, dark);
  title(slide, heading, subheading, dark);
  addMiniCode(slide, codeLines, 0.85, 1.62, 5.9, 4.6);
  slide.addText("代码说明", {
    x: 7.2,
    y: 1.62,
    w: 1.45,
    h: 0.24,
    fontFace: "Microsoft YaHei",
    fontSize: 11,
    bold: true,
    color: accent,
    margin: 0,
  });
  explainRows.forEach((row, i) => {
    const y = 2.08 + i * 0.78;
    slide.addShape(pptx.ShapeType.line, {
      x: 7.2,
      y: y + 0.47,
      w: 4.8,
      h: 0,
      line: { color: dark ? "35506B" : C.line, width: 1 },
    });
    slide.addText(row[0], {
      x: 7.2,
      y,
      w: 1.32,
      h: 0.22,
      fontFace: "Microsoft YaHei",
      fontSize: 8.8,
      bold: true,
      color: accent,
      margin: 0,
      fit: "shrink",
    });
    slide.addText(row[1], {
      x: 8.65,
      y,
      w: 3.55,
      h: 0.36,
      fontFace: "Microsoft YaHei",
      fontSize: 9.2,
      color: dark ? C.white : C.ink,
      margin: 0,
      fit: "shrink",
    });
  });
  addFooter(slide, slideNo);
  recordPreview(
    slideNo,
    `code_${slideNo}`,
    svgBase(
      heading,
      `<rect x="110" y="185" width="700" height="500" rx="18" fill="#0F172A"/><text x="145" y="245" font-family="Consolas" font-size="20" fill="#D1E7FF">${codeLines
        .slice(0, 4)
        .join(" ")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")}</text><text x="900" y="230" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#${accent}">代码说明</text><text x="900" y="310" font-family="Microsoft YaHei" font-size="24" fill="#102033">${explainRows
        .map((r) => r[0])
        .join(" / ")}</text>`
    )
  );
}

const slides = [];

function recordPreview(idx, name, svg) {
  slides.push({ idx, name, svg });
}

function svgBase(titleText, body, dark = false) {
  const bg = dark ? `#${C.navy}` : `#${C.bg}`;
  const ink = dark ? "#FFFFFF" : `#${C.ink}`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900">
<rect width="1600" height="900" fill="${bg}"/>
<text x="74" y="86" font-family="Microsoft YaHei, Arial" font-size="44" font-weight="700" fill="${ink}">${titleText}</text>
${body}
</svg>`;
}

// 1 Cover
{
  const slide = pptx.addSlide();
  addBg(slide, true);
  slide.addShape(pptx.ShapeType.line, { x: 0.75, y: 4.72, w: 10.8, h: 0, line: { color: "3DD6C6", width: 1.5, transparency: 25 } });
  [["采集", 1.0], ["Kafka", 3.6], ["Spark", 6.1], ["MySQL/HDFS", 8.6], ["Dashboard", 11.0]].forEach(([t, x], i) => {
    slide.addShape(pptx.ShapeType.ellipse, { x, y: 4.52, w: 0.38, h: 0.38, fill: { color: i === 2 ? C.green : C.blue }, line: { color: C.white, transparency: 85 } });
    slide.addText(t, { x: x - 0.38, y: 4.98, w: 1.25, h: 0.2, fontFace: "Microsoft YaHei", fontSize: 8.5, color: "D8EAF8", align: "center", margin: 0, fit: "shrink" });
  });
  slide.addText("实时数据分析模块", { x: 0.76, y: 1.3, w: 7.9, h: 0.75, fontFace: "Microsoft YaHei", fontSize: 35, bold: true, color: C.white, margin: 0, fit: "shrink" });
  slide.addText("从行情采集到流式计算，再到风险告警与大屏展示", { x: 0.79, y: 2.12, w: 6.4, h: 0.28, fontFace: "Microsoft YaHei", fontSize: 12.5, color: "B8C7D9", margin: 0, fit: "shrink" });
  slide.addText("Quant Stream", { x: 10.15, y: 0.56, w: 1.9, h: 0.24, fontFace: "Aptos Display", fontSize: 13, bold: true, color: "7DD3FC", margin: 0 });
  slide.addText("课堂汇报 / 答辩演示", { x: 0.8, y: 6.48, w: 2.0, h: 0.22, fontFace: "Microsoft YaHei", fontSize: 8.5, color: "94A3B8", margin: 0 });
  recordPreview(1, "cover", svgBase("实时数据分析模块", `<text x="76" y="205" font-family="Microsoft YaHei" font-size="28" fill="#B8C7D9">从行情采集到流式计算，再到风险告警与大屏展示</text><line x1="100" y1="570" x2="1380" y2="570" stroke="#3DD6C6" stroke-width="4"/><text x="120" y="630" font-family="Microsoft YaHei" font-size="25" fill="#D8EAF8">采集  →  Kafka  →  Spark  →  MySQL/HDFS  →  Dashboard</text>`, true));
}

// 2 Architecture
{
  const slide = pptx.addSlide();
  addBg(slide);
  title(slide, "一条实时链路，支撑整个平台的动态展示", "每 5 秒更新前端大屏，底层数据来自 Kafka + Spark 的流式处理");
  const nodes = [
    ["行情采集", "多源抓取与格式统一", 1.2, C.blue],
    ["消息缓冲", "Kafka topic 承接流量", 3.55, C.amber],
    ["流式计算", "Spark 批内聚合与告警", 5.9, C.green],
    ["结果存储", "MySQL 明细/聚合，HDFS 归档", 8.25, C.cyan],
    ["可视化", "后端接口 + 前端刷新", 10.6, C.red],
  ];
  nodes.forEach((n, i) => {
    addNode(slide, n[0], n[1], n[2], 2.55, n[3], i + 1);
    if (i < nodes.length - 1) {
      slide.addShape(pptx.ShapeType.line, { x: n[2] + 0.8, y: 2.9, w: 1.0, h: 0, line: { color: C.line, width: 2, beginArrowType: "none", endArrowType: "triangle" } });
    }
  });
  slide.addText("这部分的价值不是单纯“展示数据”，而是把采集、清洗、分析、告警和展示串成一条可运行的实时数据链。", {
    x: 1.1,
    y: 5.72,
    w: 11.1,
    h: 0.38,
    fontFace: "Microsoft YaHei",
    fontSize: 13.5,
    bold: true,
    color: C.ink,
    align: "center",
    margin: 0,
    fit: "shrink",
  });
  addFooter(slide, 2);
  recordPreview(2, "architecture", svgBase("一条实时链路，支撑整个平台的动态展示", `<text x="130" y="370" font-family="Microsoft YaHei" font-size="30" fill="#102033">行情采集 → Kafka → Spark Streaming → MySQL/HDFS → 前端大屏</text><text x="130" y="690" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#102033">价值：把采集、清洗、分析、告警和展示串成可运行的数据链</text>`));
}

// 3 Producer
{
  const slide = pptx.addSlide();
  addBg(slide);
  title(slide, "采集端：把多源行情变成标准事件", "对应代码：python/producer/stock_producer.py 与 stock_sources.py");
  bullet(slide, "读取股票池：A 股、港股等标的统一进入采集队列", 0.9, 1.65, 5.7);
  bullet(slide, "并发抓取：ThreadPoolExecutor 提高一个采集周期内的吞吐", 0.9, 2.15, 5.7);
  bullet(slide, "多源兜底：Sina / Tencent / Eastmoney 等源失败时自动切换", 0.9, 2.65, 5.7);
  bullet(slide, "事件校验：过滤价格、成交量、涨跌幅异常的数据", 0.9, 3.15, 5.7);
  bullet(slide, "写入 Kafka：以 symbol 作为 key，便于下游按股票分组", 0.9, 3.65, 5.7);
  addMiniCode(slide, [
    "quotes = [q for q in fetch_quotes() if is_valid_tick(q)]",
    "producer.send(",
    "  settings.kafka_topic,",
    "  key=quote['symbol'],",
    "  value=quote",
    ")",
  ], 7.0, 1.58, 4.95, 2.35);
  slide.addText("汇报重点", { x: 7.0, y: 4.35, w: 1.2, h: 0.2, fontFace: "Microsoft YaHei", fontSize: 9, bold: true, color: C.blue, margin: 0 });
  slide.addText("采集端只负责把“不同来源、不同格式”的行情统一成标准 JSON 事件，复杂分析留给 Spark，降低模块耦合。", {
    x: 7.0,
    y: 4.68,
    w: 4.95,
    h: 0.75,
    fontFace: "Microsoft YaHei",
    fontSize: 12,
    bold: true,
    color: C.ink,
    margin: 0,
    fit: "shrink",
  });
  addFooter(slide, 3);
  recordPreview(3, "producer", svgBase("采集端：把多源行情变成标准事件", `<text x="110" y="210" font-family="Microsoft YaHei" font-size="28" fill="#102033">股票池 → 并发抓取 → 多源兜底 → 数据校验 → Kafka</text><rect x="860" y="190" width="560" height="270" rx="18" fill="#0F172A"/><text x="900" y="260" font-family="Consolas" font-size="22" fill="#D1E7FF">producer.send(topic, key=symbol, value=quote)</text><text x="110" y="660" font-family="Microsoft YaHei" font-size="26" font-weight="700" fill="#1D7CF2">重点：采集端做标准化，不把分析逻辑写死在爬虫里</text>`));
}

// 4 Spark
{
  const slide = pptx.addSlide();
  addBg(slide);
  title(slide, "Spark Streaming：实时分析发生在微批处理中", "对应代码：python/spark/stock_streaming_job.py");
  const steps = [
    ["读取 Kafka", "readStream.format('kafka')"],
    ["解析 JSON", "from_json + schema"],
    ["质量过滤", "价格/成交量/涨跌幅合理性"],
    ["去重压缩", "event_id 与重复行情过滤"],
    ["批内计算", "聚合、统计、告警、写库"],
  ];
  steps.forEach((s, i) => {
    const x = 0.95 + i * 2.35;
    slide.addShape(pptx.ShapeType.chevron, { x, y: 2.05, w: 1.72, h: 0.78, fill: { color: i === 4 ? C.green : C.white }, line: { color: i === 4 ? C.green : C.line, width: 1.2 } });
    slide.addText(s[0], { x: x + 0.1, y: 2.25, w: 1.3, h: 0.18, fontFace: "Microsoft YaHei", fontSize: 9.8, bold: true, color: i === 4 ? C.white : C.ink, align: "center", margin: 0, fit: "shrink" });
    slide.addText(s[1], { x: x - 0.06, y: 3.08, w: 1.9, h: 0.34, fontFace: "Consolas", fontSize: 7.2, color: C.muted, align: "center", margin: 0, fit: "shrink" });
  });
  addMiniCode(slide, [
    "stream_df.writeStream",
    "  .outputMode('append')",
    "  .foreachBatch(write_batch)",
    "  .option('checkpointLocation', settings.hdfs_checkpoint_path)",
    "  .start()",
  ], 1.35, 4.45, 5.0, 1.46);
  slide.addText("为什么用 foreachBatch？", { x: 7.1, y: 4.48, w: 2.5, h: 0.22, fontFace: "Microsoft YaHei", fontSize: 10, bold: true, color: C.blue, margin: 0 });
  slide.addText("每个微批都可以同时写 MySQL 明细表、聚合表、告警表和 HDFS 归档，便于把“实时计算”和“展示查询”分开。", {
    x: 7.1,
    y: 4.84,
    w: 4.55,
    h: 0.66,
    fontFace: "Microsoft YaHei",
    fontSize: 11.2,
    color: C.ink,
    bold: true,
    margin: 0,
    fit: "shrink",
  });
  addFooter(slide, 4);
  recordPreview(4, "spark", svgBase("Spark Streaming：实时分析发生在微批处理中", `<text x="100" y="290" font-family="Microsoft YaHei" font-size="27" fill="#102033">Kafka → JSON解析 → 质量过滤 → 去重压缩 → foreachBatch 写出</text><text x="130" y="620" font-family="Consolas" font-size="24" fill="#1D7CF2">writeStream.foreachBatch(write_batch).option(checkpointLocation)</text>`));
}

// 4.1 Core file map
{
  const slide = pptx.addSlide();
  addBg(slide);
  title(slide, "代码结构：实时数据分析主要看这 4 个文件", "汇报时可以按文件职责从上游讲到下游");
  addTable(slide, [
    ["文件", "核心职责", "汇报时怎么讲"],
    ["python/producer/stock_producer.py", "采集股票行情并写入 Kafka", "负责实时数据入口，保证每轮采集形成标准事件"],
    ["python/common/stock_utils.py", "校验行情字段、生成时间格式", "把脏数据挡在进入 Kafka/Spark 之前"],
    ["python/spark/stock_streaming_job.py", "Spark 消费、清洗、聚合、告警、写库", "这是实时分析核心，所有实时统计都在这里形成"],
    ["DashboardService.java", "查询 MySQL，封装前端所需接口", "把实时计算结果转换成大屏可展示的数据"],
  ], 0.75, 1.6, [3.35, 3.55, 4.5], 0.72);
  slide.addText("讲解顺序：先讲数据从哪里来，再讲 Spark 如何处理，最后讲结果如何展示。", {
    x: 0.85,
    y: 6.12,
    w: 9.8,
    h: 0.3,
    fontFace: "Microsoft YaHei",
    fontSize: 12.5,
    bold: true,
    color: C.ink,
    margin: 0,
    fit: "shrink",
  });
  addFooter(slide, 5);
  recordPreview(5, "file_map", svgBase("代码结构：实时数据分析主要看这 4 个文件", `<text x="110" y="230" font-family="Microsoft YaHei" font-size="27" fill="#102033">stock_producer.py / stock_utils.py / stock_streaming_job.py / DashboardService.java</text><text x="110" y="650" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#102033">讲解顺序：数据来源 → Spark 处理 → 结果展示</text>`));
}

// 4.2 Producer code
addCodeExplainSlide({
  slideNo: 6,
  heading: "代码说明 1：生产者把行情写入 Kafka",
  subheading: "文件：python/producer/stock_producer.py",
  codeLines: [
    "symbols = load_symbols()",
    "with ThreadPoolExecutor(max_workers=max_workers) as executor:",
    "    quote = fetch_quote_with_fallback(item, settings.quote_sources)",
    "quotes = [q for q in fetch_quotes() if is_valid_tick(q)]",
    "producer.send(settings.kafka_topic, key=quote['symbol'], value=quote)",
    "producer.flush()",
  ],
  explainRows: [
    ["load_symbols", "从股票池读取需要监控的标的，决定实时采集范围。"],
    ["并发采集", "网络请求耗时较高，用线程池缩短一个采集周期。"],
    ["多源兜底", "某个行情源失败时切换到其他数据源，提高可用性。"],
    ["is_valid_tick", "发送 Kafka 前先过滤明显异常数据，减少下游脏数据。"],
    ["symbol key", "以股票代码作为 Kafka key，便于定位和按股票追踪。"],
  ],
  accent: C.blue,
});

// 4.3 Spark parse code
addCodeExplainSlide({
  slideNo: 7,
  heading: "代码说明 2：Spark 从 Kafka 解析实时事件",
  subheading: "文件：python/spark/stock_streaming_job.py / parse_stream",
  codeLines: [
    "raw = spark.readStream.format('kafka')",
    "    .option('kafka.bootstrap.servers', settings.kafka_bootstrap_servers)",
    "    .option('subscribe', settings.kafka_topic)",
    "    .option('startingOffsets', 'latest')",
    "parsed = raw.select(from_json(col('value').cast('string'), event_schema()))",
    "parsed = parsed.withColumn('event_time', to_timestamp('event_time'))",
  ],
  explainRows: [
    ["readStream", "持续消费 Kafka topic，不是一次性读取静态文件。"],
    ["event_schema", "用固定 schema 约束 JSON 字段，保证后续计算有类型。"],
    ["event_time", "把字符串时间转成 timestamp，用于窗口和排序。"],
    ["latest", "默认从最新 offset 开始，适合课堂演示实时流入。"],
    ["failOnDataLoss", "Kafka 数据短暂缺失时不让演示链路直接崩溃。"],
  ],
  accent: C.green,
});

// 4.4 Quality filters
addCodeExplainSlide({
  slideNo: 8,
  heading: "代码说明 3：进入分析前先做质量过滤",
  subheading: "过滤无效价格、零成交量和异常涨跌幅，避免污染看板",
  codeLines: [
    "return parsed.filter(",
    "    (col('last_price') > 0)",
    "    & (col('volume') > 0)",
    "    & (",
    "      (market.isin('SH','SZ','BJ') & (abs(col('change_pct')) < 11.0))",
    "      | ((market == 'HK') & (abs(col('change_pct')) < 50.0))",
    "    )",
    ")",
  ],
  explainRows: [
    ["last_price > 0", "价格必须为正，过滤接口异常或空值。"],
    ["volume > 0", "成交量为 0 的行不参与实时统计。"],
    ["A 股阈值", "SH/SZ/BJ 用更严格涨跌幅边界过滤异常值。"],
    ["港股阈值", "HK 波动范围更大，使用更宽松边界。"],
    ["作用", "保证实时聚合和告警不是被错误行情触发。"],
  ],
  accent: C.amber,
});

// 4.5 foreachBatch code
addCodeExplainSlide({
  slideNo: 9,
  heading: "代码说明 4：每个微批同时完成归档、聚合、告警和写库",
  subheading: "文件：stock_streaming_job.py / write_batch",
  codeLines: [
    "raw_batch = batch_df.dropDuplicates(['event_id'])",
    "raw_batch.write.mode('append').parquet(hdfs_output_path + '/quotes')",
    "write_dashboard_aggregates(raw_batch, batch_id)",
    "changed_batch = keep_changed_quotes(raw_batch)",
    "write_jdbc(build_alerts(changed_batch), 'alert_events')",
    "write_jdbc(latest_quotes, 'price_ticks')",
  ],
  explainRows: [
    ["event_id 去重", "避免同一条行情事件重复进入结果表。"],
    ["HDFS 归档", "把原始行情保存为 parquet，便于后续离线复盘。"],
    ["聚合快照", "生成首页趋势、市场宽度、行业热力等指标。"],
    ["变更过滤", "价格/涨跌幅/成交量没变的快照不重复写入。"],
    ["告警与明细", "异常事件写 alert_events，最新行情写 price_ticks。"],
  ],
  accent: C.red,
});

// 5 Outputs table
{
  const slide = pptx.addSlide();
  addBg(slide);
  title(slide, "实时分析结果不是一张表，而是一组面向展示的结果表", "每张表服务一个前端视图或系统能力");
  addTable(slide, [
    ["结果表", "写入内容", "页面价值"],
    ["price_ticks", "去重后的行情明细", "实时走势图、搜索、个股详情"],
    ["metric_snapshots", "分钟级市场快照", "首页趋势、流量、健康状态"],
    ["symbol_stats", "股票维度聚合", "关注列表、涨跌幅排行"],
    ["sector_stats / category_stats", "行业与市场分类统计", "市场热力、结构分析"],
    ["alert_events", "价格/成交量异常告警", "风险中心、闭环处理"],
    ["HDFS parquet", "原始行情归档", "离线复盘、扩展分析"],
  ], 1.0, 1.55, [2.55, 4.05, 4.35], 0.56);
  slide.addText("讲解句：Spark 不是直接服务页面，而是提前把页面需要的统计口径计算好，后端查询就会更轻。", {
    x: 1.0,
    y: 6.05,
    w: 10.6,
    h: 0.32,
    fontFace: "Microsoft YaHei",
    fontSize: 12.5,
    bold: true,
    color: C.ink,
    margin: 0,
    fit: "shrink",
  });
  addFooter(slide, 10);
  recordPreview(10, "tables", svgBase("实时分析结果不是一张表，而是一组面向展示的结果表", `<text x="120" y="220" font-family="Microsoft YaHei" font-size="27" fill="#102033">price_ticks / metric_snapshots / symbol_stats / sector_stats / alert_events / HDFS parquet</text><text x="120" y="650" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#102033">讲解句：先计算页面需要的统计口径，后端查询更轻</text>`));
}

// 6 Alerts
{
  const slide = pptx.addSlide();
  addBg(slide);
  title(slide, "告警规则：固定阈值 + 历史基线的组合判断", "目标是发现短时间内价格波动和成交量异动");
  slide.addText("价格波动告警", { x: 1.1, y: 1.65, w: 2.2, h: 0.24, fontFace: "Microsoft YaHei", fontSize: 13, bold: true, color: C.blue, margin: 0 });
  slide.addText("abs(change_pct) ≥ max(2.0, avg_abs_change_pct × 2.5)", { x: 1.1, y: 2.15, w: 5.2, h: 0.34, fontFace: "Consolas", fontSize: 13, bold: true, color: C.ink, margin: 0, fit: "shrink" });
  slide.addText("成交量异动告警", { x: 1.1, y: 3.1, w: 2.4, h: 0.24, fontFace: "Microsoft YaHei", fontSize: 13, bold: true, color: C.green, margin: 0 });
  slide.addText("volume ≥ max(market_min, avg_volume × 2.0)", { x: 1.1, y: 3.6, w: 5.2, h: 0.34, fontFace: "Consolas", fontSize: 13, bold: true, color: C.ink, margin: 0, fit: "shrink" });
  slide.addShape(pptx.ShapeType.arc, { x: 7.4, y: 1.55, w: 2.3, h: 2.3, adjustPoint: 0.2, line: { color: C.amber, width: 8, transparency: 10 } });
  slide.addShape(pptx.ShapeType.arc, { x: 8.25, y: 2.4, w: 2.3, h: 2.3, adjustPoint: 0.2, line: { color: C.red, width: 8, transparency: 10 } });
  slide.addText("MEDIUM", { x: 7.76, y: 2.12, w: 1.2, h: 0.2, fontFace: "Aptos Display", fontSize: 13, bold: true, color: C.amber, margin: 0 });
  slide.addText("HIGH", { x: 9.0, y: 3.16, w: 0.9, h: 0.2, fontFace: "Aptos Display", fontSize: 13, bold: true, color: C.red, margin: 0 });
  slide.addText("告警等级由更高阈值决定：价格高波动或成交量高放大时标记 HIGH，否则为 MEDIUM。", {
    x: 7.25,
    y: 5.18,
    w: 4.2,
    h: 0.55,
    fontFace: "Microsoft YaHei",
    fontSize: 10.8,
    color: C.ink,
    bold: true,
    margin: 0,
    fit: "shrink",
  });
  addFooter(slide, 11);
  recordPreview(11, "alerts", svgBase("告警规则：固定阈值 + 历史基线的组合判断", `<text x="120" y="250" font-family="Consolas" font-size="30" fill="#102033">abs(change_pct) ≥ max(2.0, avg_abs_change_pct × 2.5)</text><text x="120" y="390" font-family="Consolas" font-size="30" fill="#102033">volume ≥ max(market_min, avg_volume × 2.0)</text><text x="990" y="360" font-family="Arial" font-size="44" font-weight="700" fill="#F59E0B">MEDIUM</text><text x="1070" y="470" font-family="Arial" font-size="44" font-weight="700" fill="#DC2626">HIGH</text>`));
}

// 6.1 Alert code
addCodeExplainSlide({
  slideNo: 12,
  heading: "代码说明 5：告警由历史基线动态生成阈值",
  subheading: "文件：stock_streaming_job.py / read_history_baseline 与 build_alerts",
  codeLines: [
    "history = spark.read.jdbc(... price_ticks WHERE created_at >= NOW() - INTERVAL 1 DAY)",
    "avg_abs_change_pct = avg(abs(change_pct))",
    "avg_volume = avg(volume)",
    "price_alert_threshold = greatest(2.0, avg_abs_change_pct * 2.5)",
    "volume_alert_threshold = greatest(volume_min_threshold, avg_volume * 2.0)",
    "alert_type = price_volatility / volume_spike",
  ],
  explainRows: [
    ["历史基线", "读取最近一天数据，得到每只股票自己的正常波动水平。"],
    ["动态阈值", "不是所有股票都用同一标准，避免高波动股票误报。"],
    ["固定底线", "用 2% 和最低成交量兜底，避免阈值过低。"],
    ["告警类型", "价格触发为 price_volatility，否则为 volume_spike。"],
    ["告警等级", "超过更高阈值标记 HIGH，其余标记 MEDIUM。"],
  ],
  accent: C.amber,
});

// 7 Dashboard
{
  const slide = pptx.addSlide();
  addBg(slide);
  title(slide, "展示层：后端统一查询，前端定时刷新", "对应代码：DashboardService.java 与 frontend/index.html");
  addPill(slide, "/dashboard", 1.05, 1.56, C.blue);
  addPill(slide, "/health", 3.0, 1.56, C.green);
  addPill(slide, "/alerts", 4.95, 1.56, C.amber);
  addPill(slide, "/stocks/{symbol}", 6.9, 1.56, C.red);
  slide.addText("前端每 5 秒调用接口，展示实时流状态、最新行情、告警列表、行业热力和模型预测。", {
    x: 1.05,
    y: 2.3,
    w: 6.0,
    h: 0.52,
    fontFace: "Microsoft YaHei",
    fontSize: 14.5,
    bold: true,
    color: C.ink,
    margin: 0,
    fit: "shrink",
  });
  addMiniCode(slide, [
    "setInterval(safeRefresh, 5000)",
    "",
    "stream_state:",
    "  FLOWING / DELAYED / STOPPED",
    "current_mode:",
    "  LIVE / REPLAY / OFFLINE",
  ], 8.35, 1.45, 3.55, 2.8);
  bullet(slide, "FLOWING：30 秒内有新批次", 1.15, 3.6, 4.8);
  bullet(slide, "DELAYED：5 分钟内有数据，但不是持续流入", 1.15, 4.1, 4.8);
  bullet(slide, "STOPPED：采集或 Spark 链路已停止", 1.15, 4.6, 4.8);
  slide.addText("答辩亮点：实时状态不是前端猜的，而是后端根据 MySQL 中最新写入时间和分钟快照计算出来。", {
    x: 1.15,
    y: 5.55,
    w: 10.2,
    h: 0.3,
    fontFace: "Microsoft YaHei",
    fontSize: 12,
    bold: true,
    color: C.blue,
    margin: 0,
    fit: "shrink",
  });
  addFooter(slide, 13);
  recordPreview(13, "dashboard", svgBase("展示层：后端统一查询，前端定时刷新", `<text x="120" y="230" font-family="Microsoft YaHei" font-size="30" fill="#102033">/dashboard  /health  /alerts  /stocks/{symbol}</text><text x="120" y="380" font-family="Consolas" font-size="28" fill="#1D7CF2">setInterval(safeRefresh, 5000)</text><text x="120" y="610" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#102033">实时状态由最新写入时间和分钟快照计算，而不是前端猜测</text>`));
}

// 7.1 Backend code
addCodeExplainSlide({
  slideNo: 14,
  heading: "代码说明 6：后端把实时结果封装成前端接口",
  subheading: "文件：java-backend/.../DashboardService.java",
  codeLines: [
    "response.put('system_health', fetchHealth())",
    "response.put('stream_status', fetchSingleRow(... metric_snapshots ...))",
    "response.put('summary', fetchSingleRow(... latest price_ticks ...))",
    "response.put('latest_alerts', fetchRows(... alert_events ...))",
    "response.put('focus_stocks', fetchRows(... price + alert + model ...))",
    "return response",
  ],
  explainRows: [
    ["统一接口", "前端只需请求 /dashboard，就能拿到大屏所需数据。"],
    ["stream_status", "根据最新批次时间计算 FLOWING、DELAYED、STOPPED。"],
    ["summary", "从每只股票最新一条行情汇总市场涨跌、成交量。"],
    ["latest_alerts", "把 Spark 生成的告警提供给风险中心。"],
    ["focus_stocks", "融合行情、告警、模型预测，形成重点关注列表。"],
  ],
  accent: C.blue,
});

// 8 Stability
{
  const slide = pptx.addSlide();
  addBg(slide);
  title(slide, "稳定性设计：让演示时“有数据、有状态、有兜底”", "实时链路最怕断流、重复写入和脏数据，本模块针对这些点做了保护");
  const guards = [
    ["质量过滤", "过滤无效价格、零成交量、异常涨跌幅"],
    ["去重压缩", "event_id 去重 + 相同价格快照过滤"],
    ["检查点", "Spark checkpoint 支持流式恢复"],
    ["容错写出", "HDFS 写失败时继续 MySQL 写库"],
    ["状态可见", "前端显示 LIVE / REPLAY / OFFLINE"],
  ];
  guards.forEach((g, i) => {
    const y = 1.55 + i * 0.82;
    slide.addShape(pptx.ShapeType.line, { x: 1.05, y: y + 0.38, w: 10.5, h: 0, line: { color: C.line, width: 1 } });
    slide.addText(g[0], { x: 1.1, y, w: 1.55, h: 0.24, fontFace: "Microsoft YaHei", fontSize: 11.2, bold: true, color: i % 2 ? C.green : C.blue, margin: 0 });
    slide.addText(g[1], { x: 3.05, y, w: 7.8, h: 0.24, fontFace: "Microsoft YaHei", fontSize: 11.2, color: C.ink, margin: 0, fit: "shrink" });
  });
  slide.addText("讲解句：这不是一个只在理想情况下工作的 demo，而是考虑了流式系统常见问题的演示链路。", {
    x: 1.05,
    y: 6.03,
    w: 10.8,
    h: 0.3,
    fontFace: "Microsoft YaHei",
    fontSize: 12.4,
    bold: true,
    color: C.ink,
    margin: 0,
    fit: "shrink",
  });
  addFooter(slide, 15);
  recordPreview(15, "stability", svgBase("稳定性设计：让演示时“有数据、有状态、有兜底”", `<text x="120" y="220" font-family="Microsoft YaHei" font-size="28" fill="#102033">质量过滤 / 去重压缩 / Spark checkpoint / 容错写出 / 状态可见</text><text x="120" y="650" font-family="Microsoft YaHei" font-size="27" font-weight="700" fill="#102033">不是只在理想情况下工作的 demo，而是考虑了实时链路常见问题</text>`));
}

// 9 Talk track
{
  const slide = pptx.addSlide();
  addBg(slide, true);
  slide.addText("汇报收束：我会这样讲", { x: 0.78, y: 0.62, w: 4.8, h: 0.45, fontFace: "Microsoft YaHei", fontSize: 26, bold: true, color: C.white, margin: 0 });
  const talks = [
    ["第一句", "实时模块负责把行情从采集端持续送入系统，并在 Spark 中转化为可展示、可告警的数据。"],
    ["核心能力", "它不是静态图表，而是 Kafka、Spark、MySQL 和前端联动的一条实时分析链。"],
    ["分析内容", "系统会做分钟聚合、行业统计、个股排行、价格波动和成交量异动告警。"],
    ["工程价值", "去重、质量过滤、检查点和健康状态让演示更稳定，也让数据链路更容易解释。"],
    ["局限与改进", "下一步可以补充批次质量统计、告警原因字段和更细的实时监控页面。"],
  ];
  talks.forEach((t, i) => {
    const y = 1.55 + i * 0.86;
    slide.addText(t[0], { x: 1.0, y, w: 1.25, h: 0.22, fontFace: "Microsoft YaHei", fontSize: 9.4, bold: true, color: "7DD3FC", margin: 0 });
    slide.addText(t[1], { x: 2.38, y, w: 9.2, h: 0.34, fontFace: "Microsoft YaHei", fontSize: 12.1, bold: true, color: C.white, margin: 0, fit: "shrink" });
  });
  slide.addText("结束语：实时数据分析部分证明系统不是只做离线展示，而是具备持续采集、持续计算、持续告警的能力。", {
    x: 1.0,
    y: 6.23,
    w: 10.9,
    h: 0.34,
    fontFace: "Microsoft YaHei",
    fontSize: 13.5,
    bold: true,
    color: "CFFAFE",
    margin: 0,
    fit: "shrink",
  });
  recordPreview(16, "talk_track", svgBase("汇报收束：我会这样讲", `<text x="110" y="220" font-family="Microsoft YaHei" font-size="28" fill="#FFFFFF">实时模块把行情持续送入系统，并转化为可展示、可告警的数据。</text><text x="110" y="350" font-family="Microsoft YaHei" font-size="28" fill="#FFFFFF">核心能力：Kafka、Spark、MySQL 和前端联动的一条实时分析链。</text><text x="110" y="650" font-family="Microsoft YaHei" font-size="29" font-weight="700" fill="#CFFAFE">证明系统具备持续采集、持续计算、持续告警的能力。</text>`, true));
}

async function exportDeck() {
  const pptxPath = path.join(outDir, "实时数据分析模块演讲汇报_代码说明版.pptx");
  await pptx.writeFile({ fileName: pptxPath });

  for (const item of slides) {
    const png = path.join(previewDir, `${String(item.idx).padStart(2, "0")}_${item.name}.png`);
    await sharp(Buffer.from(item.svg)).png().toFile(png);
  }
  const composites = [];
  for (let i = 0; i < slides.length; i += 1) {
    const s = slides[i];
    const input = path.join(previewDir, `${String(s.idx).padStart(2, "0")}_${s.name}.png`);
    const thumb = await sharp(input).resize(480, 270).png().toBuffer();
    const x = 40 + (i % 3) * 520;
    const y = 40 + Math.floor(i / 3) * 560;
    const label = Buffer.from(
      `<svg xmlns="http://www.w3.org/2000/svg" width="90" height="36"><text x="0" y="24" font-family="Arial" font-size="22" fill="#334155">${String(s.idx).padStart(2, "0")}</text></svg>`
    );
    composites.push({ input: thumb, left: x, top: y });
    composites.push({ input: label, left: x, top: y + 292 });
  }
  const montageHeight = 40 + Math.ceil(slides.length / 3) * 560;
  await sharp({
    create: {
      width: 1600,
      height: montageHeight,
      channels: 4,
      background: "#EEF2F7",
    },
  })
    .composite(composites)
    .png()
    .toFile(path.join(previewDir, "montage.png"));

  const report = {
    pptxPath,
    previewDir,
    slideCount: slides.length,
    previews: slides.map((s) => path.join(previewDir, `${String(s.idx).padStart(2, "0")}_${s.name}.png`)),
    montage: path.join(previewDir, "montage.png"),
  };
  fs.writeFileSync(path.join(outDir, "realtime_analysis_ppt_manifest.json"), JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));
}

exportDeck().catch((err) => {
  console.error(err);
  process.exit(1);
});
