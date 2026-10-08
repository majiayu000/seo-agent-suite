# Offline comparison v1 (bounded P06)

```
seo-agent compare BEFORE.json AFTER.json --json
```

This command reads exactly two explicitly named regular files. It never collects
new evidence, resolves DNS, invokes a provider/model/subprocess, discovers a
baseline, stores history, writes files, or adds an MCP tool. Symbolic links to
regular files are allowed. `-` is not stdin. URL strings are not fetched.

## Input and exit contract

Each file must be UTF-8 JSON without a BOM, at most **8 MiB (8,388,608 bytes)**.
Read length is bounded to the limit plus one byte. Objects and arrays may nest
at most **64 containers**, counting the root object as depth 1; a string-aware
lexical scan checks depth before JSON parsing and recursive semantic validation.
Duplicate object keys (including equivalent escaped names), nonfinite numbers
(including overflowing exponents), invalid JSON/UTF-8, and non-object roots are
rejected. Parser recursion failures are reported deterministically. These are
conservative fixed bounds for this new command, not a claim of general parser
memory/security protection and not a change to any existing command's limits.

- **0:** comparable, even if there are new or persistent failures
- **1:** both inputs are parseable report objects, but the pair is incomparable
- **2:** malformed, unreadable, non-regular, or over-budget input, or CLI misuse

There is no severity threshold or implicit CI failure gate. `--json` produces
one result object on stdout for admitted command invocations, including read
and validation failures. Argument syntax errors retain argparse's stderr/exit-2
behavior. Without `--json`, a short text summary uses the same exits.

## Pure API and digest meaning

`seo_agent_suite.compare.compare_reports(before: bytes, after: bytes) -> dict`
accepts the exact bytes and shares all parsing/validation with the CLI. It does
no I/O and does not mutate inputs. Every supplied bytes input within the size
bound gets its raw-byte SHA-256 in `inputs.before/after.sha256`, even if parsing
fails. Wrong-type/oversize inputs and CLI read failures have null digests.
Whitespace-only formatting changes therefore change digests without necessarily
changing comparison outcomes. Hashes identify bytes, not authenticity, historical
producer honesty, capture freshness, deployment, or a trusted signature.

## Whole-pair eligibility

The existing P05 `validate_site_comparison_metadata` validates each **containing
report**, not just a detached metadata block. The comparator does not retrofit
or infer missing comparison metadata. It currently supports the installed tool
version and metadata contract 1.0, report schema 1.0, site-meta producer,
raw_html_lexical_presence_v1 method, and site.raw_html.presence revision 1.

Both reports must have exactly the supported five sorted unique rule/page rows,
resolvable same-report evidence and unique legacy finding links, exact usable
requested/effective URL identity, verified configuration, complete collection,
and complete pass/fail evaluations. Producer, target, contract and scope must
match across the entire pair. URLs are compared exactly, including query order,
fragments, spelling and redirects. Scope changes include body/time/redirect
limits and request headers. Timestamp, prose, severity, and legacy SEO status
are not identity keys or completeness gates.

Missing/duplicate/unknown evaluations, skip, failed/truncated capture, unsupported
versions, unknown configuration, changed inventory, target, redirect or scope
make the **whole pair incomparable**: empty changes and null counts. Never
compare an intersection or subtract legacy finding IDs. Legacy 1.0 reports
without metadata and repository reports are unsupported; no repository identity
is inferred from a root path. Resources remain explicitly excluded, including
robots/sitemap failures and discovery limits. Complete page evidence can still
be comparable when unrelated resource requests failed.

## Output interpretation

The result has `comparison_result_version: "1.0"`, status, explicit limited
scope/resources/resolution meaning, exact input digests, deterministic reasons,
changes and counts. Comparable output also includes the exact target tuple.
Changes are sorted by stable rule ID and page subject:

- pass → fail: `new`
- fail → fail: `persistent`
- fail → pass: `resolved`
- pass → pass: only increments `unchanged_passing`

Each change includes both recorded outcomes, a same-input RFC6901
`evaluation_ref`, that row's `evidence_refs`, and its legacy finding links.
The before/after labels and input digests identify which report each reference
belongs to. References are not external URLs and are never fetched. Counts are
not emitted as zeroes when incomparable or malformed.

“Resolved” means one of the **five raw-HTML lexical presence checks passed in a
new recorded comparable capture**. It does not prove a fix was deployed or
indexed, a correct canonical/JSON-LD value, improved ranking, or all SEO issues
being fixed. See [the exact five-rule semantics](comparison-metadata.md).
