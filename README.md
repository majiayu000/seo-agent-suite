# SEO Agent Suite

[![Check](https://github.com/majiayu000/seo-agent-suite/actions/workflows/check.yml/badge.svg)](https://github.com/majiayu000/seo-agent-suite/actions/workflows/check.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Codex plugin for evidence-backed SEO and discoverability audits.

This repository is the execution layer for Shipwise-style discoverability work. [Shipwise](https://majiayu000.github.io/shipwise/) remains the launch/discoverability planning system; this plugin provides reusable skills and scripts that collect evidence and turn it into repo, package, site, and content SEO actions.

## Relationship To Shipwise

```text
shipwise
├── docs/DISCOVERABILITY.md
├── templates/seo/keyword_map.md
└── projects/<project>/

seo-agent-suite
├── .codex-plugin/plugin.json
├── skills/
├── scripts/
└── references/
```

Use Shipwise to decide launch strategy, platform fit, messaging, and project records. Use SEO Agent Suite to run audits, collect public-surface evidence, and generate SEO issues or reports.

## Quick Start

Clone the repository to run the local audits with Python 3.11 or newer:

```bash
git clone https://github.com/majiayu000/seo-agent-suite.git
cd seo-agent-suite
```

Run the local validation checks:

```bash
python3 -m py_compile scripts/*.py
python3 tests/test_structure.py
python3 -m unittest discover -s tests -p 'test_*.py'
```

Run a repository baseline audit:

```bash
python3 scripts/repo_seo_baseline.py --root . --json
```

Run the same audit with a Shipwise project record:

```bash
python3 scripts/repo_seo_baseline.py --root /path/to/repo --project-yaml /path/to/project.yaml --json
```

Run a basic public-page metadata audit:

```bash
python3 scripts/site_meta_audit.py https://example.com/ --json
```

The plugin manifest lives at [.codex-plugin/plugin.json](.codex-plugin/plugin.json).
Skills live under [skills/](skills/), and reference material lives under
[references/](references/).

## Load the skills in Codex

Cloning the repository makes the Python commands available; install the plugin
to make its four skills available in Codex. This checkout includes
`.agents/plugins/marketplace.json` for local installation. Its catalog is:

```json
{
  "name": "seo-suite-local",
  "plugins": [
    {
      "name": "seo-agent-suite",
      "source": {"source": "local", "path": "./"},
      "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
      "category": "Productivity"
    }
  ]
}
```

The source path is relative to the marketplace root (this checkout), not to
`.agents/plugins/`. With Codex CLI versions supporting `plugin add` (verified
with 0.160.0), run these commands from the checkout:

```bash
codex plugin marketplace add .
codex plugin add seo-agent-suite@seo-suite-local
```

In the desktop app, restart it, open the Plugins Directory, select
`seo-suite-local`, and install SEO Agent Suite. Start a new chat or CLI session
and confirm the four skills listed below are available under the
`seo-agent-suite:` namespace. Then request, for example:
“Use seo-agent-suite:technical-seo-audit to audit https://example.com/ and produce a report.”
Confirm that the skill resolves its scripts and references from the installed
plugin root. After edits, refresh the installed copy and restart before retesting.
Provider authentication is separate and is only needed for the data you request.
See the [official OpenAI local-plugin instructions](https://developers.openai.com/plugins/build/plugins)
for client support and marketplace management.

## Choose an audit and interpret its report

| Task | Start here | What to inspect |
| --- | --- | --- |
| Review a repository before launch | `repo_seo_baseline.py --root /absolute/repo/path --json` | `readmes`, `community_files`, manifests and collected GitHub metadata |
| Check a Shipwise launch record | Add `--project-yaml /absolute/path/project.yaml` | `shipwise.checks`, `errors` and the record's proof fields |
| Check a public page | `site_meta_audit.py https://your-public-site.example/ --json` | `checks`, canonical, title, description and crawl-resource responses |
| Decide what content to write | [seo-content-geo](skills/seo-content-geo/SKILL.md) | Task intent, current source evidence, target page and unanswered questions |
| Establish demand or indexing | [seo-data-sources](skills/seo-data-sources/SKILL.md) | Authorized provider access and the claim each source can support |

Run the scripts from this repository's checkout, even when `--root` points to
another project. Save a report outside the audited repository if you want to
keep its working tree unchanged:

```bash
python3 scripts/repo_seo_baseline.py --root /absolute/repo/path --json > /absolute/report/path/repo-baseline.json
```

For the repository audit, `status: error` and exit code **1** mean a collected
manifest, site-resource or Shipwise check failed. Read each `errors` entry's
surface, check/resource and reason before fixing the source. Other evidence,
including subprocess results, still needs review; `status: ok` is not a universal
launch-readiness verdict.

For the page audit, exit code **0** means the target page was fetched successfully.
Missing metadata and crawl resources can still appear as **false** in `checks`.
A non-zero exit reports a page-fetch failure, invalid input, or an explicitly
selected findings threshold. Inspect the JSON
rather than treating either script's exit code as a search-performance score.

To use page findings as an optional CI gate:

```bash
python3 scripts/site_meta_audit.py https://example.com/page --json --fail-on error
```

`--fail-on error|warning|info` returns **1** when a finding meets or exceeds the
chosen severity; without it, the page-fetch exit behavior stays the same.
Invalid CLI arguments still return **2**. Intentional `noindex` or crawl blocks
can trigger a gate too; apply it only to URLs whose intended behavior fits it.

The page report adds `assessment` and `findings` alongside the presence checks:

- `assessment.crawl_access` evaluates the final page URL for `Googlebot`,
  `OAI-SearchBot`, and `GPTBot` separately, retaining the selected user-agent
  group and winning rule/line. Specific groups override `*`; repeated groups
  are merged, the longest matching rule wins, and Allow wins equal-length ties.
  Matching includes case-sensitive paths, query strings, UTF-8/percent escapes,
  `*`, and `$`. A robots 404/410 means no configured restriction. Other failed,
  HTML, or truncated robots responses leave permission `null` (unknown).
  This is a local rule interpretation, not a live bot/CDN probe or cached-crawler
  decision. Blocking an AI bot is reported as information, not advice to allow it.
- `assessment.indexing` evaluates head-level robots/Googlebot meta declarations
  and applicable `X-Robots-Tag` headers, including `none` and conflicting
  declarations. `noindex: false` means no such directive was observed in the
  complete response; truncated HTML without an observed noindex reports `null`.
  `indexed` remains `unknown`. A robots block can prevent crawlers seeing noindex;
  neither crawl permission nor a successful fetch proves indexing.
- `assessment.canonical` distinguishes missing, invalid, conflicting, self,
  other, and unknown HTML declarations using the final URL and document base.
  Host case, default ports and unreserved percent escapes are normalized for
  comparison. A different canonical target is a warning to review intent,
  not an invalid-URL verdict. HTTP Link canonical headers remain evidence for
  manual review and make the overall canonical assessment unknown.
- `assessment.json_ld_parse_valid` reports JSON parsing only: `null` when absent
  or capture coverage is incomplete. A parsed value does not establish Schema.org
  validity or rich-result eligibility. Title/description character lengths and
  nonempty H1 count are observations, without fixed length limits or a one-H1 gate.
- Every finding has `severity`, `confidence` (`Confirmed`, `Likely`, or
  `Hypothesis`), a message and an evidence path. Observed noindex, Googlebot
  Disallow, invalid/conflicting HTML canonicals and malformed/empty JSON-LD are
  errors; incomplete evidence, non-self canonicals and missing title/description
  are warnings; AI crawl restrictions and heading-count review are information.
  These severities support local gates, not ranking or index-state measurements.

Both reports include `collected_at`; repository evidence also includes the Git
HEAD. For pages, inspect `robots_meta_declarations`, `canonicals`, `json_ld`,
and the response's `x_robots_tag`, `link_headers` and `redirects`. Presence
checks remain presence checks: a JSON-LD tag is not proof of valid markup, and
a canonical tag is not proof Google selected it.

Sitemaps declared in robots.txt are checked before guessed paths, with at most
10 sitemap candidates per audit. Inspect `sitemap_discovery` for omitted
candidates or truncated robots evidence; incomplete coverage cannot prove a
sitemap is absent. A robots 404/410 is reported as `not_configured` and does
not by itself fail the repository audit. Community paths and issue-template
candidates are local evidence; template usability still requires review.
Automatic registry queries skip private npm packages and Cargo packages that
cannot publish to crates.io. Workspace metadata is collected with
`--locked --offline`; unavailable dependencies or metadata are reported rather
than modifying the audited project's lockfile. Crate identity and published
version come from the crates.io API, with local version differences kept
separate from fetch success.

Local scripts require no SEO-provider API keys, but repository checks can call
installed tools and public URLs. They do not connect Search Console or keyword
providers automatically. An authenticated service such as
[OpenSEO's Codex integration](https://openseo.so/docs/codex-plugin) has a separate
OAuth and data-access workflow; access must be established before using its
keyword or performance data in a claim.

For a content review, specify a real target page and ask for one or two primary
user tasks, related questions, source URLs and confidence labels. Use
[Shipwise's discoverability guide](https://github.com/majiayu000/shipwise/blob/main/docs/DISCOVERABILITY.md)
to connect those findings to the launch record and
[the report template](references/report-template.md) to keep evidence reviewable.

## Skills

- [github-repo-seo](skills/github-repo-seo/SKILL.md): GitHub repository, README, package registry, docs site, and Search Console boundary checks.
- [technical-seo-audit](skills/technical-seo-audit/SKILL.md): Crawlability, metadata, canonical, robots, sitemap, structured data, and page health checks.
- [seo-content-geo](skills/seo-content-geo/SKILL.md): Keyword mapping, content briefs, GEO/AEO readiness, and AI citation-oriented content review.
- [seo-data-sources](skills/seo-data-sources/SKILL.md): Provider selection and evidence boundaries for local scripts, Firecrawl, Google Search Console, PageSpeed/CrUX, DataForSEO, SE Ranking, and Ahrefs.

## Scripts

```bash
python3 scripts/repo_seo_baseline.py --root . --json
python3 scripts/site_meta_audit.py https://example.com/ --json
```

The scripts are local dry-audit tools. They do not require API keys and should not be used to claim keyword volume, ranking, backlink gaps, or Search Console indexing status.

## Validation

See the [acceptance status](references/acceptance-status.md) for completed
plugin, browser and public-site checks, and the remaining account-data blockers.

```bash
python3 -m py_compile scripts/*.py
python3 tests/test_structure.py
python3 -m unittest discover -s tests -p 'test_*.py'
```

## Release Notes

See [CHANGELOG.md](CHANGELOG.md).

## Boundaries

- Do not store API keys, cookies, Search Console credentials, or provider tokens in this repository.
- Do not claim Google indexing or rankings from a successful crawl alone.
- Do not present optional MCP providers as installed unless the current environment proves it.
- Do not automate posting or publishing. This plugin audits and prepares evidence; publishing still requires explicit user instruction.
- The declared `Write` capability is for local report and issue-draft files only, never for remote publishing.

## Support and license

Use [GitHub issues](https://github.com/majiayu000/seo-agent-suite/issues) for
reproducible audit failures, with redacted input and the relevant report fields.
See [LICENSE](LICENSE) for the MIT terms and [CHANGELOG.md](CHANGELOG.md) for
version history.
