# 股票实时流分析平台

本项目用于课程答辩和实时流分析演示。系统从多个股票行情网站采集数据，写入 Kafka，由 Spark Structured Streaming 实时消费、清洗、预警和归档，再落地到 MySQL 与 HDFS/本地归档目录，最后通过 Spring Boot + ECharts 前端展示。

主链路：

```text
多网站行情采集/历史回放 -> Kafka -> Spark Structured Streaming -> MySQL + HDFS/本地归档 -> Java Backend -> ECharts 前端
```

## 目录结构

```text
python/         Python 采集、Kafka Producer、Spark 流处理、机器学习预测
java-backend/   Spring Boot 后端，提供 dashboard 和 health API
frontend/       ECharts 单页可视化大屏
tools/          一键启动、停止和健康检查脚本
```

## 数据来源

当前支持多数据源 fallback：

- `yahoo`：Yahoo Finance，主要用于美股。
- `eastmoney`：东方财富，主要用于 A 股、港股兜底。
- `sina`：新浪财经，主要用于 A 股。
- `tencent`：腾讯证券，主要用于 A 股兜底。
- `stooq`：Stooq，主要用于美股兜底。

股票池配置文件：

```text
python/data/stock_symbols.json
```

## 运行方式

推荐答辩演示使用历史回放模式，因为休市时真实行情变化很少。

```powershell
cd E:\作业\ww\Comprehensive_practice
powershell -ExecutionPolicy Bypass -File .\tools\start_demo.ps1
```

打开前端：

```text
http://127.0.0.1:5500/index.html
```

如果要使用真实网站采集：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\start_demo.ps1 -UseRealCrawler
```

停止服务：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\stop_demo.ps1
```

健康检查：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\health_check.ps1
```

## 手动运行流程

1. 初始化 MySQL。

```sql
CREATE DATABASE IF NOT EXISTS stock_stream DEFAULT CHARSET utf8mb4;
USE stock_stream;
SOURCE E:/作业/ww/Comprehensive_practice/python/sql/init.sql;
```

2. 启动 ZooKeeper 和 Kafka。

```powershell
E:\software\kafka_2.13-3.7.1\bin\windows\zookeeper-server-start.bat E:\software\kafka_2.13-3.7.1\config\zookeeper.properties
E:\software\kafka_2.13-3.7.1\bin\windows\kafka-server-start.bat E:\software\kafka_2.13-3.7.1\config\server.properties
```

3. 创建 Topic。

```powershell
E:\software\kafka_2.13-3.7.1\bin\windows\kafka-topics.bat --bootstrap-server 127.0.0.1:9092 --create --if-not-exists --topic stock_realtime_topic --partitions 1 --replication-factor 1
```

4. 启动 Spark 流处理。

```powershell
E:\software\spark-3.5.2-bin-hadoop3\bin\spark-submit.cmd --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.2,mysql:mysql-connector-java:8.0.33 python\spark\stock_streaming_job.py
```

5. 启动数据生产者。

```powershell
D:\anaconda3\envs\MachineLearn\python.exe -m python.producer.stock_replay_producer --interval 3 --volatility 1.2
```

真实采集：

```powershell
D:\anaconda3\envs\MachineLearn\python.exe -m python.producer.stock_producer
```

6. 启动后端和前端。

```powershell
cd E:\作业\ww\Comprehensive_practice\java-backend
mvn -q -DskipTests package
java -jar target\stock-risk-backend-0.0.1-SNAPSHOT.jar
```

```powershell
cd E:\作业\ww\Comprehensive_practice
D:\anaconda3\envs\MachineLearn\python.exe -m http.server 5500 --directory frontend
```

## 核心功能

- 实时链路状态：展示当前是实时采集、历史回放还是离线。
- 实时入库统计：展示近 1 分钟事件数、最后入库时间。
- 多市场概览：展示 A 股、港股、美股的涨跌情况。
- 异常预警：结合固定阈值和历史均值偏离，识别价格波动和成交量异常。
- 重点关注股票：按涨跌幅、成交量、预警等级和机器学习信号综合排序。
- 数据源状态：展示每个 source 的最近入库时间、覆盖股票数和状态。
- 归档与 checkpoint：Spark 写入本机 HDFS，输出目录为 `/user/fqy/stock_output`，checkpoint 目录为 `/user/fqy/stock_checkpoint`。

## 验证命令

Python 单元测试：

```powershell
D:\anaconda3\envs\MachineLearn\python.exe -m unittest python.tests.test_stock_utils
```

Python 语法检查：

```powershell
D:\anaconda3\envs\MachineLearn\python.exe -m py_compile python\common\config.py python\common\stock_utils.py python\producer\stock_catalog_loader.py python\producer\stock_sources.py python\producer\stock_producer.py python\producer\stock_replay_producer.py python\spark\stock_streaming_job.py python\ml\stock_ml.py python\ml\train_daily_predict.py python\ml\model_drift.py
```

前端语法检查：

```powershell
node --check frontend\vendor-loader.js
node --check frontend\shared-ui.js
node --check frontend\dashboard-home.js
node --check frontend\dash-pages.js
```

前端依赖说明：
- 页面优先加载 `frontend/vendor/chart.umd.js`、`frontend/vendor/echarts.min.js`、`frontend/vendor/marked.min.js`。
- 本地文件缺失时才回退 CDN。答辩前请确认 `frontend/vendor/` 下三个文件存在。
- 首页业务逻辑已经从 `index.html` 拆到 `frontend/dashboard-home.js`，共用逻辑放在 `frontend/shared-ui.js`。

Java 构建：

```powershell
cd java-backend
mvn -q -DskipTests package
```

## 注意事项

- 休市时真实行情变化少，演示建议使用历史回放模式。
- 当前 `.env` 的归档路径使用本机 Hadoop HDFS：`hdfs://localhost:9000/user/fqy/stock_output`。
- Kafka、Spark、MySQL、Java 后端、前端、生产者都要同时运行，前端的“近 1 分钟事件数”大于 0 才说明实时流正在进入系统。

