"""Network-free tests for configured news sources and card selection."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from ingest.classify import classify_hn
from ingest.news import (
    NewsItem, SourceSpec, canonical_url, fetch_hn, fetch_tldr, load_sources,
    make_candidate, parse_arxiv, parse_rss, plain_text, run_sources,
    same_story, select_papers, title_similarity,
)


FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def fixture_bytes(name: str) -> bytes:
    """Read a synthetic fixture; name is its filename; return bytes."""
    return (FIXTURES / name).read_bytes()


def source(source_id: str, name: str, kind: str, url: str, category: str = "Development", max_items: int = 20) -> SourceSpec:
    """Build a source for tests; identifiers and settings are inputs; return a specification."""
    return SourceSpec(id=source_id, name=name, category=category, kind=kind, url=url, enabled=True, max_items=max_items)


def test_tldr_issue_split_sponsor_skip_and_clean_links() -> None:
    """Check TLDR issue expansion and outbound links; take no args and return nothing."""
    spec = source("tldr_ai", "TLDR AI", "tldr", "https://tldr.test/rss", "AI")
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve a synthetic issue and RSS feed; request is input; return a fake response."""
        calls.append(str(request.url))
        filename = "tldr_issues.xml" if str(request.url) == spec.url else "tldr_issue.html"
        return httpx.Response(200, content=fixture_bytes(filename))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        stories = fetch_tldr(client, spec, NOW)
    assert len(calls) == 2
    assert [story.title for story in stories] == ["Useful engineering story", "Another useful story"]
    assert stories[0].url == "https://example.com/story?keep=yes"
    assert stories[0].via_url == "https://tldr.tech/ai/2026-11-18"
    assert stories[0].body == "Via TLDR AI."
    card = make_candidate(stories[0], spec, NOW)
    assert card is not None
    assert card.card["via"] == {"name": "TLDR AI", "url": "https://tldr.tech/ai/2026-11-18"}
    assert card.card["source"]["url"] == "https://example.com/story?keep=yes"


def test_canonical_url_drops_tracking_and_fragment() -> None:
    """Check URL normalization; take no args and return nothing."""
    assert canonical_url("https://EXAMPLE.com/Path/?utm_campaign=x&fbclid=y&b=2&a=1#frag") == "https://example.com/Path?a=1&b=2"
    assert canonical_url("mailto:test@example.com") is None


def test_hn_score_url_and_classifier() -> None:
    """Check HN filters and keyword categories; take no args and return nothing."""
    spec = source("hn", "Hacker News", "hn", "https://hacker-news.firebaseio.com/v0/topstories.json", max_items=30)
    fixture: dict[str, Any] = json.loads(fixture_bytes("hn.json"))
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve synthetic HN IDs and items; request is input; return a fake response."""
        calls.append(str(request.url))
        if str(request.url) == spec.url:
            return httpx.Response(200, json=fixture["top"])
        item_id = request.url.path.split("/")[-1].removesuffix(".json")
        item = dict(fixture["items"][item_id])
        item["time"] = int((NOW - timedelta(hours=1)).timestamp())
        return httpx.Response(200, json=item)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        stories = fetch_hn(client, spec)
    assert len(calls) == 6
    assert len(stories) == 3
    assert {story.category for story in stories} == {"AI", "Cyber Security", "Development"}
    assert [story.hn_points for story in stories] == [150, 180, 100]
    assert classify_hn("A security flaw in an AI model") == "Cyber Security"
    assert classify_hn("Unauthenticated remote code execution in Nginx") == "Cyber Security"
    assert make_candidate(stories[0], spec, NOW).card["meta"]["hn_points"] == 150


def test_arxiv_atom_papers_and_abstract() -> None:
    """Check arXiv date filtering and abstract text; take no args and return nothing."""
    spec = source("arxiv", "arXiv", "arxiv", "https://export.arxiv.org/api/query", "AI", 5)
    papers = parse_arxiv(fixture_bytes("arxiv.xml"), spec, NOW)
    assert len(papers) == 1
    assert papers[0].card_type == "paper"
    assert papers[0].mins == 5
    assert papers[0].body == "We describe a small model. It reduces latency."
    assert len(papers[0].body) <= 220


def test_arxiv_two_paper_cap_prefers_tldr_and_hn_overlap(monkeypatch: Any) -> None:
    """Check arXiv's two-paper cap and overlap preference; monkeypatch avoids HTTP."""
    arxiv = source("arxiv", "arXiv", "arxiv", "https://arxiv.example/query", "AI", 10)
    tldr = source("tldr", "TLDR AI", "tldr", "https://tldr.example/rss", "AI")
    hn = source("hn", "Hacker News", "hn", "https://hn.example/top", "AI")
    papers = parse_arxiv(fixture_bytes("arxiv_many.xml"), arxiv, NOW)
    assert len(papers) == 4
    title_match = NewsItem(title="Shared Research Three", url="https://another.example/research", published=NOW, body="Via TLDR AI.")
    id_match = NewsItem(title="A separate discussion", url="https://arxiv.org/pdf/2611.00004", published=NOW, body="Discussed on Hacker News.")
    candidates = [make_candidate(paper, arxiv, NOW) for paper in papers]
    candidates.extend([make_candidate(title_match, tldr, NOW), make_candidate(id_match, hn, NOW)])
    selected = select_papers([candidate for candidate in candidates if candidate is not None])
    selected_papers = [candidate.card["source"]["url"] for candidate in selected if candidate.source_kind == "arxiv"]
    assert selected_papers == ["https://arxiv.org/abs/2611.00003", "https://arxiv.org/abs/2611.00004"]

    def fake_fetch(client: httpx.Client, spec: SourceSpec, now: datetime) -> list[NewsItem]:
        """Return synthetic arXiv papers; inputs are unused; return fixture papers."""
        return papers

    def unexpected_request(request: httpx.Request) -> httpx.Response:
        """Reject unexpected HTTP; request is unused; return a fake error response."""
        return httpx.Response(500)

    monkeypatch.setattr("ingest.news.fetch_source", fake_fetch)
    with httpx.Client(transport=httpx.MockTransport(unexpected_request)) as client:
        cards, stats = run_sources(client, [arxiv], NOW)
    assert len(cards) == stats[0].kept == 2
    assert all(card["type"] == "paper" for card in cards)


