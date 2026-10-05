# SEO Data Sources

Use the smallest source that can prove the claim. Keep local dry audits separate from authenticated/paid evidence. Check the actual available tool and account scope; an MCP may expose only part of a provider API.

For each claim record confidence, provider/tool, `collected_at` with timezone, data window, property/domain/URL scope, region/language/device, filters/aggregation, pagination/depth, and sampling/truncation. Mark unknown fields explicitly and reference redacted raw evidence. Before calling a provider, record current plan, permissions, quota and request scale (targets × queries × markets × devices × repeats, plus depth/pages). Estimate costs from current account/provider evidence; do not hardcode prices. Reuse existing task authorization and budget.

## Local And Free Baseline

Use first for repo/package SEO:

- `repo_seo_baseline.py`: repository metadata, manifests, package registry status, homepage, robots, and sitemap checks.
- `site_meta_audit.py`: single-page HTML metadata, canonical, robots meta, social cards, JSON-LD, headings, robots.txt, and sitemap.xml.
- `gh`, `npm view`, the crates.io API, and `curl`: direct public-surface verification;
  `cargo search` provides discovery candidates, not exact publication proof.
- Web search: exact brand/package queries and collision checks.

Limits: no keyword volume, no backlink index, no historical ranking, weak JavaScript rendering coverage.

## First-Party Google Sources

Use when the site is owned or the user can authenticate:

- Google Search Console: property-specific search performance and indexed-version inspection; sitemap submission is a separate write action.
- PageSpeed Insights: lab Lighthouse plus field data when available.
- CrUX: origin/page-level field Core Web Vitals when public data exists.

Search Console boundaries:

