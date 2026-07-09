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

## Machine Handoff

When a Shipwise project record exists, pass it to the baseline collector:

```bash
python3 scripts/repo_seo_baseline.py \
  --root /absolute/path/to/target-repo \
  --project-yaml /absolute/path/to/shipwise/projects/<project>/project.yaml \
  --json
```

The script validates the `discoverability:` block for description, primary
keyword, keyword list, GitHub topic count/format, homepage URL, social preview
state, and local community/support files. Failures are emitted in the top-level
`errors` array and return a non-zero exit code, so CI and launch-readiness gates
can fail closed instead of silently falling back to incomplete data.
