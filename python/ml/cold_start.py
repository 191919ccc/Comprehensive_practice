from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pymysql

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from python.common.config import settings
from python.common.stock_utils import calc_change_pct, detect_market, infer_sector, is_valid_tick, safe_float, safe_int
from python.ml.daily_bar_store import DAILY_BAR_COLUMNS, add_trade_date, daily_table_for_source, ensure_daily_bar_tables
from python.producer.stock_catalog_loader import load_symbols


DEFAULT_A_SYMBOLS = [
    "600519",
    "000858",
    "600809",
    "300750",
    "002594",
    "601012",
    "601318",
    "600036",
    "601398",
    "600030",
    "000333",
    "000651",
    "600887",
    "600276",
    "300760",
    "002415",
    "600000",
    "600009",
    "600015",
    "600016",
    "600028",
    "600031",
    "600048",
    "600050",
    "600104",
    "600111",
    "600150",
    "600196",
    "600309",
    "600346",
    "600406",
    "600438",
    "600570",
    "600585",
    "600690",
    "600745",
    "600760",
    "600900",
    "601088",
    "601166",
    "601288",
    "601328",
    "601601",
    "601628",
    "601668",
    "601688",
    "601766",
    "601818",
    "601857",
    "601888",
    "601899",
    "601919",
    "601988",
    "601989",
    "000001",
    "000002",
    "000063",
    "000100",
    "000166",
    "000338",
    "000568",
    "000725",
    "000776",
    "000895",
    "000938",
    "000977",
    "001979",
    "002027",
    "002050",
    "002129",
    "002142",
    "002230",
    "002271",
    "002304",
    "002352",
    "002371",
    "002475",
    "002493",
    "002714",
    "002812",
    "300014",
    "300015",
    "300059",
    "300122",
    "300124",
    "300274",
    "300316",
    "300347",
    "300408",
    "300433",
    "300498",
    "300759",
]

