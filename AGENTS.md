# Spark: engineer learning feed

Static PWA plus a scheduled Python ingest job. No backend, no database in v1.

## Layout
- ingest/   Python 3.12 job that writes data/feed.json
- web/      Vite + React + TypeScript PWA that reads feed.json (later task)
- data/     generated feed.json (committed by the scheduled workflow)
- .github/workflows/  scheduled ingest + deploy (later task)

## Rules
- Every function gets a docstring explaining purpose, args, return value.
- Use type hints everywhere. Dependencies: httpx, pytest, feedparser, pyyaml only unless I approve more.
- No LLM calls in ingest v1. Hooks and bodies are built from templates.
- Each source fails independently: log the error, keep going, never crash the run.
- Be idempotent: same inputs produce same feed.json. Dedupe by card id.
- Respect API rate limits and set timeouts on every request.
- No secrets in code. Read keys from environment variables.
- Before using any external API, check the official docs for the current URL and fields.

## Web rules
- Use strict TypeScript in `web/`.
- Add a JSDoc comment explaining purpose, arguments, and return value to every function and component.
- Do not add web dependencies without asking unless the user explicitly approves them.
- Render feed text as text, and validate external URLs before making links.

## Commands
- Run ingest:  python -m ingest.main
- Tests:       pytest
- Web:         cd web && npm install && npm run dev
- Web build:   cd web && npm run build
- Web tests:   cd web && npm test

## Done means
- Tests pass, and a sample run writes valid data/feed.json.
