"""Fetch CISA KEV and recent NVD CVEs and write the version 1 feed."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import httpx

from ingest.news import SourceStats, load_sources, plain_text, run_sources


LOGGER = logging.getLogger(__name__)
CISA_URL = "https://raw.githubusercontent.com/cisagov/kev-data/main/known_exploited_vulnerabilities.json"
CISA_PAGE = "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"
NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
NVD_DETAIL = "https://nvd.nist.gov/vuln/detail/"
FEED_PATH = Path(__file__).resolve().parent.parent / "data" / "feed.json"
PAGE_SIZE = 2000
CARD_LIMIT = 10
KEV_LIMIT = 6
KEV_WINDOW_DAYS = 7
MIN_NVD_CVSS = 7.0
CVE_PATTERN = re.compile(r"^CVE-\d{4}-\d{4,19}$")


def utc_text(value: datetime) -> str:
    """Format a datetime as ISO-8601 UTC; value is the datetime; return its UTC string."""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_datetime(value: str) -> datetime:
    """Parse an ISO-8601 date or datetime; value is the source text; return a UTC datetime."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def clean_text(value: Any) -> str:
    """Strip markup and collapse whitespace; value is any JSON value; return display text."""
    return plain_text(value) if isinstance(value, str) else ""


def trim_text(value: str, limit: int) -> str:
    """Trim text at a word boundary; value is text and limit is characters; return shortened text."""
    if len(value) <= limit:
        return value
    shortened = value[: limit - 1].rsplit(" ", 1)[0]
    return (shortened or value[: limit - 1]).rstrip(" ,;:") + "…"


def body_text(value: str) -> str:
    """Keep one or two short sentences; value is a source description; return card body text."""
    sentences = re.split(r"(?<=[.!?])\s+", clean_text(value), maxsplit=2)
    first_two = " ".join(sentences[:2])
    selected = first_two if len(first_two) <= 320 else sentences[0]
    result = trim_text(selected, 320)
    return result if not result or result[-1] in ".!?…" else result + "."


def description_text(descriptions: Any) -> str:
    """Choose an English NVD description; descriptions is a JSON list; return its plain text."""
    if not isinstance(descriptions, list):
        return ""
    for item in descriptions:
        if isinstance(item, dict) and item.get("lang") == "en":
            return clean_text(item.get("value"))
    return ""


def metric_details(metrics: Any) -> tuple[float | None, str]:
    """Read the best available CVSS metric; metrics is an NVD object; return score and severity."""
    if not isinstance(metrics, dict):
        return None, "Unknown"
    for name in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        entries = metrics.get(name)
        if not isinstance(entries, list):
            continue
        primary = sorted((entry for entry in entries if isinstance(entry, dict)), key=lambda entry: entry.get("type") != "Primary")
        for entry in primary:
            data = entry.get("cvssData")
            if not isinstance(data, dict):
                continue
            score = data.get("baseScore")
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                continue
            severity = clean_text(data.get("baseSeverity") or entry.get("baseSeverity"))
            return float(score), severity.title() if severity else "Unknown"
    return None, "Unknown"


def cpe_matches(node: Any) -> Iterator[dict[str, Any]]:
    """Walk an NVD configuration node; node is JSON; yield vulnerable CPE matches."""
    if not isinstance(node, dict):
        return
    for match in node.get("cpeMatch", []):
        if isinstance(match, dict) and match.get("vulnerable") is True:
            yield match
    for child in node.get("children", []):
        yield from cpe_matches(child)


def cpe_details(configurations: Any) -> tuple[str | None, str | None]:
    """Read one vulnerable CPE; configurations is NVD JSON; return product and affected text."""
    if not isinstance(configurations, list):
        return None, None
    for configuration in configurations:
        if not isinstance(configuration, dict):
            continue
        for node in configuration.get("nodes", []):
            for match in cpe_matches(node):
                parts = str(match.get("criteria", "")).split(":")
                if len(parts) < 6:
                    continue
                vendor, product, version = parts[3:6]
                if vendor in ("*", "-") or product in ("*", "-"):
                    continue
                label = clean_text(f"{vendor.replace('_', ' ')} {product.replace('_', ' ')}").title()
                bounds = []
                for key, marker in (("versionStartIncluding", "from"), ("versionStartExcluding", "after"), ("versionEndIncluding", "through"), ("versionEndExcluding", "before")):
                    if match.get(key):
                        bounds.append(f"{marker} {match[key]}")
                if bounds:
                    return label, f"{label} {' '.join(bounds)}"
                if version not in ("*", "-"):
                    return label, f"{label} {version}"
                return label, label
    return None, None