DEFAULT_INDEX_SYMBOLS = {
    "INDEX_SH000001": {"ak_symbol": "sh000001", "company_name": "上证指数", "market": "INDEX", "sector": "Market Index"},
    "INDEX_SZ399006": {"ak_symbol": "sz399006", "company_name": "创业板指", "market": "INDEX", "sector": "Market Index"},
    "INDEX_SH000300": {"ak_symbol": "sh000300", "company_name": "沪深300", "market": "INDEX", "sector": "Market Index"},
}
DEFAULT_AK_SOURCES = ["tencent", "sina", "eastmoney"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import AKShare daily A-share history into dedicated daily bar tables for ML cold start.")
    parser.add_argument("--symbols", default="", help="Comma-separated A-share symbols. Defaults to key A-share symbols in the catalog.")
    parser.add_argument("--days", type=int, default=1500, help="History window in calendar days.")
    parser.add_argument("--adjust", default="qfq", help="AKShare adjust mode: qfq, hfq or empty.")
    parser.add_argument("--include-index", action="store_true", help="Also import Shanghai, ChiNext and CSI 300 index daily bars.")
    parser.add_argument("--index-only", action="store_true", help="Only import index daily bars and skip stock symbols.")
    parser.add_argument("--use-proxy", action="store_true", help="Keep current proxy environment for AKShare requests.")
    parser.add_argument(
        "--sources",
        default=",".join(DEFAULT_AK_SOURCES),
        help="Comma-separated stock history sources. Supported: eastmoney,tencent,sina.",
    )
    parser.add_argument("--request-timeout", type=float, default=10.0, help="AKShare request timeout for supported sources.")
    parser.add_argument("--retries", type=int, default=1, help="Retry count per source before falling back to the next source.")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds to sleep between source failures.")
    return parser.parse_args()


def disable_proxy_env() -> None:
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def load_akshare():
    try:
        import akshare as ak  # type: ignore
    except ImportError as exc:
        raise RuntimeError("akshare is not installed. Run: pip install -r python/requirements.txt") from exc
    return ak


def selected_symbols(raw_symbols: str) -> list[dict]:
    catalog = load_symbols()
    by_symbol = {str(item.get("symbol", "")).upper(): item for item in catalog}
    if raw_symbols.strip():
        wanted = [item.strip().upper() for item in raw_symbols.split(",") if item.strip()]
    else:
        wanted = [symbol for symbol in DEFAULT_A_SYMBOLS if detect_market(symbol) in {"SH", "SZ", "BJ"}]
    result: list[dict] = []
    for symbol in wanted:
        item = dict(by_symbol.get(symbol, {}))
        item.setdefault("symbol", symbol)
        item.setdefault("company_name", symbol)
        item.setdefault("category", "A Share Cold Start")
        item.setdefault("sector", infer_sector(symbol))
        item.setdefault("market", detect_market(symbol))
        if detect_market(symbol, item.get("market", "")) in {"SH", "SZ", "BJ"}:
            result.append(item)
    return result


def selected_sources(raw_sources: str) -> list[str]:
    supported = set(DEFAULT_AK_SOURCES)
    sources = [item.strip().lower() for item in raw_sources.split(",") if item.strip()]
    invalid = [item for item in sources if item not in supported]
    if invalid:
        raise ValueError(f"Unsupported AKShare source(s): {', '.join(invalid)}. Supported: {', '.join(DEFAULT_AK_SOURCES)}")
    return sources or DEFAULT_AK_SOURCES


def market_prefixed_symbol(symbol: str, market: str = "") -> str:
    detected_market = detect_market(symbol, market)
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(detected_market, "")
    return f"{prefix}{symbol}" if prefix else symbol


def row_value(row: dict, *names: str, default: object = "") -> object:
    for name in names:
        if name in row and row.get(name) is not None:
            return row.get(name)
    return default


def normalize_trade_date(value: object) -> str:
    text = str(value).strip().split()[0].replace("-", "").replace("/", "")
    if len(text) < 8:
        raise ValueError(f"Invalid trade date: {value!r}")
    return text[:8]


def normalize_ak_row(symbol_info: dict, row: dict, source: str = "eastmoney", previous_close_override: float | None = None) -> dict:
    symbol = str(symbol_info["symbol"]).upper()
    trade_date = normalize_trade_date(row_value(row, "\u65e5\u671f", "date"))
    close_price = safe_float(row_value(row, "\u6536\u76d8", "close"))
    previous_close = previous_close_override if previous_close_override is not None else safe_float(row_value(row, "\u6628\u6536"), 0.0)
    if previous_close <= 0:
        change_pct = safe_float(row_value(row, "\u6da8\u8dcc\u5e45"))
        previous_close = close_price / (1 + change_pct / 100) if change_pct > -99 and close_price > 0 else close_price
    if source == "tencent":
        volume = safe_int(row_value(row, "\u6210\u4ea4\u91cf", "amount"))
        turnover = 0.0
    elif source == "sina":
        volume = safe_int(row_value(row, "\u6210\u4ea4\u91cf", "volume"))
        turnover = safe_float(row_value(row, "\u6210\u4ea4\u989d", "amount"))
    else:
        volume = safe_int(row_value(row, "\u6210\u4ea4\u91cf", "volume"))
        turnover = safe_float(row_value(row, "\u6210\u4ea4\u989d", "amount"))
    event_time = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d 15:00:00")
    quote = {
        "event_id": f"cold-akshare-{symbol}-{trade_date}",
        "symbol": symbol,
        "company_name": symbol_info.get("company_name", symbol),
        "category": symbol_info.get("category", "A Share Cold Start"),
        "sector": symbol_info.get("sector", infer_sector(symbol)),
        "market": detect_market(symbol, symbol_info.get("market", "")),
        "open_price": round(safe_float(row_value(row, "\u5f00\u76d8", "open"), close_price), 2),
        "high_price": round(safe_float(row_value(row, "\u6700\u9ad8", "high"), close_price), 2),
        "low_price": round(safe_float(row_value(row, "\u6700\u4f4e", "low"), close_price), 2),
        "last_price": round(close_price, 2),
        "previous_close": round(previous_close, 2),
        "change_pct": calc_change_pct(close_price, previous_close),
        "volume": volume,
        "turnover": round(turnover, 2),
        "trade_date": datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d"),
        "event_time": event_time,
        "source": "akshare_cold_start",
    }
    return quote


def normalize_index_row(index_symbol: str, index_info: dict, row: dict, previous_close_override: float | None = None) -> dict:
    trade_date = normalize_trade_date(row_value(row, "\u65e5\u671f", "date"))
    close_price = safe_float(row_value(row, "\u6536\u76d8", "close"))
    change_pct = safe_float(row_value(row, "\u6da8\u8dcc\u5e45"))
    previous_close = previous_close_override if previous_close_override is not None else 0.0
    if previous_close <= 0:
        previous_close = close_price / (1 + change_pct / 100) if change_pct > -99 and close_price > 0 else close_price
    volume = safe_int(row_value(row, "\u6210\u4ea4\u91cf", "volume", "amount"), 1)
    turnover = safe_float(row_value(row, "\u6210\u4ea4\u989d", "amount"))
    event_time = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d 15:00:00")
    return {
        "event_id": f"index-akshare-{index_symbol}-{trade_date}",
        "symbol": index_symbol,
        "company_name": index_info["company_name"],
        "category": "Market Index",
        "sector": index_info["sector"],
        "market": index_info["market"],
        "open_price": round(safe_float(row_value(row, "\u5f00\u76d8", "open"), close_price), 2),
        "high_price": round(safe_float(row_value(row, "\u6700\u9ad8", "high"), close_price), 2),
        "low_price": round(safe_float(row_value(row, "\u6700\u4f4e", "low"), close_price), 2),
        "last_price": round(close_price, 2),
        "previous_close": round(previous_close, 2),
        "change_pct": calc_change_pct(close_price, previous_close),
        "volume": volume,
        "turnover": round(turnover, 2),
        "trade_date": datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d"),
        "event_time": event_time,
        "source": "akshare_index",
    }


def fetch_stock_frame(ak, source: str, symbol_info: dict, start: str, end: str, adjust: str, timeout: float):
    symbol = str(symbol_info["symbol"]).upper()
    if source == "eastmoney":
        return ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start, end_date=end, adjust=adjust, timeout=timeout)
    prefixed_symbol = market_prefixed_symbol(symbol, symbol_info.get("market", ""))
    if source == "tencent":
        return ak.stock_zh_a_hist_tx(symbol=prefixed_symbol, start_date=start, end_date=end, adjust=adjust, timeout=timeout)
    if source == "sina":
        return ak.stock_zh_a_daily(symbol=prefixed_symbol, start_date=start, end_date=end, adjust=adjust)
    raise ValueError(f"Unsupported AKShare source: {source}")


