# LightGBM 与 LSTM 参数分组测试说明

## 修改目标

为日线机器学习模型增加可重复的参数分组测试工具，用于比较 LightGBM 和 LSTM 的多组参数效果，找到当前数据集下更合适的一组参数。测试结果只写入 CSV 报告，不覆盖正式模型、不写入 `ml_predictions`、不污染仪表盘。

## 当前默认参数

### LightGBM

- `n_estimators=300`
- `learning_rate=0.02`
- `num_leaves=31`
- `min_child_samples=20`
- `class_weight="balanced"`

### LSTM

- `window=30`
- `hidden=48`
- `head=32`
- `layers=1`
- `dropout=0.30`
- `learning_rate=0.0007`
- `weight_decay=0.001`
- `batch_size=128`
- `epochs=60`
- `early_stop_patience=8`

## 新增文件

- `python/ml/tune_daily_params.py`

## 分组测试内容

### LightGBM 分组

1. `lgbm_current`
   - 当前默认参数，用作对照组。

2. `lgbm_slow_regularized`
   - 更低学习率、更强正则、更大 `min_child_samples`。
   - 目标：降低过拟合，提高 walk-forward 稳定性。

3. `lgbm_shallow_stable`
   - 更浅的树、更稳定的叶子数。
   - 目标：让方向分类更保守，减少噪声拟合。

4. `lgbm_more_leaves`
   - 增加叶子数，但配合采样和正则。
   - 目标：测试更强表达能力是否能提升方向识别。

### LSTM 分组

1. `lstm_current_quick`
   - 当前结构的快速测试版。

2. `lstm_short_window`
   - 窗口从 30 缩短到 20。
   - 目标：测试近期行情是否比长窗口更有效。

3. `lstm_wider`
   - hidden 从 48 提高到 64，并降低学习率。
   - 目标：测试更宽模型是否提升方向表达能力。

## 运行命令

请在你已经激活的 `(MachineLearn)` PowerShell 里运行：

```powershell
cd E:\作业\ww\Comprehensive_practice
python -m python.ml.tune_daily_params --models lightgbm,lstm --max-rows 30000 --lstm-max-sequences 12000 --lstm-epochs 10 --lstm-patience 4
```

这是一轮快速初筛。输出文件在：

```text
reports/ml_tuning/daily_param_tuning_*.csv
```

如果初筛结果稳定，再跑更接近正式训练的版本：

```powershell
cd E:\作业\ww\Comprehensive_practice
python -m python.ml.tune_daily_params --models lightgbm,lstm --max-rows 120000 --lstm-max-sequences 40000 --lstm-epochs 30 --lstm-patience 6
```

## 结果判断方式

CSV 中优先看这些列：

- `score`：综合排序分数，按 walk-forward 平衡准确率、macro F1、相对基线提升综合计算。
- `walk_forward_balanced_direction_accuracy`：最关键，越高越好。
- `walk_forward_direction_macro_f1`：三类方向整体识别能力，越高越好。
- `walk_forward_direction_lift_over_baseline`：是否超过多数类基线，必须尽量为正。
- `return_mae`：收益率误差，辅助参考。

不要只看 `direction_accuracy`。如果 `walk_forward_direction_lift_over_baseline` 仍为负，说明模型还没有真正超过“猜多数类”的基线。

## 当前执行情况

我已完成脚本语法检查：

```powershell
python -m py_compile .\python\ml\tune_daily_params.py .\python\ml\stock_ml.py
```

结果：通过。

但 Codex 工具环境默认只找到 `E:\sofeware\MSYS2\ucrt64\bin\python.exe`，该环境没有 `pandas` 和 `pip`，无法直接复用你终端中的 `(MachineLearn)` 环境。因此分组测试命令需要在你的 `(MachineLearn)` PowerShell 中运行。

## 后续动作

运行后把 CSV 或终端输出发给我，我会根据结果把最佳 LightGBM / LSTM 参数写回正式训练配置，并同步更新说明文档。

## 2026-05-13 快速初筛结果

本轮命令：

```powershell
python -m python.ml.tune_daily_params --models lightgbm,lstm --max-rows 30000 --lstm-max-sequences 12000 --lstm-epochs 10 --lstm-patience 4
```

输出报告：

```text
reports/ml_tuning/daily_param_tuning_20260513122215.csv
```

最佳 LightGBM 组：

- 组名：`lgbm_more_leaves`
- `score=0.3630`
- `walk_forward_balanced_direction_accuracy=0.4062`
- `walk_forward_direction_macro_f1=0.4055`
- `walk_forward_direction_lift_over_baseline=-0.0243`

结论：这是 LightGBM 组内最好的一组，但仍低于多数类基线，不能解释成 LightGBM 已经真正强于基线。

最佳 LSTM 组：

- 组名：`lstm_wider`
- `score=0.3733`
- `walk_forward_balanced_direction_accuracy=0.4108`
- `walk_forward_direction_macro_f1=0.4073`
- `walk_forward_direction_lift_over_baseline=0.0449`

结论：这是本轮全局最好的参数组，而且相对多数类基线为正，优先采用。

## 已回写到正式配置

### LightGBM

`python/ml/stock_ml.py` 已改为：

- `n_estimators=350`
- `learning_rate=0.02`
- `num_leaves=63`
- `min_child_samples=40`
- `subsample=0.8`
- `colsample_bytree=0.85`
- `reg_lambda=1.5`

### LSTM

`python/common/config.py` 默认值已改为：

- `ML_LSTM_WINDOW_SIZE=30`
- `ML_LSTM_HIDDEN_SIZE=64`
- `ML_LSTM_HEAD_SIZE=32`
- `ML_LSTM_NUM_LAYERS=1`
- `ML_LSTM_DROPOUT=0.35`
- `ML_LSTM_LEARNING_RATE=0.0005`
- `ML_LSTM_WEIGHT_DECAY=0.0015`
- `ML_LSTM_BATCH_SIZE=128`

## 回写后建议重训

```powershell
cd E:\作业\ww\Comprehensive_practice
python -m python.ml.train_daily_predict
```

重训后重点看：

- `lstm walk_forward_direction_lift_over_baseline` 是否仍为正。
- `lightgbm walk_forward_direction_lift_over_baseline` 是否改善到接近 0 或转正。
- 页面“模型验证状态”不要只看准确率，要继续看多数类基线对比。
