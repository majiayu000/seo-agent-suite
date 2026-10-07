---
name: github-repo-seo
description: Audit and improve GitHub/open-source repository discoverability across GitHub metadata, README/docs, package registries, public docs sites, release verification, and Search Console readiness boundaries. Use when the user asks why a repo/package cannot be found on Google, npm, crates.io, PyPI, etc.; asks to do SEO for a GitHub repo; needs README/package metadata optimization; needs Search Console handoff steps for an owned property; needs branded package scope planning for public repos; or wants evidence-backed repo/package/site discoverability audits.
---

# GitHub Repo SEO

Use this skill to make a public repository findable as a product, not just correct as code. Treat SEO as five connected surfaces: GitHub repo metadata, README/docs content, package registry metadata, public site crawlability, and external search/indexing.

Keep claims evidence-based. Separate `locally healthy`, `merged on GitHub`, `published to registries`, and `indexed by Google`; they move on different clocks.

## Workflow

1. Start from current state. Run `git status --short --branch`; record the branch, commit and collection time. If remote currency matters, fetch the relevant remote for evidence and compare its ref, without pulling, merging, resetting, switching or otherwise synchronizing the user's branch. Label local and remote states separately rather than calling an unverified checkout latest.
2. Run the baseline collector via the `seo-agent` CLI (preferred) or legacy
   scripts from the suite/plugin root. Keep `--root` pointed at the repository
   being audited:

```bash
seo-agent repo-baseline --root /absolute/path/to/target-repo --json
# legacy: python3 scripts/repo_seo_baseline.py --root /absolute/path/to/target-repo --json
```

3. If an optional Shipwise project record exists, include it:

```bash
seo-agent repo-baseline --root /absolute/path/to/target-repo --project-yaml /absolute/path/to/project.yaml --json
```

4. If a public site exists, run:

```bash
seo-agent site-meta <homepage> --json
# legacy: python3 scripts/site_meta_audit.py <homepage> --json
```

Prefer the Report Envelope `findings[]` when writing the audit report.

5. Search exact brand, repo, package, and docs-site names when search visibility is the question.
6. Record repo, docs site, package registry, and release discoverability separately.
7. Read `references/data-sources.md` before recommending paid APIs or MCP providers.

## Check Surfaces

- GitHub About description, homepage, topics, social preview, releases, and community profile files.
- README first screen: name, what it does, who it is for, install command, demo/proof, and authoritative links.
- Package metadata: npm, crates.io, PyPI, Homebrew or other actual distribution channels.
- Docs site: title, meta description, canonical, OG/Twitter cards, JSON-LD, robots, sitemap, and crawlability.
- Search Console: readiness and handoff only; verification, sitemap submission,
  and indexing requests require owned-property access and task authorization through the requested access path.

## Verify Identity And Availability

- Confirm GitHub owner/repo and the public About homepage, then compare README, manifest and registry links. Resolve conflicting homepage candidates before auditing the wrong property.
- Check supported community files in the root, `.github/` and `docs/`, plus inherited account defaults where applicable. A local absence is not proof that GitHub lacks the file; verify the [community profile/defaults](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/creating-a-default-community-health-file) and follow help/contribution links to confirm they work. File presence is a usability signal, not proof of search ranking.
- Identify actual publishable packages, including workspace members and scoped names, and exclude private/non-published packages from missing-publication findings. Query the exact package identity and expected version in its registry; check repository/homepage ownership, public metadata, install instructions and the actual published artifact when release verification is in scope. A search hit, matching name, tag or GitHub release alone does not prove that version is published or installable.
- Treat guessed registry endpoints, homepage URLs and help/support links as candidates until manually verified against the authoritative public surface. Distinguish absent, access-blocked and unverified resources; do not manufacture a missing-resource finding from a failed probe.

## Rules

- Do not keyword-stuff descriptions, topics, package keywords, or README headings.
- Do not claim Google has indexed a page immediately after sitemap submission.
- Do not treat a successful crawl as proof of ranking.
- Do not force unrelated projects under one package scope.
- Do not expose tokens. Keep npm/GitHub/provider credentials outside reports and commits.
- An audit defaults to a report and local issue drafts. Modify files, open remote issues/PRs, republish packages, submit Search Console or deploy only when included in the user's authorized task; continue already authorized implementation without a new approval gate.

## Decision Table

| Symptom | Candidate explanation to verify | Next evidence / scoped action |
|---|---|---|
| Google cannot find the repo/site | Crawl/indexing limits, new page, ambiguous product description | Verify exact query and URL, crawl/index evidence and README/site metadata; draft the supported fix |
| Package is published but not discoverable | Wrong package/version queried or unclear registry metadata | Verify exact identity, version and install path before proposing metadata changes |
| Branded search shows another product | Name collision or ambiguous identity | Record current SERP and authoritative identity links before proposing disambiguation |
| Site checks pass but ranking is unknown | No SERP/rank data | Use Search Console for owned properties or DataForSEO/SE Ranking/Ahrefs for SERP evidence |

## Done Criteria

Finish with the report/local drafts or authorized changed files and issue links, exact verification commands and outcomes, public URLs, and remaining external/manual blockers. Every action specifies target, before evidence, concrete change, owner, retest and expected result, and completion condition.

Separate three clocks: **live change** (GitHub/site/registry exposes the intended version and its retest passes), **index observation** (a later crawl or Search Console indexed result reflects that version), and **measured effect** (comparable query/page, market/device and time-window metrics). A local check or successful release is not evidence of indexing, and indexing alone is not evidence of improved ranking or traffic.
