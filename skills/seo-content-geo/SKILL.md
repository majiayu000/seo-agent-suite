---
name: seo-content-geo
description: Plan and review SEO content, keyword maps, content briefs, GEO/AEO readiness, AI-search citation potential, FAQ/schema opportunities, and comparison/disambiguation pages. Use when Codex needs content strategy, long-tail page ideas, AI answer optimization, E-E-A-T/entity clarity, or launch/discoverability copy that should align with Shipwise positioning.
---

# SEO Content GEO

Create content and GEO/AEO recommendations with clear evidence boundaries. This skill plans content; it does not invent keyword volume, rankings, backlinks, or AI visibility.

## Workflow

1. Read the product/repo/site surface first: README, docs, package metadata, homepage, and Shipwise project records when present.
2. Build a keyword map:
   - Primary: 1-2 high-intent terms.
   - Secondary: 3-6 related terms.
   - Long-tail: specific problem phrases and comparison queries.
3. Separate owned facts from hypotheses. Use `seo-data-sources` when volume, SERP, competitor, backlink, or AI visibility data is required.
4. Produce a brief or issue set, not generic advice.
5. Format the deliverable with `references/report-template.md`, resolved from
   the suite/plugin root.

## Content Types

- README first-screen rewrite.
- Docs landing pages and long-tail pages.
- FAQ and troubleshooting pages.
- Comparison and alternative pages.
- Brand disambiguation pages.
- AI answer/GEO snippets with explicit source-backed claims.

## GEO/AEO Checklist

- Entity clarity: product name, category, user, use case, maintainer, repository, package, docs site.
- Citation readiness: clear factual sentences, install commands, examples, limitations, license, version links.
- Answer shape: concise definitions, comparison tables, task-specific examples, FAQ blocks.
- Trust signals: real release links, package registry links, docs links, issue/support path, security/privacy boundaries.

## Output

Deliver one of:

- A content brief using `references/report-template.md`, with keyword map,
  target pages, and per-claim evidence status (`Confirmed`, `Likely`,
  `Hypothesis`).
- A GitHub issue set where each issue names the page, the change, and the
  evidence behind it.

## Failure Handling

- If the product surface (README, docs, Shipwise record) is missing or
  unreadable, stop and report the missing input instead of writing copy.
- If volume/SERP/competitor data is required but no provider is available,
  mark those items `Hypothesis` and list the provider gap as a blocker.

## Rules

- Do not keyword-stuff.
- Do not fabricate search volume, difficulty, backlinks, rankings, or AI share-of-voice.
- Do not create content for irrelevant queries just because they have traffic.
- Do not overpromise product capabilities that code/docs do not support.
