"""Load configured news sources and turn recent items into deduplicated cards."""

from __future__ import annotations

import calendar
import hashlib
import html
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx
import yaml

from ingest.classify import classify_hn


LOGGER = logging.getLogger(__name__)
SOURCE_PATH = Path(__file__).with_name("sources.yaml")
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{}.json"
NEWS_WINDOW_HOURS = 48
SOURCE_CARD_LIMIT = 4
CATEGORY_CARD_LIMIT = 10
ARXIV_LIMIT = 2
TRACKING_PARAMS = {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "msclkid", "ref", "ref_src", "yclid"}
CVE_IN_TEXT = re.compile(r"CVE-\d{4}-\d{4,19}", re.I)
ARXIV_IN_URL = re.compile(r"/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$", re.I)
TITLE_STOP_WORDS = {"a", "an", "and", "are", "as", "at", "attacker", "attackers", "before", "by", "can", "for", "from", "in", "is", "its", "lets", "new", "of", "old", "on", "or", "server", "servers", "that", "the", "this", "to", "was", "were", "with", "year", "years"}


@dataclass(frozen=True)
class SourceSpec:
    """Describe one configured source and its limits."""

    id: str
    name: str
    category: str
    kind: str
    url: str
    enabled: bool
    max_items: int
    weight: float = 1.0


@dataclass(frozen=True)
class NewsItem:
    """Hold one parsed story before ranking and URL deduplication."""

    title: str
    url: str
    published: datetime
    body: str
    card_type: str = "article"
    mins: int = 2
    category: str | None = None
    via_url: str | None = None
    hn_points: int = 0


@dataclass
class SourceStats:
    """Count fetched and kept cards and retain a source error for logging."""

    source: str
    fetched: int = 0
    kept: int = 0
    error: str = "-"


@dataclass
class Candidate:
    """Bind a ranked card to its source for caps and duplicate merging."""

    card: dict[str, Any]
    source_id: str
    source_name: str
    source_kind: str
    weight: float
    rank: float
    seen_in: set[str] = field(default_factory=set)


class TLDRIssueParser(HTMLParser):
    """Collect linked article headlines from a TLDR issue page."""

    def __init__(self) -> None:
        """Initialize parser state; take no args; return nothing."""
        super().__init__(convert_charrefs=True)
        self.stories: list[tuple[str, str]] = []
        self.section_depth = 0
        self.section_sponsored = False
        self.header_depth = 0
        self.header_parts: list[str] = []
        self.article_depth = 0
        self.anchor_href: str | None = None
        self.headline_depth = 0
        self.headline_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track article structure; tag and attributes are inputs; return nothing."""
        if tag == "section":
            if self.section_depth == 0:
                self.section_sponsored = False
            self.section_depth += 1
        elif tag == "header" and self.section_depth:
            self.header_depth += 1
            self.header_parts = []
        elif tag == "article" and self.section_depth:
            self.article_depth += 1
        elif tag == "a" and self.article_depth and self.anchor_href is None:
            self.anchor_href = dict(attrs).get("href")
        elif tag == "h3" and self.anchor_href:
            self.headline_depth += 1
            self.headline_parts = []

    def handle_data(self, data: str) -> None:
        """Collect header and headline text; data is HTML text; return nothing."""
        if self.header_depth:
            self.header_parts.append(data)
        if self.headline_depth:
            self.headline_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        """Finish a section or headline; tag is the closing name; return nothing."""
        if tag == "h3" and self.headline_depth:
            self.headline_depth -= 1
            title = " ".join(" ".join(self.headline_parts).split())
            if title and self.anchor_href and not self.section_sponsored and not re.search(r"\b(sponsor|sponsored)\b", title, re.I):
                self.stories.append((title, self.anchor_href))
        elif tag == "a" and self.anchor_href is not None:
            self.anchor_href = None
        elif tag == "article" and self.article_depth:
            self.article_depth -= 1
        elif tag == "header" and self.header_depth:
            self.header_depth -= 1
            header = " ".join(self.header_parts).lower()
            if any(label in header for label in ("together with", "sponsored", "sponsor", "a message from")):
                self.section_sponsored = True
        elif tag == "section" and self.section_depth:
            self.section_depth -= 1


def load_sources(path: Path = SOURCE_PATH) -> list[SourceSpec]:
    """Load source definitions; path is the YAML file; return validated specifications."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("sources.yaml must contain a list")
    specs: list[SourceSpec] = []
    ids: set[str] = set()
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError("Each source must be a mapping")
        spec = SourceSpec(
            id=str(row["id"]), name=str(row["name"]), category=str(row["category"]),
            kind=str(row["kind"]), url=str(row["url"]), enabled=row["enabled"],
            max_items=int(row["max_items"]), weight=float(row.get("weight", 1.0)),
        )
        if spec.id in ids or spec.kind not in {"rss", "tldr", "hn", "arxiv"} or spec.category not in {"AI", "Development", "Cyber Security"} or spec.max_items < 1 or spec.weight <= 0:
            raise ValueError(f"Invalid source configuration: {spec.id}")
        ids.add(spec.id)
        specs.append(spec)
    return specs