def affected_text(configurations: Any, affected: Any = None) -> str:
    """Describe a vulnerable version; configurations and affected are NVD JSON; return text or fallback."""
    _, cpe_affected = cpe_details(configurations)
    if cpe_affected:
        return cpe_affected
    if isinstance(affected, list):
        for group in affected:
            if not isinstance(group, dict) or not isinstance(group.get("affectedData"), list):
                continue
            for product in group["affectedData"]:
                if not isinstance(product, dict):
                    continue
                label = " ".join(filter(None, (clean_text(product.get("vendor")), clean_text(product.get("product")))))
                for version in product.get("versions", []):
                    if not isinstance(version, dict) or version.get("status") != "affected":
                        continue
                    start = clean_text(version.get("version"))
                    if not label or not start or start == "*":
                        continue
                    if version.get("lessThan"):
                        return f"{label} {start} to before {version['lessThan']}"
                    if version.get("lessThanOrEqual"):
                        return f"{label} {start} through {version['lessThanOrEqual']}"
                    return f"{label} {start}"
    return "See advisory"


def parse_cisa(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse CISA's KEV catalog; payload is its JSON object; return usable CVE records."""
    records = payload.get("vulnerabilities")
    if not isinstance(records, list):
        raise ValueError("CISA payload has no vulnerabilities list")
    parsed: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict) or not CVE_PATTERN.fullmatch(str(item.get("cveID", ""))):
            continue
        try:
            published = utc_text(datetime.combine(date.fromisoformat(item["dateAdded"]), datetime.min.time(), timezone.utc))
        except (KeyError, TypeError, ValueError):
            continue
        parsed.append({
            "id": item["cveID"],
            "published": published,
            "vendor": clean_text(item.get("vendorProject")),
            "product": clean_text(item.get("product")),
            "name": clean_text(item.get("vulnerabilityName")),
            "description": clean_text(item.get("shortDescription")),
            "fix": clean_text(item.get("requiredAction")) or "See advisory",
        })
    return parsed


