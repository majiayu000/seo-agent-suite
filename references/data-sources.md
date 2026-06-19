# SEO Data Sources

Use the smallest source that can prove the claim. Do not present a paid provider or MCP as installed, authenticated, or authoritative unless the current environment proves it.

## Local And Free Baseline

Use first for repo/package SEO:

- `repo_seo_baseline.py`: repository metadata, manifests, package registry status, homepage, robots, and sitemap checks.
- `site_meta_audit.py`: single-page HTML metadata, canonical, robots meta, social cards, JSON-LD, headings, robots.txt, and sitemap.xml.
- `gh`, `npm view`, `cargo search`, `curl`: direct public-surface verification.
- Web search: exact brand/package queries and collision checks.

Limits: no keyword volume, no backlink index, no historical ranking, weak JavaScript rendering coverage.

## First-Party Google Sources

Use when the site is owned or the user can authenticate:

- Google Search Console: sitemap submission, indexing status, branded query impressions, click-through data.
- PageSpeed Insights: lab Lighthouse plus field data when available.
- CrUX: origin/page-level field Core Web Vitals when public data exists.

Limits: Search Console requires property access; indexing is delayed; CrUX is unavailable for low-traffic pages.

## Crawling And Rendering

Use when HTML fetches are insufficient:

- Firecrawl MCP: crawl/render pages, extract clean page text, inspect competitor pages, and gather page-level evidence.
- Playwright/Lighthouse: local rendering, Core Web Vitals proxies, screenshots, console/network proof.

Choose Firecrawl for multi-page external crawling. Choose Playwright/Lighthouse for local app/site QA or when visual/runtime proof matters.

## Keyword, SERP, And Competitive Data

Use when recommendations depend on search volume, difficulty, SERP shape, competitor rankings, or keyword clusters:

- DataForSEO MCP: broad keyword/SERP APIs, flexible country/language/device parameters, good for custom analysis.
- SE Ranking MCP + skills: finished SEO deliverables such as keyword clusters, content briefs, AI Search share of voice, page intelligence, and SXO analysis.
- Ahrefs MCP: backlinks, competing pages, content gap, keyword and traffic estimates when an Ahrefs plan is available.

Do not block simple repo metadata fixes on these providers. Do require one of them before claiming rank potential, search volume, backlink gaps, or competitor share of voice.

## Provider Decision Table

| Need | Preferred source | Notes |
|---|---|---|
| Repo/package discoverability | Local scripts + `gh` + registries | Default for open-source repos |
| Crawlability and metadata | `site_meta_audit.py`, Firecrawl for scale | Single page locally, site crawl via MCP |
| Search Console submission | Google Search Console | Manual/browser auth may be required |
| Core Web Vitals | PageSpeed Insights, CrUX | Treat lab and field data separately |
| Keyword research | DataForSEO or SE Ranking | Needs API/account |
| AI visibility / GEO | SE Ranking skills or provider-specific AI visibility data | Mark methodology clearly |
| Backlinks and content gaps | Ahrefs | Requires Ahrefs plan |
| Competitor page extraction | Firecrawl | Avoid claiming ranking data from crawl data alone |

## Output Rules

- Label each finding as `Confirmed`, `Likely`, or `Hypothesis`.
- Attach the source used for each claim.
- Keep manual/account blockers explicit: missing API key, missing OAuth, missing Search Console property, or provider not installed.
- Separate crawl/indexability from ranking. A crawlable page is not proof of indexing or ranking.
