# 代码修改说明：walk-forward 模型选择、指数特征与板块特征

## 1. 修改目标

本次修改对应三个优化方向：

1. 模型选择逻辑更重视 walk-forward 稳定性；
2. 将真实指数行情作为外部市场特征并入训练特征；
3. 增加更明确的行业/板块收益与强弱特征。

这些修改不改变项目定位。项目仍然是“股票价格预测与告警”：价格分支继续预测 `predicted_next_price`，方向分支继续输出 `UP / DOWN / WATCH`。

## 2. 修改文件

修改文件：

- `python/ml/stock_ml.py`
- `python/ml/train_daily_predict.py`

新增文档：

- `docs/代码修改说明_2026-05-09_walkforward指数与板块特征.md`

## 3. 具体修改

### 3.1 模型选择优先 walk-forward

原来的 `direction_quality_score()` 更偏向单次验证集指标。现在改为更重视：

```text
walk_forward_balanced_direction_accuracy
walk_forward_direction_macro_f1
walk_forward_direction_lift_over_baseline
```

这样选择出来的最佳模型更关注跨时间窗口稳定性，而不是某一次 8:2 切分上的偶然表现。

### 3.2 加入真实指数特征

新增指数特征构造逻辑：

```text
index_sh_return_1
index_sh_return_3
index_cyb_return_1
index_cyb_return_3
index_hs300_return_1
index_hs300_return_3
market_index_return_1
market_index_return_3
relative_hs300_return_1
relative_hs300_return_3
```

指数来源为 `price_ticks` 中的 `akshare_index` 数据：

```text
INDEX_SH000001  -> 上证指数
INDEX_SZ399006  -> 创业板指
INDEX_SH000300  -> 沪深300
```

这些指数只作为外部特征合并到股票样本中，不会把指数本身当作股票训练样本。

### 3.3 增加板块/行业特征

新增板块特征：

```text
sector_return_1
sector_return_3
sector_relative_return_1
sector_relative_return_3
sector_strength_rank
sector_volatility_5
sector_up_ratio_3
```

含义：

- `sector_return_1`：同板块当日平均收益；
- `sector_return_3`：同板块 3 日平均收益；
- `sector_relative_return_1`：个股相对板块当日强弱；
- `sector_relative_return_3`：个股相对板块 3 日强弱；
- `sector_strength_rank`：板块在当天所有板块中的相对排名；
- `sector_volatility_5`：板块短期波动水平；
- `sector_up_ratio_3`：板块内 3 日上涨股票比例。

### 3.4 训练入口加载指数数据

`train_daily_predict.py` 现在会额外加载：

```python
load_price_ticks(source="akshare_index")
```

并传入：

```python
prepare_dataset(ticks, index_ticks)
predict_latest_ensemble(ticks, model_results, version, index_ticks)
```

因此训练和最新预测都会使用同一套指数特征。

### 3.5 阈值实验扩展

阈值实验列表从：

```text
0.3%, 0.5%, 1.0%
```

扩展为：

```text
0.3%, 0.5%, 1.0%, 1.5%, 2.0%
```

方便后续比较 `WATCH` 边界。

## 4. 验证结果

已执行语法检查：

```powershell
D:\anaconda3\envs\MachineLearn\python.exe -m py_compile python\ml\stock_ml.py python\ml\train_daily_predict.py
```

已执行小规模特征生成检查，结果：

```text
rows 4865
symbols 3
sector_return_1 True
sector_strength_rank True
index_hs300_return_3 True
market_index_return_3 True
relative_hs300_return_3 True
feature_count 45
```

说明新增特征可以正常生成。

## 5. 当前限制

当前数据库里的指数数据较少：

```text
akshare_index: 120 rows, 3 symbols
```

这意味着 2019 到 2026 的大量历史股票样本暂时还匹配不到长期指数特征，缺失部分会填 0。后续如果要让指数特征真正发挥作用，需要先补齐更长周期指数数据。

## 6. 后续训练命令

按用户要求，本次不由 Codex 自动训练。建议用户先补指数数据，再训练：

```powershell
python -m python.ml.cold_start --include-index --index-only --days 2500 --sources tencent --sleep 0
```

然后训练：

```powershell
python -m python.ml.train_daily_predict
```

当前 `python/.env` 已设置：

```text
ML_DIRECTION_THRESHOLD=0.015
```

所以直接训练时仍会使用 `WATCH=1.5%` 的三分类边界。
