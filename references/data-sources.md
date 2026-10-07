# SEO Data Sources

Use the smallest source that can prove the claim. Keep local dry audits separate from authenticated/paid evidence. Check the actual available tool and account scope; an MCP may expose only part of a provider API.

For each claim record confidence, provider/tool, `collected_at` with timezone, data window, property/domain/URL scope, region/language/device, filters/aggregation, pagination/depth, and sampling/truncation. Mark unknown fields explicitly and reference redacted raw evidence. Before calling a provider, record current plan, permissions, quota and request scale (targets × queries × markets × devices × repeats, plus depth/pages). Estimate costs from current account/provider evidence; dated public credit examples below are not fixed prices or proof of account entitlement. Record the price-source check date, billable unit and currency separately from observed request counts; retain unknown charges instead of assuming zero. Reuse existing task authorization and budget.

## Local And Free Baseline

Use first for repo/package SEO:

- `repo_seo_baseline.py`: repository metadata, manifests, package registry status, homepage, robots, and sitemap checks.
- `site_meta_audit.py`: single-page HTML metadata, canonical, robots meta, social cards, JSON-LD, headings, robots.txt, and sitemap.xml.
- `gh`, `npm view`, the crates.io API, and `curl`: direct public-surface verification;
  `cargo search` provides discovery candidates, not exact publication proof.
- Web search: exact brand/package queries and collision checks.

Limits: no keyword volume, no backlink index, no historical ranking, weak JavaScript rendering coverage.

## First-Party Google Sources

### Property-Authorized Search Console

Use Google Search Console only with explicit authorized access to the relevant property, through the actual account/browser/API route. Ownership or delegated property permission is separate from merely having a Google account or API key. It supplies property-specific search performance and indexed-version inspection; sitemap submission is a separate write action.

Search Console boundaries:

