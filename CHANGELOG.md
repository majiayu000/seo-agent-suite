# Changelog

## Unreleased

- Package the suite as installable `seo-agent-suite` (`pip install -e .`) with
  console script `seo-agent` (`repo-baseline`, `site-meta`, `doctor`, `version`,
  optional `mcp`).
- Add Report Envelope fields to JSON output: `schema_version`, `tool_version`,
  `target`, and `findings[]` (severity / confidence / surface / evidence /
  action). Legacy evidence fields are preserved.
- Add optional MCP server (`pip install 'seo-agent-suite[mcp]'` then
  `seo-agent mcp`) exposing `repo_baseline`, `site_meta`, and `doctor`.
- Identify public fetches as `seo-agent-suite/0.2.0` and add a small
  `robots_path_allowed` helper (not a sitewide crawler).
- Clarify multi-runtime use (Codex / Cursor / Claude Code / MCP) and mark
  Shipwise as an optional adapter.

- Recover raw H1 text once across heading boundaries and EOF without stale-buffer
  duplicates; retain the collector's lexical, non-DOM scope.
- Decode single-line YAML double-quoted escapes into Unicode values and reject
  invalid escapes without input disclosure; keep plain/single-quoted backslashes
  literal and preserve the project-YAML CLI error contract.

- Keep repository JSON reports available when external commands cannot launch
  or emit invalid UTF-8; preserve existing missing-tool/timeout/exit behavior.
- Separate public performance access from property-authorized Search Console,
  and refresh dated AI reporting, structured-data and provider billing guidance.
- Classify sitemap XML by root/namespace and keep dormant templates, SVG titles
  and script/style source out of raw document metadata; recognize omitted heads.
- Preserve homepage path slashes, validate restricted Shipwise input structure
  and array members, and return structured errors for manifest numeric limits.
- Retain ordered Open Graph declarations and keep the first image's attributes
  together instead of combining fields from different images. Apply the same
  first-root ownership to audio and video summaries.
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