def normalize_stock_frame(symbol_info: dict, rows: list[dict], source: str) -> list[dict]:
    quotes: list[dict] = []
    previous_close = 0.0
    for row in rows:
        close_price = safe_float(row_value(row, "\u6536\u76d8", "close"))
        override = previous_close if source in {"tencent", "sina"} and previous_close > 0 else None
        quote = normalize_ak_row(symbol_info, row, source=source, previous_close_override=override)
        if is_valid_tick(quote):
            quotes.append(quote)
        if close_price > 0:
            previous_close = close_price
    return quotes


def fetch_a_stock(
    ak,
    symbol_info: dict,
    days: int,
    adjust: str,
    sources: list[str],
    retries: int,
    timeout: float,
    sleep_seconds: float,
) -> list[dict]:
    symbol = str(symbol_info["symbol"]).upper()
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=max(days, 30))).strftime("%Y%m%d")
    last_error: Exception | None = None
    for source in sources:
        for attempt in range(1, max(retries, 1) + 1):
            try:
                df = fetch_stock_frame(ak, source, symbol_info, start, end, adjust, timeout)
                rows = df.to_dict("records")
                quotes = normalize_stock_frame(symbol_info, rows, source)
                if quotes:
                    if source != sources[0] or attempt > 1:
                        print(f"[cold-start] {symbol} source={source} recovered rows={len(quotes)}", flush=True)
                    return quotes
                raise ValueError(f"{source} returned no valid rows")
            except Exception as exc:
                last_error = exc
                print(f"[cold-start] {symbol} source={source} attempt={attempt} failed: {exc}", flush=True)
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
    if last_error is not None:
        raise last_error
    return []


def normalize_index_frame(index_symbol: str, index_info: dict, rows: list[dict], source: str) -> list[dict]:
    quotes: list[dict] = []
    previous_close = 0.0
    for row in rows:
        close_price = safe_float(row_value(row, "\u6536\u76d8", "close"))
        override = previous_close if source == "tencent" and previous_close > 0 else None
        quote = normalize_index_row(index_symbol, index_info, row, previous_close_override=override)
        if quote["last_price"] > 0:
            quotes.append(quote)
        if close_price > 0:
            previous_close = close_price
    return quotes


