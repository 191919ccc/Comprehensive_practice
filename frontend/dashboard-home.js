const API_BASE = window.StockShared?.API_BASE || "http://127.0.0.1:8080/api";
    /*
     * 首页大屏运行脚本。
     *
     * 负责首屏 KPI、主图（日线/分钟线）、告警摘要、模型状态、股票历史/导出和 AI 助手。
     * 与子页面共用的口径优先从 shared-ui.js 读取，避免“首页和子页面展示不一致”。
     */
    // 页面级状态：图表实例、当前股票、AI 上下文和刷新锁都集中放在这里，避免重复刷新互相覆盖。
    let priceChart = null;
    let flowChart = null;
    let selectedSymbol = "";
    let aiChatHistory = [];
    let chartMode = "daily";
    let isRefreshing = false;
    let consecutiveRefreshErrors = 0;
    let homeAlertFilter = "all";

    // 后端返回的是英文枚举，首页统一在这里翻译成课堂演示更易理解的中文文案。
    const textMap = {LIVE:"真实采集", REPLAY:"历史回放", OFFLINE:"离线", FLOWING:"FLOWING", DELAYED:"DELAYED", STOPPED:"STOPPED", UP:"看多", DOWN:"看空", WATCH:"观望", HIGH:"高危", MEDIUM:"中危", LOW:"提示", price_volatility:"价格波动", volume_spike:"成交量异常", model_drift:"模型漂移"};
    const alertTitles = {HIGH:["价格异常波动","成交量异常放大","高危风险预警"], MEDIUM:["价格波动预警","放量异动提示","短线波动放大"], LOW:["趋势观察提示","成交活跃提示","低风险提示"]};
    // 后端 alert_level 是权威字段；只有历史数据或旧接口缺失该字段时，前端才用这套轻量兜底规则。
    function deriveAlertLevel(row={}){
        const change=num(row.change_pct);
        const type=row.alert_type||"";
        const volumeRatio=num(row.volume_ratio ?? row.volume_change_ratio ?? row.turnover_ratio);
        const hasVolumeSpike=type==="volume_spike" || volumeRatio>=2;
        if(change<=-3 && hasVolumeSpike) return "HIGH";
        if(hasVolumeSpike || Math.abs(change)>=1.5 || type==="model_drift") return "MEDIUM";
        return "LOW";
    }
    function normalizeAlertLevel(row={}){
        const level=String(row.alert_level||"").toUpperCase();
        return ["HIGH","MEDIUM","LOW"].includes(level) ? level : deriveAlertLevel(row);
    }

    function setText(id, value){const el=document.getElementById(id); if(el) el.textContent=value;}
    function num(value, fallback=0){
        if(typeof value==="string"){
            const cleaned=value.replace(/[%+,，\s]/g,"");
            const parsed=Number(cleaned);
            if(Number.isFinite(parsed)) return parsed;
        }
        const n=Number(value); return Number.isFinite(n)?n:fallback;
    }
    function pct(value){const n=num(value); return `${n>0?"+":""}${n.toFixed(2)}%`;}
    function price(value){return num(value).toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2});}
    function priceOrEmpty(value){return value==null || value==="" ? "--" : price(value);}
    // Chart.js tooltip 的开盘/收盘说明集中封装，保证日线图和实时图的悬浮提示口径一致。
    function chartTooltipOptions(rows=[], {openKey="open_price", closeKey="last_price", fallbackOpen=null, preferFallbackOpen=false, showOpenCloseExtra=true}={}){
        return {
            callbacks:{
                afterBody(items){
                    if(!showOpenCloseExtra) return [];
                    const item=items?.[0];
                    if(!item || item.dataIndex==null) return [];
                    const row=rows[item.dataIndex];
                    if(!row) return [];
                    const openValue=preferFallbackOpen && fallbackOpen!=null ? fallbackOpen : (row[openKey] ?? row.open ?? row.open_price ?? fallbackOpen);
                    const closeValue=row[closeKey] ?? row.close ?? row.last_price ?? row.avg_price;
                    return [
                        `开盘价：${priceOrEmpty(openValue)}`,
                        `收盘/最新价：${priceOrEmpty(closeValue)}`
                    ];
                }
            }
        };
    }
    function cls(value){const n=num(value); return n>0?"g":n<0?"r":"a";}
    function esc(value){return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]));}
    function pill(signal){return signal==="UP"?"pill pill-g":signal==="DOWN"?"pill pill-r":"pill pill-a";}
    function signalTag(signal){
        const value=(signal||"WATCH").toUpperCase();
        const clsName=value==="UP"?"signal-up":value==="DOWN"?"signal-down":value==="WATCH"?"signal-watch":"signal-none";
        const icon=value==="UP"?"▲":value==="DOWN"?"▼":value==="WATCH"?"—":"?";
        return `<span class="signal-tag ${clsName}">${icon} ${esc(value==="WATCH"?"WATCH":value)}</span>`;
    }
    function isFlatWatch(row){return (row?.predicted_signal||"WATCH")==="WATCH" && Math.abs(num(row?.predicted_gap))<=0.02 && num(row?.confidence)>=.95;}
    function predictionState(row){
        const signal=row?.predicted_signal||"WATCH", c=Math.round(num(row?.confidence)*100);
        if(isFlatWatch(row)) return {text:"低波动", cls:"a"};
        if(!c) return {text:"--", cls:"muted"};
        return {text:`${c}%`, cls:c>=70?"g":c>=55?"a":"r"};
    }
    function statusClass(status){return status==="OK"||status==="FLOWING"||status==="LIVE"?"st-ok":status==="DELAYED"||status==="REPLAY"?"st-w":"st-e";}
    function setChartState(title="", text="", show=false){
        const box=document.getElementById("chartState");
        if(!box) return;
        setText("chartStateTitle", title);
        setText("chartStateText", text);
        box.classList.toggle("show", Boolean(show));
    }
    function updateChartModeHint(detail=""){
        const base=chartMode==="realtime" ? "分钟线接口 · 实时入库行情" : "日线接口 · 历史走势 + T+3";
        setText("chartModeHint", detail ? `${base} · ${detail}` : base);
    }
    function updateClock(){const d=new Date(); const pad=n=>String(n).padStart(2,"0"); setText("clock", `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}  ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`);}
    // 首页只展示一个“模型验证状态”，优先使用被选中的最佳模型和 walk-forward/balanced 指标。
    function modelQualityMetric(rows=[]){
        const selected=rows.find(r=>r.model_name==="selection" && r.metric_name==="best_model_code");
        const selectedName={1:"random_forest",2:"lightgbm",3:"lstm"}[Math.round(num(selected?.metric_value))];
        if(selectedName){
            for(const metric of ["walk_forward_balanced_direction_accuracy","balanced_direction_accuracy","direction_macro_f1","direction_accuracy"]){
                const row=rows.find(r=>r.model_name===selectedName && r.metric_name===metric);
                if(row) return row;
            }
        }
        for(const metric of ["balanced_direction_accuracy","direction_macro_f1","direction_accuracy"]){
            const items=rows.filter(r=>r.metric_name===metric);
            if(items.length) return items.reduce((a,b)=>num(b.metric_value)>num(a.metric_value)?b:a,items[0]);
        }
        return null;
    }
    function metricFor(rows=[], modelName="", metricName=""){return window.StockShared?.metricFor ? StockShared.metricFor(rows, modelName, metricName) : rows.find(r=>r.model_name===modelName&&r.metric_name===metricName);}
    function modelBenchmark(rows=[], row=null){
        if(window.StockShared?.modelBenchmark) return StockShared.modelBenchmark(rows,row);
        if(!row) return null;
        const metric=String(row.metric_name||"");
        if(metric.includes("balanced_direction_accuracy")){
            return {value:1/3,label:"随机三分类基线",kind:"balanced"};
        }
        if(metric.includes("direction_macro_f1")){
            return {value:1/3,label:"随机宏 F1 参考",kind:"macro"};
        }
        const baselineMetric=metric.startsWith("walk_forward_")?"walk_forward_majority_baseline_accuracy":"majority_baseline_accuracy";
        const baseline=metricFor(rows,row.model_name,baselineMetric);
        return baseline?{value:num(baseline.metric_value),label:"多数类基线",kind:"accuracy"}:null;
    }
    function metricLabel(metricName){
        if(window.StockShared?.metricLabel) return StockShared.metricLabel(metricName);
        return metricName==="walk_forward_balanced_direction_accuracy"?"walk-forward balanced":metricName==="balanced_direction_accuracy"?"balanced accuracy":metricName==="direction_macro_f1"?"macro F1":metricName==="direction_accuracy"?"direction accuracy":metricName||"metric";
    }
    function dailyFreshnessMessage(freshness={}){
        const status=String(freshness.status||"OK").toUpperCase();
        const stockDate=freshness.stock_latest_trade_date||"--";
        const indexDate=freshness.index_latest_trade_date||"--";
        const stockAge=Number.isFinite(Number(freshness.stock_age_days))?`${freshness.stock_age_days}天`:"未知";
        const indexAge=Number.isFinite(Number(freshness.index_age_days))?`${freshness.index_age_days}天`:"未知";
        return {
            stale: status==="STALE" || status==="MISSING",
            status,
            detail:`日线 ${stockDate}(${stockAge})，指数 ${indexDate}(${indexAge})`
        };
    }
    function isModelMetricAbnormal(row, rows=[]){
        if(!row) return false;
        const acc=num(row.metric_value);
        const baseline=num(metricFor(rows,row.model_name,"majority_baseline_accuracy")?.metric_value);
        const flat=num(metricFor(rows,row.model_name,"validation_flat_ratio")?.metric_value);
        return row.status==="abnormal" || (acc>.95 && baseline>.8) || baseline>.85 || flat>.9;
    }
    function market(data, name){return (data.market_overview||[]).find(r=>r.market===name)||{};}
    function calcScores(data){
        const s=data.summary||{}, stream=data.stream_status||{}, model=modelQualityMetric(data.model_comparison||[]);
        const accRows=(data.model_comparison||[]).filter(r=>r.metric_name==="direction_accuracy");
        const modelLooksSkewed=accRows.length>1 && accRows.every(r=>num(r.metric_value)>=.995 || r.status==="abnormal");
        const trend=Math.min(100,Math.round(Math.abs(num(s.avg_change_pct))*14+52));
        const fund=Math.min(100,Math.round(num(stream.events_last_minute)/7));
        const technical=model?Math.min(modelLooksSkewed?70:100,Math.round(num(model.metric_value)*100)):0;
        const risk=Math.min(100,Math.round(Math.log10(num(s.alert_count)+1)*28));
        const overall=Math.round(trend*.25+fund*.2+technical*.35+(100-risk)*.2);
        return {trend,fund,technical,risk,overall};
    }
    function setBar(id, value){const el=document.getElementById(id); if(el) el.style.width=`${Math.max(0,Math.min(100,value))}%`;}
    function renderKpis(data){
        const s=data.summary||{}, model=modelQualityMetric(data.model_comparison||[]);
        const sh=market(data,"SH").avg_change_pct ?? s.avg_change_pct;
        const hk=market(data,"HK").avg_change_pct ?? 0;
        [["sh",3287.64,sh],["hk",22418.55,hk]].forEach(([prefix,base,change])=>{
            setText(`${prefix}Index`, price(base*(1+num(change)/100)));
            const el=document.getElementById(`${prefix}Delta`);
            if(el){el.textContent=`${num(change)>=0?"▲":"▼"} ${pct(change)}`; el.className=`kpi-meta ${cls(change)}`;}
        });
        setText("stockCountKpi", num(s.symbol_count).toLocaleString("zh-CN"));
        setText("stockSourceMeta", `SH/SZ/HK · ${num((data.stream_status||{}).source_count).toLocaleString("zh-CN")} 个数据源`);
        const freshness=dailyFreshnessMessage(data.daily_data_freshness||{});
        const modelAbnormal=isModelMetricAbnormal(model,data.model_comparison||[]);
        const modelPct=model?Math.max(0,Math.min(100,num(model.metric_value)*100)):0;
        const benchmark=modelBenchmark(data.model_comparison||[],model);
        const baselinePct=benchmark?benchmark.value*100:null;
        const lift=baselinePct==null?null:modelPct-baselinePct;
        const progress=document.getElementById("modelProgressFill");
        const note=document.getElementById("modelBaselineNote");
        if(freshness.stale){
            setText("modelAccuracy","数据过期");
            setText("modelMeta",freshness.detail);
            setText("modelMetricName","训练数据新鲜度");
            setText("modelBaselineText",`状态 ${freshness.status}`);
            if(progress) progress.style.width="0%";
            if(note){
                note.textContent="请先更新 daily_stock_bars / daily_index_bars 后再重新训练。";
                note.className="baseline-note baseline-bad";
            }
        }else{
            setText("modelAccuracy", model?`${modelPct.toFixed(1)}%`:"--");
            setText("modelMeta", model?(modelAbnormal?"样本偏态，谨慎参考":`${model.model_name} / ${model.model_version}`):"暂无模型指标");
            setText("modelMetricName", model?`${model.model_name} ${metricLabel(model.metric_name)}`:"balanced accuracy");
            setText("modelBaselineText", baselinePct==null?"参考 --":`${benchmark.label} ${baselinePct.toFixed(1)}% · 相对 ${lift>=0?"+":""}${lift.toFixed(1)}pt`);
            if(progress) progress.style.width=`${modelPct.toFixed(0)}%`;
            if(note){
            if(!model || baselinePct==null){
                note.textContent="等待模型指标";
                note.className="baseline-note baseline-neutral";
            }else if(modelPct < baselinePct){
                note.textContent=`低于${benchmark.label} ↓ ${(baselinePct-modelPct).toFixed(1)} 个百分点`;
                note.className="baseline-note baseline-bad";
            }else{
                note.textContent=`高于${benchmark.label} ↑ ${(modelPct-baselinePct).toFixed(1)} 个百分点`;
                note.className="baseline-note baseline-good";
            }
            }
        }
        setText("eventsMinute", num((data.stream_status||{}).events_last_minute).toLocaleString("zh-CN"));
        setText("alertCount", num(s.alert_count).toLocaleString("zh-CN"));
        setText("symbolCount", num(s.symbol_count).toLocaleString("zh-CN"));
        setText("sourceCount", num(s.source_count).toLocaleString("zh-CN"));
    }
    function pickMain(data){return (data.ml_predictions||[])[0] || (data.focus_stocks||[])[0] || (data.latest_ticks||[])[0] || {};}
    function parseTrendTime(value){
        const date=new Date(String(value||"").replace(" ","T"));
        return Number.isNaN(date.getTime()) ? null : date;
    }
    function shortFutureLabels(rows=[], n=6){
        const times=rows.map(r=>parseTrendTime(r.event_time||r.window_bucket)).filter(Boolean);
        const last=times.length ? times[times.length-1] : new Date();
        const prev=times.length>1 ? times[times.length-2] : null;
        const step=prev ? Math.max(60_000, Math.min(30*60_000, last.getTime()-prev.getTime())) : 5*60_000;
        const out=[];
        for(let i=1;i<=n;i++){
            const d=new Date(last.getTime()+step*i);
            out.push(`${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")} ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`);
        }
        return out;
    }
    function renderPriceChart(data, trend=[], main={}){
        setChartState("", "", false);
        updateChartModeHint(trend.length ? `${trend.length} 个分钟点` : "");
        const sourceRows=trend.length ? trend : (main.symbol ? [] : (data.trend||[]));
        const rows=[...sourceRows].sort((a,b)=>String(a.event_time||a.window_bucket||"").localeCompare(String(b.event_time||b.window_bucket||""))).slice(-24);
        const labels=rows.map(r=>String(r.event_time||r.window_bucket||"").slice(5,16));
        const actual=rows.map(r=>num(r.last_price ?? r.avg_price));
        const pred=(data.ml_predictions||[]).find(r=>r.symbol===main.symbol);
        const last=actual.length?actual[actual.length-1]:num(pred?.current_price);
        const target=pred?num(pred.predicted_next_price,last):last;
        const predSeries=actual.map(()=>null);
        if(predSeries.length) predSeries[predSeries.length-1]=last;
        const future=shortFutureLabels(rows,1);
        const futureVals=future.map(()=>target);
        const allLabels=labels.length?[...labels,...future]:["当前",...future];
        const allActual=actual.length?[...actual,...future.map(()=>null)]:[last,...future.map(()=>null)];
        const allPred=actual.length?[...predSeries,...futureVals]:[last,...futureVals];
        setText("chartTitle", `${main.company_name||""} ${main.symbol||""} · 分钟趋势与短期预测`.trim() || "分钟趋势与短期预测");
        const signal=pred?.predicted_signal||"WATCH";
        const mainSignal=document.getElementById("mainSignal");
        if(mainSignal){
            const state=predictionState(pred);
            mainSignal.textContent=`${textMap[signal]||signal} · ${state.text}`;
            mainSignal.className=pill(signal);
        }
        const config={type:"line",data:{labels:allLabels,datasets:[
            {label:"实际价格",data:allActual,borderColor:"#2563eb",backgroundColor:"rgba(37,99,235,.08)",borderWidth:2,pointRadius:2,tension:.35,fill:true},
            {label:"短期预测",data:allPred,borderColor:"#f59e0b",borderWidth:2,borderDash:[5,4],pointRadius:2,tension:.35}
        ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{legend:{display:false},tooltip:chartTooltipOptions(rows,{openKey:"open_price",closeKey:"last_price",fallbackOpen:main.open_price ?? main.open,preferFallbackOpen:true})},scales:{x:{grid:{color:"#f1efe8"},ticks:{color:"#888780",font:{size:10}}},y:{grid:{color:"#f1efe8"},ticks:{color:"#888780",font:{size:10}}}}}};
        const ctx=document.getElementById("priceChart").getContext("2d");
        if(priceChart){priceChart.data=config.data; priceChart.options=config.options; priceChart.update();} else priceChart=new Chart(ctx,config);
    }
    function renderPredictionOnlyChart(data={}, main={}, reason="日线数据缺失，显示AI预测"){
        setChartState("预测展示", reason, true);
        updateChartModeHint("仅模型预测");
        const pred=(data.ml_predictions||[]).find(r=>r.symbol===main.symbol) || main || {};
        const last=num(pred.current_price ?? pred.last_price ?? pred.close ?? pred.predicted_next_price);
        const target=num(pred.predicted_next_price ?? pred.target_price ?? last, last);
        const signal=pred.predicted_signal||main.predicted_signal||"WATCH";
        setText("chartTitle", `${main.company_name||pred.company_name||""} ${main.symbol||pred.symbol||""} · ${reason}`.trim());
        setText("refreshStatus", reason);
        const mainSignal=document.getElementById("mainSignal");
        if(mainSignal){
            const state=predictionState(pred);
            mainSignal.textContent=`${textMap[signal]||signal} · ${state.text}`;
            mainSignal.className=pill(signal);
        }
        const config={type:"line",data:{labels:["当前","T+3预测"],datasets:[
            {label:"当前价格",data:[last,null],borderColor:"#2563eb",backgroundColor:"rgba(37,99,235,.08)",borderWidth:2,pointRadius:3,tension:.2,fill:true},
            {label:"AI预测",data:[last,target],borderColor:"#f59e0b",borderWidth:2,borderDash:[5,4],pointRadius:3,tension:.2}
        ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{color:"#f1efe8"},ticks:{color:"#888780",font:{size:10}}},y:{grid:{color:"#f1efe8"},ticks:{color:"#888780",font:{size:10}}}}}};
        const ctx=document.getElementById("priceChart").getContext("2d");
        if(priceChart){priceChart.data=config.data; priceChart.options=config.options; priceChart.update();} else priceChart=new Chart(ctx,config);
    }
    function renderDailyPriceChart(dailyData={}, main={}){
        setChartState("", "", false);
        const history=[...(dailyData.daily||[])].sort((a,b)=>String(a.trade_date||"").localeCompare(String(b.trade_date||""))).slice(-60);
        const pred=dailyData.prediction||{};
        const labels=history.map(r=>String(r.trade_date||"").slice(5));
        const open=history.map(r=>num(r.open));
        const close=history.map(r=>num(r.close));
        const last=close.length?close[close.length-1]:num(pred.predicted_next_price);
        const predPrice=pred.predicted_next_price==null?null:num(pred.predicted_next_price,last);
        const allLabels=labels.length?[...labels,"预测"]:["当前","预测"];
        const openData=labels.length?[...open,null]:[num(main.open_price ?? main.open ?? last),null];
        const closeData=labels.length?[...close,null]:[last,null];
        const predData=labels.length?[...Array(Math.max(labels.length-1,0)).fill(null),last,predPrice]:[last,predPrice];
        const sourceLabel=dailyData.daily_source==="price_ticks_aggregated"?"分钟线聚合日线":"日线历史";
        updateChartModeHint(`${sourceLabel} · ${history.length} 天`);
        setText("chartTitle", `${main.company_name||""} ${main.symbol||dailyData.symbol||""} · ${sourceLabel}与AI预测`.trim() || "日线收盘价与AI预测");
        setText("refreshStatus", sourceLabel);
        const signal=pred.predicted_signal||main.predicted_signal||"WATCH";
        const mainSignal=document.getElementById("mainSignal");
        if(mainSignal){
            const state=predictionState(pred.predicted_signal?pred:main);
            mainSignal.textContent=`${textMap[signal]||signal} · ${state.text}`;
            mainSignal.className=pill(signal);
        }
        const config={type:"line",data:{labels:allLabels,datasets:[
            {label:"日线开盘价",data:openData,borderColor:"#0f766e",backgroundColor:"rgba(15,118,110,.06)",borderWidth:2,pointRadius:2,tension:.25,fill:false},
            {label:"日线收盘价",data:closeData,borderColor:"#2563eb",backgroundColor:"rgba(37,99,235,.08)",borderWidth:2,pointRadius:2,tension:.25,fill:true},
            {label:"AI预测",data:predData,borderColor:"#f59e0b",borderWidth:2,borderDash:[5,4],pointRadius:3,tension:.2}
        ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{legend:{display:false},tooltip:chartTooltipOptions(history,{openKey:"open",closeKey:"close",showOpenCloseExtra:false})},scales:{x:{grid:{color:"#f1efe8"},ticks:{color:"#888780",font:{size:10},maxRotation:45,minRotation:0}},y:{grid:{color:"#f1efe8"},ticks:{color:"#888780",font:{size:10}}}}}};
        const ctx=document.getElementById("priceChart").getContext("2d");
        if(priceChart){priceChart.data=config.data; priceChart.options=config.options; priceChart.update();} else priceChart=new Chart(ctx,config);
    }
    function renderEmptyRealtimeChart(main={}, message="暂无分钟级实时数据"){
        setText("chartTitle", `${main.company_name||""} ${main.symbol||""} · ${message}`.trim() || message);
        setText("refreshStatus", "暂无实时数据");
        updateChartModeHint("无分钟点");
        setChartState("暂无分钟级实时数据", "当前股票没有实时入库点，可切换到“日线+预测”查看历史走势和模型预测。", true);
        const ctx=document.getElementById("priceChart").getContext("2d");
        const config={type:"line",data:{labels:[],datasets:[
            {label:"实际价格",data:[],borderColor:"#2563eb",backgroundColor:"rgba(37,99,235,.08)",borderWidth:2,pointRadius:2,tension:.35,fill:true},
            {label:"短期预测",data:[],borderColor:"#f59e0b",borderWidth:2,borderDash:[5,4],pointRadius:2,tension:.35}
        ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{color:"#f1efe8"},ticks:{color:"#888780",font:{size:10}}},y:{grid:{color:"#f1efe8"},ticks:{color:"#888780",font:{size:10}}}}}};
        if(priceChart){priceChart.data=config.data; priceChart.options=config.options; priceChart.update();} else priceChart=new Chart(ctx,config);
    }
    function updateChartModeButtons(){
        document.getElementById("btnRealtime")?.classList.toggle("active",chartMode==="realtime");
        document.getElementById("btnDaily")?.classList.toggle("active",chartMode==="daily");
    }
    // 主图根据模式在“日线+AI 预测”和“分钟级实时走势”之间切换，缺数据时给出明确空状态。
    async function renderSelectedChart(data, main={}){
        if(!main.symbol){
            renderPriceChart(data,[],main);
            return;
        }
        if(chartMode==="daily"){
            const daily=await api(`/stocks/${encodeURIComponent(main.symbol)}/daily?days=120`).catch(()=>null);
            if(daily && (daily.daily||[]).length){
                renderDailyPriceChart(daily,main);
                return;
            }
            renderPredictionOnlyChart(data, main, "暂无日线历史，显示AI预测");
            return;
        }
        const trend=await api(`/stocks/${encodeURIComponent(main.symbol)}/trend?minutes=1440`).catch(()=>[]);
        if(!(trend||[]).length){
            renderEmptyRealtimeChart(main);
            return;
        }
        renderPriceChart(data,trend,main);
    }
    async function switchChartMode(mode){
        chartMode=mode==="realtime"?"realtime":"daily";
        updateChartModeButtons();
        const data=window.latestDashboard||{};
        const main=window.mainStock||pickMain(data);
        await renderSelectedChart(data,main);
    }
    function renderFlow(data){
        const rows=[...(data.trend||[])].sort((a,b)=>String(a.window_bucket||"").localeCompare(String(b.window_bucket||""))).slice(-12);
        const labels=rows.map(r=>String(r.window_bucket||"").slice(11,16));
        const values=rows.map(r=>num(r.symbol_count));
        const config={type:"bar",data:{labels,datasets:[{data:values,backgroundColor:"#16a34a",borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:"#888780",font:{size:10}}},y:{title:{display:true,text:"条/分钟",color:"#888780",font:{size:10}},grid:{color:"#f1efe8"},ticks:{color:"#888780",font:{size:10}}}}}};
        const ctx=document.getElementById("flowChart").getContext("2d");
        if(flowChart){flowChart.data=config.data; flowChart.update();} else flowChart=new Chart(ctx,config);
    }
    // 首页只展示告警摘要和处理入口，完整统计图与筛选逻辑放在风险告警子页面。
    function renderAlerts(rows=[]){
        const box=document.getElementById("alertList");
        const levels=rows.reduce((acc,row)=>{acc[normalizeAlertLevel(row)]++; return acc;},{HIGH:0,MEDIUM:0,LOW:0});
        const byCategory=rows.reduce((acc,row)=>{
            const type=row.alert_type==="volume_spike"?"volume":row.alert_type==="model_drift"||row.alert_type==="model_signal"?"model":"price";
            acc[type]++;
            return acc;
        },{price:0,volume:0,model:0});
        const high=levels.HIGH;
        setText("highRiskCount", `${high} 高危`);
        const tabs=document.getElementById("homeAlertTabs");
        if(tabs){
            const items=[
                ["all",`全部(${rows.length})`],
                ["HIGH",`高危(${levels.HIGH})`],
                ["MEDIUM",`中危(${levels.MEDIUM})`],
                ["LOW",`低危(${levels.LOW})`],
                ["price",`价格(${byCategory.price})`],
                ["volume",`成交量(${byCategory.volume})`],
                ["model",`模型(${byCategory.model})`]
            ];
            tabs.innerHTML=items.map(([key,label])=>`<button type="button" class="${homeAlertFilter===key?"active":""}" data-home-alert-filter="${key}">${label}</button>`).join("");
        }
        box.innerHTML="";
        const filtered=rows.filter(row=>{
            const level=normalizeAlertLevel(row);
            const category=row.alert_type==="volume_spike"?"volume":row.alert_type==="model_drift"||row.alert_type==="model_signal"?"model":"price";
            return homeAlertFilter==="all" || homeAlertFilter===level || homeAlertFilter===category;
        });
        if(!filtered.length){box.innerHTML='<div class="empty">当前筛选条件下暂无风险告警</div>'; return;}
        filtered.slice(0,6).forEach((r,i)=>{
            const level=normalizeAlertLevel(r), type=level==="HIGH"?"high":level==="MEDIUM"?"med":"low";
            const icon=level==="HIGH"?"H":level==="MEDIUM"?"M":"L";
            const names=alertTitles[level]||alertTitles.LOW;
            const status=r.action_status||"OPEN";
            const el=document.createElement("article");
            el.className=`al al-${type}${status==="IGNORED"?" is-ignored":""}`;
            el.innerHTML=`<div class="al-icon al-icon-${type[0]}">${icon}</div><div class="al-body"><div class="al-title">${esc(names[i%names.length])} · ${esc(r.symbol)}</div><div class="al-sub">${esc(r.company_name)}，${textMap[r.alert_type]||r.alert_type||"异常"}，涨跌幅 ${pct(r.change_pct)}</div><div class="al-time mono">${esc(r.event_time||r.created_at||"")}</div>${r.id?`<div class="al-actions"><button type="button" data-alert-id="${esc(r.id)}" data-alert-status="ACKED" ${status==="ACKED"?"disabled":""}>确认</button><button type="button" data-alert-id="${esc(r.id)}" data-alert-status="IGNORED" ${status==="IGNORED"?"disabled":""}>忽略</button><button type="button" data-alert-id="${esc(r.id)}" data-alert-status="RESOLVED" ${status==="RESOLVED"?"disabled":""}>解决</button></div>`:""}</div>`;
            box.appendChild(el);
        });
    }
    function renderHeat(rows=[]){
        const box=document.getElementById("heatmap");
        box.innerHTML="";
        if(!rows.length){box.innerHTML='<div class="empty">暂无行业数据</div>'; return;}
        rows.slice(0,9).forEach(r=>{
            const c=num(r.avg_change_pct);
            const level=c>2?"s5":c>.5?"s4":c< -2?"s1":c<-.5?"s2":"s3";
            const el=document.createElement("div");
            el.className=`hcell hc-${level}`;
            el.innerHTML=`<div class="hcell-name">${esc(r.sector||r.category||r.market||"未知")}</div><div class="hcell-val mono">${pct(c)}</div>`;
            box.appendChild(el);
        });
    }
    function renderPredictions(rows=[]){
        const body=document.getElementById("predictionBody");
        body.innerHTML="";
        if(!rows.length){body.innerHTML='<tr><td colspan="3">暂无预测</td></tr>'; return;}
        rows.slice(0,6).forEach(r=>{
            const signal=r.predicted_signal||"WATCH", state=predictionState(r);
            const tr=document.createElement("tr");
            tr.innerHTML=`<td>${esc(r.symbol)}<br><span class="muted">${esc(r.company_name||"")}</span></td><td>${signalTag(signal)}</td><td class="${state.cls}">${state.text}</td>`;
            body.appendChild(tr);
        });
        if(rows.length>3 && rows.every(isFlatWatch)){
            const tr=document.createElement("tr");
            tr.innerHTML='<td colspan="3" class="a">当前预测集中在观望，说明样本波动较低或模型输出过于单一。</td>';
            body.appendChild(tr);
        }
    }
    function renderScore(data){
        const s=calcScores(data);
        setText("aiScore", s.overall); setText("trendScore",s.trend); setText("fundScore",s.fund); setText("technicalScore",s.technical); setText("riskScore",s.risk);
        setBar("trendBar",s.trend); setBar("fundBar",s.fund); setBar("technicalBar",s.technical); setBar("riskBar",s.risk);
        const ring=document.getElementById("scoreRing"); if(ring) ring.style.strokeDashoffset=String(188-188*s.overall/100);
        const model=modelQualityMetric(data.model_comparison||[]); setText("scoreModel",model?model.model_name:"Ensemble");
    }
    // 模型卡片展示平衡准确率、宏 F1、收益误差等指标，并对接近基线的指标做显式弱化。
    function renderModels(rows=[]){
        const box=document.getElementById("modelBars");
        const data=rows.filter(r=>r.metric_name==="balanced_direction_accuracy").slice(0,6);
        const fallbackData=rows.filter(r=>r.metric_name==="direction_accuracy").slice(0,6);
        const maeRows=rows.filter(r=>r.metric_name==="return_mae").slice(0,3);
        const qualityRows=rows.filter(r=>["direction_macro_f1","balanced_direction_accuracy","majority_baseline_accuracy"].includes(r.metric_name)).slice(0,3);
        box.innerHTML="";
        const barRows=data.length?data:fallbackData;
        if(!barRows.length){box.innerHTML='<div class="empty">暂无模型指标</div>'; return;}
        barRows.forEach((r,i)=>{
            const val=Math.min(100,Math.max(0,Math.round(num(r.metric_value)*100)));
            const color=["#16a34a","#2563eb","#f59e0b","#dc2626"][i%4];
            const abnormal=isModelMetricAbnormal(r,rows);
            const el=document.createElement("div");
            el.className="model-bar-row";
            const label=r.metric_name==="balanced_direction_accuracy"?"平衡":r.metric_name==="direction_macro_f1"?"F1":"方向";
            el.innerHTML=`<div class="model-label">${esc(r.model_name)} ${label}</div><div class="model-track"><div class="model-fill" style="width:${val}%;background:${color};opacity:${abnormal ? .45 : 1}"></div></div><div class="model-val mono">${val}%${abnormal?"*":""}</div>`;
            box.appendChild(el);
        });
        if(maeRows.length || qualityRows.length){
            const metrics=document.createElement("div");
            metrics.className="model-metrics";
            const tiles=qualityRows.length ? qualityRows : maeRows;
            const names={direction_macro_f1:"宏平均 F1",balanced_direction_accuracy:"平衡准确率",majority_baseline_accuracy:"多数类基线",return_mae:"收益率误差"};
            metrics.innerHTML=tiles.map(r=>{
                const isRate=r.metric_name!=="return_mae";
                const value=isRate?`${Math.round(num(r.metric_value)*100)}%`:num(r.metric_value).toFixed(4);
                return `<div class="model-metric"><div class="model-metric-name">${esc(r.model_name)} ${esc(names[r.metric_name]||r.metric_name)}</div><div class="model-metric-val mono">${value}</div></div>`;
            }).join("");
            box.appendChild(metrics);
        }
        const suspicious=barRows.length>1 && barRows.every(r=>isModelMetricAbnormal(r,rows));
        if(suspicious){
            const note=document.createElement("div");
            note.className="model-note";
            note.textContent="* 当前验证指标偏弱或接近基线，模型已经生成预测，但验证效果还不足以作为强结论。建议增加历史日线样本后重新训练。";
            box.appendChild(note);
        }
    }
    function renderSystem(data){
        const health=data.system_health||{}, stream=data.stream_status||{};
        const items=[
            ["MySQL", health.database?.status||"UNKNOWN"],
            ["实时流", stream.stream_state||"STOPPED"],
            ["数据模式", stream.current_mode||"OFFLINE"],
            ["数据源", `${num(stream.source_count)} 个`],
            ["归档", health.storage?.output?.status||"UNKNOWN"],
            ["Checkpoint", health.storage?.checkpoint?.status||"UNKNOWN"]
        ];
        const box=document.getElementById("systemGrid");
        box.innerHTML=items.map(([k,v])=>`<div class="sys-chip"><span class="sys-name">${esc(k)}</span><span class="sys-st mono ${statusClass(v)}">${esc(textMap[v]||v)}</span></div>`).join("");
        setText("streamMode", textMap[stream.current_mode]||stream.current_mode||"离线");
        setText("streamState", stream.stream_state||"STOPPED");
        const dot=document.getElementById("liveDot"); if(dot) dot.style.background=stream.stream_state==="FLOWING"?"#22c55e":stream.stream_state==="DELAYED"?"#f59e0b":"#dc2626";
    }
    function renderTicks(rows=[]){
        const body=document.getElementById("tickBody");
        body.innerHTML="";
        if(!rows.length){body.innerHTML='<tr><td colspan="3">暂无行情</td></tr>'; return;}
        rows.slice(0,7).forEach(r=>{
            const tr=document.createElement("tr");
            tr.innerHTML=`<td>${esc(r.symbol)}<br><span class="muted">${esc(r.company_name||"")}</span></td><td class="${cls(r.change_pct)}">${pct(r.change_pct)}</td><td class="muted">${esc(r.source||"")}</td>`;
            body.appendChild(tr);
        });
    }
    const KNOWN_SYMBOL_NAMES={
        "000001":"Ping An Bank","000002":"Vanke A","000063":"ZTE","000100":"TCL Technology","000166":"Shenwan Hongyuan",
        "000333":"Midea Group","000338":"Weichai Power","000568":"Luzhou Laojiao","000651":"Gree Electric","000725":"BOE Technology",
        "000776":"GF Securities","000858":"Wuliangye","000895":"Shuanghui Development","000938":"Unisplendour","000977":"Inspur Information",
        "001979":"China Merchants Shekou","002027":"Focus Media","002050":"Sanhua Intelligent Controls","002129":"TCL Zhonghuan","002142":"Bank of Ningbo",
        "002230":"iFLYTEK","002271":"Oriental Yuhong","002304":"Yanghe Brewery","002352":"SF Holding","002371":"NAURA Technology",
        "002415":"Hikvision","002475":"Luxshare Precision","002493":"Rongsheng Petrochemical","002594":"BYD","002714":"Muyuan Foods",
        "002812":"Yunnan Energy New Material","300014":"EVE Energy","300015":"Aier Eye Hospital","300059":"East Money","300122":"Zhifei Biological",
        "300124":"Inovance Technology","300274":"Sungrow","300316":"Jingsheng Mechanical","300347":"Tigermed","300408":"Three-Circle Group",
        "300433":"Lens Technology","300498":"Wens Foodstuff","300750":"CATL","300759":"Pharmaron","300760":"Mindray Medical",
        "600000":"Shanghai Pudong Development Bank","600009":"Shanghai Airport","600015":"Hua Xia Bank","600016":"China Minsheng Bank","600028":"Sinopec",
        "600030":"CITIC Securities","600031":"Sany Heavy Industry","600036":"China Merchants Bank","600048":"Poly Developments","600050":"China Unicom",
        "600104":"SAIC Motor","600111":"China Northern Rare Earth","600150":"China CSSC","600196":"Fosun Pharma","600276":"Hengrui Medicine",
        "600309":"Wanhua Chemical","600346":"Hengli Petrochemical","600406":"NARI Technology","600438":"Tongwei","600519":"Kweichow Moutai",
        "600570":"Hundsun Technologies","600585":"Conch Cement","600690":"Haier Smart Home","600745":"Wingtech Technology","600760":"AVIC Shenyang Aircraft",
        "600809":"Shanxi Fenjiu","600887":"Yili Industrial","600900":"Yangtze Power","601012":"LONGi Green Energy","601088":"China Shenhua",
        "601166":"Industrial Bank","601288":"Agricultural Bank of China","601318":"Ping An Insurance","601328":"Bank of Communications","601398":"ICBC",
        "601601":"China Pacific Insurance","601628":"China Life Insurance","601668":"China State Construction","601688":"Huatai Securities","601766":"CRRC",
        "601818":"China Everbright Bank","601857":"PetroChina","601888":"China Tourism Duty Free","601899":"Zijin Mining","601919":"COSCO Shipping Holdings",
        "601988":"Bank of China","601989":"China Shipbuilding Industry","00700":"Tencent Holdings","09988":"Alibaba-SW","03690":"Meituan-W",
        "01810":"Xiaomi-W","00981":"SMIC","00941":"China Mobile","00005":"HSBC Holdings","00388":"Hong Kong Exchanges","02318":"Ping An Insurance-H","00883":"CNOOC"
    };
    function normalizeSymbol(value){
        return String(value||"").trim().toUpperCase();
    }
    function hasReadableCompanyName(row){
        const symbol=normalizeSymbol(row?.symbol);
        const name=String(row?.company_name||"").trim();
        return !!name && normalizeSymbol(name)!==symbol;
    }
    function displayCompanyName(row){
        if(hasReadableCompanyName(row)) return String(row.company_name).trim();
        return KNOWN_SYMBOL_NAMES[normalizeSymbol(row?.symbol)] || "";
    }
    function isDomesticStock(row){
        const symbol=normalizeSymbol(row?.symbol);
        const market=normalizeSymbol(row?.market);
        if(["SH","SZ","BJ","HK"].includes(market)) return true;
        if(/^\d{6}$/.test(symbol) || /^\d{5}$/.test(symbol)) return true;
        return false;
    }
    function stockLabel(row){
        const symbol=normalizeSymbol(row?.symbol);
        const name=displayCompanyName(row);
        const sourceHint=row?._stockSource==="ml_predictions" ? " · \u65e5\u7ebf\u9884\u6d4b" : "";
        return `${symbol}${name?` · ${name}`:""}${sourceHint}`.trim();
    }
    function stockRecordScore(row){
        return (row?._sourceRank||0) + (hasReadableCompanyName(row)?20:0);
    }
    function collectStocks(data){
        const map=new Map();
        [
            ["latest_ticks", data.latest_ticks||[], 50],
            ["focus_stocks", data.focus_stocks||[], 40],
            ["risk_stocks", data.risk_stocks||[], 35],
            ["optimal_stocks", data.optimal_stocks||[], 30],
            ["ml_predictions", data.ml_predictions||[], 10]
        ].forEach(([source, rows, rank])=>{
            rows.forEach(row=>{
                const symbol=normalizeSymbol(row?.symbol);
                if(!symbol) return;
                const enriched={...row, symbol, _stockSource:source, _sourceRank:rank};
                if(!isDomesticStock(enriched)) return;
                const existing=map.get(symbol);
                if(!existing || stockRecordScore(enriched)>stockRecordScore(existing)){
                    map.set(symbol, enriched);
                }else if(!hasReadableCompanyName(existing) && hasReadableCompanyName(enriched)){
                    map.set(symbol, {...existing, company_name:enriched.company_name});
                }
            });
        });
        return Array.from(map.values()).slice(0,100);
    }
    function findKnownStock(data, symbol){
        const normalized=String(symbol||"").trim().toUpperCase();
        return collectStocks(data).find(row=>String(row.symbol||"").toUpperCase()===normalized) || null;
    }
    function renderStockSelect(data, selectedSymbol=""){
        const select=document.getElementById("stockSelect");
        if(!select) return;
        const stocks=collectStocks(data);
        select.innerHTML='<option value="">选择股票</option>';
        stocks.forEach(row=>{
            const option=document.createElement("option");
            option.value=row.symbol;
            option.textContent=stockLabel(row);
            if(row.symbol===selectedSymbol) option.selected=true;
            select.appendChild(option);
        });
    }
    async function switchMainStock(symbol){
        const normalized=String(symbol||"").trim().toUpperCase();
        if(!normalized) return;
        const data=window.latestDashboard||{};
        const stock=await api(`/stocks/${encodeURIComponent(normalized)}`).catch(()=>null);
        const fallbackStock=findKnownStock(data, normalized);
        const targetStock=stock?.stock || fallbackStock || {symbol:normalized, company_name:normalized};
        const daily=await api(`/stocks/${encodeURIComponent(normalized)}/daily?days=120`).catch(()=>null);
        if(stock?.stock || (daily && ((daily.daily||[]).length || daily.prediction)) || fallbackStock){
            selectedSymbol=targetStock.symbol || normalized;
            window.mainStock=targetStock;
            await renderSelectedChart(data,targetStock);
            renderStockSelect(data,targetStock.symbol);
            const manual=document.getElementById("chartStockInput");
            if(manual) manual.value="";
        } else {
            alert(`未找到股票 ${normalized} 的实时或日线数据`);
        }
    }
    function buildPrompt(){
        const data=window.latestDashboard||{}, s=data.summary||{};
        const picks=(data.ml_predictions||[]).slice(0,5).map(r=>`${r.symbol} ${r.company_name} 方向${textMap[r.predicted_signal]||r.predicted_signal} 状态${predictionState(r).text}`).join("\\n");
        return `请基于股票实时流分析平台数据生成课堂答辩用分析：监控股票${s.symbol_count||0}只，平均涨跌幅${pct(s.avg_change_pct)}，近30分钟告警${s.alert_count||0}条。模型预测如下：\\n${picks||"暂无预测"}\\n请输出市场结论、重点关注股票、风险提示和模型局限。`;
    }
    async function openAiPrompt(text){
        const prompt=text||buildPrompt();
        try{await navigator.clipboard.writeText(prompt); alert("分析提示词已复制，即将打开 ChatGPT。");}catch{alert(prompt);}
        window.open("https://chatgpt.com/","_blank");
    }
    function openAiPanel(){
        document.getElementById("aiPanel")?.classList.add("open");
        setTimeout(()=>document.getElementById("aiInput")?.focus(), 50);
    }
    function sanitizeHtml(html){
        const template=document.createElement("template");
        template.innerHTML=html;
        template.content.querySelectorAll("script,style,iframe,object,embed").forEach(node=>node.remove());
        template.content.querySelectorAll("*").forEach(node=>{
            [...node.attributes].forEach(attr=>{
                const name=attr.name.toLowerCase();
                const value=String(attr.value||"").trim().toLowerCase();
                if(name.startsWith("on") || value.startsWith("javascript:")) node.removeAttribute(attr.name);
            });
            if(node.tagName==="A"){
                node.setAttribute("target","_blank");
                node.setAttribute("rel","noopener noreferrer");
            }
        });
        return template.innerHTML;
    }
    // AI 消息支持 Markdown，但渲染前必须复用 shared-ui 的清洗逻辑，避免把后端 HTML 直接写入页面。
    function renderMarkdown(text){
        if(window.StockShared?.renderMarkdown) return StockShared.renderMarkdown(text);
        const source=String(text||"");
        if(window.marked?.parse){
            marked.setOptions({breaks:true,gfm:true});
            return sanitizeHtml(marked.parse(source));
        }
        return esc(source).replace(/\n/g,"<br>");
    }
    function setAiMessageContent(item, text){
        if(!item) return;
        if(item.classList.contains("assistant")){
            item.innerHTML=renderMarkdown(text);
        }else{
            item.textContent=text;
        }
    }
    function addAiMessage(role, text){
        const box=document.getElementById("aiMessages");
        if(!box) return null;
        const item=document.createElement("div");
        item.className=`ai-msg ${role}`;
        setAiMessageContent(item,text);
        box.appendChild(item);
        box.scrollTop=box.scrollHeight;
        return item;
    }
    function normalizeStockText(value){
        return String(value||"")
            .toUpperCase()
            .replace(/[\s·.\-_()（）股份控股集团有限公司公司]/g,"")
            .replace(/W$/,"");
    }
    function inferSymbolFromQuestion(question){
        const text=String(question||"");
        const normalizedQuestion=normalizeStockText(text);
        const stocks=collectStocks(window.latestDashboard||{});
        const explicit=(text.match(/[A-Za-z]{2,6}[0-9]{0,4}|[0-9]{5,6}/g)||[])
            .map(item=>item.toUpperCase())
            .find(item=>stocks.some(stock=>String(stock.symbol||"").toUpperCase()===item));
        if(explicit) return explicit;
        const matched=stocks.find(stock=>{
            const symbol=String(stock.symbol||"").toUpperCase();
            const name=normalizeStockText(stock.company_name||"");
            return symbol && normalizedQuestion.includes(symbol)
                || name && (normalizedQuestion.includes(name) || name.includes(normalizedQuestion));
        });
        return matched?.symbol || "";
    }
    async function sendAiQuestion(question, mode="chat", symbol=""){
        const text=String(question||"").trim();
        if(!text) return;
        openAiPanel();
        addAiMessage("user", text);
        aiChatHistory.push({role:"user", content:text});
        aiChatHistory=aiChatHistory.slice(-30);
        const pending=addAiMessage("assistant", "");
        const btn=document.getElementById("aiSend");
        if(btn) btn.disabled=true;
        setText("aiModelStatus","正在读取系统数据并连接 DeepSeek...");
        let assistantText="";
        try{
            const res=await fetch(`${API_BASE}/ai/chat`,{
                method:"POST",
                headers:{"Content-Type":"application/json"},
                body:JSON.stringify({
                    messages:aiChatHistory,
                    question:text,
                    mode,
                    symbol:symbol||inferSymbolFromQuestion(text),
                    stream:false
                })
            });
            if(!res.ok) throw new Error(`HTTP ${res.status}`);
            const contentType=res.headers.get("content-type")||"";
            if(res.body && contentType.includes("text/event-stream")){
                const reader=res.body.getReader();
                const decoder=new TextDecoder("utf-8");
                let buffer="";
                while(true){
                    const {value,done}=await reader.read();
                    if(done) break;
                    buffer+=decoder.decode(value,{stream:true});
                    const parts=buffer.split("\n\n");
                    buffer=parts.pop()||"";
                    for(const part of parts){
                        const line=part.split("\n").find(row=>row.startsWith("data:"));
                        if(!line) continue;
                        const data=line.slice(5).trim();
                        if(data==="[DONE]") continue;
                        const json=JSON.parse(data);
                        assistantText+=json.content||"";
                        if(pending){
                            setAiMessageContent(pending, assistantText || "正在生成...");
                            pending.scrollIntoView({block:"nearest"});
                        }
                    }
                }
                if(!assistantText && pending) setAiMessageContent(pending, "AI 暂无回复。");
                if(assistantText) aiChatHistory.push({role:"assistant", content:assistantText});
                setText("aiModelStatus","模型：deepseek-v4-flash · 流式对话");
            }else{
                const data=await res.json();
                assistantText=data.reply || "AI 暂无回复。";
                if(pending) setAiMessageContent(pending, assistantText);
                aiChatHistory.push({role:"assistant", content:assistantText});
                const webText=data.web_enabled ? " · 联网增强" : "";
                setText("aiModelStatus", data.warning ? `本地数据解读模式${webText}` : `模型：${data.model || "AI"}${webText}`);
            }
            aiChatHistory=aiChatHistory.slice(-30);
        }catch(err){
            if(pending) setAiMessageContent(pending, `AI 接口暂时不可用：${err.message}`);
            setText("aiModelStatus","接口连接失败");
        }finally{
            if(btn) btn.disabled=false;
        }
    }
    async function api(path){return window.StockShared?.requestJson ? StockShared.requestJson(path) : fetch(`${API_BASE}${path}`,{cache:"no-store"}).then(res=>{if(!res.ok) throw new Error(`HTTP ${res.status}`); return res.json();});}
    async function postApi(path,payload){return window.StockShared?.postJson ? StockShared.postJson(path,payload) : fetch(`${API_BASE}${path}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}).then(res=>{if(!res.ok) throw new Error(`HTTP ${res.status}`); return res.json();});}
    function currentChartSymbol(){
        return String(selectedSymbol || window.mainStock?.symbol || document.getElementById("stockSelect")?.value || document.getElementById("chartStockInput")?.value || "").trim().toUpperCase();
    }
    function historyPrice(value){
        const number=num(value);
        return Number.isFinite(number) ? number.toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2}) : "--";
    }
    // 股票历史记录属于首页主图能力：用户先选中一只股票，再查看该股票的历史行情表。
    function renderMainHistory(rows=[], symbol=""){
        const panel=document.getElementById("mainHistoryPanel");
        const body=document.getElementById("mainHistoryBody");
        if(!panel||!body) return;
        panel.hidden=false;
        setText("mainHistoryTitle", `${symbol||"股票"} 历史行情记录`);
        setText("mainHistoryStatus", rows.length ? `最近 ${rows.length} 条股票行情数据` : "没有查询到历史行情");
        body.innerHTML=rows.length ? rows.map(row=>`
            <tr>
                <td>${esc(row.symbol||"")}<br><span class="muted">${esc(row.company_name||"")}</span></td>
                <td>${esc(row.event_time||"")}</td>
                <td>${historyPrice(row.last_price)}</td>
                <td class="${cls(row.change_pct)}">${pct(row.change_pct)}</td>
                <td>${num(row.volume).toLocaleString("zh-CN")}</td>
                <td>${esc(row.source||"")}</td>
            </tr>
        `).join("") : '<tr><td colspan="6" class="muted">暂无历史行情</td></tr>';
    }
    // 历史查询走 /api/history，范围固定为最近 1440 分钟，避免和告警数据导出混淆。
    async function loadMainHistory(){
        const symbol=currentChartSymbol();
        if(!symbol){alert("请先在图表区域选择或输入股票代码"); return;}
        setText("mainHistoryStatus","正在读取历史行情...");
        const historyPath=window.StockShared?.historyPath ? StockShared.historyPath({symbol,minutes:1440,limit:80}) : `/history?${new URLSearchParams({symbol,minutes:"1440",limit:"80"}).toString()}`;
        const rows=await api(historyPath);
        renderMainHistory(rows,symbol);
    }
    // CSV 导出只导出当前主图股票行情，不导出告警列表。
    function exportMainHistory(){
        const symbol=currentChartSymbol();
        if(!symbol){alert("请先在图表区域选择或输入股票代码"); return;}
        const exportUrl=window.StockShared?.historyExportUrl ? StockShared.historyExportUrl({symbol,minutes:1440,limit:1000}) : `${API_BASE}/history/export?${new URLSearchParams({symbol,minutes:"1440",limit:"1000"}).toString()}`;
        window.open(exportUrl,"_blank");
    }
    async function updateAlertAction(alertId,status,target){
        const item=target?.closest?.(".al");
        const originalText=target?.textContent||"";
        if(target){target.disabled=true; target.textContent="处理中";}
        try{
            if(status==="IGNORED" && item) item.classList.add("is-ignored");
            await postApi(`/alerts/${encodeURIComponent(alertId)}/status`,{status,note:`前端标记为 ${status}`,handled_by:"dashboard"});
            await safeRefresh();
        }catch(err){
            if(status==="IGNORED" && item) item.classList.remove("is-ignored");
            alert(`告警状态更新失败：${err.message}`);
        }finally{
            if(target){target.disabled=false; target.textContent=originalText;}
        }
    }
    // 首页刷新一次性拉取 /dashboard，再分发给各个渲染函数，减少多个模块各自请求造成的闪烁。
    async function refresh(){
        try{
            const data=await api("/dashboard");
            consecutiveRefreshErrors=0;
            const main=selectedSymbol ? ({symbol:selectedSymbol}) : pickMain(data);
            const detail=selectedSymbol ? await api(`/stocks/${encodeURIComponent(selectedSymbol)}`).catch(()=>null) : null;
            const chartStock=detail?.stock || main;
            window.latestDashboard=data; window.mainStock=chartStock;
            renderStockSelect(data,chartStock.symbol);
            renderKpis(data); await renderSelectedChart(data,chartStock); renderFlow(data); renderAlerts(data.latest_alerts||[]);
            renderHeat(data.sector_stats||data.sector_heat||data.category_heat||data.market_overview||[]); renderPredictions(data.ml_predictions||[]);
            renderScore(data); renderModels(data.model_comparison||[]); renderSystem(data); renderTicks(data.latest_ticks||[]);
            setText("refreshStatus", `已刷新 ${new Date().toLocaleTimeString("zh-CN",{hour12:false})}`);
        }catch(err){
            console.error(err);
            consecutiveRefreshErrors+=1;
            setText("refreshStatus",`刷新失败 ${consecutiveRefreshErrors}/3`);
            if(consecutiveRefreshErrors>=3){setText("streamMode","后端未连接"); setText("streamState","STOPPED");}
        }
    }
    // 定时刷新和用户操作可能同时触发，刷新锁用于防止并发请求覆盖较新的页面状态。
    async function safeRefresh(){
        if(isRefreshing) return;
        isRefreshing=true;
        try{await refresh();}finally{isRefreshing=false;}
    }
    document.getElementById("aiFab")?.addEventListener("click",()=>openAiPanel());
    document.getElementById("aiClose")?.addEventListener("click",()=>document.getElementById("aiPanel")?.classList.remove("open"));
    document.getElementById("aiForm")?.addEventListener("submit",(event)=>{
        event.preventDefault();
        const input=document.getElementById("aiInput");
        const question=input?.value||"";
        if(input) input.value="";
        sendAiQuestion(question);
    });
    document.querySelectorAll("[data-ai-question]").forEach(btn=>btn.addEventListener("click",()=>sendAiQuestion(btn.dataset.aiQuestion)));
    document.getElementById("reportBtn")?.addEventListener("click",()=>{
        const stock=window.mainStock||{};
        const symbol=stock.symbol||selectedSymbol||"";
        const name=stock.company_name||"";
        const target=symbol ? `${symbol}${name?` ${name}`:""}` : "当前图表股票";
        sendAiQuestion(`请生成 ${target} 的完整股票分析报告，包括行情表现、告警风险、模型预测，并基于数据给出系统建议。`,"report",symbol);
    });
    document.getElementById("aiExplainBtn")?.addEventListener("click",()=>sendAiQuestion(`请解读 ${window.mainStock?.symbol||"当前重点股票"} 的趋势、告警和模型预测。`,"symbol",window.mainStock?.symbol||""));
    document.getElementById("stockSelect")?.addEventListener("change",(event)=>switchMainStock(event.target.value));
    document.getElementById("chartQueryBtn")?.addEventListener("click",()=>switchMainStock(document.getElementById("chartStockInput")?.value));
    document.getElementById("btnRealtime")?.addEventListener("click",()=>switchChartMode("realtime"));
    document.getElementById("btnDaily")?.addEventListener("click",()=>switchChartMode("daily"));
    document.getElementById("mainHistoryBtn")?.addEventListener("click",()=>loadMainHistory().catch(err=>alert(`历史记录读取失败：${err.message}`)));
    document.getElementById("mainExportBtn")?.addEventListener("click",()=>exportMainHistory());
    document.getElementById("mainHistoryClose")?.addEventListener("click",()=>{
        const panel=document.getElementById("mainHistoryPanel");
        if(panel) panel.hidden=true;
    });
    document.getElementById("chartStockInput")?.addEventListener("keydown",(event)=>{
        if(event.key==="Enter") switchMainStock(event.target.value);
    });
    document.getElementById("queryBtn")?.addEventListener("click",async()=>{
        const symbol=document.getElementById("stockInput").value.trim();
        if(!symbol) return;
        switchMainStock(symbol);
    });
    document.getElementById("alertList")?.addEventListener("click",(event)=>{
        const target=event.target;
        if(!(target instanceof HTMLButtonElement)) return;
        const alertId=target.dataset.alertId;
        const status=target.dataset.alertStatus;
        if(alertId&&status) updateAlertAction(alertId,status,target).catch(console.error);
    });
    document.getElementById("homeAlertTabs")?.addEventListener("click",(event)=>{
        const target=event.target;
        if(!(target instanceof HTMLButtonElement)) return;
        if(!target.dataset.homeAlertFilter) return;
        homeAlertFilter=target.dataset.homeAlertFilter;
        renderAlerts(window.latestDashboard?.latest_alerts||[]);
    });
    updateChartModeButtons(); updateClock(); setInterval(updateClock,1000); safeRefresh(); setInterval(safeRefresh,5000);

