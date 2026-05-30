"""Small shared helpers for stock-code handling and quote validation."""

from __future__ import annotations

from datetime import datetime


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


def is_valid_tick(row: dict) -> bool:
    """Filter obviously invalid quote rows before Kafka/Spark processing."""

    market = detect_market(str(row.get("symbol", "")), str(row.get("market", "")))
    symbol = str(row.get("symbol", "")).strip()
    change_pct = safe_float(row.get("change_pct"))
    volume = safe_int(row.get("volume"))
    last_price = safe_float(row.get("last_price"))
    if last_price <= 0 or volume <= 0:
        return False
    if market in {"SH", "SZ", "BJ"}:
        if market == "BJ":
            return abs(change_pct) < 31
        if symbol.startswith(("300", "301", "688")):
            return abs(change_pct) < 21
        return abs(change_pct) < 11
    if market == "HK":
        return abs(change_pct) < 50
    return False


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