def parse_nvd(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse one NVD API page; payload is its JSON object; return usable CVE records."""
    vulnerabilities = payload.get("vulnerabilities")
    if not isinstance(vulnerabilities, list):
        raise ValueError("NVD payload has no vulnerabilities list")
    parsed: list[dict[str, Any]] = []
    for wrapper in vulnerabilities:
        if not isinstance(wrapper, dict) or not isinstance(wrapper.get("cve"), dict):
            continue
        cve = wrapper["cve"]
        cve_id = cve.get("id")
        if not isinstance(cve_id, str) or not CVE_PATTERN.fullmatch(cve_id) or cve.get("vulnStatus") == "Rejected":
            continue
        try:
            published = utc_text(parse_datetime(cve["published"]))
        except (KeyError, TypeError, ValueError):
            continue
        score, severity = metric_details(cve.get("metrics"))
        product, _ = cpe_details(cve.get("configurations"))
        parsed.append({
            "id": cve_id,
            "published": published,
            "description": description_text(cve.get("descriptions")),
            "cvss": score,
            "severity": severity,
            "product": product,
            "affected": affected_text(cve.get("configurations"), cve.get("affected")),
        })
    return parsed


def request_json(client: httpx.Client, url: str, **kwargs: Any) -> dict[str, Any]:
    """Fetch JSON with one rate-limit retry; client, URL and request options are inputs; return an object."""
    for attempt in range(2):
        response = client.get(url, timeout=20.0, **kwargs)
        if response.status_code == 429 and attempt == 0:
            retry_after = response.headers.get("Retry-After", "30")
            try:
                delay = max(1.0, float(retry_after))
            except ValueError:
                delay = 30.0
            time.sleep(delay)
            continue
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Expected a JSON object from {url}")
        return payload
    raise RuntimeError(f"Could not fetch {url}")


def fetch_cisa(client: httpx.Client) -> list[dict[str, Any]]:
    """Fetch CISA KEV records; client is the HTTP session; return parsed entries."""
    return parse_cisa(request_json(client, CISA_URL))


def select_recent_kev(records: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Keep six newest KEVs from seven days; records and UTC now are inputs; return entries."""
    today = now.astimezone(timezone.utc).date()
    cutoff = today - timedelta(days=KEV_WINDOW_DAYS)
    recent = [record for record in records if cutoff <= parse_datetime(record["published"]).date() <= today]
    recent.sort(key=lambda record: (record["published"], record["id"]), reverse=True)
    unique: dict[str, dict[str, Any]] = {}
    for record in recent:
        unique.setdefault(record["id"], record)
    return list(unique.values())[:KEV_LIMIT]


def nvd_request(client: httpx.Client, params: dict[str, str | int], api_key: str | None, last_request: list[float]) -> dict[str, Any]:
    """Pace and retry an NVD timeout; client, params, key and clock are inputs; return JSON."""
    interval = 0.7 if api_key else 6.1
    headers = {"apiKey": api_key} if api_key else {}
    for attempt in range(2):
        if last_request:
            time.sleep(max(0.0, interval - (time.monotonic() - last_request[0])))
        last_request[:] = [time.monotonic()]
        try:
            return request_json(client, NVD_URL, params=params, headers=headers)
        except httpx.TimeoutException:
            if attempt:
                raise
            LOGGER.warning("NVD request timed out; retrying %s", params)
    raise RuntimeError("NVD request retry exhausted")


def fetch_nvd(client: httpx.Client, now: datetime, api_key: str | None, last_request: list[float] | None = None) -> list[dict[str, Any]]:
    """Fetch three days of NVD CVEs; client, UTC now, key and request clock are inputs; return records."""
    start = now.astimezone(timezone.utc) - timedelta(days=3)
    request_clock = last_request if last_request is not None else []
    params: dict[str, str | int] = {
        "pubStartDate": utc_text(start),
        "pubEndDate": utc_text(now),
        "resultsPerPage": PAGE_SIZE,
    }
    records: list[dict[str, Any]] = []
    index = 0
    while True:
        params["startIndex"] = index
        payload = nvd_request(client, params, api_key, request_clock)
        records.extend(parse_nvd(payload))
        total = payload.get("totalResults")
        count = payload.get("resultsPerPage")
        if not isinstance(total, int) or not isinstance(count, int) or count <= 0:
            raise ValueError("NVD pagination metadata is invalid")
        index += count
        if index >= total:
            break
    return records


def fetch_nvd_by_id(client: httpx.Client, cve_id: str, api_key: str | None, last_request: list[float]) -> dict[str, Any] | None:
    """Look up one CVE in NVD; client, ID, key and request clock are inputs; return record or None."""
    payload = nvd_request(client, {"cveId": cve_id}, api_key, last_request)
    return next((record for record in parse_nvd(payload) if record["id"] == cve_id), None)


def make_card(cisa: dict[str, Any] | None, nvd: dict[str, Any] | None) -> dict[str, Any]:
    """Combine one CVE's CISA and NVD data; inputs are optional records; return a feed card."""
    record = cisa or nvd
    if record is None:
        raise ValueError("A CVE needs at least one source record")
    cve_id = record["id"]
    score = nvd["cvss"] if nvd else None
    severity = nvd["severity"] if nvd else "Unknown"
    vendor_product = " ".join(part for part in ((cisa or {}).get("vendor", ""), (cisa or {}).get("product", "")) if part)
    if cisa:
        subject = vendor_product or cisa.get("name") or cve_id
        headline = f"{severity} flaw in {subject}" if severity != "Unknown" else f"Known exploited flaw in {subject}"
    elif nvd and nvd.get("product"):
        headline = f"{severity} flaw in {nvd['product']}" if severity != "Unknown" else f"Vulnerability in {nvd['product']}"
    else:
        description = clean_text((nvd or {}).get("description"))
        first_sentence = re.split(r"(?<=[.!?])\s+", description, maxsplit=1)[0]
        headline = first_sentence if first_sentence and not CVE_PATTERN.fullmatch(first_sentence.rstrip(". ")) else f"Vulnerability disclosed: {cve_id}"
    hook = trim_text(clean_text(headline), 90)
    detail = (nvd or {}).get("description") or (cisa or {}).get("description") or "See advisory for details."
    body = body_text(detail)
    published = (cisa or nvd)["published"]
    exploited = cisa is not None
    rank = float(200 + parse_datetime(published).timestamp() / 1_000_000_000) if exploited else float((score if score is not None else -1) * 10 + parse_datetime(published).timestamp() / 100_000_000_000)
    card: dict[str, Any] = {
        "id": f"cve:{cve_id}",
        "category": "CVEs",
        "type": "advisory",
        "hook": hook,
        "body": body,
        "mins": 2,
        "source": {"name": "NVD", "url": f"{NVD_DETAIL}{cve_id}"},
        "published": published,
        "rank": rank,
        "cve": {
            "id": cve_id,
            "cvss": score,
            "severity": severity,
            "affected": vendor_product if exploited and vendor_product else "See advisory" if exploited else (nvd or {}).get("affected", "See advisory"),
            "exploited": "Exploited in the wild" if exploited else "No known exploitation",
            "fix": (cisa or {}).get("fix", "See advisory"),
        },
    }
    if exploited:
        card["via"] = {"name": "CISA KEV", "url": CISA_PAGE}
    return card


def build_feed(cisa_records: list[dict[str, Any]], nvd_records: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Dedupe and rank records; source lists and UTC now are inputs; return version 1 feed JSON."""
    recent_kev = select_recent_kev(cisa_records, now)
    all_kev_ids = {record["id"] for record in cisa_records}
    nvd_by_id = {record["id"]: record for record in nvd_records}
    kev_cards = [make_card(record, nvd_by_id.get(record["id"])) for record in recent_kev]
    nvd_cards = [make_card(None, record) for cve_id, record in nvd_by_id.items() if cve_id not in all_kev_ids and record["cvss"] is not None and record["cvss"] >= MIN_NVD_CVSS]
    nvd_cards.sort(key=lambda card: (card["cve"]["cvss"], card["published"], card["id"]), reverse=True)
    cards = kev_cards + nvd_cards
    return {"version": 1, "generated_at": utc_text(now), "cards": cards[:CARD_LIMIT]}


def serialize_feed(feed: dict[str, Any]) -> bytes:
    """Encode stable LF-terminated JSON; feed is the input; return UTF-8 bytes."""
    return (json.dumps(feed, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_feed(feed: dict[str, Any], path: Path) -> None:
    """Atomically write feed JSON; feed and destination path are inputs; return nothing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_bytes(serialize_feed(feed))
    temporary.replace(path)


def main() -> None:
    """Run both independent sources and write data/feed.json; take no args and return nothing."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    now = datetime.now(timezone.utc)
    cisa_records: list[dict[str, Any]] = []
    nvd_records: list[dict[str, Any]] = []
    api_key = os.getenv("NVD_API_KEY")
    request_clock: list[float] = []
    cisa_error = "-"
    nvd_error = "-"
    news_cards: list[dict[str, Any]] = []
    news_stats: list[SourceStats] = []
    with httpx.Client(follow_redirects=True, headers={"User-Agent": "spark-feed/0.1 (+https://github.com/JustJakee/spark)"}) as client:
        try:
            cisa_records = fetch_cisa(client)
        except Exception as error:
            cisa_error = str(error)
            LOGGER.error("CISA KEV ingest failed: %s", error)
        try:
            nvd_records = fetch_nvd(client, now, api_key, request_clock)
        except Exception as error:
            nvd_error = str(error)
            LOGGER.error("NVD ingest failed: %s", error)
        for record in select_recent_kev(cisa_records, now):
            try:
                enriched = fetch_nvd_by_id(client, record["id"], api_key, request_clock)
                if enriched is not None:
                    nvd_records.append(enriched)
            except Exception as error:
                nvd_error = str(error)
                LOGGER.error("NVD lookup failed for %s: %s", record["id"], error)
        try:
            news_cards, news_stats = run_sources(client, load_sources(), now)
        except Exception as error:
            LOGGER.error("News source configuration failed: %s", error)
            news_stats = [SourceStats(source="news config", error=str(error))]
    cve_feed = build_feed(cisa_records, nvd_records, now)
    feed = {"version": 1, "generated_at": utc_text(now), "cards": cve_feed["cards"] + news_cards}
    write_feed(feed, FEED_PATH)
    LOGGER.info("Wrote %d cards (%d CVE, %d news) to %s", len(feed["cards"]), len(cve_feed["cards"]), len(news_cards), FEED_PATH)
    rows = [
        SourceStats(source="CISA KEV", fetched=len(cisa_records), kept=sum(card.get("via", {}).get("name") == "CISA KEV" for card in cve_feed["cards"]), error=cisa_error),
        SourceStats(source="NVD", fetched=len(nvd_records), kept=sum("via" not in card for card in cve_feed["cards"]), error=nvd_error),
        *news_stats,
    ]
    LOGGER.info("%-24s %7s %5s %s", "source", "fetched", "kept", "error")
    for row in rows:
        LOGGER.info("%-24s %7d %5d %s", row.source, row.fetched, row.kept, row.error)


if __name__ == "__main__":
    main()
