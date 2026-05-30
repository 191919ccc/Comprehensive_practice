import argparse
import json
import random
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from kafka import KafkaProducer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from python.common.config import settings
from python.common.stock_utils import calc_change_pct, is_valid_tick
from python.producer.stock_catalog_loader import load_symbols


def latest_crawled_file() -> Path:
    """默认使用最近一次真实采集快照作为回放基础。"""
    crawled_dir = PROJECT_ROOT / "python" / "data" / "crawled"
    files = sorted(crawled_dir.glob("stock_quotes_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"no crawled stock quote files found in {crawled_dir}")
    return files[0]


def load_quotes(path: Path) -> list[dict]:
    """加载真实行情快照，并用当前股票池补齐名称、行业、市场等展示字段。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    quotes = payload.get("quotes", payload if isinstance(payload, list) else [])
    if not quotes:
        raise RuntimeError(f"no quotes found in {path}")

    # Use the current symbol catalog as the source of truth for readable metadata.
    catalog = {item["symbol"].upper(): item for item in load_symbols()}
    normalized = []
    for quote in quotes:
        symbol = str(quote["symbol"]).upper()
        meta = catalog.get(symbol, {})
        normalized.append({**quote, **meta, "symbol": symbol})
    return normalized


def replay_quote(base_quote: dict, round_no: int, volatility_pct: float) -> dict:
    """基于真实快照生成一条新的行情事件，用于休市时演示实时流动效果。"""
    previous_close = float(base_quote.get("previous_close") or base_quote.get("last_price") or 0)
    base_price = float(base_quote.get("last_price") or previous_close)
    drift = random.uniform(-volatility_pct, volatility_pct) / 100
    cycle_bias = ((round_no % 7) - 3) * volatility_pct / 600
    last_price = max(0.01, round(base_price * (1 + drift + cycle_bias), 2))
    change_pct = calc_change_pct(last_price, previous_close)
    volume = max(1, int(float(base_quote.get("volume") or 1) * random.uniform(0.85, 1.18)))

    return {
        **base_quote,
        "event_id": str(uuid.uuid4()),
        "last_price": last_price,
        "high_price": max(last_price, float(base_quote.get("high_price") or last_price)),
        "low_price": min(last_price, float(base_quote.get("low_price") or last_price)),
        "previous_close": round(previous_close or last_price, 2),
        "change_pct": change_pct,
        "volume": volume,
        "turnover": round(last_price * volume, 2),
        "event_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "replay",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay crawled stock quotes to Kafka as a realtime stream.")
    parser.add_argument("--file", type=Path, default=None, help="Crawled JSON file. Defaults to latest python/data/crawled file.")
    parser.add_argument("--interval", type=float, default=settings.quote_interval_seconds, help="Seconds between replay rounds.")
    parser.add_argument("--rounds", type=int, default=0, help="Replay rounds. 0 means run forever.")
    parser.add_argument("--limit", type=int, default=0, help="Limit symbols per round. 0 means all quotes.")
    parser.add_argument("--volatility", type=float, default=1.2, help="Random price volatility percentage for each round.")
    parser.add_argument("--no-jitter", action="store_true", help="Do not perturb prices while replaying.")
    return parser.parse_args()


def main() -> None:
    """把历史快照按固定间隔回放到 Kafka，保证答辩演示时前端持续变化。"""
    args = parse_args()
    source_file = args.file or latest_crawled_file()
    quotes = load_quotes(source_file)
    if args.limit > 0:
        quotes = quotes[: args.limit]

    producer = KafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
        key_serializer=lambda value: value.encode("utf-8"),
        value_serializer=lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
    )

    print(
        f"Replaying {len(quotes)} quotes from {source_file} to topic={settings.kafka_topic} "
        f"interval={args.interval}s rounds={'forever' if args.rounds == 0 else args.rounds}"
    )

    round_no = 0
    try:
        while args.rounds == 0 or round_no < args.rounds:
            round_no += 1
            started_at = time.time()
            for base_quote in quotes:
                quote = replay_quote(base_quote, round_no, 0 if args.no_jitter else args.volatility)
                if not is_valid_tick(quote):
                    continue
                producer.send(settings.kafka_topic, key=quote["symbol"], value=quote)
                print(
                    f"[replay] round={round_no} {quote['symbol']} "
                    f"last={quote['last_price']} change={quote['change_pct']} source={quote['source']}"
                )
            producer.flush()
            elapsed = time.time() - started_at
            sleep_seconds = max(0, args.interval - elapsed)
            print(f"[cycle] round={round_no} sent={len(quotes)} elapsed={elapsed:.2f}s next_sleep={sleep_seconds:.2f}s")
            time.sleep(sleep_seconds)
    except KeyboardInterrupt:
        print("Replay stopped by user.")
    finally:
        producer.close()


if __name__ == "__main__":
    main()