def fetch_index(ak, index_symbol: str, index_info: dict, days: int, sources: list[str], timeout: float, sleep_seconds: float) -> list[dict]:
    end = datetime.now().strftime("%Y%m%d")
    start_dt = datetime.now() - timedelta(days=max(days, 30))
    start = start_dt.strftime("%Y%m%d")
    last_error: Exception | None = None
    for source in sources:
        if source == "sina":
            continue
        try:
            if source == "eastmoney":
                df = ak.stock_zh_index_daily_em(symbol=index_info["ak_symbol"])
                if "\u65e5\u671f" in df.columns:
                    df = df[df["\u65e5\u671f"].astype(str).str.replace("-", "") >= start]
            elif source == "tencent":
                df = ak.stock_zh_a_hist_tx(symbol=index_info["ak_symbol"], start_date=start, end_date=end, adjust="", timeout=timeout)
            else:
                continue
            quotes = normalize_index_frame(index_symbol, index_info, df.to_dict("records"), source)
            if quotes:
                if source != sources[0]:
                    print(f"[cold-start] index {index_symbol} source={source} recovered rows={len(quotes)}", flush=True)
                return quotes
            raise ValueError(f"{source} returned no valid index rows")
        except Exception as exc:
            last_error = exc
            print(f"[cold-start] index {index_symbol} source={source} failed: {exc}", flush=True)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    if last_error is not None:
        raise last_error
    return []


def insert_quotes(quotes: list[dict]) -> int:
    if not quotes:
        return 0
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset="utf8mb4",
        autocommit=True,
    )
    inserted = 0
    try:
        with conn.cursor() as cursor:
            ensure_daily_bar_tables(cursor)
            insert_columns = ", ".join(DAILY_BAR_COLUMNS)
            insert_values = ", ".join(f"%({column})s" for column in DAILY_BAR_COLUMNS)
            for quote in quotes:
                quote = add_trade_date(quote)
                table = daily_table_for_source(quote.get("source"))
                if table is None:
                    raise ValueError(f"Unsupported daily bar source: {quote.get('source')!r}")
                cursor.execute(f"SELECT 1 FROM {table} WHERE event_id = %s LIMIT 1", (quote["event_id"],))
                if cursor.fetchone():
                    continue
                cursor.execute(
                    f"""
                    SELECT 1
                    FROM {table}
                    WHERE source = %(source)s AND symbol = %(symbol)s AND event_time = %(event_time)s
                    LIMIT 1
                    """,
                    quote,
                )
                if cursor.fetchone():
                    continue
                cursor.execute(
                    f"""
                    INSERT INTO {table}
                    ({insert_columns})
                    VALUES ({insert_values})
                    """,
                    quote,
                )
                inserted += 1
    finally:
        conn.close()
    return inserted


def main() -> None:
    args = parse_args()
    if not args.use_proxy:
        disable_proxy_env()
    ak = load_akshare()
    sources = selected_sources(args.sources)
    total = 0
    if args.include_index:
        for index_symbol, index_info in DEFAULT_INDEX_SYMBOLS.items():
            print(f"[cold-start] fetching index {index_symbol}", flush=True)
            try:
                quotes = fetch_index(ak, index_symbol, index_info, args.days, sources, args.request_timeout, args.sleep)
                inserted = insert_quotes(quotes)
                total += inserted
                print(f"[cold-start] index {index_symbol} rows={len(quotes)} inserted={inserted}", flush=True)
            except Exception as exc:
                print(f"[cold-start] index {index_symbol} failed: {exc}", flush=True)
    if args.index_only:
        print(f"[cold-start] done inserted={total}", flush=True)
        print("[cold-start] next: python -m python.ml.train_daily_predict", flush=True)
        return
    for symbol_info in selected_symbols(args.symbols):
        symbol = str(symbol_info["symbol"]).upper()
        print(f"[cold-start] fetching {symbol}", flush=True)
        try:
            quotes = fetch_a_stock(ak, symbol_info, args.days, args.adjust, sources, args.retries, args.request_timeout, args.sleep)
            inserted = insert_quotes(quotes)
            total += inserted
            print(f"[cold-start] {symbol} rows={len(quotes)} inserted={inserted}", flush=True)
        except Exception as exc:
            print(f"[cold-start] {symbol} failed: {exc}", flush=True)
    print(f"[cold-start] done inserted={total}", flush=True)
    print("[cold-start] next: python -m python.ml.train_daily_predict", flush=True)


if __name__ == "__main__":
    main()
