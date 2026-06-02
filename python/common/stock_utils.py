"""Small shared helpers for stock-code handling and quote validation."""

from __future__ import annotations

from datetime import datetime

DEFAULT_TEXT = {
    "company_name": "",
    "category": "Unknown",
    "sector": "Other",
}


def detect_market(symbol: str, market_hint: str = "") -> str:
    """Infer the domestic market from a stock code.

    The stock pool normally provides `market`, so the hint wins. If the hint is
    missing, six-digit codes are treated as A shares and five-digit codes as HK.
    Unknown non-numeric codes are marked as UNKNOWN instead of being treated as
    US stocks, because the current project scope excludes US markets.
    """

    if market_hint:
        return market_hint.upper()

    normalized = symbol.strip().upper()
    if normalized.isdigit() and len(normalized) == 6:
        if normalized.startswith("6"):
            return "SH"
        if normalized.startswith(("0", "3")):
            return "SZ"
        if normalized.startswith(("4", "8")):
            return "BJ"
    if normalized.isdigit() and len(normalized) == 5:
        return "HK"
    return "UNKNOWN"


def infer_sector(symbol: str) -> str:
    """Return a fallback sector when the stock pool has no sector value."""

    return "Other"


def calc_change_pct(price: float, previous_close: float) -> float:
    """Calculate percentage change from previous close."""

    if not previous_close:
        return 0.0
    return round((price - previous_close) / previous_close * 100, 4)


def market_change_limit(symbol: str, market_hint: str = "") -> float | None:
    """Return a conservative daily percent-change sanity limit.

    The value is not a trading rule. It is a data-quality guard used to reject
    clearly broken source responses before they pollute storage or training.
    """

    market = detect_market(symbol, market_hint)
    normalized = str(symbol).strip().upper()
    if market == "BJ":
        return 31.0
    if market in {"SH", "SZ"}:
        if normalized.startswith(("300", "301", "688")):
            return 21.0
        return 11.0
    if market == "HK":
        return 30.0
    if market in {"US", "NASDAQ", "NYSE"}:
        return 25.0
    if market == "INDEX":
        return 15.0
    return None


def is_valid_ohlc(row: dict, *, require_volume: bool = True) -> bool:
    """Validate price-bar geometry and basic numeric fields."""

    open_price = safe_float(row.get("open_price"))
    high_price = safe_float(row.get("high_price"))
    low_price = safe_float(row.get("low_price"))
    last_price = safe_float(row.get("last_price"))
    previous_close = safe_float(row.get("previous_close"), last_price)
    volume = safe_int(row.get("volume"))
    if min(open_price, high_price, low_price, last_price) <= 0:
        return False
    if previous_close <= 0:
        return False
    if require_volume and volume <= 0:
        return False
    if high_price < low_price:
        return False
    if not (low_price <= open_price <= high_price):
        return False
    if not (low_price <= last_price <= high_price):
        return False
    return True


def is_valid_tick(row: dict) -> bool:
    """Filter obviously invalid quote rows before Kafka/Spark processing."""

    market = detect_market(str(row.get("symbol", "")), str(row.get("market", "")))
    symbol = str(row.get("symbol", "")).strip()
    change_pct = safe_float(row.get("change_pct"))
    if not is_valid_ohlc(row, require_volume=market != "INDEX"):
        return False
    limit = market_change_limit(symbol, market)
    return limit is not None and abs(change_pct) < limit


def normalize_quote_text(row: dict) -> dict:
    """Fill display metadata so categorical ML features stay stable."""

    result = dict(row)
    symbol = str(result.get("symbol", "")).strip().upper()
    result["symbol"] = symbol
    company_name = str(result.get("company_name") or "").strip()
    result["company_name"] = company_name or symbol
    result["category"] = str(result.get("category") or DEFAULT_TEXT["category"]).strip() or DEFAULT_TEXT["category"]
    result["sector"] = str(result.get("sector") or DEFAULT_TEXT["sector"]).strip() or DEFAULT_TEXT["sector"]
    result["market"] = detect_market(symbol, str(result.get("market") or ""))
    return result


def safe_float(value: object, default: float = 0.0) -> float:
    """Convert source values to float while tolerating blanks and dashes."""

    try:
        text = str(value).strip()
        if not text or text == "--":
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def safe_int(value: object, default: int = 0) -> int:
    """Convert source values to int while tolerating commas and blanks."""

    try:
        text = str(value).strip().replace(",", "")
        if not text or text == "--":
            return default
        return int(float(text))
    except (TypeError, ValueError):
        return default


def eastmoney_price(value: object) -> float:
    """Normalize Eastmoney scaled price fields."""

    raw = safe_float(value)
    return round(raw / 100, 2) if abs(raw) >= 100000 else round(raw, 2)


def eastmoney_secid(symbol: str, market_hint: str = "") -> str:
    """Build Eastmoney `secid` for SH/SZ/BJ/HK symbols."""

    market = detect_market(symbol, market_hint)
    normalized = symbol.strip().upper()
    if market == "SH":
        return f"1.{normalized}"
    if market in {"SZ", "BJ"}:
        return f"0.{normalized}"
    if market == "HK":
        return f"116.{normalized.zfill(5)}"
    raise ValueError(f"unsupported market for Eastmoney: {market} ({symbol})")


def sina_code(symbol: str, market_hint: str = "") -> str:
    """Build Sina quote code for SH/SZ/BJ/HK symbols."""

    market = detect_market(symbol, market_hint)
    normalized = symbol.strip().upper()
    if market == "SH":
        return f"sh{normalized}"
    if market in {"SZ", "BJ"}:
        return f"sz{normalized}"
    if market == "HK":
        return f"rt_hk{normalized.zfill(5)}"
    raise ValueError(f"unsupported market for Sina: {market} ({symbol})")


def tencent_code(symbol: str, market_hint: str = "") -> str:
    """Build Tencent quote code for SH/SZ/BJ/HK symbols."""

    market = detect_market(symbol, market_hint)
    normalized = symbol.strip().upper()
    if market == "SH":
        return f"sh{normalized}"
    if market in {"SZ", "BJ"}:
        return f"sz{normalized}"
    if market == "HK":
        return f"hk{normalized.zfill(5)}"
    raise ValueError(f"unsupported market for Tencent: {market} ({symbol})")


def now_ts() -> str:
    """Return the local timestamp format stored in Kafka events and MySQL."""

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