def canonical_url(value: str) -> str | None:
    """Normalize an article URL; value is the raw link; return a canonical HTTP URL or None."""
    decoded = html.unescape(html.unescape(value.strip()))
    parts = urlsplit(decoded)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        return None
    host = parts.hostname.lower()
    if parts.port:
        host += f":{parts.port}"
    query = sorted((key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True) if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS)
    return urlunsplit((parts.scheme.lower(), host, parts.path.rstrip("/"), urlencode(query), ""))


def plain_text(value: str) -> str:
    """Strip feed HTML and collapse whitespace; value is source text; return plain text."""
    decoded = html.unescape(html.unescape(value))
    return " ".join(re.sub(r"<[^>]*>", " ", decoded).split())


def shorten(value: str, limit: int) -> str:
    """Shorten display text at a word; value and maximum length are inputs; return text."""
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    start = text[: limit - 1].rsplit(" ", 1)[0] or text[: limit - 1]
    return start.rstrip(" ,;:") + "…"


def first_sentences(value: str, limit: int, count: int) -> str:
    """Use initial sentences within a limit; value, length and count are inputs; return text."""
    text = plain_text(value)
    sentences = re.split(r"(?<=[.!?])\s+", text, maxsplit=count)
    chosen = " ".join(sentences[:count])
    if len(chosen) > limit:
        chosen = sentences[0]
    return shorten(chosen, limit)


