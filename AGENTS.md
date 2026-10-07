# Agent Instructions

This repository is `seo-agent-suite`: an evidence-backed SEO execution layer
(skills + installable CLI + optional MCP) that pairs with optional Shipwise
discoverability planning.

Before editing:

1. Run `git status --short`.
2. Search existing skills/scripts before adding new ones.
3. Keep Shipwise as an optional strategy adapter; this repo stays the execution layer.
4. Do not invent a sitewide crawler core here unless explicitly requested.

Rules:

- Keep each skill focused. Do not collapse repo SEO, technical SEO, content/GEO, and provider selection into one giant skill.
- Keep local dry-audits separate from paid or authenticated provider data.
- Mark findings as `Confirmed`, `Likely`, or `Hypothesis` (and write them into `findings[].confidence` when emitting JSON).
- Do not store or print API keys, cookies, OAuth tokens, or Search Console credentials.
- Do not claim indexing, ranking, search volume, backlinks, or AI share-of-voice without a current data source that actually measures it.

Preferred invocation (agents):

```bash
pip install -e .
seo-agent doctor
seo-agent repo-baseline --root /path/to/target-repo --json
seo-agent site-meta https://example.com/ --json
```

Legacy scripts remain supported from the suite root:

```bash
python3 scripts/repo_seo_baseline.py --root /path/to/target-repo --json
python3 scripts/site_meta_audit.py https://example.com/ --json
```

Validation:

```bash
pip install -e .
python3 -m py_compile scripts/*.py
python3 tests/test_structure.py
python3 -m unittest discover -s tests -p 'test_*.py'
```
