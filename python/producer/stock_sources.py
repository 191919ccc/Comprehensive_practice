"""Quote source adapters for the real-time stock producer.

This module is responsible for one thing: fetch one quote from a configured
website and normalize it into the JSON structure consumed by Kafka and Spark.

The project currently keeps only domestic-related markets:
- SH/SZ/BJ: A shares
- HK: Hong Kong stocks

Older US-source adapters such as Yahoo/Stooq were removed after the project was
scoped down to domestic markets, which avoids confusing sparse US market data
with the real-time A-share/HK demonstration.
"""

from __future__ import annotations

import re
import uuid
from typing import Callable

import requests

from python.common.config import settings
from python.common.stock_utils import (
    calc_change_pct,
    detect_market,
    eastmoney_price,
    eastmoney_secid,
    infer_sector,
    is_valid_tick,
    now_ts,
    normalize_quote_text,
    safe_float,
    safe_int,
    sina_code,
    tencent_code,
)


def normalize_quote(
    symbol_info: dict,
    *,
    open_price: float,
    high_price: float,
    low_price: float,
    last_price: float,
    previous_close: float,
    volume: int,
    source: str,
) -> dict:
    """Build the standard quote event shared by Producer, Kafka and Spark.

    Every data source returns different field names and formats. This function
    hides those differences and produces a stable event schema:
    price fields, volume, market metadata, source name and event time.
    """

    symbol = symbol_info["symbol"].upper()
    return normalize_quote_text({
        "event_id": str(uuid.uuid4()),
        "symbol": symbol,
        "company_name": symbol_info.get("company_name", symbol),
        "category": symbol_info.get("category", "Uncategorized"),
        "sector": symbol_info.get("sector", infer_sector(symbol)),
        "market": symbol_info.get("market", detect_market(symbol)),
        "open_price": round(float(open_price), 2),
        "high_price": round(float(high_price), 2),
        "low_price": round(float(low_price), 2),
        "last_price": round(float(last_price), 2),
        "previous_close": round(float(previous_close), 2),
        "change_pct": calc_change_pct(float(last_price), float(previous_close)),
        "volume": int(volume),
        "turnover": round(float(last_price) * int(volume), 2),
        "event_time": now_ts(),
        "source": source,
    })


def fetch_from_eastmoney(symbol_info: dict) -> dict:
    """Fetch an A-share/HK quote from Eastmoney.

    Eastmoney encodes prices as scaled numbers, so `eastmoney_price` converts
    them into normal decimal prices before the quote is normalized.
    """

    market = detect_market(symbol_info["symbol"], symbol_info.get("market", ""))
    response = requests.get(
        "https://push2.eastmoney.com/api/qt/stock/get",
        params={
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "invt": "2",
            "fltt": "2",
            "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60",
            "secid": eastmoney_secid(symbol_info["symbol"], market),
        },
        headers={"User-Agent": settings.http_user_agent},
        timeout=settings.http_timeout_seconds,
    )
    response.raise_for_status()
    data = response.json().get("data") or {}
    return normalize_quote(
        {
            **symbol_info,
            "company_name": data.get("f58") or symbol_info.get("company_name", symbol_info["symbol"]),
            "market": market,
        },
        open_price=eastmoney_price(data.get("f46")),
        high_price=eastmoney_price(data.get("f44")),
        low_price=eastmoney_price(data.get("f45")),
        last_price=eastmoney_price(data.get("f43")),
        previous_close=eastmoney_price(data.get("f60")) or eastmoney_price(data.get("f43")),
        volume=safe_int(data.get("f47")),
        source="eastmoney",
    )


def _extract_sina_payload(text: str) -> list[str]:
    """Extract the comma-separated payload from Sina's JavaScript response."""

    matched = re.search(r'="(.*)"', text)
    if not matched:
        raise RuntimeError("invalid sina response")
    return matched.group(1).split(",")


