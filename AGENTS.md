# Agent Instructions

This repository is `seo-agent-suite`: a Codex plugin that operationalizes Shipwise discoverability checks with skills and local audit scripts.

Before editing:

1. Run `git status --short`.
2. Search existing skills/scripts before adding new ones.
3. Keep Shipwise as the strategy layer and this repo as the execution layer.

Rules:

- Keep each skill focused. Do not collapse repo SEO, technical SEO, content/GEO, and provider selection into one giant skill.
- Keep local dry-audit checks separate from paid or authenticated provider data.
- Mark findings as `Confirmed`, `Likely`, or `Hypothesis`.
- Do not store or print API keys, cookies, OAuth tokens, or Search Console credentials.
- Do not claim indexing, ranking, search volume, backlinks, or AI share-of-voice without a current data source that actually measures it.

Validation:

```bash
python3 -m py_compile scripts/*.py
python3 tests/test_structure.py
```
