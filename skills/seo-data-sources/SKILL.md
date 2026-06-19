---
name: seo-data-sources
description: Choose and document SEO data sources and MCP/provider boundaries for audits. Use when Codex needs to decide between local scripts, Firecrawl, Google Search Console, PageSpeed Insights, CrUX, DataForSEO, SE Ranking, Ahrefs, browser checks, or paid/live integrations; or when SEO findings require explicit source, cost, account, API-key, and confidence boundaries.
---

# SEO Data Sources

Use this skill before relying on external SEO data. Read `../../references/data-sources.md` first.

## Workflow

1. State the claim that needs proof.
2. Pick the smallest source that can prove it.
3. Verify whether the provider is installed/authenticated in the current environment.
4. If unavailable, mark it as a blocker or hypothesis, not a confirmed finding.
5. Attach the data source to each SEO claim.

## Provider Roles

- Local scripts: repo/package/site metadata and crawlability baseline.
- Firecrawl: rendered crawl and competitor page extraction.
- Google Search Console: owned-site indexing, queries, impressions, sitemap submission.
- PageSpeed/CrUX: lab and field performance evidence.
- DataForSEO: keyword, SERP, and competitor data via API.
- SE Ranking: packaged SEO/GEO workflows and share-of-voice style reporting.
- Ahrefs: backlinks, content gap, competing pages, and authority estimates.

## Rules

- Do not present optional MCPs as installed without current proof.
- Do not use crawl data as ranking data.
- Do not use Search Console without explicit account/browser/API access.
- Do not put API keys in repo files, reports, prompts, or screenshots.
