---
name: seo-data-sources
description: Choose and document SEO data sources and MCP/provider boundaries for audits. Use when Codex needs to decide between local scripts, Firecrawl, Google Search Console, PageSpeed Insights, CrUX, DataForSEO, SE Ranking, Ahrefs, browser checks, or paid/live integrations; or when SEO findings require explicit source, cost, account, API-key, and confidence boundaries.
---

# SEO Data Sources

Use this skill before relying on external SEO data. Read `references/data-sources.md` (resolved from the suite/plugin root) first.

## Workflow

1. State the claim that needs proof.
2. Pick the smallest source that can prove it.
3. Check the actual available tool/endpoint, authentication, and property scope. An installed MCP does not imply access to every underlying API capability.
4. Before an actual provider call, record current plan/permission/quota constraints and the intended request scale (targets, queries, markets, devices, depth, repeats). Use current provider/account evidence for cost estimates; record unknown costs explicitly. Continue within existing authorization and budget; clarify only a missing decision that changes the result or exceeds that scope.
5. If unavailable, mark the affected claim as a blocker or hypothesis; continue independent local dry-audit work.
6. Attach the evidence record below to each SEO claim. Choose the same measurement scope for before/after comparisons.

## Provider Roles

- Local scripts: repo/package/site metadata and crawlability baseline.
- Firecrawl: rendered crawl and competitor page extraction.
- Google Search Console: owned-property query/performance evidence and indexed-version inspection; sitemap submission only when that action is authorized.
- PageSpeed/CrUX: lab and field performance evidence.
- DataForSEO: keyword, SERP, and competitor data via API.
- SE Ranking: packaged SEO/GEO workflows and share-of-voice style reporting.
- Backlinks: existing authorized Search Console Links exports for owned-site samples, or available DataForSEO/Ahrefs tools for their index and competitor scope.
- AI visibility: authorized Bing Webmaster Tools citation reports for supported surfaces, or provider-defined prompt samples; document what the metric measures.

## Output

A short decision and evidence record attached to the audit report or issue:

- Claim and confidence; chosen provider and actual tool/endpoint; why a smaller source is insufficient; access status and any applicable request/cost boundary.
- `collected_at` with timezone; measurement window; property/domain/URL scope; region, language, device, filters, and aggregation used (or `unknown` / not applicable).
- Returned rows, pagination/depth and truncation/sampling limits; redacted raw response/export reference or reproducible public evidence; unresolved limitations.

Use the provider-specific boundaries in `references/data-sources.md`; an empty response is not proof that traffic, links, or citations do not exist.

## Failure Handling

- If no available source can prove the claim, report it as `Hypothesis` with
  the missing provider named as a blocker. Do not downgrade silently to a
  weaker source without recording the substitution.

## Rules

- Do not present optional MCPs as installed without current proof.
- Do not use crawl data as ranking data.
- Do not use Search Console without explicit account/browser/API access.
- Do not put API keys in repo files, reports, prompts, or screenshots.
