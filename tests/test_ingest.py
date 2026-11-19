"""Network-free tests for Spark's CVE ingest."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from ingest.main import affected_text, build_feed, clean_text, fetch_nvd, fetch_nvd_by_id, main, make_card, nvd_request, parse_cisa, parse_nvd, select_recent_kev, serialize_feed


FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def load_fixture(name: str) -> dict[str, Any]:
    """Read a saved JSON fixture; name is its filename; return its object."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parsing_and_enrichment() -> None:
    """Check parsing and CISA/NVD enrichment; take no args and return nothing."""
    cisa = parse_cisa(load_fixture("cisa.json"))
    nvd = parse_nvd(load_fixture("nvd.json"))
    assert len(cisa) == 2
    assert len(nvd) == 2  # Rejected CVEs do not become cards.
    feed = build_feed(cisa, nvd, NOW)
    cards = {card["id"]: card for card in feed["cards"]}
    overlap = cards["cve:CVE-2026-10001"]
    assert overlap["cve"]["cvss"] == 8.8
    assert overlap["cve"]["severity"] == "High"
    assert overlap["cve"]["affected"] == "Example Co Widget"
    assert overlap["published"] == "2026-11-18T00:00:00Z"
    assert overlap["cve"]["exploited"] == "Exploited in the wild"
    assert overlap["cve"]["fix"] == "Apply the vendor update."
    assert overlap["source"] == {"name": "NVD", "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-10001"}
    assert overlap["via"] == {"name": "CISA KEV", "url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"}
    assert cards["cve:CVE-2026-10002"]["cve"]["fix"] == "See advisory"
    assert cards["cve:CVE-2026-10003"]["cve"]["affected"] == "See advisory"
    assert cards["cve:CVE-2026-10003"]["cve"]["exploited"] == "No known exploitation"
    assert all(len(card["hook"]) <= 90 for card in feed["cards"])


def test_dedupe_ranking_and_cap() -> None:
    """Check stable ID dedupe, ranking and ten-card cap; take no args and return nothing."""
    cisa = parse_cisa(load_fixture("cisa.json"))
    nvd = parse_nvd(load_fixture("nvd.json"))
    nvd.append(dict(nvd[0]))
    for number in range(20):
        nvd.append({
            "id": f"CVE-2026-{20000 + number}",
            "published": f"2026-11-18T{number:02d}:00:00Z",
            "description": "A test flaw.",
            "cvss": 9.9,
            "severity": "Critical",
            "affected": "See advisory",
        })
    feed = build_feed(cisa, nvd, NOW)
    ids = [card["id"] for card in feed["cards"]]
    assert len(ids) == len(set(ids)) == 10
    assert ids[:2] == ["cve:CVE-2026-10001", "cve:CVE-2026-10002"]
    assert ids[2] == "cve:CVE-2026-20019"
    assert feed["cards"][0]["rank"] > feed["cards"][1]["rank"]
    assert feed["cards"][1]["rank"] > feed["cards"][2]["rank"]


def test_feed_serialization_is_stable() -> None:
    """Check schema and byte-stable JSON; take no args and return nothing."""
    feed = build_feed(parse_cisa(load_fixture("cisa.json")), parse_nvd(load_fixture("nvd.json")), NOW)
    first = serialize_feed(feed)
    assert serialize_feed(feed) == first
    assert b"\r\n" not in first
    saved = json.loads(first)
    assert set(saved) == {"version", "generated_at", "cards"}
    assert saved["version"] == 1
    assert saved["generated_at"] == "2026-11-18T12:00:00Z"
    required = {"id", "category", "type", "hook", "body", "mins", "source", "published", "rank", "cve"}
    assert all(required <= set(card) <= required | {"via"} for card in saved["cards"])
    assert all(set(card["source"]) == {"name", "url"} for card in saved["cards"])
    assert all(set(card["cve"]) == {"id", "cvss", "severity", "affected", "exploited", "fix"} for card in saved["cards"])
    assert all(card.get("via", {}).get("name") == "CISA KEV" for card in saved["cards"] if card["cve"]["exploited"] == "Exploited in the wild")


def test_nvd_cpe_hook_and_description_fallback() -> None:
    """Check CPE-derived hooks and no-CPE description fallback; take no args and return nothing."""
    from_cpe = parse_nvd(load_fixture("nvd_cpe.json"))[0]
    card = make_card(None, from_cpe)
    assert card["hook"] == "Critical flaw in Example Vendor Sample Runtime"
    assert card["cve"]["affected"] == "Example Vendor Sample Runtime before 2.5"
    no_cpe = make_card(None, parse_nvd(load_fixture("nvd.json"))[1])
    assert no_cpe["hook"] == "A parser issue affects a test product."
    assert "CVE-" not in no_cpe["hook"]
    assert len(no_cpe["hook"]) <= 90


