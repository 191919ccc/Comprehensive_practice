"""Real-time quote producer.

Runtime role:
1. Load the configured stock pool.
2. Fetch quotes concurrently from Sina/Tencent/Eastmoney.
3. Validate each quote.
4. Send standard quote JSON events to Kafka.

Spark Structured Streaming consumes the Kafka topic and writes aggregates,
alerts and raw ticks into MySQL/HDFS.
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from kafka import KafkaProducer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from python.common.config import settings
from python.common.stock_utils import is_valid_tick
from python.producer.stock_catalog_loader import load_symbols
from python.producer.stock_sources import fetch_quote_with_fallback


def fetch_one(item: dict) -> dict | None:
    """Fetch one stock quote and isolate failures to that symbol only."""

    try:
        return fetch_quote_with_fallback(item, settings.quote_sources)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] skip {item.get('symbol')} because quote fetch failed: {exc}")
        return None


def fetch_quotes() -> list[dict]:
    """Fetch one full watchlist cycle in parallel.

    Network calls dominate crawler time. A small thread pool keeps the cycle
    fast without putting too much pressure on public finance websites.
    """

    symbols = load_symbols()
    quotes: list[dict] = []
    max_workers = max(1, min(settings.stock_producer_max_workers, len(symbols)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, item): item for item in symbols}
        for future in as_completed(futures):
            quote = future.result()
            if quote is not None:
                quotes.append(quote)
    return quotes


def main() -> None:
    """Continuously publish valid quote events to Kafka."""

    producer = KafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
        key_serializer=lambda value: value.encode("utf-8"),
        value_serializer=lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
    )

    print(
        f"Producing stock quotes to topic={settings.kafka_topic} "
        f"bootstrap={settings.kafka_bootstrap_servers} sources={','.join(settings.quote_sources)} "
        f"cycle={settings.quote_interval_seconds}s workers={settings.stock_producer_max_workers}"
    )

    cycle_no = 0
    while True:
        cycle_no += 1
        started_at = time.time()
        quotes = [quote for quote in fetch_quotes() if is_valid_tick(quote)]
        for quote in quotes:
            # Use the stock symbol as Kafka key so downstream logs and tooling
            # can group messages by the same stock.
            producer.send(settings.kafka_topic, key=quote["symbol"], value=quote)
            print(f"[quote] {quote['symbol']} last={quote['last_price']} change={quote['change_pct']}%")
        producer.flush()
        elapsed = time.time() - started_at
        sleep_seconds = max(0, settings.quote_interval_seconds - elapsed)
        print(
            f"[cycle] no={cycle_no} sent={len(quotes)} "
            f"elapsed={elapsed:.2f}s next_sleep={sleep_seconds:.2f}s"
        )
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    main()