## 机器学习模型

当前日线模型已经调整为“下跌风险识别”口径，不再按传统三分类强行预测看多/看空/观望。生产组合默认训练两类模型：

- `lightgbm`：正式风险识别主模型，使用清洗后的日线、指数、行业相对强弱、波动率和成交量特征。
- `lstm`：保留为辅助序列模型并记录指标；如果 walk-forward 负提升或风险覆盖率失控，会被自动剔除出 ensemble 权重。

`random_forest` 仍保留在代码中作为可选实验模型，但默认训练和写库不再启用，避免完整校准和 walk-forward 评估拖慢正式训练。

正式重新训练命令：

```powershell
$env:ML_MAX_TRAIN_ROWS='120000'
$env:ML_LSTM_EPOCHS='60'
$env:ML_LSTM_MAX_SEQUENCES='80000'
$env:ML_LSTM_AUX_MAX_WEIGHT='0.10'
$env:ML_LIGHTGBM_MIN_WEIGHT='0.85'
D:\anaconda3\envs\MachineLearn\python.exe -m python.ml.train_daily_predict --version-label clean-risk --models lightgbm,lstm --prediction-horizon 5 --horizon-experiments 1,3,5
```

正式训练会执行质量门禁。只有 `quality_gate=PASS` 时才会保存模型并写入 MySQL；如果门禁失败，会在写库前退出，避免坏模型覆盖当前结果。调试时如必须绕过，可追加 `--allow-quality-gate-fail`，正式演示不要使用这个参数。

训练完成后必须运行只读验证：

```powershell
D:\anaconda3\envs\MachineLearn\python.exe -m python.ml.verify_training_quality --version-prefix clean-risk
```

通过时应看到：

```text
[verify-ml] quality_gate=PASS
```

训练前会检查 `daily_stock_bars` 和 `daily_index_bars` 的最新交易日期。默认超过 `ML_MAX_DAILY_DATA_AGE_DAYS=10` 天会停止训练，避免用过期日线生成看似最新的预测。调试时如必须绕过，可临时追加：

```powershell
$env:ML_ALLOW_STALE_DAILY_DATA='true'
```

轻量验证命令：

```powershell
$env:ML_MAX_TRAIN_ROWS='15000'
$env:ML_LSTM_EPOCHS='5'
$env:ML_LSTM_MAX_SEQUENCES='30000'
$env:ML_LSTM_AUX_MAX_WEIGHT='0.10'
$env:ML_LIGHTGBM_MIN_WEIGHT='0.85'
D:\anaconda3\envs\MachineLearn\python.exe -m python.ml.train_daily_predict --version-label clean-risk-check --models lightgbm,lstm --prediction-horizon 5 --horizon-experiments 1,3,5 --no-write
```

训练流程会从 MySQL 的 `daily_stock_bars` 和 `daily_index_bars` 读取日线行情与指数特征。数据会先经过统一清洗、选源、去重和 OHLC 合法性检查，再生成技术特征。当前标签目标是未来 5 个交易日是否存在下跌风险，模型指标写入 `ml_model_metrics`，预测写入 `ml_predictions` 和 `ml_prediction_history`。

当前方向信号分为两类：

- `predicted_signal`：模型原始预测方向，用于模型漂移检测和预测历史评估。
- `alert_signal`：经过置信度过滤后的告警侧信号，用于控制模型告警误报。

当前风险目标模式下，UP 预测会统一归并为 WATCH，前端展示应按“风险/观望”理解模型输出。

当前数据库里旧正式模型仍未通过新门禁，重新训练前会看到：

```text
[verify-ml] quality_gate=FAIL
```
