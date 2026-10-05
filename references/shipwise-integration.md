# Shipwise Integration

Shipwise is the planning and record layer. SEO Agent Suite is the execution layer.

## Use Shipwise For

- Project archetype and launch channel selection.
- Positioning and launch copy.
- Project records under `projects/<project>/`.
- Platform rules and launch feedback loops.
- Discoverability principles in `docs/DISCOVERABILITY.md` and the pre-launch
  run sheet in `checklists/discoverability.md`.
- Repo metadata drafting via `templates/github/REPO_METADATA.md`.
- Keyword tiers: `templates/seo/keyword_map.md` is the single source of truth
  for the Primary/Secondary/Long-tail structure; this suite consumes it and
  must not redefine it.

## Use SEO Agent Suite For

- Repository, README, package registry, and docs-site evidence collection.
- Technical site SEO checks.
- Keyword map and content/GEO brief generation with clear source boundaries.
- Provider selection for Firecrawl, Search Console, PageSpeed/CrUX, DataForSEO, SE Ranking, and Ahrefs.

## Handoff Pattern

1. Run the relevant SEO Agent Suite audit.
2. Turn confirmed findings into issues or a report.
3. Record decisions and links in the Shipwise project folder when the work affects launch or relaunch readiness.
4. Keep provider credentials outside both repositories.

For a content brief, consume the project's existing keyword map and positioning
first. Link query, user task, current/target URL, and the update/merge/new
decision to evidence; use Shipwise's keyword template without duplicating tier
definitions here. If Shipwise is absent, deliver the same standalone brief
without requiring a project record.

Use existing project fields for the evidence handoff:

- `signals.sources_checked` and `signals.retrieval_date` identify sources and
  collection date; `signals.decision`, `signals.local_issue`, and
  `signals.local_pr` link the decision and implementation where applicable.
- `verification.verification_command`, `verification.verification_date`,
  `verification.expected_output`, and `verification.proof_asset_path` capture
  completed product checks and proof assets, when applicable.
- The existing `proof.md` Claim Inventory carries source/command, date,
  verification status, and publishability. Keep SEO confidence
  (`Confirmed`/`Likely`/`Hypothesis`) in the linked audit report rather than
  inventing new Shipwise status values or treating readiness as visibility.

Link the audit report's raw evidence, measurement scope, retest/done criteria,
and before/after observations from these records. Distinguish verified local
changes, live deployment, engine indexing, and measured effect; do not mark
unknown outcomes verified. No additional project schema is required.

## Machine Handoff

When a Shipwise project record exists, pass it to the baseline collector:

```bash
python3 scripts/repo_seo_baseline.py \
  --root /absolute/path/to/target-repo \
  --project-yaml /absolute/path/to/shipwise/projects/<project>/project.yaml \
  --json
```

The script validates the declared `discoverability:` block plus local
community-file evidence: description/primary-keyword alignment, keyword list,
GitHub topic count/format/uniqueness, homepage URL, social preview state,
README, license, contributing guide, code of conduct, security policy, and
issue templates. Failures are emitted in the top-level `errors` array and
return a non-zero exit code, so CI and launch-readiness gates can fail closed.

This is a local contract gate, not proof of the complete Shipwise checklist. It
does not prove live GitHub metadata, release state, indexing, rankings, or
search visibility; collect those surfaces separately with their current data
sources.