- [Search Analytics query](https://developers.google.com/webmaster-tools/v1/searchanalytics/query): record property, inclusive PT date range, search type, dimensions/filters, requested and returned aggregation, `dataState`, `rowLimit` and `startRow`. Results are top rows, not a complete query log, even after pagination. Mark fresh/incomplete data and keep these settings consistent across comparisons. [Privacy filtering](https://support.google.com/webmasters/answer/96568?hl=en) also omits anonymized queries; do not force query-row sums to equal property totals.
- [URL Inspection API](https://developers.google.com/webmaster-tools/v1/urlInspection.index/inspect) reports the indexed version, not a live URL test. Preserve [`lastCrawlTime`, fetch/index state and Google-selected canonical](https://developers.google.com/webmaster-tools/v1/urlInspection.index/UrlInspectionResult). Compare a fresh HTTP/render check separately; a deploy passing today does not prove Google has recrawled it.
- [Sitemap submission](https://developers.google.com/webmaster-tools/v1/sitemaps/submit) requires write-capable `webmasters` OAuth scope, property access and authorization for that specific action. An audit or read-only account is insufficient; proceed if submission is already authorized. Submission success does not prove indexing.
- GA4 is optional downstream traffic/key-event or conversion evidence when authorized. Record landing-page/channel, timezone, event definition and [attribution model](https://developers.google.com/analytics/devguides/reporting/data/v1/conversions-api-basics); do not equate analytics visits with Search Console clicks or infer causation from a before/after change.

### Public PageSpeed Insights And CrUX

Access guidance checked **2026-10-07**: a public, non-owned URL can use PageSpeed Insights and available public CrUX evidence without Search Console ownership verification. Google's [PageSpeed API guide](https://developers.google.com/speed/docs/insights/v5/get-started) permits keyless use and recommends a key for frequent automated queries. The [CrUX API](https://developer.chrome.com/docs/crux/api) requires a configured Google Cloud API key; this is API access, not proof of website ownership. Check public report availability, API enablement, quotas and the actual tool route separately. Do not create credentials or assume account access from these docs. [CrUX inclusion](https://developer.chrome.com/docs/crux/methodology) depends on eligibility and sufficient observations, so a public URL can still lack field data.

[PageSpeed Insights](https://developers.google.com/speed/docs/insights/v5/about) separates Lighthouse lab diagnostics from CrUX field data. Record mobile/desktop, URL versus origin, the collection period, and field percentile for LCP/INP/CLS. Preserve insufficient-data or origin-fallback status; a lab score/TBT is not field INP or proof of a CWV pass. Use comparable lab settings/runs and field windows for retests.

Check which fields the current endpoint actually returns. Google’s
[API guide](https://developers.google.com/speed/docs/insights/v5/get-started)
announces planned removal of PageSpeed's embedded field data and recommends
the CrUX APIs. Missing field data is not a passing result. For authentication,
permission or quota failures, retain the HTTP status and redacted provider
reason, mark the affected measurement blocked, and resume with authorized
access or quota. Do not treat an error response as an empty measurement.

## Crawling And Rendering

Use when HTML fetches are insufficient:

- Firecrawl, if the available tool supports the required operation: crawl/render pages, extract page text and gather competitor page evidence.
- Playwright/Lighthouse: local rendering, Core Web Vitals proxies, screenshots, console/network proof.

Choose available, authorized Firecrawl for multi-page external crawling; it is optional, not a prerequisite for the baseline. Choose Playwright/Lighthouse for local app/site QA or when visual/runtime proof matters.

Firecrawl cost guidance checked **2026-10-07**: [Enhanced Mode](https://docs.firecrawl.dev/features/enhanced-mode) documents the same base 1-credit request cost for basic/enhanced, with no separate charge for its internal escalation retry. The [billing guide](https://docs.firecrawl.dev/billing) distinguishes endpoint units and stackable scrape options; the base is not an all-in quote. Record endpoint, pages, options, provider-reported usage and current plan evidence. Do not double-count the internal retry or equate credits with currency. A returned document can be billable even for a target HTTP error; some no-document outcomes also charge. Unknown actual cost stays unknown. Recheck both sources before estimating a task; this guidance does not authorize provider calls, paid options or changes to access policy.

### Structured-Data Feature Selection

For structured data, JSON-LD presence or valid JSON is only the first check. Use the [Schema Markup Validator for general schema.org markup and Rich Results Test for Google-supported features](https://developers.google.com/search/docs/appearance/structured-data). Retain tested URL/code, time, types and warnings/errors; validation does not guarantee rich-result display. Before recommending a feature, record its exact name, consumer, schema type, page purpose, market, official source/check date and feature-specific validation evidence. Keep content quality, JSON syntax, schema semantics, current eligibility and observed appearance separate; absent evidence means `not_checked`.

Feature status checked **2026-10-07**:

- **FAQ:** Google's [May 2026 changelog](https://developers.google.com/search/updates) says FAQ rich results stopped appearing on **2026-05-07**, including the formerly eligible health/government sites. [FAQPage](https://schema.org/FAQPage) remains a schema.org type. Review useful visible answers independently; retirement alone does not require deleting content or markup. Do not substitute [QAPage](https://developers.google.com/search/docs/appearance/structured-data/qapage) on ordinary FAQ pages. [Google AI features](https://developers.google.com/search/docs/appearance/ai-features) do not require special schema markup.
- **Courses:** [Course Info was retired](https://developers.google.com/search/blog/2025/06/simplifying-search-results); [Course list](https://developers.google.com/search/docs/appearance/structured-data/course) remains a distinct documented feature with its own requirements, including at least three courses and carousel markup. A `Course` type or valid JSON alone does not identify which feature is supported or establish eligibility. A single lesson, flashcard or video is not automatically a course list; do not delete generic semantic markup solely because Course Info ended.
- **Datasets:** [Dataset markup](https://developers.google.com/search/docs/appearance/structured-data/dataset) serves Dataset Search. Google's [November 2025 clarification](https://developers.google.com/search/updates) separates that consumer from ordinary Google Search results. Name the consumer/profile before judging requirements; do not promise an ordinary Search rich result from valid Dataset JSON-LD.

## Keyword, SERP, And Competitive Data

Use when recommendations depend on search volume, difficulty, SERP shape, competitor rankings, or keyword clusters:

- DataForSEO: keyword/SERP data when the available endpoint supports the claim; [SERP snapshots depend on location/device and collection time](https://docs.dataforseo.com/v3/serp-google-organic-overview/), and endpoint depth/format affects what is captured.
- SE Ranking: keyword, competitive or AI visibility reporting when supported by the actual available tool/account; inspect its metric definition before using it.
- Ahrefs: backlink/competitor index evidence and keyword/traffic estimates when the current tool and plan allow them; label estimates as estimates.

Do not block simple repo metadata fixes on these providers. Keyword volume, backlink gaps and competitive visibility need a source that measures that specific claim; a crawl or one search result is insufficient. Keep forecasts of ranking potential as hypotheses.

## Backlinks And AI Visibility

For owned-site links, prefer an already authorized [Search Console Links export](https://support.google.com/webmasters/answer/9049606) when its sample answers the question. Record property, export time/type and row limits. It is not exhaustive, can include removed links, and does not report follow/nofollow. Do not assume the Search Analytics API exposes this report or automate browser access without authorization.

For competitor/index comparisons, choose an available authorized [DataForSEO backlinks endpoint](https://docs.dataforseo.com/v3/backlinks-backlinks-live/) or [Ahrefs backlinks tool](https://docs.ahrefs.com/en/api/reference/site-explorer/get-all-backlinks). Record domain/subdomain/exact-URL scope, grouping/filters and live/lost/history selection; retain `last_seen` or the provider's equivalent when supplied. Distinguish crawl timestamps from link creation/removal dates and unknown fields from zero. Confirm priority link presence with a current page fetch before recommending action.

### Google Generative AI Impressions

Checked **2026-10-07**: the authorized [Generative AI performance report (Search)](https://support.google.com/webmasters/answer/16984139?hl=en) reports AI Overviews/AI Mode **impressions**. Record property, PT date window, page/country/device/date dimensions, search-type filter, preliminary status and row limits. Chart/property and table/page aggregation can differ; retain both. Export maps unavailable `~`/`-` values to zero, so preserve their UI status instead of declaring measured zeros. Confirm report access and evidence for the specific property; absent reports do not prove zero exposure. This UI/export documentation does not establish API/MCP support, queries, clicks, conversions or rankings. Its data overlaps [Search Console Web totals](https://developers.google.com/search/docs/appearance/ai-features); do not add them together or call either an all-engine share-of-voice denominator.

### Google Search Generative AI Control

Checked **2026-10-07**: the [Search generative AI control](https://support.google.com/webmasters/answer/16908024) has Include, Exclude and Inherit settings for supported Search/Discover generative features. With authorized account evidence, record property, retrieval time, configured setting, effective state and inherited parent when applicable. Default inclusion does not prove a specific property's effective state; unavailable settings remain `unknown`. This display/grounding choice is distinct from Google-Extended's training control and from ordinary Search ranking/indexing. Inclusion is not a display guarantee. Do not change a setting as part of an audit or infer its state from public HTML.

### Bing Citation Evidence

[Bing Webmaster Tools AI Performance](https://blogs.bing.com/webmaster/2026/2/Introducing-AI-Performance-in-Bing-Webmaster-Tools-Public-Preview/) provides aggregated citation counts for supported Microsoft/partner surfaces and sampled grounding-query evidence, not every AI engine or individual prompts. Use an authorized report/export actually available; do not assume an API/MCP exposes it.

Checked **2026-10-07**: Bing's [June 2026 update](https://blogs.bing.com/search/2026/6/New-AI-Visibility-Insights-in-Bing-Webmaster-Tools-Intents-Topics-Citation-Share-Compare/) defines **Citation Share** as the site's citations divided by all sites' citations for the **same grounding query**. Preserve returned shares, query, filters, window and supported surfaces; do not average query percentages into a global share without compatible denominators. Intents/Topics are evolving AI-derived classifications: retain their labels and classification version, or `unknown`. Compare describes changes between periods, not causal uplift. Citation Share is not traffic share, CTR, rankings, quality scores or disclosure of competitor identities.

### Observed AI-Attributed Sessions

Checked **2026-10-07**: GA4's [default channel guidance](https://support.google.com/analytics/answer/9756891) includes **AI Assistant**, using `ai-assistant` medium for recognized assistant referrers. Google AI Overviews/AI Mode are excluded from that channel; their organic Search visits remain Organic Search. Start with authorized native session channel/source evidence, not a referral-only filter. Record property, timezone/window, source/medium, landing page, filters, collection time and quality limits. Keep session/engagement metrics separate from event attribution and key-event definitions. Label any supplemental source/UTM classification and avoid overlapping sums; an allowlist needs a dated hostname-boundary rule, not broad brand substrings. Direct/unknown traffic stays unattributed. Missing referrers and no-click answers are not recoverable sessions; citations do not create visits, and zero observed sessions does not prove zero AI visibility.

For provider AI visibility samples, record platform/model, prompt set and selection, market/language, run times, repetitions, successful/failed runs and the denominator. Distinguish brand mentions from linked citations; define share-of-voice numerator and comparison set. A sampled non-mention does not prove absence across all users or prompts.

## Provider Decision Table

| Need | Preferred source | Notes |
|---|---|---|
| Repo/package discoverability | Local scripts + `gh` + registries | Default for open-source repos |
| Crawlability and metadata | `site_meta_audit.py`, Firecrawl for scale | Single page locally, site crawl via MCP |
| Owned search performance / indexing | Google Search Console | Top-row/privacy limits; indexed-version inspection |
| Sitemap submission | Google Search Console | Write scope and authorized action required |
| Core Web Vitals | Public PageSpeed Insights, available CrUX | No site ownership prerequisite; check route/key/quota and field availability; separate lab/field |
| Keyword research | DataForSEO or SE Ranking | Needs API/account |
| Structured data | Schema Markup Validator / Rich Results Test | General vocabulary versus Google feature eligibility |
| Google AI impressions | Authorized GSC Generative AI performance UI/export | AIO/AI Mode impressions; overlaps Web totals; preserve unavailable values |
| AI visibility / GEO | Authorized Bing citation report or provider prompt samples | Same-query Citation Share versus prompt-sample denominators; no global share inference |
| Observed AI-attributed visits | Authorized GA4 native session reports | AI Assistant versus Organic Search; preserve attribution scope and unknowns |
| Owned-site backlinks | Authorized GSC Links export; DataForSEO/Ahrefs if needed | GSC is a sample; check index scope and live/lost status |
| Competitor backlinks / content gaps | Available DataForSEO or Ahrefs tool | Record index, scope, timestamps, filters and limits |
| Competitor page extraction | Firecrawl | Avoid claiming ranking data from crawl data alone |

## Output Rules

- Label each finding as `Confirmed`, `Likely`, or `Hypothesis`.
- Attach the source used for each claim and its check date. Dated guidance above is a snapshot, not proof of current account state; recheck changing product, feature and cost claims at use time.
- Keep manual/account blockers explicit: missing API key, missing OAuth, missing Search Console property, or provider not installed.
- Separate crawl/indexability from ranking. A crawlable page is not proof of indexing or ranking.
