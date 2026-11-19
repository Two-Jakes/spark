"""Validate the version 1 feed described in docs/feed-schema.md."""

import argparse
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import re
import sys


CATEGORIES = ("AI", "Development", "CVEs", "Cyber Security")
CARD_TYPES = ("advisory", "article", "paper")


def require_fields(value: object, path: str, **fields: type) -> dict[str, object]:
    """Check the object at path against required field types and return it."""
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    for name, expected in fields.items():
        if name not in value:
            raise ValueError(f"{path}.{name} is required")
        if type(value[name]) is not expected:
            raise ValueError(f"{path}.{name} must be of type {expected.__name__}")
    return value


def require_utc(value: str, path: str) -> None:
    """Raise ValueError if the timestamp at path is invalid or uses a non-UTC offset."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{path} must be an ISO-8601 UTC timestamp") from None
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{path} must be an ISO-8601 UTC timestamp")


def require_number(value: object, path: str) -> None:
    """Raise ValueError unless the value at path is a finite JSON number."""
    if type(value) is int or (type(value) is float and math.isfinite(value)):
        return
    raise ValueError(f"{path} must be a finite number")


def validate_link(value: object, path: str) -> None:
    """Raise ValueError if the link at path lacks a name or an HTTP(S) URL."""
    link = require_fields(value, path, name=str, url=str)
    url = link["url"]
    assert isinstance(url, str)
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"{path}.url must start with http:// or https://")


def validate_card(value: object, path: str) -> None:
    """Validate a card at path and raise ValueError on the first schema violation."""
    card = require_fields(
        value, path, id=str, category=str, type=str, hook=str, body=str, mins=int,
        source=dict, published=str,
    )
    if card["category"] not in CATEGORIES:
        raise ValueError(f"{path}.category must be one of {', '.join(CATEGORIES)}")
    if card["type"] not in CARD_TYPES:
        raise ValueError(f"{path}.type must be one of {', '.join(CARD_TYPES)}")
    card_id, hook, published = card["id"], card["hook"], card["published"]
    assert isinstance(card_id, str) and isinstance(hook, str) and isinstance(published, str)
    id_pattern = r"cve:CVE-[0-9]{4}-[0-9]{4,}" if card["category"] == "CVEs" else r"news:[0-9a-fA-F]+"
    if not re.fullmatch(id_pattern, card_id):
        raise ValueError(f"{path}.id must be a CVE ID or news URL hash with the appropriate prefix")
    if len(hook) > 90:
        raise ValueError(f"{path}.hook must be at most 90 characters")
    require_utc(published, f"{path}.published")
    require_number(card.get("rank"), f"{path}.rank")
    validate_link(card["source"], f"{path}.source")
    if "via" in card:
        validate_link(card["via"], f"{path}.via")
    if card["category"] == "CVEs" or "cve" in card:
        cve = require_fields(
            card.get("cve"), f"{path}.cve", id=str, severity=str, affected=str,
            exploited=str, fix=str,
        )
        if "cvss" not in cve:
            raise ValueError(f"{path}.cve.cvss is required")
        if cve["cvss"] is not None:
            require_number(cve["cvss"], f"{path}.cve.cvss")
    if "meta" in card:
        meta = require_fields(card["meta"], f"{path}.meta")
        if "seen_in" in meta:
            seen_in = meta["seen_in"]
            if not isinstance(seen_in, list) or any(not isinstance(name, str) for name in seen_in):
                raise ValueError(f"{path}.meta.seen_in must be an array of strings")
        if "hn_points" in meta:
            require_fields(meta, f"{path}.meta", hn_points=int)


def validate_feed(value: object, min_cards: int = 0) -> int:
    """Validate a feed and minimum card count, returning the number of cards."""
    feed = require_fields(value, "feed", version=int, generated_at=str, cards=list)
    if feed["version"] != 1:
        raise ValueError("feed.version must be 1")
    generated_at, cards = feed["generated_at"], feed["cards"]
    assert isinstance(generated_at, str) and isinstance(cards, list)
    require_utc(generated_at, "feed.generated_at")
    if len(cards) < min_cards:
        raise ValueError(f"feed has {len(cards)} cards, but at least {min_cards} are required")
    for index, card in enumerate(cards):
        validate_card(card, f"feed.cards[{index}]")
    return len(cards)


def main() -> int:
    """Read the CLI path and minimum count and return a process exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, nargs="?", default=Path("data/feed.json"))
    parser.add_argument("--min-cards", type=int, default=0)
    args = parser.parse_args()
    if args.min_cards < 0:
        parser.error("--min-cards must be non-negative")
    try:
        feed = json.loads(args.path.read_text(encoding="utf-8"))
        count = validate_feed(feed, args.min_cards)
    except (OSError, ValueError) as error:
        print(f"Feed validation failed for {args.path}: {error}", file=sys.stderr)
        return 1
    print(f"Validated {count} cards in {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
