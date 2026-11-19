"""Tests for the scheduled feed validator."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.validate_feed import validate_feed


@pytest.fixture
def feed() -> dict:
    """Return a minimal version 1 feed with one news card."""
    return {
        "version": 1,
        "generated_at": "2026-11-19T12:00:00Z",
        "cards": [{
            "id": "news:abc",
            "category": "AI",
            "type": "article",
            "hook": "A headline",
            "body": "A short explanation.",
            "mins": 2,
            "source": {"name": "Example", "url": "https://example.com/article"},
            "published": "2026-11-19T10:00:00+00:00",
            "rank": 1.5,
            "via": {"name": "Example newsletter", "url": "http://example.com/issue"},
            "meta": {"seen_in": ["Example"], "hn_points": 4},
        }],
    }


def test_valid_feed_with_cve(feed: dict) -> None:
    """Accept news and CVE cards, including an unknown CVSS score."""
    card = feed["cards"][0]
    cve_card = {
        **card,
        "id": "cve:CVE-2026-12345",
        "category": "CVEs",
        "type": "advisory",
        "cve": {
            "id": "CVE-2026-12345", "cvss": None, "severity": "Unknown",
            "affected": "Example", "exploited": "Unknown", "fix": "Update",
        },
    }
    feed["cards"].append(cve_card)
    assert validate_feed(feed) == 2
    del cve_card["cve"]
    with pytest.raises(ValueError, match=r"cve must be an object"):
        validate_feed(feed)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("category", "Other", "category must be one of"),
        ("id", "invalid", "id must be a CVE ID or news URL hash"),
        ("type", "video", "type must be one of"),
        ("hook", "a" * 91, "hook must be at most 90 characters"),
        ("mins", True, "mins must be of type int"),
        ("rank", float("nan"), "rank must be a finite number"),
        ("published", "2026-11-19T10:00:00+01:00", "published must be an ISO-8601 UTC timestamp"),
        ("source", {"name": "Example", "url": "ftp://example.com"}, "source.url must start"),
        ("via", {"name": "Example", "url": "//example.com"}, "via.url must start"),
        ("meta", {"seen_in": [1]}, "meta.seen_in must be an array of strings"),
    ],
)
def test_invalid_card(feed: dict, field: str, value: object, message: str) -> None:
    """Reject an invalid card field and identify it in the error."""
    feed["cards"][0][field] = value
    with pytest.raises(ValueError, match=message):
        validate_feed(feed)


@pytest.mark.parametrize(("container", "field"), [("feed", "generated_at"), ("card", "body")])
def test_missing_required_field(feed: dict, container: str, field: str) -> None:
    """Reject a missing required field in the feed or card."""
    target = feed if container == "feed" else feed["cards"][0]
    del target[field]
    with pytest.raises(ValueError, match=rf"\.{field} is required"):
        validate_feed(feed)


@pytest.mark.parametrize(
    ("contents", "exit_code", "message"),
    [
        (None, 1, "Feed validation failed"),
        (14, 1, "feed has 14 cards, but at least 15 are required"),
        (15, 0, "Validated 15 cards"),
    ],
)
def test_cli(
    feed: dict, tmp_path: Path, contents: int | None, exit_code: int, message: str,
) -> None:
    """Check CLI exit status and messages for malformed, short, and valid feeds."""
    path = tmp_path / "feed.json"
    if contents is not None:
        feed["cards"] *= contents
    path.write_text("{" if contents is None else json.dumps(feed), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "scripts/validate_feed.py", "--min-cards", "15", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == exit_code
    assert message in (result.stderr if exit_code else result.stdout)
