---
name: github-repo-seo
description: Audit and improve GitHub/open-source repository discoverability across GitHub metadata, README/docs, package registries, public docs sites, release verification, and Search Console readiness boundaries. Use when the user asks why a repo/package cannot be found on Google, npm, crates.io, PyPI, etc.; asks to do SEO for a GitHub repo; needs README/package metadata optimization; needs Search Console handoff steps for an owned property; needs branded package scope planning for public repos; or wants evidence-backed repo/package/site discoverability audits.
---

# GitHub Repo SEO

Use this skill to make a public repository findable as a product, not just correct as code. Treat SEO as five connected surfaces: GitHub repo metadata, README/docs content, package registry metadata, public site crawlability, and external search/indexing.

Keep claims evidence-based. Separate `locally healthy`, `merged on GitHub`, `published to registries`, and `indexed by Google`; they move on different clocks.

## Workflow

1. Start from current state. Run `git status --short --branch` and fetch/sync before calling anything latest.
2. Run the baseline collector from the SEO Agent Suite repository or installed
   plugin root. Keep `--root` pointed at the repository being audited:

```bash
python3 scripts/repo_seo_baseline.py --root /absolute/path/to/target-repo --json
```

3. If a Shipwise project record exists, include it:

```bash
python3 scripts/repo_seo_baseline.py --root /absolute/path/to/target-repo --project-yaml /absolute/path/to/project.yaml --json
```

4. If a public site exists, run:

```bash
python3 scripts/site_meta_audit.py <homepage> --json
```

5. Search exact brand, repo, package, and docs-site names when search visibility is the question.
6. Record repo, docs site, package registry, and release discoverability separately.
7. Read `references/data-sources.md` before recommending paid APIs or MCP providers.

## Check Surfaces

- GitHub About description, homepage, topics, social preview, releases, and community profile files.
- README first screen: name, what it does, who it is for, install command, demo/proof, and authoritative links.
- Package metadata: npm, crates.io, PyPI, Homebrew or other actual distribution channels.
- Docs site: title, meta description, canonical, OG/Twitter cards, JSON-LD, robots, sitemap, and crawlability.
- Search Console: readiness and handoff only; verification, sitemap submission,
  and indexing requests require owned-property credentials/browser access.

## Rules

- Do not keyword-stuff descriptions, topics, package keywords, or README headings.
- Do not claim Google has indexed a page immediately after sitemap submission.
- Do not treat a successful crawl as proof of ranking.
- Do not force unrelated projects under one package scope.
- Do not expose tokens. Keep npm/GitHub/provider credentials outside reports and commits.

## Decision Table

| Symptom | Likely cause | Action |
|---|---|---|
| Google cannot find the repo/site | No crawlable site, weak README text, new page, missing sitemap | Improve README/site metadata, verify robots/sitemap, submit Search Console |
| Package is published but not discoverable | Weak name/description/keywords/readme | Improve package metadata and republish a patch release |
| Branded search shows another product | Name collision, weak entity signals, no disambiguation | Add brand qualifiers, sameAs links, and a disambiguation page or issue |
| Site checks pass but ranking is unknown | No SERP/rank data | Use Search Console for owned properties or DataForSEO/SE Ranking/Ahrefs for SERP evidence |

## Done Criteria

Finish with changed files or issue links, exact verification commands and outcomes, public URLs, and remaining external/manual blockers.