def entry_time(entry: Any) -> datetime | None:
    """Read a feedparser entry date; entry is an RSS or Atom item; return UTC time or None."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime.fromtimestamp(calendar.timegm(parsed), timezone.utc) if parsed else None


def utc_text(value: datetime) -> str:
    """Format a datetime in UTC; value is the timestamp; return its ISO-8601 string."""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def recent(value: datetime, now: datetime) -> bool:
    """Check the 48-hour news window; value and now are datetimes; return eligibility."""
    hours = (now.astimezone(timezone.utc) - value.astimezone(timezone.utc)).total_seconds() / 3600
    return 0 <= hours <= NEWS_WINDOW_HOURS


def get_response(client: httpx.Client, url: str, **kwargs: Any) -> httpx.Response:
    """Fetch a public source with a timeout; client, URL and options are inputs; return response."""
    response = client.get(url, timeout=15.0, **kwargs)
    response.raise_for_status()
    return response


def parse_tldr_issue(issue_html: str, issue_url: str, published: datetime, source: SourceSpec) -> list[NewsItem]:
    """Split one TLDR issue; HTML, issue URL, date and source are inputs; return stories."""
    parser = TLDRIssueParser()
    parser.feed(issue_html)
    stories: list[NewsItem] = []
    for raw_title, raw_url in parser.stories:
        article_url = canonical_url(raw_url)
        host = urlsplit(article_url).hostname if article_url else None
        if not article_url or not host or host == "tldr.tech" or host.endswith(".tldr.tech") or host.endswith(".typeform.com"):
            continue
        title = re.sub(r"\s*\(\d+ minutes? read\)$", "", raw_title, flags=re.I)
        if re.search(r"\(\d+ minutes? form\)$|\(product launch\)$", title, re.I):
            continue
        stories.append(NewsItem(title=title, url=article_url, published=published, body=f"Via {source.name}.", via_url=issue_url))
    return stories


def parse_rss(content: bytes, source: SourceSpec) -> list[NewsItem]:
    """Parse a generic RSS or Atom feed; bytes and source are inputs; return stories."""
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Invalid RSS/Atom from {source.name}: {feed.bozo_exception}")
    stories: list[NewsItem] = []
    for entry in feed.entries[: source.max_items]:
        published = entry_time(entry)
        if not published or not entry.get("title") or not entry.get("link"):
            continue
        stories.append(NewsItem(
            title=plain_text(entry.title), url=entry.link, published=published,
            body=first_sentences(entry.get("summary", ""), 200, 1) or "See the source article.",
        ))
    return stories


def parse_arxiv(content: bytes, source: SourceSpec, now: datetime) -> list[NewsItem]:
    """Parse arXiv Atom papers; bytes, source and now are inputs; return recent papers."""
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Invalid arXiv Atom: {feed.bozo_exception}")
    papers: list[NewsItem] = []
    for entry in feed.entries:
        published = entry_time(entry)
        if not published or not recent(published, now) or not entry.get("title") or not entry.get("link"):
            continue
        papers.append(NewsItem(
            title=plain_text(entry.title), url=entry.link, published=published,
            body=first_sentences(entry.get("summary", ""), 220, 2), card_type="paper", mins=5,
        ))
        if len(papers) >= source.max_items:
            break
    return papers


def fetch_tldr(client: httpx.Client, source: SourceSpec, now: datetime) -> list[NewsItem]:
    """Fetch one TLDR feed and recent issue pages; client, source and now are inputs; return stories."""
    feed = feedparser.parse(get_response(client, source.url).content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Invalid TLDR RSS: {feed.bozo_exception}")
    stories: list[NewsItem] = []
    seen_issues: set[str] = set()
    for entry in feed.entries:
        published = entry_time(entry)
        issue_url = str(entry.get("link", ""))
        if not published or not recent(published, now) or not issue_url or issue_url in seen_issues:
            continue
        seen_issues.add(issue_url)
        issue_html = get_response(client, issue_url).text
        stories.extend(parse_tldr_issue(issue_html, issue_url, published, source))
        if len(stories) >= source.max_items:
            break
    return stories[: source.max_items]


def fetch_hn(client: httpx.Client, source: SourceSpec) -> list[NewsItem]:
    """Fetch HN top 30 IDs and qualifying items; client and source are inputs; return stories."""
    ids = get_response(client, source.url).json()
    if not isinstance(ids, list):
        raise ValueError("HN top stories response is not a list")
    stories: list[NewsItem] = []
    for item_id in ids[:30]:
        if not isinstance(item_id, int):
            continue
        try:
            item = get_response(client, HN_ITEM_URL.format(item_id)).json()
        except (httpx.HTTPError, ValueError) as error:
            LOGGER.warning("HN item %s failed: %s", item_id, error)
            continue
        if not isinstance(item, dict) or item.get("type") != "story" or item.get("dead") or item.get("deleted"):
            continue
        if not isinstance(item.get("score"), int) or item["score"] < 100 or not item.get("url") or not item.get("title") or not isinstance(item.get("time"), int):
            continue
        stories.append(NewsItem(
            title=plain_text(item["title"]), url=item["url"],
            published=datetime.fromtimestamp(item["time"], timezone.utc),
            body="Discussed on Hacker News.", category=classify_hn(item["title"]),
            hn_points=item["score"],
        ))
    return stories[: source.max_items]


def fetch_arxiv(client: httpx.Client, source: SourceSpec, now: datetime) -> list[NewsItem]:
    """Fetch recent AI papers; client, source and now are inputs; return parsed papers."""
    params = {"search_query": "cat:cs.AI OR cat:cs.LG OR cat:cs.CL", "start": 0, "max_results": 50, "sortBy": "submittedDate", "sortOrder": "descending"}
    return parse_arxiv(get_response(client, source.url, params=params).content, source, now)


def fetch_source(client: httpx.Client, source: SourceSpec, now: datetime) -> list[NewsItem]:
    """Fetch a configured source; client, specification and now are inputs; return stories."""
    if source.kind == "tldr":
        return fetch_tldr(client, source, now)
    if source.kind == "hn":
        return fetch_hn(client, source)
    if source.kind == "arxiv":
        return fetch_arxiv(client, source, now)
    return parse_rss(get_response(client, source.url).content, source)


def make_candidate(item: NewsItem, source: SourceSpec, now: datetime) -> Candidate | None:
    """Rank a fresh news item; item, source and now are inputs; return candidate or None."""
    url = canonical_url(item.url)
    title = shorten(plain_text(item.title), 90)
    if not url or not title or not recent(item.published, now):
        return None
    age_hours = (now - item.published.astimezone(timezone.utc)).total_seconds() / 3600
    recency_factor = 2 ** (-age_hours / 24)
    rank = float(source.weight * recency_factor + math.log1p(item.hn_points) * 0.2)
    source_name = (urlsplit(url).hostname or source.name) if source.kind == "tldr" else source.name
    card: dict[str, Any] = {
        "id": "news:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:24],
        "category": item.category or source.category,
        "type": item.card_type,
        "hook": title,
        "body": plain_text(item.body),
        "mins": item.mins,
        "source": {"name": source_name, "url": url},
        "published": utc_text(item.published),
        "rank": rank,
        "meta": {"seen_in": [source.name]},
    }
    if item.via_url:
        card["via"] = {"name": source.name, "url": item.via_url}
    if item.hn_points:
        card["meta"]["hn_points"] = item.hn_points
    return Candidate(card=card, source_id=source.id, source_name=source.name, source_kind=source.kind, weight=source.weight, rank=rank, seen_in={source.name})


def title_words(title: str) -> set[str]:
    """Reduce a headline to meaningful words; title is input; return a lowercase word set."""
    lowered = plain_text(title).lower()
    lowered = re.sub(r"\b(?:remote code execution|code execution|execute code)\b", "rce", lowered)
    return {word for word in re.findall(r"[a-z0-9]+", lowered) if len(word) > 2 and word not in TITLE_STOP_WORDS}


def title_similarity(first: str, second: str) -> float:
    """Measure headline Jaccard similarity; two titles are inputs; return a value from 0 to 1."""
    left, right = title_words(first), title_words(second)
    return len(left & right) / len(left | right) if left and right else 0.0


def story_cves(card: dict[str, Any]) -> set[str]:
    """Find CVE identifiers in a news card; card is input; return uppercase IDs."""
    combined = " ".join((card["hook"], card["body"], card["source"]["url"]))
    return {match.upper() for match in CVE_IN_TEXT.findall(combined)}


def same_story(first: Candidate, second: Candidate) -> bool:
    """Compare two news cards in one category; candidates are inputs; return duplicate status."""
    if first.card["category"] != second.card["category"]:
        return False
    first_cves, second_cves = story_cves(first.card), story_cves(second.card)
    return bool(first_cves & second_cves) or title_similarity(first.card["hook"], second.card["hook"]) >= 0.6


def arxiv_id(url: str) -> str | None:
    """Extract an arXiv paper ID; URL is input; return the ID without version or None."""
    parsed = urlsplit(url)
    if parsed.hostname not in {"arxiv.org", "www.arxiv.org"}:
        return None
    match = ARXIV_IN_URL.search(parsed.path)
    return match.group(1) if match else None


def paper_matches_provider(paper: Candidate, provider: Candidate) -> bool:
    """Match a paper with TLDR or HN; candidates are inputs; return overlap status."""
    paper_id = arxiv_id(paper.card["source"]["url"])
    provider_id = arxiv_id(provider.card["source"]["url"])
    if paper_id and provider_id and paper_id == provider_id:
        return True
    return title_similarity(paper.card["hook"], provider.card["hook"]) >= 0.6


def select_papers(candidates: list[Candidate]) -> list[Candidate]:
    """Keep two arXiv candidates, preferring TLDR/HN overlap; candidates are input; return list."""
    papers = [candidate for candidate in candidates if candidate.source_kind == "arxiv"]
    providers = [candidate for candidate in candidates if candidate.source_kind in {"tldr", "hn"}]
    papers.sort(key=lambda paper: (
        any(paper_matches_provider(paper, provider) for provider in providers),
        paper.rank, paper.card["published"], paper.card["id"],
    ), reverse=True)
    selected = {id(candidate) for candidate in papers[:ARXIV_LIMIT]}
    return [candidate for candidate in candidates if candidate.source_kind != "arxiv" or id(candidate) in selected]


def merge_providers(winner: Candidate, other: Candidate, now: datetime) -> None:
    """Combine duplicate provenance and HN points; candidates and now are inputs; return nothing."""
    winner.seen_in |= other.seen_in
    points = max(winner.card["meta"].get("hn_points", 0), other.card["meta"].get("hn_points", 0))
    if points:
        winner.card["meta"]["hn_points"] = points
        published = datetime.fromisoformat(winner.card["published"].replace("Z", "+00:00"))
        age_hours = (now - published).total_seconds() / 3600
        winner.rank = float(winner.weight * 2 ** (-age_hours / 24) + math.log1p(points) * 0.2)
        winner.card["rank"] = winner.rank


def run_sources(client: httpx.Client, sources: list[SourceSpec], now: datetime) -> tuple[list[dict[str, Any]], list[SourceStats]]:
    """Fetch, dedupe and cap news; client, sources and now are inputs; return cards and stats."""
    candidates: list[Candidate] = []
    stats: list[SourceStats] = []
    for source in sources:
        if not source.enabled:
            continue
        row = SourceStats(source=source.name)
        stats.append(row)
        try:
            items = fetch_source(client, source, now)
            row.fetched = len(items)
            for item in items:
                candidate = make_candidate(item, source, now)
                if candidate:
                    candidates.append(candidate)
        except Exception as error:
            row.error = str(error)
            LOGGER.error("%s ingest failed: %s", source.name, error)
    candidates = select_papers(candidates)
    by_url: dict[str, Candidate] = {}
    for candidate in candidates:
        key = candidate.card["source"]["url"]
        old = by_url.get(key)
        if old is None:
            by_url[key] = candidate
            continue
        winner = max((old, candidate), key=lambda choice: (choice.rank, choice.card["published"], choice.source_id))
        merge_providers(winner, candidate if winner is old else old, now)
        by_url[key] = winner
    ranked = sorted(by_url.values(), key=lambda candidate: (candidate.rank, candidate.card["published"], candidate.card["id"]), reverse=True)
    distinct: list[Candidate] = []
    for candidate in ranked:
        duplicate = next((existing for existing in distinct if same_story(existing, candidate)), None)
        if duplicate:
            merge_providers(duplicate, candidate, now)
        else:
            distinct.append(candidate)
    ranked = sorted(distinct, key=lambda candidate: (candidate.rank, candidate.card["published"], candidate.card["id"]), reverse=True)
    kept: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    stats_by_name = {row.source: row for row in stats}
    for candidate in ranked:
        category = candidate.card["category"]
        if source_counts.get(candidate.source_id, 0) >= SOURCE_CARD_LIMIT or category_counts.get(category, 0) >= CATEGORY_CARD_LIMIT:
            continue
        candidate.card["meta"]["seen_in"] = sorted(candidate.seen_in)
        kept.append(candidate.card)
        source_counts[candidate.source_id] = source_counts.get(candidate.source_id, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        stats_by_name[candidate.source_name].kept += 1
    return kept, stats
