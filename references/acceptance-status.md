# SEO suite acceptance status

This record distinguishes delivered fixes and workflows from measured site or
account outcomes. It covers the 20 exploration areas, not a claim that every
possible SEO problem has been eliminated.

## Baseline and evidence

- Baseline: `6db89009dad8bb67ee36ad5db15b8cdeb0280a1a`, merged in
  [PR #20](https://github.com/majiayu000/seo-agent-suite/pull/20).
- The baseline has 122 passing Python tests, including 44 added regressions.
  These verify local behavior, not Google indexing or ranking.
- Follow-up acceptance date: 2026-10-05 (UTC). Public responses and local
  loader evidence were collected under `/tmp/seo-acceptance-20261005/` on the
  accepting machine; they are local, ephemeral artifacts, not bundled data.
- No GSC, backlink-index, keyword-volume or AI visibility account was connected
  during this run. No paid provider calls or sitemap submissions were made.

## Coverage by exploration area

| Area | Delivered and checked | Remaining measurement boundary |
|---|---|---|
| Crawl/indexing | Robots declarations, HTTP status and raw-capture evidence; real public fetch | Owned-property indexed-version evidence needs GSC |
| Canonical URLs | Multiple canonicals, base/final URL resolution, head/body evidence and regressions | Google-selected canonical needs URL Inspection |
| Sitemaps/architecture | Declared sitemap discovery, XML evidence, bounded candidates and regressions | Child traversal/site-wide inventory is a separate crawl |
| Rendering/performance | Conditional raw/rendered, deep-route and mobile workflow; browser acceptance | Field CWV needs available CrUX data; PageSpeed quota blocked this run |
| Structured data | JSON-LD parse/type/error evidence and regressions; validator handoff | Parser success does not prove schema validity or rich-result eligibility |
| International SEO | Locale/canonical/reciprocity workflow and browser acceptance | Public page samples do not prove entire-site consistency |
| Keywords/intent | Query/task/page-format brief with dated SERP evidence requirements | Volume/difficulty estimates need an authorized measuring provider |
| Content quality | Original contribution, task completion and update/merge/create workflow | No ranking improvement or content-effect claim measured |
| GEO/AEO | Platform eligibility and reproducible prompt-sample definitions | Account/platform citation samples not available |
| GitHub discoverability | Current public `gh` metadata and community-file candidate regressions | File presence does not prove GitHub template usability or search rank |
| Package registries | Exact npm/crates identity, version, privacy and explicit/implicit Cargo workspace regressions | Suite itself has no npm/Cargo package; publication checks require a target package; PyPI publication remains a manual workflow |
| Data providers | Installed-tool/account scope, request budget, source limits and failure handling | Real authenticated accounts remain required |
| GSC/measurement | Indexed/live/effect separation, window/privacy/top-row and GA4 boundaries | Property, account and real exports missing |
| Backlinks/off-page | Export/index scope, live/lost and current-page verification workflow | No backlink index or GSC Links export available |
| Image/video SEO | Purpose-aware alt and watch-page workflow; browser media acceptance | Media inventory samples are not image/video search visibility |
| Plugin/workflow | Actual CLI installation and four enabled skills returned by Codex loader | New sessions must load the installed plugin version |
| Report/handoff | Confidence/action/retest, revision/scope and query/task/URL templates | Effect measurements depend on matching before/after windows |
| Script reliability | URL encoding, charset/error contracts and regression coverage | Network/provider failures remain explicit errors |
| Security boundaries | Public IP pinning, redirect validation and credential redaction regressions | This machine's fake-IP DNS is intentionally rejected |
| Prior art/design | Focused four-skill execution layer; existing provider/browser tools | No crawler, keyword index or ranking engine is implemented by this suite |

## Public HTTP acceptance

Normal invocations of both local scripts rejected the machine's DNS answers:
`docs.python.org` and `majiayu000.github.io` resolved to `198.18.0.0/15` addresses.
The public-address guard returned structured errors and exit status 1. This
is a confirmed environment constraint, not proof that either public site failed.

For a controlled retest, an acceptance-only process wrapper supplied real A
records obtained from `https://dns.google/resolve`. The scripts still validated
every address as public, pinned connections and verified TLS for the original
hostname. No production code, system DNS or proxy settings were changed.

- `site_meta_audit.py https://docs.python.org/3/ --json`: exit 0, HTTP 200,
  complete raw HTML, title `3.14.8 Documentation`, canonical
  `https://docs.python.org/3/index.html`; robots and root sitemap returned 200.
  The declared/root sitemap had eight absolute locations; the fallback
  `/3/sitemap.xml` returned 404 and stayed visible in the report.
- `repo_seo_baseline.py --root . --json`: exit 0 with public GitHub metadata,
  homepage `https://majiayu000.github.io/shipwise/` returning 200 and a present
  sitemap. Root robots.txt returned 404; the report preserved that observation.
- One unauthenticated PageSpeed mobile request for `https://docs.python.org/3/`
  returned HTTP 429 / `RESOURCE_EXHAUSTED`. No Lighthouse or field metrics were
  returned, and no CWV verdict was inferred.

The successful HTTP runs used the captured public DNS answers. They do not
show that ordinary script invocations work with this machine's fake-IP DNS.

## Browser acceptance

The optional [browser harness](browser-acceptance.md) actually ran in headless
Chromium 140.0.7339.16. Six controlled groups passed: raw/rendered JavaScript
differences, direct 200/404 routes, desktop/mobile equivalence and deliberate
mobile content loss, reciprocal hreflang and a deliberately missing return,
the complete six-page fixture's orphan difference, and loaded image/video/
poster evidence. Mobile is Chromium with iPhone user-agent/viewport emulation,
not a physical device or Safari.

Three public Python documentation pages (English and Chinese homepages and
the turtle documentation) loaded on desktop and mobile: six HTTP 200 loads,
with equivalent observed main content and metadata. The turtle image loaded
at a natural width of 250 pixels. These samples exercise real public
collection; complete orphan and reciprocal-language/media checks use the
controlled fixture, not a complete crawl of Python's public site.

## Plugin and workspace acceptance

Codex CLI 0.160.0 installed `seo-agent-suite@seo-suite-local`. The app-server
`skills/list` response returned all four namespaced skills enabled with no
suite loading errors. One actual Codex execution read all four installed skill
files and their references, ran the installed repository collector, and
produced a content brief and source decision. Its sandbox DNS failure for the
site run remained an explicit limitation; a direct installed-cache script
retest with the controlled public DNS wrapper succeeded with HTTP 200.

The original workspace finding was rechecked using real Cargo, exposing a
remaining omission: `[workspace]` without a truthy `members` field skipped
metadata entirely. The follow-up now invokes Cargo metadata for workspaces
with a root package or explicit members; an empty virtual workspace remains
optional. Two additional regressions cover inherited root values
and implicit members. A real locked/offline Cargo fixture returned the root's
inherited version/homepage and the implicit path member's `publish=false`
metadata; file hashes before/after collection were identical.

## Offsite brand acceptance

Four selected public pages were fetched on 2026-10-05, all returning HTTP 200.
Three matched the repository identity; one same-name agency product was
excluded. The matched sample contained two owned references and one
third-party hosted directory, with zero verified original independent reviews:

- [SkillsMP](https://skillsmp.com/ko/creators/majiayu000/seo-agent-suite)
  listed four skills and linked the exact repository. Copied descriptions
  establish a directory listing, not an independent endorsement.
- [Shipwise](https://majiayu000.github.io/shipwise/) and the
  [maintainer profile](https://github.com/majiayu000) linked the repository;
  repeated links were deduplicated as owned source references.
- [Neuralhewn services](https://neuralhewn.com/services) had the same display
  name without matching owner/repository anchors; it was excluded.

This four-page sample demonstrates the workflow, not global backlink coverage,
brand authority, original-review absence across the web or AI citation share.
Direct curl observations and the suite fetcher's fake-IP rejection are recorded
separately in the local acceptance artifacts.

## Authenticated acceptance still required

GSC Wizard and Ahrefs were discovered as available integrations, but neither
was connected. Their directory descriptions are capability claims, not
evidence of account access or successful measurements.

To finish the account-dependent acceptance, provide the target domain/GSC
property and connect an authorized account, or provide a local path to an
existing authorized export. Continue the existing audit without another
permission gate, within its recorded account quota and cost boundary:

1. GSC: collect one consistent, finalized date window and inspect a target URL;
   retain returned aggregation, top-row/privacy limits, last crawl time and
   selected canonical. Use a Links export for owned-site link samples.
2. Keywords/backlinks: use a supported endpoint for that same target; retain
   locale/device, estimate definitions, index scope, live/lost status and dates.
3. AI visibility: retain the platform, prompt/grounding-query sample and
   successful-run denominator; distinguish mentions, citations and referrals.
4. Attach redacted response/export references and mark each actual result
   separately. An unavailable endpoint or empty sample proves no absence.

These measurements remain **blocked**, rather than passed by mocked data or
documentation tests. Installation, scripts, browser workflows and public
brand checks can be accepted independently of those accounts.

## Completed follow-up checks

The integrated worktree passed script compilation, `tests/test_structure.py`,
all 124 Python unit tests, Node syntax checking of the optional browser harness
and `git diff --check`. The final integrated browser rerun passed all six
fixture groups; both desktop and mobile returned HTTP 200 for all three public
URLs, with zero failed resource requests and equivalent captured main content
and metadata. A separate read-only review found no material merge blocker.
GitHub CI and unresolved review threads must still be checked on the PR before
merging; these local checks do not substitute for that gate.
