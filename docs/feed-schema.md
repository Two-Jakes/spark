# Feed JSON schema (version 1)

`data/feed.json` is a UTF-8 JSON object with:

| Field | Type | Meaning |
| --- | --- | --- |
| `version` | integer | Always `1` |
| `generated_at` | ISO-8601 UTC string | Time of the ingest run |
| `cards` | array of Card | Ranked cards |

Every Card has these fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Stable ID (`cve:<CVE-ID>` or `news:<URL hash>`) |
| `category` | string | `AI`, `Development`, `CVEs`, or `Cyber Security` |
| `type` | string | `advisory`, `article`, or `paper` |
| `hook` | string | Headline, at most 90 characters |
| `body` | string | Short template or source-derived text |
| `mins` | integer | Estimated reading time |
| `source` | object | `{ "name": string, "url": string }` linking to the original article or NVD CVE detail page |
| `published` | ISO-8601 UTC string | Article or issue publication time; for KEV, the CISA `dateAdded` at midnight UTC |
| `rank` | number | Higher values show first within a category |

CVEs also have `cve`: `{ "id": string, "cvss": number|null, "severity": string, "affected": string, "exploited": string, "fix": string }`.

Optional Card fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `via` | object | `{ "name": string, "url": string }`, used for TLDR issue provenance or the CISA KEV catalog |
| `meta` | object | Extra machine-readable data. News cards include `seen_in` (array of source names). Hacker News cards may include `hn_points` (integer). |

News article URLs are canonicalized before deduplication: hosts are lowercased, tracking query parameters and fragments are removed, and trailing slashes are trimmed. A second pass within each category merges articles whose normalized title word sets have Jaccard similarity of at least 0.6 or that mention the same CVE ID. The highest-ranked card is retained and all provider names appear in `meta.seen_in`. At most two arXiv paper cards appear per run, with papers also found in TLDR or Hacker News preferred. CVE cards retain their stable CVE IDs. KEV cards link to the NVD detail page in `source` and the CISA catalog in `via`.
