"""Load the stock watchlist used by the real-time producer.

The crawler does not scan the whole market. It reads a controlled stock pool
from `python/data/stock_symbols.json`, which keeps the demo stable and avoids
unbounded requests to public finance websites.
"""

from __future__ import annotations

import json
from pathlib import Path

from python.common.config import settings
from python.common.stock_utils import infer_sector


def quote_path() -> Path:
    """Return the configured stock-pool JSON path."""

    return (Path(__file__).resolve().parents[1] / settings.quote_output).resolve()


def fallback_symbols() -> list[dict]:
    """Build a minimal stock pool from `.env` when the JSON file is missing.

    This fallback keeps the producer runnable, but it cannot provide rich
    company names, categories or sectors. The normal path should be
    `python/data/stock_symbols.json`.
    """

    return [
        {
            "symbol": symbol,
            "company_name": symbol,
            "category": "Custom Watchlist",
            "sector": infer_sector(symbol),
            "market": "",
        }
        for symbol in settings.stock_symbols
    ]


def load_symbols() -> list[dict]:
    """Read the stock pool used by each crawler cycle."""

    path = quote_path()
    if not path.exists():
        return fallback_symbols()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback_symbols()


def save_symbols(items: list[dict]) -> Path:
    """Persist a stock pool after manual or scripted edits."""

    path = quote_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