def test_news_text_normalization() -> None:
    """Check markup and whitespace boundaries in cards; take no args and return nothing."""
    assert plain_text("Selection<b>Base</b>\nTools\t in") == "Selection Base Tools in"
    spec = source("rss", "RSS", "rss", "https://rss.example/feed")
    item = NewsItem(title="Selection<b>Base</b>\nTools\t in", url="https://example.com/story", published=NOW, body="<p>First</p>\n<p>second</p> sentence.")
    candidate = make_candidate(item, spec, NOW)
    assert candidate is not None
    assert candidate.card["hook"] == "Selection Base Tools in"
    assert candidate.card["body"] == "First second sentence."


def test_rss_first_sentence_and_url_dedupe() -> None:
    """Check RSS summaries and duplicate provider metadata; take no args and return nothing."""
    first = source("a", "Source A", "rss", "https://source-a.example/rss")
    second = source("b", "Source B", "rss", "https://source-b.example/rss")

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve two feeds with one shared article; request is input; return a fake response."""
        name = "rss_a.xml" if str(request.url) == first.url else "rss_b.xml"
        return httpx.Response(200, content=fixture_bytes(name))

    parsed = parse_rss(fixture_bytes("rss_a.xml"), first)
    assert parsed[0].body == "First sentence."
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        cards, stats = run_sources(client, [first, second], NOW)
    assert len(cards) == 1
    assert cards[0]["source"]["url"] == "https://example.com/news?id=7"
    assert cards[0]["meta"]["seen_in"] == ["Source A", "Source B"]
    assert sum(row.kept for row in stats) == 1


def test_fuzzy_title_and_shared_cve_dedupe(monkeypatch: Any) -> None:
    """Check same-story merging across article URLs; monkeypatch supplies fixture items."""
    fixture: dict[str, Any] = json.loads(fixture_bytes("news_duplicates.json"))
    nginx = fixture["nginx"]
    assert title_similarity(nginx[0]["title"], nginx[1]["title"]) >= 0.6
    assert title_similarity(fixture["cve"][0]["title"], fixture["cve"][1]["title"]) < 0.6

    def fake_fetch(client: httpx.Client, spec: SourceSpec, now: datetime) -> list[NewsItem]:
        """Return a publisher's fixture story; source selects the item; return one story."""
        row = next(row for row in current if row["provider"] == spec.name)
        return [NewsItem(title=row["title"], url=row["url"], published=NOW, body=row["body"])]

    def unexpected_request(request: httpx.Request) -> httpx.Response:
        """Reject unexpected HTTP; request is unused; return a fake error response."""
        return httpx.Response(500)

    monkeypatch.setattr("ingest.news.fetch_source", fake_fetch)
    for key in ("nginx", "cve"):
        current = fixture[key]
        specs = [source(str(index), row["provider"], "rss", f"https://feed{index}.example/rss", "Cyber Security") for index, row in enumerate(current)]
        with httpx.Client(transport=httpx.MockTransport(unexpected_request)) as client:
            cards, _ = run_sources(client, specs, NOW)
        assert len(cards) == 1
        assert cards[0]["meta"]["seen_in"] == sorted(row["provider"] for row in current)


