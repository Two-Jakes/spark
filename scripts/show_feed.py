"""Print a one-line summary of every card in data/feed.json."""

import json
import sys
from collections import Counter
from pathlib import Path


FEED_PATH = Path(__file__).resolve().parent.parent / "data" / "feed.json"


def main() -> None:
    """Print feed counts and card summaries; take no args and return nothing.

    Read UTF-8 explicitly because Windows may default to a legacy encoding.
    """
    sys.stdout.reconfigure(encoding="utf-8")
    feed = json.loads(FEED_PATH.read_text(encoding="utf-8"))
    cards = feed["cards"]

    print(f"{len(cards)} cards, generated {feed.get('generated_at')}")
    for category, count in Counter(c["category"] for c in cards).items():
        print(f"  {category}: {count}")
    print()

    for c in cards:
        via = (c.get("via") or {}).get("name", "")
        url = c["source"]["url"]
        print(f"{c['category']:<15} | {c['hook'][:70]:<70} | via {via or '-':<10} | {url[:50]}")


if __name__ == "__main__":
    main()