- [Search Analytics query](https://developers.google.com/webmaster-tools/v1/searchanalytics/query): record property, inclusive PT date range, search type, dimensions/filters, requested and returned aggregation, `dataState`, `rowLimit` and `startRow`. Results are top rows, not a complete query log, even after pagination. Mark fresh/incomplete data and keep these settings consistent across comparisons. [Privacy filtering](https://support.google.com/webmasters/answer/96568?hl=en) also omits anonymized queries; do not force query-row sums to equal property totals.
- [URL Inspection API](https://developers.google.com/webmaster-tools/v1/urlInspection.index/inspect) reports the indexed version, not a live URL test. Preserve [`lastCrawlTime`, fetch/index state and Google-selected canonical](https://developers.google.com/webmaster-tools/v1/urlInspection.index/UrlInspectionResult). Compare a fresh HTTP/render check separately; a deploy passing today does not prove Google has recrawled it.
- [Sitemap submission](https://developers.google.com/webmaster-tools/v1/sitemaps/submit) requires write-capable `webmasters` OAuth scope, property access and authorization for that specific action. An audit or read-only account is insufficient; proceed if submission is already authorized. Submission success does not prove indexing.
- GA4 is optional downstream traffic/key-event or conversion evidence when authorized. Record landing-page/channel, timezone, event definition and [attribution model](https://developers.google.com/analytics/devguides/reporting/data/v1/conversions-api-basics); do not equate analytics visits with Search Console clicks or infer causation from a before/after change.

[PageSpeed Insights](https://developers.google.com/speed/docs/insights/v5/about) separates Lighthouse lab diagnostics from CrUX field data. Record mobile/desktop, URL versus origin, the collection period, and field percentile for LCP/INP/CLS. Preserve insufficient-data or origin-fallback status; a lab score/TBT is not field INP or proof of a CWV pass. Use comparable lab settings/runs and field windows for retests.

## Crawling And Rendering

Use when HTML fetches are insufficient:

- Firecrawl, if the available tool supports the required operation: crawl/render pages, extract page text and gather competitor page evidence.
- Playwright/Lighthouse: local rendering, Core Web Vitals proxies, screenshots, console/network proof.

Choose Firecrawl for multi-page external crawling. Choose Playwright/Lighthouse for local app/site QA or when visual/runtime proof matters.

For structured data, JSON-LD presence or valid JSON is only the first check. Use the [Schema Markup Validator for general schema.org markup and Rich Results Test for Google-supported features](https://developers.google.com/search/docs/appearance/structured-data). Retain tested URL/code, time, types and warnings/errors; validation does not guarantee rich-result display.

## Keyword, SERP, And Competitive Data

Use when recommendations depend on search volume, difficulty, SERP shape, competitor rankings, or keyword clusters:

- DataForSEO: keyword/SERP data when the available endpoint supports the claim; [SERP snapshots depend on location/device and collection time](https://docs.dataforseo.com/v3/serp-google-organic-overview/), and endpoint depth/format affects what is captured.
- SE Ranking: keyword, competitive or AI visibility reporting when supported by the actual available tool/account; inspect its metric definition before using it.
- Ahrefs: backlink/competitor index evidence and keyword/traffic estimates when the current tool and plan allow them; label estimates as estimates.

Do not block simple repo metadata fixes on these providers. Keyword volume, backlink gaps and competitive visibility need a source that measures that specific claim; a crawl or one search result is insufficient. Keep forecasts of ranking potential as hypotheses.

## Backlinks And AI Visibility

For owned-site links, prefer an already authorized [Search Console Links export](https://support.google.com/webmasters/answer/9049606) when its sample answers the question. Record property, export time/type and row limits. It is not exhaustive, can include removed links, and does not report follow/nofollow. Do not assume the Search Analytics API exposes this report or automate browser access without authorization.

For competitor/index comparisons, choose an available authorized [DataForSEO backlinks endpoint](https://docs.dataforseo.com/v3/backlinks-backlinks-live/) or [Ahrefs backlinks tool](https://docs.ahrefs.com/en/api/reference/site-explorer/get-all-backlinks). Record domain/subdomain/exact-URL scope, grouping/filters and live/lost/history selection; retain `last_seen` or the provider's equivalent when supplied. Distinguish crawl timestamps from link creation/removal dates and unknown fields from zero. Confirm priority link presence with a current page fetch before recommending action.

[Bing Webmaster Tools AI Performance](https://blogs.bing.com/webmaster/2026/2/Introducing-AI-Performance-in-Bing-Webmaster-Tools-Public-Preview/) provides aggregated citation counts for supported Microsoft/partner surfaces and sampled grounding-query evidence, not every AI engine, individual prompts or rankings. Use an authorized report/export actually available; do not assume an API/MCP exposes it. [Google AI-feature traffic is included in Search Console's Web totals](https://developers.google.com/search/docs/appearance/ai-features), so those totals alone cannot isolate AI share of voice.

For provider AI visibility samples, record platform/model, prompt set and selection, market/language, run times, repetitions, successful/failed runs and the denominator. Distinguish brand mentions from linked citations; define share-of-voice numerator and comparison set. A sampled non-mention does not prove absence across all users or prompts.

## Provider Decision Table

| Need | Preferred source | Notes |
|---|---|---|
| Repo/package discoverability | Local scripts + `gh` + registries | Default for open-source repos |
| Crawlability and metadata | `site_meta_audit.py`, Firecrawl for scale | Single page locally, site crawl via MCP |
| Owned search performance / indexing | Google Search Console | Top-row/privacy limits; indexed-version inspection |
| Sitemap submission | Google Search Console | Write scope and authorized action required |
| Core Web Vitals | PageSpeed Insights, CrUX | Treat lab and field data separately |
| Keyword research | DataForSEO or SE Ranking | Needs API/account |
| Structured data | Schema Markup Validator / Rich Results Test | General vocabulary versus Google feature eligibility |
| AI visibility / GEO | Authorized Bing citation report or provider prompt samples | Record supported surfaces, sample and denominator |
| Owned-site backlinks | Authorized GSC Links export; DataForSEO/Ahrefs if needed | GSC is a sample; check index scope and live/lost status |
| Competitor backlinks / content gaps | Available DataForSEO or Ahrefs tool | Record index, scope, timestamps, filters and limits |
| Competitor page extraction | Firecrawl | Avoid claiming ranking data from crawl data alone |

## Output Rules

- Label each finding as `Confirmed`, `Likely`, or `Hypothesis`.
- Attach the source used for each claim.
- Keep manual/account blockers explicit: missing API key, missing OAuth, missing Search Console property, or provider not installed.
- Separate crawl/indexability from ranking. A crawlable page is not proof of indexing or ranking.
