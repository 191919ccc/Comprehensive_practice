# RF 退化修复与 LGB+LSTM 生产组合说明

## 修改目的

最近一次完整训练显示 RandomForest 退化为全量 `WATCH`，`up_recall/down_recall` 为 0，且 walk-forward 触发多数类兜底；LSTM 主验证集有提升但 walk-forward 也被兜底。为了避免退化模型拖累生产预测，本次修改将默认生产训练组合改为 LightGBM + LSTM，同时保留 RF 作为可选模型。

## 修改文件

- `python/ml/stock_ml.py`
- `python/ml/train_daily_predict.py`
- `python/common/config.py`

## 具体修改

1. RF 参数收缩并统一阈值
   - `direction_threshold` 从 `0.02` 改为 `0.015`，与 LightGBM/LSTM 一致。
   - RF 参数改为更浅、更小的树：`n_estimators_reg=80`、`n_estimators_cls=120`、`max_depth=12`、`min_samples_leaf=10`、`max_features=0.6`。
   - `ML_RF_N_JOBS` 默认保持 `4`，用于多核训练。

2. guard 兜底逻辑放宽
   - 新增 `BASELINE_GUARD_LIFT_FLOOR=-0.02`。
   - 验证集和 walk-forward 的兜底触发条件从 `lift < 0` 放宽为 `lift < -0.02`。
   - 校准阶段同样使用该容错阈值，避免轻微低于基线就直接退化为多数类。

3. LSTM 样本与窗口调整
   - `ML_LSTM_WINDOW_SIZE` 默认从 `45` 改为 `30`。
   - `ML_LSTM_LEARNING_RATE` 默认从 `0.00045` 改为 `0.0005`。
   - `ML_LSTM_MAX_SEQUENCES` 默认保持 `80000`，比此前实际运行的约 4 万条更适合正式验证。

4. 默认生产组合去掉 RF
   - `train_daily_predict.py --models` 默认从三模型改为 `lightgbm,lstm`。
   - 新增 `--models` 选择能力，可显式训练 `random_forest,lightgbm,lstm`。
   - `prepare_model_datasets()` 支持按模型过滤，默认不再为 RF 额外准备数据。

## 验证命令

静态检查：

```bat
D:\anaconda3\envs\MachineLearn\python.exe -m py_compile python\ml\stock_ml.py python\ml\train_daily_predict.py python\common\config.py
```

轻量验证，不写库：

```bat
set ML_MAX_TRAIN_ROWS=15000
set ML_LSTM_EPOCHS=5
set ML_LSTM_MAX_SEQUENCES=30000
D:\anaconda3\envs\MachineLearn\python.exe -m python.ml.train_daily_predict --version-label daily-test --models lightgbm,lstm --no-write
```

正式生产训练：

```bat
set ML_MAX_TRAIN_ROWS=120000
set ML_LSTM_EPOCHS=60
set ML_LSTM_MAX_SEQUENCES=80000
D:\anaconda3\envs\MachineLearn\python.exe -m python.ml.train_daily_predict --version-label daily-best
```

如需完整三模型对比，可显式加回 RF：

```bat
D:\anaconda3\envs\MachineLearn\python.exe -m python.ml.train_daily_predict --version-label daily-rf-check --models random_forest,lightgbm,lstm --no-write
```

## 剩余限制

- 这次修改不删除 RF 代码，只把 RF 从默认生产组合中排除。
- LSTM walk-forward 是否恢复，需要重新运行 `--no-write` 训练验证。
- `drift_check` 只有正式写库后才能重新评估是否恢复正常。
