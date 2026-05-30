"""Daily-bar data quality report before ML training."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from python.ml.stock_ml import load_price_ticks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate daily stock data quality reports.")
    parser.add_argument("--source", default="akshare_cold_start", help="Price source to inspect.")
    parser.add_argument("--out-dir", default="reports/ml_data_quality", help="Output directory.")
    parser.add_argument("--min-rows", type=int, default=500, help="Warn when a symbol has fewer rows.")
    return parser.parse_args()


def quality_by_symbol(df: pd.DataFrame, min_rows: int) -> pd.DataFrame:
    frame = df.copy()
    frame["event_time"] = pd.to_datetime(frame["event_time"], errors="coerce")
    for column in ("open_price", "high_price", "low_price", "last_price", "volume", "turnover"):
        if column not in frame.columns:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    rows: list[dict[str, object]] = []
    for symbol, group in frame.sort_values("event_time").groupby("symbol", sort=False):
        price = group["last_price"]
        repeated = price.eq(price.shift()).sum()
        bad_ohlc = (
            (group["high_price"] < group["low_price"])
            | (group["last_price"] > group["high_price"])
            | (group["last_price"] < group["low_price"])
            | (group["open_price"] > group["high_price"])
            | (group["open_price"] < group["low_price"])
        ).sum()
        dates = group["event_time"].dropna().dt.normalize()
        max_gap_days = int(dates.diff().dt.days.max()) if len(dates) > 1 and pd.notna(dates.diff().dt.days.max()) else 0
        zero_volume = group["volume"].fillna(0).le(0).sum()
        missing_price = group[["open_price", "high_price", "low_price", "last_price"]].isna().any(axis=1).sum()
        rows.append(
            {
                "symbol": symbol,
                "company_name": group["company_name"].dropna().iloc[-1] if "company_name" in group and group["company_name"].notna().any() else "",
                "market": group["market"].dropna().iloc[-1] if "market" in group and group["market"].notna().any() else "",
                "rows": len(group),
                "start_time": dates.min().date().isoformat() if len(dates) else "",
                "end_time": dates.max().date().isoformat() if len(dates) else "",
                "max_gap_days": max_gap_days,
                "repeated_close_ratio": round(float(repeated / max(len(group), 1)), 4),
                "zero_volume_ratio": round(float(zero_volume / max(len(group), 1)), 4),
                "bad_ohlc_rows": int(bad_ohlc),
                "missing_price_rows": int(missing_price),
                "warning": "; ".join(
                    item
                    for item in [
                        "rows_too_few" if len(group) < min_rows else "",
                        "large_gap" if max_gap_days > 14 else "",
                        "bad_ohlc" if bad_ohlc > 0 else "",
                        "missing_price" if missing_price > 0 else "",
                        "many_repeated_close" if repeated / max(len(group), 1) > 0.25 else "",
                        "many_zero_volume" if zero_volume / max(len(group), 1) > 0.05 else "",
                    ]
                    if item
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(["warning", "rows"], ascending=[False, True])


def summary_report(symbol_report: pd.DataFrame) -> pd.DataFrame:
    total = len(symbol_report)
    warnings = symbol_report["warning"].astype(str).ne("").sum() if total else 0
    return pd.DataFrame(
        [
            {"metric": "symbol_count", "value": total},
            {"metric": "warning_symbol_count", "value": int(warnings)},
            {"metric": "min_rows", "value": int(symbol_report["rows"].min()) if total else 0},
            {"metric": "median_rows", "value": float(np.median(symbol_report["rows"])) if total else 0},
            {"metric": "max_rows", "value": int(symbol_report["rows"].max()) if total else 0},
            {"metric": "bad_ohlc_symbols", "value": int((symbol_report["bad_ohlc_rows"] > 0).sum()) if total else 0},
            {"metric": "missing_price_symbols", "value": int((symbol_report["missing_price_rows"] > 0).sum()) if total else 0},
        ]
    )


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    df = load_price_ticks(source=args.source)
    symbol_report = quality_by_symbol(df, args.min_rows)
    summary = summary_report(symbol_report)
    symbol_path = out_dir / f"daily_data_quality_symbols_{timestamp}.csv"
    summary_path = out_dir / f"daily_data_quality_summary_{timestamp}.csv"
    symbol_report.to_csv(symbol_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"[quality] rows={len(df)}, symbols={df['symbol'].nunique() if not df.empty else 0}")
    print(f"[quality] wrote {symbol_path}")
    print(f"[quality] wrote {summary_path}")


if __name__ == "__main__":
    main()
