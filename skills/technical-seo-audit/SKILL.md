---
name: technical-seo-audit
description: Run evidence-backed technical SEO audits for websites, docs sites, landing pages, and GitHub Pages properties. Use when Codex needs to inspect crawlability, title/meta/canonical tags, robots.txt, sitemap.xml, Open Graph/Twitter metadata, JSON-LD/schema, status codes, redirect/canonical issues, internal links, JavaScript rendering risk, Core Web Vitals boundaries, or technical SEO issues for a site.
---

# Technical SEO Audit

Audit crawlability and page-level technical SEO. Prefer deterministic evidence before recommendations.

## Workflow

1. Identify the target URL and scope: single page, docs site, sitemap URLs, or selected landing pages. Record collection time, URL set, exclusions, and available site ownership/access.
2. Run the local page audit first from the SEO Agent Suite repository or
   installed plugin root:

```bash
python3 scripts/site_meta_audit.py <url> --json
```

3. For repository-backed sites, also run `github-repo-seo` baseline collection.
4. For multi-page or JavaScript-rendered sites, read `references/data-sources.md` and choose Firecrawl, Playwright, or Lighthouse based on the proof needed and authorized access path. An audit does not authorize desktop UI operation or authenticated submissions.
5. Classify every finding as `Confirmed`, `Likely`, or `Hypothesis`.

## Inspect

- HTTP status, redirects, canonical URL, and duplicate canonical risk.
- `<title>`, meta description, robots meta, H1, headings, and indexability.
- `robots.txt`, `sitemap.xml`, sitemap freshness, and discoverable URLs.
- Open Graph, Twitter cards, social preview assets.
- JSON-LD/schema presence and whether it matches page content.
- Internal links and orphaned page risk when sitemap/crawl data is available.
- Mobile/performance/CWV only when PageSpeed, CrUX, Lighthouse, or browser evidence is available.

## Collect The Missing Evidence When Relevant

- **JavaScript:** for representative page types, save the response HTML and the rendered DOM after normal loading, without clicking, scrolling, typing, or signing in to reveal primary content. Compare main text, crawlable links, title, robots, canonical, and structured data; record blocked/failed resources and the render wait condition. Directly load a valid SPA deep link and a nonexistent route, retaining response codes and rendered error content. A browser render proves that environment's behavior; use Google's rendered HTML in URL Inspection or Rich Results Test when claiming what Google can render. See [JavaScript guidance](https://developers.google.com/search/docs/crawling-indexing/javascript/fix-search-javascript).
- **Mobile:** when dynamic serving, separate mobile URLs, or device-specific content is present or suspected, compare equivalent mobile and desktop pages for primary content, links, metadata, robots, schema, and asset access. Record user agent and viewport; different layouts alone are not missing content. See [mobile guidance](https://developers.google.com/search/docs/crawling-indexing/mobile/mobile-sites-mobile-first-indexing).
- **Performance:** separate a Lighthouse lab run from CrUX field data. Record tested URL, device, run time and lab conditions, and whether field data describes that URL or the origin with its collection window. PSI field data uses a trailing 28-day period; missing field coverage is `unknown`, and origin results do not prove a specific URL passes CWV. Retest lab behavior after the change; do not expect the field window to change immediately. See [PSI data boundaries](https://developers.google.com/speed/docs/insights/v5/about).
- **Structured data:** distinguish markup presence, valid JSON/Schema.org vocabulary, eligibility for a supported Google rich result, and actual search appearance. Inspect correspondence with visible content; use [Schema Markup Validator](https://validator.schema.org/) for generic validation and [Rich Results Test](https://search.google.com/test/rich-results) for Google's supported features. Save URL, time, errors and warnings. Unsupported types are not automatically invalid; passing a test does not guarantee display, per [Google's policies](https://developers.google.com/search/docs/appearance/structured-data/sd-policies).
- **Orphans:** crawl internal links from normal entry pages and compare the URLs reached with an independent inventory such as a sitemap, CMS export, or known route list. Keep inventory-only URLs separate from crawl-discovered URLs with no inbound link; test candidate status and indexability. Report the set difference and crawl scope, caps, exclusions and render coverage. Confirm an orphan only within a complete declared scope; an incomplete crawl/inventory supports `Likely` risk, not a sitewide claim. Sitemap discovery alone does not prove an internal link exists.
- **Language variants:** only when equivalent localized pages already exist, inspect their chosen hreflang channel (HTML, HTTP headers, or sitemap), self references, reciprocal links, fully qualified URLs, language/region codes, reachable targets and canonical consistency. Do not prescribe duplicate channels or new translations for a monolingual site. See [localized-page guidance](https://developers.google.com/search/docs/specialty/international/localized-versions).
- **Images and video:** when these matter to the requested pages, inspect informative body images as well as social previews: crawlable source URLs, relevant surrounding text, meaningful alt text, responsive loading and dimensions. Judge image purpose before flagging alt: [decorative images](https://www.w3.org/WAI/tutorials/images/decorative/) can correctly use `alt=""`. For video, inspect embed/media and thumbnail access, visible content, and matching metadata/schema. Recommend a dedicated watch page only when video search features are a stated goal and it fits the content; a supplementary product demo does not require one. See [image](https://developers.google.com/search/docs/appearance/google-images) and [video guidance](https://developers.google.com/search/docs/appearance/video).

## Output

Use `references/report-template.md`. Default to an audit report and local issue drafts; create remote issues or change/deploy the site only within the user's authorized task. Each action needs its exact target URL/file, before evidence, proposed change, retest command/tool and expected result, owner and completion condition. Keep unavailable evidence and account blockers explicit.

Track three separate clocks: the change is live and verified at the URL; a later crawl/index observation reflects that version; comparable traffic/ranking measurements show an effect. A passing deployment retest completes the technical fix without claiming indexing or SEO gains.

## Rules

- Do not claim Core Web Vitals from HTML-only checks.
- Do not claim index coverage without Search Console or search-result evidence.
- Do not claim sitewide crawl health from a single page.
- Do not recommend hidden text, crawler-only copy, or model-only instructions.
