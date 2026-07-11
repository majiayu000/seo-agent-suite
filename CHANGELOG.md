# Changelog

## Unreleased

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
