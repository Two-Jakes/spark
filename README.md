# Spark

A swipeable, finite learning feed for engineers. AI, development, CVEs, and security, in 2-minute cards.

## What it is

Spark turns the firehose of tech news into a short feed of single-idea cards. Each card has a link back to its source. When you've seen today's cards, it tells you you're caught up and lets you go.

**Categories:** AI · Development · CVEs · Cyber Security

**Card types:**
- Release notes: what changed, and whether you should care
- Code diff: a before/after pattern worth knowing
- Spot the bug: tap the vulnerable line
- Paper in 60 seconds: problem, idea, result, catch
- Repo spotlight: what it does and how to install it
- How it flows: step through an architecture
- CVE advisory: CVSS score, affected versions, exploit status, fix

**Other features:** time filters (2 / 5 / 10 min), "go deeper" rabbit holes, save for later, listen mode.

## How it works

```
GitHub Action (scheduled)
        |
  ingest/ (Python)  -->  data/feed.json  -->  web/ (PWA)  -->  static hosting
```

- `ingest/` pulls sources, dedupes, ranks, and writes `data/feed.json`.
- `web/` is a static PWA that reads `feed.json`. Saves and preferences live in the browser.
- No backend or database in v1.

## Repo layout

```
ingest/             Python ingest job
web/                Vite + React + TypeScript PWA
data/               generated feed.json
.github/workflows/  scheduled ingest and deploy
AGENTS.md           standing rules for coding agents
```

## Data sources

| Category | Sources |
|---|---|
| CVEs | CISA Known Exploited Vulnerabilities, NVD API |
| AI | TLDR AI, arXiv, Hacker News (classified stories) |
| Development | TLDR Dev, TLDR DevOps, Hacker News (classified stories), Lobsters |
| Cyber Security | TLDR InfoSec, Hacker News (classified stories), Krebs on Security, BleepingComputer, The Hacker News, Google Project Zero |

## Getting started

Requires Python 3.12.

```bash
pip install -r requirements.txt
python -m ingest.main     # writes data/feed.json
pytest                    # runs tests (no network needed)
```

Optional: set `NVD_API_KEY` for higher NVD rate limits.

## Run the web app

Requires Node.js 20.19+ or 22.12+ and a generated `data/feed.json`.

```bash
cd web
npm install
npm run dev      # copies ../data/feed.json and starts Vite
npm run build    # type-checks and creates the static PWA in dist/
npm test         # runs Vitest
```

`predev` and `prebuild` copy the current feed into `web/public/feed.json`. The app refreshes that file without using the browser's normal HTTP cache. Saved and dismissed card IDs stay in browser storage when available.

## Cost

Runs on free tiers: static hosting plus a scheduled GitHub Action. LLM summaries, when added, are expected to cost a few dollars a month.

## License

TBD
