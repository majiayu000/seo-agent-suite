---
name: technical-seo-audit
description: Run evidence-backed technical SEO audits for websites, docs sites, landing pages, and GitHub Pages properties. Use when Codex needs to inspect crawlability, title/meta/canonical tags, robots.txt, sitemap.xml, Open Graph/Twitter metadata, JSON-LD/schema, status codes, redirect/canonical issues, internal links, JavaScript rendering risk, Core Web Vitals boundaries, or technical SEO issues for a site.
---

# Technical SEO Audit

Audit crawlability and page-level technical SEO. Prefer deterministic evidence before recommendations.

## Workflow

1. Identify the target URL and scope: single page, docs site, sitemap URLs, or selected landing pages.
2. Run the local page audit first from the SEO Agent Suite repository or
   installed plugin root:

```bash
python3 scripts/site_meta_audit.py <url> --json
```

3. For repository-backed sites, also run `github-repo-seo` baseline collection.
4. For multi-page or JavaScript-rendered sites, read `references/data-sources.md` and choose Firecrawl, Playwright, or Lighthouse based on the proof needed.
5. Classify every finding as `Confirmed`, `Likely`, or `Hypothesis`.

## Inspect

- HTTP status, redirects, canonical URL, and duplicate canonical risk.
- `<title>`, meta description, robots meta, H1, headings, and indexability.
- `robots.txt`, `sitemap.xml`, sitemap freshness, and discoverable URLs.
- Open Graph, Twitter cards, social preview assets.
- JSON-LD/schema presence and whether it matches page content.
- Internal links and orphaned page risk when sitemap/crawl data is available.
- Mobile/performance/CWV only when PageSpeed, CrUX, Lighthouse, or browser evidence is available.

## Output

Use `references/report-template.md`. Keep a concise action plan with owner-ready tasks or GitHub issues.

## Rules

- Do not claim Core Web Vitals from HTML-only checks.
- Do not claim index coverage without Search Console or search-result evidence.
- Do not claim sitewide crawl health from a single page.
- Do not recommend hidden text, crawler-only copy, or model-only instructions.
