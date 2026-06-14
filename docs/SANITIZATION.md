# Sanitization And Data Boundaries

This repository should contain infrastructure source code and synthetic examples only.

## Include

- Source code.
- Schemas.
- Docker/Compose templates.
- Scripts that do not contain secrets.
- `.env.example`.
- Synthetic sample events.
- Sanitized documentation.

## Exclude

- `.env` and generated secrets.
- API keys, cookies, browser profiles, auth headers, localStorage/sessionStorage, SSH config, or tokens.
- Captured private evidence from social networks, search engines, websites, or research sessions.
- Screenshots, OCR artifacts, downloaded media, videos, Redpanda data, Pebble state, Typesense data, Qdrant data, ClickHouse data, or local outbox records.
- User-private absolute paths unless they are clearly marked as examples.

## Pre-Commit Checks

Before committing or publishing:

```bash
git status --short --ignored
git diff --cached
```

Also run a secret scan appropriate for your environment before pushing to any public remote.
