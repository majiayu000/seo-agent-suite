# Changelog

## Unreleased

- Classify sitemap XML by root/namespace and keep dormant templates, SVG titles
  and script/style source out of raw document metadata; recognize omitted heads.
- Preserve homepage path slashes, validate restricted Shipwise input structure
  and array members, and return structured errors for manifest numeric limits.
- Retain ordered Open Graph declarations and keep the first image's attributes
  together instead of combining fields from different images.
- Preserve HTTP redirect/error status without reading irrelevant bodies and
  reject premature EOF in Content-Length responses.
- Scope HTML findings to supported media types and unencoded responses;
  retain applicable noindex headers and mark compressed crawl resources unknown.
- Report Unicode-aware keyword substring counts as observations rather than
  automatically failing launch checks for keyword stuffing.
- Test Python 3.11/3.12 in CI and run controlled browser fixtures independently
  of public-site availability with `--fixtures-only`.

- Add evidence-backed page findings and opt-in `--fail-on` severity gates while
  preserving default fetch exit codes. Evaluate per-crawler robots permissions,
  scoped noindex directives, HTML canonical declarations and JSON-LD parsing;
  keep indexing state unknown and heading/length observations separate.

- Include implicit Cargo workspace members and resolve inherited root-package
  metadata even when no explicit member list is provided.
- Add a CLI-installable local marketplace, exercised plugin/browser acceptance,
  and an offsite brand evidence workflow with source identity and ownership.

- Retain robots, canonical, redirect and structured-data evidence; discover
  sitemaps declared in robots.txt and distinguish resource presence from validity.
- Handle international URLs and declared HTML encodings without interrupting
  structured audit errors, and redact credentials from report and error paths.
- Cover GitHub community-file locations, repository homepages and actual public
  workspace packages, with exact registry identity and version evidence.
- Record collection time and revision, and add actionable content briefs,
  provider measurement boundaries, local plugin setup and repair retests.
- Run the new behavior regressions alongside the existing suite in CI.

- Fixed local audit scripts to return non-zero status for invalid inputs,
  unreachable audited pages, manifest parser failures, and Shipwise
  discoverability gate failures.
- Added `--project-yaml` handoff support for Shipwise `discoverability:` fields.
- Added script behavior tests for URL validation, TOML parser errors,
  soft-404 resource detection, and Shipwise gate failures.
- Clarified skill command paths so audits run from the suite/plugin root while
  `--root` points at the target repository.

## 0.1.0 - 2026-06-25

- Initial public Codex plugin suite for evidence-backed SEO and discoverability audits.
- Added four focused skills for repository SEO, technical SEO, content/GEO, and provider selection.
- Added local dry-audit scripts and structure validation.
- Added GitHub Actions validation and README quick start.
