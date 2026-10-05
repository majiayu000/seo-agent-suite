---
name: seo-content-geo
description: Plan and review SEO content, keyword maps, content briefs, GEO/AEO readiness, offsite brand evidence, AI-search citation potential, FAQ/schema opportunities, and comparison/disambiguation pages. Use when Codex needs content strategy, long-tail page ideas, AI answer optimization, E-E-A-T/entity clarity, offsite brand/mention review, or launch/discoverability copy that should align with Shipwise positioning.
---

# SEO Content GEO

Create content and GEO/AEO recommendations with clear evidence boundaries. This skill plans content; it does not invent keyword volume, rankings, backlinks, or AI visibility.

## Workflow

1. Read the available product surfaces: README, docs, package metadata,
   homepage, and Shipwise project records when present. Define the target
   user, their task, and what they should be able to do after reading.
2. State the target market/language and search engine or AI platform. Inspect
   current SERPs for the proposed queries: record date, device, representative
   result URLs, dominant page type, and how the product fits that task. Without
   SERP evidence, label intent and page-format choices `Hypothesis`; product
   vocabulary alone does not establish high intent.
3. Map queries to tasks and pages using the table below. When Shipwise is
   available, consume `templates/seo/keyword_map.md` and the existing project
   map; do not redefine its tiers or counts. Without Shipwise, produce a
   standalone brief using the same query/task/page table.
4. Inspect existing pages before choosing update, merge, or new. Compare the
   task and page purpose, internal links, and query/page performance when
   available. Shared words alone do not prove keyword cannibalization. Prefer
   improving a relevant existing page when it can complete the user task.
5. Specify the page's original contribution: a reproducible example,
   first-hand result, supported comparison, or explanation missing from the
   current material. Verify technical claims against source/docs for the
   stated version; run proposed commands when feasible and record environment,
   expected/actual output, and proof. Mark unverified claims explicitly.
6. Use `seo-data-sources` for measured volume, SERP, competitor, backlink, or
   AI visibility claims. Produce a brief or issue set with a concrete change,
   retest method, and completion criterion.
7. Format the deliverable with `references/report-template.md`, resolved from
   the suite/plugin root.

| Query | User task / completion criterion | Current / target URL | Update / merge / new and reason | Evidence / confidence |
|---|---|---|---|---|
|  |  |  |  |  |

## Content Types

- README first-screen rewrite.
- Docs landing pages and long-tail pages.
- FAQ and troubleshooting pages.
- Comparison and alternative pages.
- Brand disambiguation pages.
- AI answer/GEO snippets with explicit source-backed claims.

## GEO/AEO Checklist

- Platform eligibility: carry forward `technical-seo-audit` evidence for
  crawler access (including CDN rules), indexing, and snippet controls; record
  unknowns rather than treating a successful fetch as indexing. For Google AI
  Overviews/AI Mode, pages must be indexed and eligible for a search snippet;
  eligibility does not guarantee inclusion. [Google guidance](https://developers.google.com/search/docs/appearance/ai-features).
- For ChatGPT search, check `OAI-SearchBot` access separately from `GPTBot`
  training access; one permission does not imply the other. `ChatGPT-User`
  visits do not prove search eligibility. [OpenAI crawler guidance](https://developers.openai.com/api/docs/bots).
- Use each target platform's current rules. Do not prescribe `llms.txt`,
  special AI markup, or FAQ schema as a universal requirement; Google requires
  no additional AI text files or special schema for its AI search features.
- Entity clarity: product name, category, user, use case, maintainer, repository, package, docs site.
- Citation readiness: clear factual sentences, install commands, examples, limitations, license, version links.
- Answer shape: concise definitions, comparison tables, task-specific examples, FAQ blocks.
- Trust signals: real release links, package registry links, docs links, issue/support path, security/privacy boundaries.
- Measured AI visibility: state platform/model or mode, query/prompt sample,
  locale, collection window, repetitions, and denominator. Distinguish brand
  mentions from linked citations. Report observed counts and exclusions; a
  small manual sample measures that sample, not general AI share-of-voice.

## Offsite Brand Evidence (When Requested)

1. Establish identity from maintained product surfaces: exact name, owner,
   repository/package URL, category, and known name collisions. Search the
   exact name with the owner or repository identifier as well as the name
   alone; exclude unrelated entities rather than counting matching words.
2. Record queries, search tool/engine, collection time, language/market when
   known, result depth, candidate URLs, and fetch failures. Fetch relevant
   candidate pages to verify the identity and context; search snippets alone
   are discovery evidence. Preserve the distinction between current fetches
   and cached extracts with an unknown refresh time.
3. Classify each source as owner-controlled, third-party, or ownership
   unknown. A maintainer's GitHub profile or hosted docs remain owned material.
   Distinguish original third-party discussion/reviews from directories,
   mirrors, syndicated copy, paid placements and disclosed relationships.
   A copied listing establishes a listing, not independent endorsement.
4. Record mention context, linked citation versus unlinked mention, the
   observed destination, fetch status, and `rel` values when inspected. Check
   priority destinations and redirects. An inaccessible page or cached link
   is unverified; a working link does not prove indexing or link equity.
   Reuse `seo-data-sources` for backlink-index coverage or measured AI claims.
5. Deduplicate shared origin/copy and language variants when counting sources.
   Report candidate, fetched, identity-matched, excluded and unverified counts
   with their denominator. These counts describe this sample; do not turn
   them into an invented authority score or infer global absence from a
   non-mention. Recommend only specific supported corrections or hypotheses,
   with a retest criterion; outreach/posting requires existing authorization.

Use the optional brand evidence table in `references/report-template.md`.

## Output

Deliver one of:

- A content brief using `references/report-template.md`, with the task/page
  map, original contribution, supported claims, and per-claim evidence status
  (`Confirmed`, `Likely`, `Hypothesis`).
- A GitHub issue set where each issue names the page, the change, and the
  evidence behind it.
- An offsite brand evidence report with source ownership, identity matches,
  mention/link observations, sampling limits and concrete retest actions.

## Failure Handling

- If all product surfaces are missing or unreadable, report the missing input
  instead of inventing product copy. A missing Shipwise record alone does not
  block an otherwise supported standalone brief.
- If a measurement source is unavailable, report the gap and leave its claims
  unmeasured. Continue supported work with intent/format recommendations marked
  `Hypothesis`; block only conclusions that depend on the missing measurement.

## Rules

- Do not keyword-stuff.
- Do not fabricate search volume, difficulty, backlinks, rankings, or AI share-of-voice.
- Do not create content for irrelevant queries just because they have traffic.
- Do not overpromise product capabilities that code/docs do not support.
