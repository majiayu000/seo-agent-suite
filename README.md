# SEO Agent Suite

[![Check](https://github.com/majiayu000/seo-agent-suite/actions/workflows/check.yml/badge.svg)](https://github.com/majiayu000/seo-agent-suite/actions/workflows/check.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Evidence-backed SEO and discoverability audits for **agents** — Codex skills, Cursor / Claude Code workflows, a `seo-agent` CLI, and an optional MCP server.

This repository is the execution layer for Shipwise-style discoverability work. [Shipwise](https://majiayu000.github.io/shipwise/) remains an **optional** launch/discoverability planning adapter; this suite collects public-surface evidence and turns it into repo, package, site, and content SEO actions. It does **not** auto-publish, mutate remote sites, or claim rankings from a crawl alone.

## Relationship To Shipwise

```text
shipwise (optional adapter)
├── docs/DISCOVERABILITY.md
├── templates/seo/keyword_map.md
└── projects/<project>/

seo-agent-suite (this repo)
├── seo-agent CLI / optional MCP
├── skills/
├── scripts/
└── references/
```

Use Shipwise when you already keep launch strategy there. Use SEO Agent Suite alone when you only need audits and evidence.

## Quick Start

Requires Python 3.11+.

```bash
git clone https://github.com/majiayu000/seo-agent-suite.git
cd seo-agent-suite
pip install -e .
seo-agent doctor
seo-agent repo-baseline --root . --json
seo-agent site-meta https://example.com/ --json
```

Legacy script paths still work from the suite root (agents do not need to `cd scripts/`):

```bash
python3 scripts/repo_seo_baseline.py --root /path/to/target-repo --json
python3 scripts/site_meta_audit.py https://example.com/ --json
```

For an optional per-file admission limit, add `--max-input-bytes N` to the direct
script command. `N` is a nonnegative byte count; `0` rejects every nonempty input,
and omitting it preserves the existing unlimited read policy. It covers only
files directly read by the collector: JSON manifests, root Cargo/Python TOML,
README candidates, and the selected Shipwise YAML. Oversized inputs are rejected
before decoding/parsing (at most one extra byte is read to detect overflow),
reported as collection errors, and make `--json` exit 1 while preserving valid
sibling evidence. No truncated prefix is treated as a complete document.

This is not a total-memory, parser-depth, elapsed-time, subprocess-output, or
network limit. Discovery and path/symlink behavior are unchanged. The packaged
`seo-agent`/MCP interface does not forward this direct-script option yet.

### Optional direct-site payload allowance

`python3 scripts/site_meta_audit.py URL --max-http-body-bytes N --json`
sets one nonnegative allowance across the page, robots, sitemap candidates and
endpoint fallbacks. It counts **encoded response-body payload bytes exposed by
HTTP reads**, before text decoding, including discarded sample lookahead and
exposed partial-failure bytes. This is **not a physical bandwidth limit**:
headers, HTTP/TLS/proxy framing, socket buffering and bytes hidden inside failed
reads are excluded. Redirect/error bodies remain unread and cost zero.

Omitting the option preserves existing behavior. `0`, or an exhausted allowance,
refuses the next fetch before DNS/transport. Empty responses encountered while
allowance remains cost zero; zero does not start header-only probes. Each read
is bounded by the remaining allowance, with no global N+1 probe. The existing
per-response sample cap still applies. A fully read declared Content-Length can
prove completion at the exact boundary; unknown-length/chunked responses that
merely fill the allowance remain incomplete, even if their prefix looks valid.

Opt-in `execution` reports limits, exposed-byte usage and limit events; its
completion describes only collection omitted by selected allowances. Observed
positive page/resource evidence is retained, while incomplete or unchecked
resources cannot prove absence. Default exits remain page-fetch-based: page
success with limited body/auxiliary evidence returns 0; a refused page fetch
returns 1. The existing `--fail-on` can gate limit warnings. Invalid limits return
2. This option can be combined with direct-script `--max-http-attempts`.

No elapsed-time, decompression, parser-depth or total-memory bound is promised.
The repository collector and packaged `seo-agent`/MCP interfaces do not forward
this option. It is a bounded single-page collection feature, not a crawler.

### Report Envelope

CLI JSON output includes a stable envelope **in addition to** legacy evidence fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Envelope schema (`1.0`) |
| `tool_version` | Package version (`0.2.0`) |
| `target` | `{kind: repo\|site, id: ...}` |
| `status` | `ok` / `partial` / `error` |
| `findings[]` | Agent-facing list with `id`, `severity`, `confidence`, `surface`, `status`, `detail`, `evidence`, optional `action` |

Prefer `findings[]` for reports. Keep reading nested evidence when you need raw proof.

### Exit codes

| Command | Exit `0` | Exit `1` |
| --- | --- | --- |
| `seo-agent repo-baseline` / `repo_seo_baseline.py` | No structured `errors[]` | Manifest / site-resource / Shipwise collection errors |
| `seo-agent site-meta` / `site_meta_audit.py` | Page fetch succeeded | Page fetch failed (meta gaps still exit `0`, surfaced as findings) |
| `seo-agent doctor` | Scripts present | Suite scripts missing |

`status: ok` is **not** a ranking or launch-readiness verdict.

### Page comparison metadata (bounded P05 prerequisite)

New packaged `seo-agent site-meta` reports include an additive `comparison`
block with independent `contract_version: "1.0"`; the existing `site_meta` MCP
wrapper returns the same block. Unknown envelope fields are ignorable. This
retains the observed-open envelope `schema_version: "1.0"`, but strict external
exact-key consumers must accommodate the new field.

Only five existing raw-HTML lexical presence checks are covered: title, meta
description, canonical link, `og:title`, and a JSON-LD script start. Their
stable rule IDs and `page` subject do not depend on outcome-dependent legacy
finding IDs. A collection can be complete while SEO status is partial. A
truncated page can contain positive observations without becoming complete.

The requested and successful effective URLs are exact strings: spelling,
query order, fragment, casing and slashes are preserved. Scope includes actual
bound body/timeout/redirect defaults and public User-Agent/Accept headers.
Unrecognized callable paths or unavailable configuration produce explicit
nulls and unknown collection. The runtime resolver recognizes reviewed
collector source and executed code; source-less/custom wrappers are
conservatively unverified, including in an installed package. It reads no
credentials, proxies or environment configuration.

Resources are excluded with unknown coverage even when legacy sitemap
discovery says complete. Repository reports and old reports without metadata
are incomparable; enriching an old report does not retrofit the block.

See [the metadata contract](references/comparison-metadata.md) and
[block-only JSON Schema](references/comparison-metadata.schema.json). The
dependency-free `validate_site_comparison_metadata(report)` checks containing
evidence and contract consistency beyond schema shape. Original invocation
URL and runtime policy may be supplied to verify those production inputs;
stored metadata is not a historical attestation. There is no comparator or
history database yet. Future resolution may mean only a passing lexical check
in a new, fully comparable capture, never proof of deployment, indexing,
ranking, or all SEO issues being fixed.

### Optional MCP

```bash
pip install -e '.[mcp]'
seo-agent mcp
```

Tools: `doctor`, `repo_baseline`, `site_meta`. No paid SEO APIs are embedded.

Configure your MCP client with the `seo-agent mcp` stdio command after the extra is installed.

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

The raw-HTML metadata collector excludes template descendants (including
shadow-root templates), SVG titles, and script/style source from document
metadata or heading text. Rendered template/shadow-tree content and CSS
visibility require the separate rendered-DOM workflow; this collector is not
a full HTML5 DOM parser. An omitted `<head>` is supported until body content
starts. HTML checks require an HTML/XHTML Content-Type and an unencoded body.
Non-HTML, unknown-type, and compressed responses report HTML checks as unavailable
without inventing missing titles or malformed structured data. Applicable
`X-Robots-Tag` headers are still assessed. Compressed robots/sitemaps are marked
unsupported (this collector does not decompress them); robots permission and
sitemap validation remain unknown.


| Task | Start here | What to inspect |
| --- | --- | --- |
| Review a repository before launch | `seo-agent repo-baseline --root /absolute/repo/path --json` | `findings`, `readmes`, `community_files`, manifests and collected GitHub metadata |
| Check a Shipwise launch record (optional) | Add `--project-yaml /absolute/path/project.yaml` | `shipwise.checks`, `errors` and the record's proof fields |
| Check a public page | `seo-agent site-meta https://your-public-site.example/ --json` | `findings`, `checks`, canonical, title, description and crawl-resource responses |
| Decide what content to write | [seo-content-geo](skills/seo-content-geo/SKILL.md) | Task intent, current source evidence, target page and unanswered questions |
| Establish demand or indexing | [seo-data-sources](skills/seo-data-sources/SKILL.md) | Authorized provider access and the claim each source can support |

`seo-agent` locates the suite root automatically. Legacy scripts should still be
run from this repository's checkout (or via `pip install -e .`). Save a report
outside the audited repository if you want to keep its working tree unchanged:

```bash
seo-agent repo-baseline --root /absolute/repo/path --json > /absolute/report/path/repo-baseline.json
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

Shipwise keyword repetition is an observation in `keyword_observations`, not a
keyword-stuffing verdict or launch gate. Counts use casefolded substring matching
(including word fragments and Unicode case folding); the same basis is used for
the Shipwise primary-keyword presence requirement. Review copy quality in context.

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

## CLI and scripts

```bash
seo-agent repo-baseline --root . --json
seo-agent site-meta https://example.com/ --json
# equivalent legacy entrypoints:
python3 scripts/repo_seo_baseline.py --root . --json
python3 scripts/site_meta_audit.py https://example.com/ --json
```

These are local dry-audit tools. They do not require API keys and should not be used to claim keyword volume, ranking, backlink gaps, or Search Console indexing status.

## Open Graph report compatibility

`open_graph` remains a flat string-valued compatibility summary, not a complete
media representation. Each image, audio and video summary selects its **first** media root (including
the corresponding `:url` alias), following the [Open Graph array preference](https://ogp.me/#array),
instead of the previous last-media selection. Only that root's following
matching media properties enter the summary, stopping at the next top-level OG
root or media URL alias. Repeated media properties also keep their first value.
Blank or missing content stays an empty string; no preferred media or dimensions
are inferred from a later declaration. The selected root keeps its written key,
so an `og:image:url` declaration does not invent an `og:image` declaration.

For example, `first.png`, width `100`, then `second.png` now summarizes
`{"og:image": "first.png", "og:image:width": "100"}`. If the width is declared
only after `second.png`, it does not appear in the first image's summary.
An ordinary single-media group retains its supplied fields. Non-media OG and
Twitter duplicate selection remains last-value; OG URL userinfo is redacted.

Use `open_graph_declarations` for ordered evidence. Each entry has `property`,
`content`, and `location` (`head`, `body`, or `outside_head_body`), with duplicates,
orphan properties, and blank content retained. An orphan media property appears
only here, never attached to another image, audio or video in the summary. The array is empty
when no matching OG declarations exist, and it shares the report's raw-HTML
capture/truncation limits. URL credentials are removed using the existing
userinfo-redaction policy; unrelated HTML attributes are not copied. These
fields neither fetch media nor predict a social platform's rendered preview.

## Validation

See the [acceptance status](references/acceptance-status.md) for completed
plugin, browser and public-site checks, and the remaining account-data blockers.

```bash
pip install -e .
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
- Do not automate posting or publishing. This suite audits and prepares evidence; publishing still requires explicit user instruction.
- The declared Codex `Write` capability is for local report and issue-draft files only, never for remote publishing.
- This release does not ship a sitewide crawler core; single-URL public fetches stay fail-closed and polite.

## Support and license

Use [GitHub issues](https://github.com/majiayu000/seo-agent-suite/issues) for
reproducible audit failures, with redacted input and the relevant report fields.
See [LICENSE](LICENSE) for the MIT terms and [CHANGELOG.md](CHANGELOG.md) for
version history.