def test_cve_text_normalization() -> None:
    """Check HTML boundaries and whitespace in CVE text; take no args and return nothing."""
    assert clean_text("Selection<b>Base</b>\nTools\t in") == "Selection Base Tools in"
    nvd = parse_nvd(load_fixture("nvd_cpe.json"))[0]
    nvd["description"] = "A <b>critical</b> flaw\n affects the runtime."
    card = make_card(None, nvd)
    assert card["body"] == "A critical flaw affects the runtime."


def test_nvd_ranks_by_score_then_publication() -> None:
    """Check score and newest tie-break ordering; take no args and return nothing."""
    records = parse_nvd(load_fixture("nvd.json"))
    records.append({**records[0], "id": "CVE-2026-30000", "published": "2026-11-18T11:00:00Z"})
    feed = build_feed([], records, NOW)
    assert [card["cve"]["id"] for card in feed["cards"]] == [
        "CVE-2026-10003", "CVE-2026-30000", "CVE-2026-10001"
    ]


def test_kev_window_is_inclusive_and_excludes_future() -> None:
    """Check the seven-day KEV cutoff; take no args and return nothing."""
    example = parse_cisa(load_fixture("cisa.json"))[0]
    records = [
        {**example, "id": "CVE-2026-30001", "published": "2026-11-11T00:00:00Z"},
        {**example, "id": "CVE-2026-30002", "published": "2026-11-10T00:00:00Z"},
        {**example, "id": "CVE-2026-30003", "published": "2026-11-19T00:00:00Z"},
    ]
    assert [record["id"] for record in select_recent_kev(records, NOW)] == ["CVE-2026-30001"]
    assert [card["cve"]["id"] for card in build_feed(records, [], NOW)["cards"]] == ["CVE-2026-30001"]
    older_nvd = {"id": "CVE-2026-30002", "published": "2026-11-18T08:00:00Z", "description": "Old KEV entry.", "cvss": 9.9, "severity": "Critical", "affected": "See advisory"}
    assert [card["cve"]["id"] for card in build_feed(records, [older_nvd], NOW)["cards"]] == ["CVE-2026-30001"]


def test_six_kev_cap_leaves_nvd_room() -> None:
    """Check six KEVs and four high-CVSS NVD cards; take no args and return nothing."""
    example = parse_cisa(load_fixture("cisa.json"))[0]
    kev = [
        {**example, "id": f"CVE-2026-{40000 + day}", "published": (NOW - timedelta(days=day)).strftime("%Y-%m-%dT00:00:00Z")}
        for day in range(8)
    ]
    nvd = [
        {"id": f"CVE-2026-{50000 + number}", "published": "2026-11-18T09:00:00Z", "description": "Test flaw.", "cvss": 9.9 - number / 10, "severity": "Critical", "affected": "See advisory"}
        for number in range(5)
    ]
    nvd.append({**nvd[0], "id": "CVE-2026-60000", "cvss": 6.9})
    feed = build_feed(kev, nvd, NOW)
    assert len(feed["cards"]) == 10
    assert [card["cve"]["id"] for card in feed["cards"][:6]] == [f"CVE-2026-{40000 + day}" for day in range(6)]
    assert [card["cve"]["id"] for card in feed["cards"][6:]] == [f"CVE-2026-{50000 + number}" for number in range(4)]
    assert all(card["cve"]["cvss"] >= 7.0 for card in feed["cards"][6:])