def fetch_from_sina(symbol_info: dict) -> dict:
    """Fetch an A-share/HK quote from Sina Finance.

    Sina is preferred for A shares because it usually returns fast quotes and
    Chinese company names. Unsupported markets are rejected early.
    """

    market = detect_market(symbol_info["symbol"], symbol_info.get("market", ""))
    if market not in {"SH", "SZ", "BJ", "HK"}:
        raise RuntimeError(f"sina source supports SH/SZ/BJ/HK symbols only, got market={market}")

    response = requests.get(
        "https://hq.sinajs.cn/list=" + sina_code(symbol_info["symbol"], market),
        headers={"User-Agent": settings.http_user_agent, "Referer": "https://finance.sina.com.cn"},
        timeout=settings.http_timeout_seconds,
    )
    response.raise_for_status()
    payload = _extract_sina_payload(response.text)
    return normalize_quote(
        {
            **symbol_info,
            "company_name": payload[0] or symbol_info.get("company_name", symbol_info["symbol"]),
            "market": market,
        },
        open_price=safe_float(payload[1]),
        high_price=safe_float(payload[4]),
        low_price=safe_float(payload[5]),
        last_price=safe_float(payload[3]),
        previous_close=safe_float(payload[2]) or safe_float(payload[3]),
        volume=safe_int(payload[8] if len(payload) > 8 else 0),
        source="sina",
    )


def fetch_from_tencent(symbol_info: dict) -> dict:
    """Fetch an A-share/HK quote from Tencent as a fallback source."""

    market = detect_market(symbol_info["symbol"], symbol_info.get("market", ""))
    response = requests.get(
        "https://qt.gtimg.cn/q=" + tencent_code(symbol_info["symbol"], market),
        headers={"User-Agent": settings.http_user_agent, "Referer": "https://gu.qq.com"},
        timeout=settings.http_timeout_seconds,
    )
    response.raise_for_status()
    matched = re.search(r'="(.*)";', response.text)
    if not matched:
        raise RuntimeError("invalid tencent response")
    payload = matched.group(1).split("~")
    return normalize_quote(
        {
            **symbol_info,
            "company_name": payload[1] or symbol_info.get("company_name", symbol_info["symbol"]),
            "market": market,
        },
        open_price=safe_float(payload[5] if len(payload) > 5 else 0),
        high_price=safe_float(payload[33] if len(payload) > 33 else payload[3] if len(payload) > 3 else 0),
        low_price=safe_float(payload[34] if len(payload) > 34 else payload[3] if len(payload) > 3 else 0),
        last_price=safe_float(payload[3] if len(payload) > 3 else 0),
        previous_close=safe_float(payload[4] if len(payload) > 4 else payload[3] if len(payload) > 3 else 0),
        volume=safe_int(payload[36] if len(payload) > 36 else 0),
        source="tencent",
    )


SOURCE_FETCHERS: dict[str, Callable[[dict], dict]] = {
    "eastmoney": fetch_from_eastmoney,
    "sina": fetch_from_sina,
    "tencent": fetch_from_tencent,
}


def preferred_sources(symbol_info: dict, configured_sources: list[str]) -> list[str]:
    """Return the source order used by fallback fetching.

    `.env` may still contain old source names. The `allowed` filter below keeps
    only implemented adapters, so stale values such as yahoo/stooq are ignored.
    """

    market = detect_market(symbol_info["symbol"], symbol_info.get("market", ""))
    if market in {"SH", "SZ", "BJ"}:
        priority = ["sina", "tencent", "eastmoney"]
    elif market == "HK":
        priority = ["eastmoney", "sina", "tencent"]
    else:
        priority = ["eastmoney", "tencent", "sina"]

    allowed = {source for source in configured_sources if source in SOURCE_FETCHERS}
    ordered = [source for source in priority if source in allowed]
    for source in configured_sources:
        if source in SOURCE_FETCHERS and source not in ordered:
            ordered.append(source)
    return ordered


def fetch_quote_with_fallback(symbol_info: dict, sources: list[str]) -> dict:
    """Try each configured source until one quote succeeds."""

    last_error: Exception | None = None
    for source in preferred_sources(symbol_info, sources):
        fetcher = SOURCE_FETCHERS.get(source)
        if fetcher is None:
            continue
        try:
            quote = fetcher(symbol_info)
            if is_valid_tick(quote):
                return quote
            last_error = RuntimeError(f"{source} returned invalid quote for {symbol_info['symbol']}")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    if last_error is not None:
        raise RuntimeError(f"all quote sources failed for {symbol_info['symbol']}: {last_error}") from last_error
    raise RuntimeError("no valid quote source configured")
