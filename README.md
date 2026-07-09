# SEO Agent Suite

[![Check](https://github.com/majiayu000/seo-agent-suite/actions/workflows/check.yml/badge.svg)](https://github.com/majiayu000/seo-agent-suite/actions/workflows/check.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Codex plugin for evidence-backed SEO and discoverability audits.

This repository is the execution layer for Shipwise-style discoverability work. Shipwise remains the launch/discoverability planning system; this plugin provides reusable skills and scripts that collect evidence and turn it into repo, package, site, and content SEO actions.

## Relationship To Shipwise

```text
shipwise
├── docs/DISCOVERABILITY.md
├── templates/seo/keyword_map.md
└── projects/<project>/

seo-agent-suite
├── .codex-plugin/plugin.json
├── skills/
├── scripts/
└── references/
```

Use Shipwise to decide launch strategy, platform fit, messaging, and project records. Use SEO Agent Suite to run audits, collect public-surface evidence, and generate SEO issues or reports.

## Quick Start

Run the local validation checks:

```bash
python3 -m py_compile scripts/*.py
python3 tests/test_structure.py
python3 tests/test_scripts.py
```

Run a repository baseline audit:

```bash
python3 scripts/repo_seo_baseline.py --root . --json
```

Run the same audit with a Shipwise project record:

```bash
python3 scripts/repo_seo_baseline.py --root /path/to/repo --project-yaml /path/to/project.yaml --json
```

Run a basic public-page metadata audit:

```bash
python3 scripts/site_meta_audit.py https://example.com/ --json
```

The plugin manifest lives at [.codex-plugin/plugin.json](.codex-plugin/plugin.json).
Skills live under [skills/](skills/), and reference material lives under
[references/](references/).

## Skills

- `github-repo-seo`: GitHub repository, README, package registry, docs site, and Search Console boundary checks.
- `technical-seo-audit`: Crawlability, metadata, canonical, robots, sitemap, structured data, and page health checks.
- `seo-content-geo`: Keyword mapping, content briefs, GEO/AEO readiness, and AI citation-oriented content review.
- `seo-data-sources`: Provider selection and evidence boundaries for local scripts, Firecrawl, Google Search Console, PageSpeed/CrUX, DataForSEO, SE Ranking, and Ahrefs.

## Scripts

```bash
python3 scripts/repo_seo_baseline.py --root . --json
python3 scripts/site_meta_audit.py https://example.com/ --json
```

The scripts are local dry-audit tools. They do not require API keys and should not be used to claim keyword volume, ranking, backlink gaps, or Search Console indexing status.

## Validation

```bash
python3 -m py_compile scripts/*.py
python3 tests/test_structure.py
python3 tests/test_scripts.py
```

## Release Notes

See [CHANGELOG.md](CHANGELOG.md).

## Boundaries

- Do not store API keys, cookies, Search Console credentials, or provider tokens in this repository.
- Do not claim Google indexing or rankings from a successful crawl alone.
- Do not present optional MCP providers as installed unless the current environment proves it.
- Do not automate posting or publishing. This plugin audits and prepares evidence; publishing still requires explicit user instruction.
- The declared `Write` capability is for local report and issue-draft files only, never for remote publishing.
