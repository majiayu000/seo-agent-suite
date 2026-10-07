# Browser acceptance

`tests/browser_acceptance.cjs` is an optional headless integration check for the technical SEO skill. It serves an isolated HTTP fixture and captures three public Python documentation URLs. It does not change the public-URL fetcher's private-address boundary, operate desktop UI, sign in, click, scroll, or submit requests to indexing tools. Playwright and FFmpeg are test prerequisites, not plugin runtime dependencies.

Run from the repository root with Node.js, npm and FFmpeg installed:

```bash
acceptance_tools="$(mktemp -d)"
npm install --prefix "$acceptance_tools" --no-audit --no-fund playwright@1.55.0
"$acceptance_tools/node_modules/.bin/playwright" install chromium
ffmpeg -hide_banner -loglevel error -f lavfi -i color=c=black:s=16x16:r=1 \
  -t 1 -an -c:v libvpx "$acceptance_tools/fixture.webm"
NODE_PATH="$acceptance_tools/node_modules" node tests/browser_acceptance.cjs \
  "$acceptance_tools/artifacts" "$acceptance_tools/fixture.webm"
```

Add `--fixtures-only` after the WebM path to skip all public URL captures.
This is the CI mode: the six controlled checks run against the isolated local
server and `public` is empty in the report. Installing prerequisites still needs
network access; fixture execution does not depend on public websites.

The script exits nonzero on failed fixture assertions, failed public page loads, or missing expected public content. The default mode requires network access. It saves response HTML, rendered HTML and `acceptance.json` in the artifact directory; keep these out of commits. The fixture deliberately contains missing mobile content and an absent hreflang return link to verify that these defects are detected.

## Completed run: 2026-10-05

Headless Chromium 140.0.7339.16 with Playwright 1.55.0 completed the checks below. Mobile uses iPhone 13 user agent and viewport emulation in Chromium; it does not demonstrate behavior on an actual iPhone, Safari, or Googlebot. The desktop viewport is 1440×900 and the fixture mobile CSS viewport is 390×664. Each run records actual user agent, viewport, browser version, collection time, failed resources and wait condition.

| Check | Evidence and result |
| --- | --- |
| JavaScript | Raw deep-route main content and links are empty; after normal loading, primary text, one link and WebPage JSON-LD appear, and the title changes. Raw HTML is parsed without executing its scripts. |
| Direct routes | Direct valid SPA deep link responds 200 and renders its content; nonexistent route responds 404 and renders error content. |
| Mobile | Primary text, links, canonical, robots and JSON-LD match the equivalent desktop fixture; the separate fixture with deliberately missing mobile primary content is detected. |
| Language variants | Existing English/Chinese fixture pages respond 200 with self references, reciprocal HTML hreflang and matching self canonicals; a deliberately absent return link is detected. |
| Orphan pages | Complete independent six-page sitemap inventory compared with rendered traversal from `/` reaches five pages and identifies `/orphan`; candidate responds 200 with `index,follow`. This is confirmed within the fixture scope; search index status remains unknown. |
| Images/video | Informative and decorative images load with 32-pixel natural width and appropriate nonempty/empty alt. Video metadata loads without interaction. Image, WebM and poster URLs respond 200. VideoObject name, content URL and thumbnail match visible caption and media. Google rich-result eligibility and actual video search appearance remain unmeasured. |

The public checks loaded each URL on desktop and mobile, for six successful page loads:

- `https://docs.python.org/3/`
- `https://docs.python.org/zh-cn/3/`
- `https://docs.python.org/3/library/turtle.html`

**Confirmed for this sample:** all responses were 200; main content, links, canonical, robots and JSON-LD matched between desktop and mobile. Response and rendered title, links, canonical, robots and JSON-LD also matched. No failed resource requests were recorded. The turtle page's informative image loaded with 250-pixel natural width and descriptive alt. Raw and rendered text lengths can differ because source text includes content not visible in the rendered layout; this alone is not a content-loss finding.

**Confirmed observation, intent unknown:** the sampled Chinese homepage had no HTML hreflang links and its canonical pointed to the English homepage. This does not establish the site's complete localization policy or search indexing outcome; HTTP/sitemap hreflang channels and site-owner intent were not assessed. No external website was changed.

This acceptance establishes browser collection and bounded workflow behavior. It does not establish a complete public-site crawl, public-site orphan status, Google's rendered/indexed version, field Core Web Vitals, rankings, traffic improvement, rich-result eligibility, or authenticated provider data. The media and reciprocal-hreflang assertions use the controlled fixture; the public pages supply real response/DOM, mobile and image evidence.
