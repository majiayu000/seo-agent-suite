# Site comparison metadata v1

This is a bounded P05 prerequisite for a future P06 comparator. The standalone
legacy script and repository collector do not emit it. Only a new package
CLI/MCP site invocation attaches it after the existing enrichment step. Existing
findings, IDs, status, exits and MCP inventory remain unchanged.

## Rule semantics

| Stable rule ID | Source check | Exact lexical meaning |
|---|---|---|
| site.meta.title | has_title | Concatenated title text after whitespace normalization, including body titles; template/SVG handling is unchanged |
| site.meta.description | has_meta_description | First matching description meta at any recorded location has non-whitespace content; later duplicates cannot rescue an empty first declaration |
| site.meta.canonical | has_canonical | First canonical link at any location has a truthy href; whitespace counts; later duplicates cannot rescue an empty first declaration |
| site.meta.og_title | has_og_title | Last exact-case og:title summary value at any location is truthy; whitespace counts and a later empty value overrides a present one |
| site.meta.json_ld | has_json_ld | A script start with type lowercasing to application/ld+json was observed at any parsed location; closing tag and valid JSON are not required |

These are not head-only DOM validation, title quality, canonical correctness,
JSON validity, rendered coverage, indexability or performance checks. In
particular JSON-LD presence may pass while the separate parse assessment fails.
Changes to extraction, applicability, completeness, identity or rule semantics
require a method/ruleset revision, not just a tool version change.

## Identity, scope and completeness

Producer `seo-agent-suite/site-meta`, ruleset `site.raw_html.presence` revision
`1`, method `raw_html_lexical_presence_v1`, subject `page`. All five sorted rows
are present on every report, including fetch errors and non-HTML responses.

The exact tuple is (original requested URL, successfully observed effective
URL). No canonical aliasing, query sorting, URL normalization or resource
redirect deduplication is performed. Syntactic identity requires HTTP(S), a
nonempty host, no credentials/control/ASCII whitespace, and a usable port
1–65535 if supplied. It does not do DNS or establish public reachability.
Source pointers may be null when missing. Redacted credentials are never
retained or hashed. Failed fetches never establish effective identity.

The scope records actual invoked callable defaults, not mutable default
constants. Unrecognized functions yield null settings, retaining only settings
verified independently. All numeric values and both public headers must be
known for configuration to be verified. Partial unknown policy always makes
collection unknown. The pure builder and validator do no I/O; the separate
runtime resolver reads installed source to recognize the invoked method and
checks code against that source, then reads bound defaults. This is conservative
method recognition, not an attestation or a security mechanism.

Collection completion is independent of legacy SEO status:
- complete: successful integer 2xx, supported unencoded HTML, raw_html scope,
  rendered exactly false, agreeing false boolean truncation flags in page and
  capture, five actual boolean checks, exact identity, verified configuration
- incomplete: failed fetch or observed truncation (unverified configuration
  takes precedence and yields unknown)
- unknown: malformed/missing capture or checks, unknown media, unsupported
  encoding, unavailable identity or configuration
- not_applicable: positively non-HTML with supported encoding and known inputs

Rows prioritize fetch failure, encoding/media uncertainty, then non-HTML skip,
then missing capture/check evidence. Supported observed true means pass;
observed false means fail only for untruncated capture. Otherwise absence is
unknown. Skip never means collection failure. Resources are always excluded,
coverage unknown, reason not_assessed_by_this_contract. Page-only completeness
can coexist with robots/sitemap failures or capped discovery.

## Semantic validation and future consumption

The adjacent schema is intentionally only for the comparison block; the legacy
envelope remains open. Schema validation cannot establish semantic consistency.
The dependency-free validator checks closed block fields and strict types,
unique complete sorted inventory, containing producer/schema/target agreement,
identity/provenance, capture/outcome/reason consistency, configuration null
rules, resolvable RFC6901 pointers and uniquely resolving legacy links. Empty
legacy links are allowed. It neither rewrites old reports nor verifies historical
honesty. Supply original URL and runtime policy when checking production inputs.

Future comparison must first pass the pair-wide gate: supported equal producer,
tool, contract, ruleset, scope and exact target tuple; five unique complete rows;
complete collection on both sides; valid pointers/links. Only then pass→fail is
new, fail→fail persistent, fail→pass resolved, and pass→pass unchanged. Unknown,
skip, missing metadata, changed versions/scope, failed/truncated capture, and
unsupported repository identity make the whole pair incomparable. Do not match
only intersecting rows or subtract legacy finding IDs. No comparator is shipped
in this change.