def test_kev_lookup_enriches_and_failure_keeps_card(monkeypatch: Any) -> None:
    """Check ID lookups and a failed lookup; monkeypatch avoids delays; return nothing."""
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve one CVE and fail another; request is input; return a fake response."""
        calls.append(request)
        if request.url.params["cveId"] == "CVE-2026-10001":
            page = load_fixture("nvd.json")
            page["vulnerabilities"] = page["vulnerabilities"][:1]
            return httpx.Response(200, json=page)
        return httpx.Response(503)

    def no_sleep(seconds: float) -> None:
        """Skip pacing in this network-free test; seconds is unused; return nothing."""
        return None

    monkeypatch.setattr("ingest.main.time.sleep", no_sleep)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        request_clock: list[float] = []
        enriched = fetch_nvd_by_id(client, "CVE-2026-10001", "test-key", request_clock)
        try:
            fetch_nvd_by_id(client, "CVE-2026-10002", "test-key", request_clock)
        except httpx.HTTPStatusError:
            pass
        else:
            raise AssertionError("The failed lookup should raise")
    assert enriched is not None
    assert len(calls) == 2
    assert all(request.headers["apiKey"] == "test-key" for request in calls)
    feed = build_feed(parse_cisa(load_fixture("cisa.json")), [enriched], NOW)
    cards = {card["cve"]["id"]: card for card in feed["cards"]}
    assert cards["CVE-2026-10001"]["cve"]["cvss"] == 8.8
    assert cards["CVE-2026-10001"]["body"].startswith("Widget allows remote code execution")
    assert cards["CVE-2026-10002"]["cve"]["cvss"] is None
    assert cards["CVE-2026-10002"]["cve"]["affected"] == "Demo Server"


def test_nvd_affected_product_versions() -> None:
    """Check NVD's affectedData version ranges; take no args and return nothing."""
    affected = [{"source": "example", "affectedData": [{
        "vendor": "Example Co", "product": "Widget", "versions": [
            {"version": "1.0", "status": "affected", "versionType": "semver", "lessThan": "2.0"}
        ]
    }]}]
    assert affected_text([], affected) == "Example Co Widget 1.0 to before 2.0"


def test_one_source_failure_keeps_other_source(monkeypatch: Any) -> None:
    """Check source failure isolation; monkeypatch supplies inputs; return nothing."""
    def fail_cisa(client: httpx.Client) -> list[dict[str, Any]]:
        """Simulate a CISA failure; client is unused; raise an HTTP error."""
        raise httpx.ConnectError("CISA unavailable")

    def saved_nvd(client: httpx.Client, now: datetime, api_key: str | None, last_request: list[float]) -> list[dict[str, Any]]:
        """Serve saved NVD records; arguments are unused; return fixture records."""
        return parse_nvd(load_fixture("nvd.json"))

    captured: list[dict[str, Any]] = []

    def capture_feed(feed: dict[str, Any], path: Path) -> None:
        """Capture the feed instead of writing it; feed and path are inputs; return nothing."""
        captured.append(feed)

    monkeypatch.setattr("ingest.main.fetch_cisa", fail_cisa)
    monkeypatch.setattr("ingest.main.fetch_nvd", saved_nvd)
    monkeypatch.setattr("ingest.main.write_feed", capture_feed)
    monkeypatch.setattr("ingest.main.load_sources", list)
    main()
    saved = captured[0]
    assert len(saved["cards"]) == 2
    assert all(card["source"]["name"] == "NVD" for card in saved["cards"])


def test_nvd_paginates_without_network(monkeypatch: Any) -> None:
    """Check NVD pagination and key header; monkeypatch patches sleep; return nothing."""
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve saved NVD JSON; request is the HTTP request; return a fake response."""
        calls.append(request)
        page = load_fixture("nvd.json")
        if len(calls) == 1:
            page["resultsPerPage"] = 2
            page["totalResults"] = 3
            page["vulnerabilities"] = page["vulnerabilities"][:2]
        else:
            page["resultsPerPage"] = 1
            page["startIndex"] = 2
            page["vulnerabilities"] = page["vulnerabilities"][2:]
        return httpx.Response(200, json=page)

    def no_sleep(seconds: float) -> None:
        """Skip pacing in this network-free test; seconds is unused; return nothing."""
        return None

    monkeypatch.setattr("ingest.main.time.sleep", no_sleep)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        records = fetch_nvd(client, NOW, "test-key")
    assert len(records) == 2
    assert len(calls) == 2
    assert calls[0].url.params["pubStartDate"] == "2026-11-15T12:00:00Z"
    assert calls[1].url.params["startIndex"] == "2"
    assert calls[0].headers["apiKey"] == "test-key"


def test_nvd_timeout_retries_with_pacing(monkeypatch: Any) -> None:
    """Check one NVD timeout retry; monkeypatch skips waiting; return nothing."""
    calls: list[httpx.Request] = []
    waits: list[float] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Time out once, then serve JSON; request is input; return a fake response."""
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow NVD page")
        return httpx.Response(200, json=load_fixture("nvd.json"))

    def record_wait(seconds: float) -> None:
        """Record a pacing delay; seconds is input; return nothing."""
        waits.append(seconds)

    monkeypatch.setattr("ingest.main.time.sleep", record_wait)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = nvd_request(client, {"cveId": "CVE-2026-10001"}, None, [])
    assert len(calls) == 2
    assert len(waits) == 1 and 0 < waits[0] <= 6.1
    assert result["totalResults"] == 3