def test_fuzzy_dedupe_keeps_higher_rank_within_category(monkeypatch: Any) -> None:
    """Check category scope and winner ranking; monkeypatch supplies articles; return nothing."""
    lower = SourceSpec("lower", "Lower", "Cyber Security", "rss", "https://lower.example/rss", True, 1, 1.0)
    higher = SourceSpec("higher", "Higher", "Cyber Security", "rss", "https://higher.example/rss", True, 1, 2.0)
    other_category = source("other", "Other", "rss", "https://other.example/rss", "Development", 1)
    first = make_candidate(NewsItem("Nginx security issue CVE-2026-71001", "https://lower.example/a", NOW, "Details."), lower, NOW)
    second = make_candidate(NewsItem("Nginx security issue CVE-2026-71002", "https://higher.example/b", NOW, "Details."), higher, NOW)
    assert first is not None and second is not None and same_story(first, second)

    def fake_fetch(client: httpx.Client, spec: SourceSpec, now: datetime) -> list[NewsItem]:
        """Return matching headlines from different providers; inputs choose URL; return one item."""
        return [NewsItem(title="Important Nginx security update", url=f"https://{spec.id}.example/story", published=NOW, body="Details.")]

    monkeypatch.setattr("ingest.news.fetch_source", fake_fetch)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))) as client:
        cards, _ = run_sources(client, [lower, higher, other_category], NOW)
    assert len(cards) == 2
    cyber = next(card for card in cards if card["category"] == "Cyber Security")
    assert cyber["source"]["url"] == "https://higher.example/story"
    assert cyber["meta"]["seen_in"] == ["Higher", "Lower"]
    assert cyber["rank"] == 2.0
    assert next(card for card in cards if card["category"] == "Development")["meta"]["seen_in"] == ["Other"]


def test_per_source_and_category_caps(monkeypatch: Any) -> None:
    """Check four-per-source and ten-per-category limits; monkeypatch supplies stories."""
    specs = [source(f"s{index}", f"Source {index}", "rss", f"https://source-{index}.example/rss", "AI") for index in range(4)]

    def fake_fetch(client: httpx.Client, spec: SourceSpec, now: datetime) -> list[NewsItem]:
        """Return five synthetic articles per source; inputs select URLs; return stories."""
        return [NewsItem(title=f"Project{spec.id} feature{number}", url=f"https://example.com/{spec.id}/{number}", published=NOW - timedelta(minutes=number), body="Summary.") for number in range(5)]

    def unexpected_request(request: httpx.Request) -> httpx.Response:
        """Reject unexpected HTTP; request is unused; return a fake error response."""
        return httpx.Response(500)

    monkeypatch.setattr("ingest.news.fetch_source", fake_fetch)
    with httpx.Client(transport=httpx.MockTransport(unexpected_request)) as client:
        cards, stats = run_sources(client, specs, NOW)
    assert len(cards) == 10
    assert all(row.kept <= 4 for row in stats)
    assert sum(row.kept for row in stats) == 10


def test_duplicate_hn_points_use_rank_formula(monkeypatch: Any) -> None:
    """Check merged HN points affect duplicate rank; monkeypatch supplies stories; return nothing."""
    rss = SourceSpec(id="rss", name="RSS", category="Development", kind="rss", url="https://rss.example/feed", enabled=True, max_items=1, weight=3.0)
    hn = source("hn", "Hacker News", "hn", "https://hn.example/top")

    def fake_fetch(client: httpx.Client, spec: SourceSpec, now: datetime) -> list[NewsItem]:
        """Return one shared article; inputs identify the source; return a synthetic item."""
        points = 100 if spec.kind == "hn" else 0
        return [NewsItem(title="Shared story", url="https://example.com/shared", published=NOW, body="Summary.", hn_points=points)]

    def unexpected_request(request: httpx.Request) -> httpx.Response:
        """Reject unexpected HTTP; request is unused; return a fake error response."""
        return httpx.Response(500)

    monkeypatch.setattr("ingest.news.fetch_source", fake_fetch)
    with httpx.Client(transport=httpx.MockTransport(unexpected_request)) as client:
        cards, _ = run_sources(client, [rss, hn], NOW)
    assert len(cards) == 1
    assert cards[0]["meta"] == {"seen_in": ["Hacker News", "RSS"], "hn_points": 100}
    assert math.isclose(cards[0]["rank"], 3.0 + math.log1p(100) * 0.2)


def test_one_source_error_does_not_stop_others() -> None:
    """Check per-source failure isolation; take no args and return nothing."""
    failed = source("bad", "Broken Feed", "rss", "https://bad.example/rss")
    working = source("good", "Working Feed", "rss", "https://good.example/rss")

    def respond(request: httpx.Request) -> httpx.Response:
        """Fail one feed and serve the other; request is input; return a fake response."""
        return httpx.Response(503) if str(request.url) == failed.url else httpx.Response(200, content=fixture_bytes("rss_a.xml"))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        cards, stats = run_sources(client, [failed, working], NOW)
    assert len(cards) == 1
    assert stats[0].error != "-"
    assert stats[1].kept == 1


def test_plain_rss_needs_only_yaml_entry() -> None:
    """Check default weight for a new RSS source; take no args and return nothing."""
    specs = load_sources(FIXTURES / "sources_minimal.yaml")
    assert len(specs) == 1
    assert specs[0].kind == "rss"
    assert specs[0].weight == 1.0
