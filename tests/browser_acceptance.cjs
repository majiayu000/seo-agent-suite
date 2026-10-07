// Optional integration acceptance: requires Playwright + its Chromium, and a tiny WebM.
// Usage: node tests/browser_acceptance.cjs <artifact-directory> <fixture.webm> [--fixtures-only]
// Uses a headless browser only. This is a controlled fixture, not a production crawler.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const { chromium, devices } = require('playwright');

async function main() {
  const [output, videoFile, mode, ...extra] = process.argv.slice(2);
  if (!output || !videoFile || (mode && mode !== '--fixtures-only') || extra.length) {
    throw new Error('Expected artifact directory, WebM path, and optional --fixtures-only');
  }
  const fixturesOnly = mode === '--fixtures-only';
  await fs.mkdir(output, { recursive: true });
  const video = await fs.readFile(videoFile);
  const inventory = ['/', '/linked', '/spa/deep', '/en', '/zh', '/orphan'];
  let origin;
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" fill="blue"/></svg>';
  const server = http.createServer((req, res) => {
    const route = new URL(req.url, origin).pathname;
    if (route === '/image.svg') {
      res.writeHead(200, { 'Content-Type': 'image/svg+xml' });
      return res.end(svg);
    }
    if (route === '/video.webm') {
      res.writeHead(200, { 'Content-Type': 'video/webm', 'Content-Length': video.length });
      return res.end(video);
    }
    if (route === '/sitemap.xml') {
      res.writeHead(200, { 'Content-Type': 'application/xml' });
      return res.end(`<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${inventory.map(p => `<url><loc>${origin}${p}</loc></url>`).join('')}</urlset>`);
    }
    const missing = !inventory.includes(route) && !['/mobile-gap', '/bad/en', '/bad/zh'].includes(route);
    const locale = route === '/en' || route === '/zh';
    const alternates = locale ? `<link rel="alternate" hreflang="en" href="${origin}/en"><link rel="alternate" hreflang="zh" href="${origin}/zh">` :
      route === '/bad/en' ? `<link rel="alternate" hreflang="en" href="${origin}/bad/en"><link rel="alternate" hreflang="zh" href="${origin}/bad/zh">` :
      route === '/bad/zh' ? `<link rel="alternate" hreflang="zh" href="${origin}/bad/zh">` : '';
    const primary = route === '/mobile-gap' && /Mobile/.test(req.headers['user-agent']) ? '' : 'Primary task instructions';
    const links = route === '/' ? ['/linked', '/spa/deep', '/en', '/zh'] : route === '/en' ? ['/zh'] : route === '/zh' ? ['/en'] : [];
    const media = route === '/' ? `<img src="/image.svg" alt="Blue diagram" width="32" height="32"><img src="/image.svg" alt="" width="32" height="32"><figure><video controls preload="metadata" poster="/image.svg"><source src="/video.webm" type="video/webm"></video><figcaption>Fixture video demonstration</figcaption></figure>` : '';
    const videoSchema = route === '/' ? `<script type="application/ld+json">${JSON.stringify({ '@context': 'https://schema.org', '@type': 'VideoObject', name: 'Fixture video demonstration', contentUrl: origin + '/video.webm', thumbnailUrl: origin + '/image.svg', uploadDate: '2026-10-05', duration: 'PT1S' })}</script>` : '';
    const script = route === '/spa/deep' ? `<script>document.querySelector('main').innerHTML='<h1>Deep route</h1><p>Rendered primary task</p><a href="/linked">Next</a>';document.title='Rendered deep route';const s=document.createElement('script');s.type='application/ld+json';s.textContent=JSON.stringify({'@context':'https://schema.org','@type':'WebPage'});document.head.append(s);document.body.dataset.ready='true';</script>` : `<script>document.body.dataset.ready='true';</script>`;
    res.writeHead(missing ? 404 : 200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(`<!doctype html><html lang="${route === '/zh' ? 'zh' : 'en'}"><head><title>${missing ? 'Not found' : 'Fixture page'}</title><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="index,follow"><link rel="canonical" href="${origin}${route}">${alternates}${videoSchema}</head><body><main>${route === '/spa/deep' ? '' : `<h1>${missing ? 'Not found' : 'Fixture page'}</h1><p>${missing ? 'No such page' : primary}</p>`}${links.map(p => `<a href="${p}">${p}</a>`).join('')}${media}</main>${script}</body></html>`);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  let browser;
  const report = { collected_at: new Date().toISOString(), scope: fixturesOnly ? 'Controlled local fixture only; no public page requests' : 'Controlled fixture plus three public documentation URLs; no sitewide public crawl', checks: {} };
  try {
    browser = await chromium.launch({ headless: true });
    report.browser = { engine: 'chromium', version: browser.version(), headless: true, mobile: 'iPhone 13 user agent and viewport emulation; Chromium engine, not an actual iPhone or Googlebot' };
    const desktop = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const mobile = await browser.newContext(devices['iPhone 13']);
    async function capture(context, url, name, fixture = true) {
      const page = await context.newPage();
      const failures = [];
      page.on('requestfailed', req => failures.push({ url: req.url(), error: req.failure().errorText }));
      try {
        const response = await page.goto(url, { waitUntil: 'load', timeout: 45000 });
        const raw = await response.text();
        const wait = fixture ? 'body[data-ready="true"]' : '[role="main"] h1';
        await page.waitForSelector(wait);
        if (fixture && new URL(url).pathname === '/') {
          await page.waitForFunction(() => [...document.querySelectorAll('video')].every(v => v.readyState >= 1 || v.error));
        }
        const rendered = await page.content();
        const rawSnapshot = await page.evaluate(({ html, base }) => {
          const doc = new DOMParser().parseFromString(html, 'text/html');
          const main = doc.querySelector('main, [role="main"], #content') || doc.body;
          const jsonLd = [...doc.querySelectorAll('script[type="application/ld+json"]')].map(n => n.textContent);
          main.querySelectorAll('script,style').forEach(n => n.remove());
          const resolve = value => new URL(value, base).href;
          return { title: doc.title, main_text: main.textContent.replace(/\s+/g, ' ').trim(),
            links: [...main.querySelectorAll('a[href]')].map(n => resolve(n.getAttribute('href'))),
            canonicals: [...doc.querySelectorAll('link[rel="canonical"]')].map(n => resolve(n.getAttribute('href'))),
            robots: [...doc.querySelectorAll('meta[name="robots"]')].map(n => n.content),
            json_ld: jsonLd };
        }, { html: raw, base: page.url() });
        await fs.writeFile(path.join(output, `${name}.raw.html`), raw);
        await fs.writeFile(path.join(output, `${name}.rendered.html`), rendered);
        return { url: page.url(), http_status: response.status(), wait_condition: wait, failed_resources: failures,
          raw_file: `${name}.raw.html`, rendered_file: `${name}.rendered.html`, raw, raw_snapshot: rawSnapshot,
          ...await page.evaluate(() => {
            const main = document.querySelector('main, [role="main"], #content') || document.body;
            const links = [...main.querySelectorAll('a[href]')].map(a => a.href);
            return { user_agent: navigator.userAgent, viewport: { width: innerWidth, height: innerHeight }, title: document.title,
              main_text: main.innerText.replace(/\s+/g, ' ').trim(), h1: [...document.querySelectorAll('h1')].map(n => n.innerText), links,
              canonicals: [...document.querySelectorAll('link[rel="canonical"]')].map(n => n.href),
              robots: [...document.querySelectorAll('meta[name="robots"]')].map(n => n.content),
              hreflang: [...document.querySelectorAll('link[hreflang]')].map(n => ({ language: n.hreflang, url: n.href })),
              json_ld: [...document.querySelectorAll('script[type="application/ld+json"]')].map(n => n.textContent),
              images: [...main.querySelectorAll('img')].map(n => ({ src: n.currentSrc || n.src, alt: n.getAttribute('alt'), width: n.width, height: n.height, natural_width: n.naturalWidth })),
              videos: [...main.querySelectorAll('video')].map(n => ({ src: n.currentSrc, poster: n.poster, ready_state: n.readyState, error: n.error && n.error.code })) };
          }) };
      } finally { await page.close(); }
    }
    const captures = {};
    for (const route of [...inventory, '/does-not-exist', '/mobile-gap', '/bad/en', '/bad/zh']) {
      captures[route] = await capture(desktop, origin + route, `fixture-${route.replaceAll('/', '_') || 'root'}`);
    }
    const deep = captures['/spa/deep'];
    assert.equal(deep.http_status, 200);
    assert.match(deep.main_text, /Rendered primary task/);
    assert.equal(deep.raw_snapshot.main_text, '');
    assert.equal(deep.raw_snapshot.links.length, 0);
    assert.equal(deep.raw_snapshot.json_ld.length, 0);
    assert.equal(deep.raw_snapshot.title, 'Fixture page');
    assert.equal(deep.title, 'Rendered deep route');
    assert.equal(deep.json_ld.length, 1);
    report.checks.javascript = { outcome: 'passed', raw_main: 'empty', rendered_main: deep.main_text, raw_title: 'Fixture page', rendered_title: deep.title, rendered_links: deep.links, rendered_json_ld_count: deep.json_ld.length };
    assert.equal(captures['/does-not-exist'].http_status, 404);
    assert.match(captures['/does-not-exist'].main_text, /No such page/);
    report.checks.direct_routes = { outcome: 'passed', valid_status: deep.http_status, missing_status: captures['/does-not-exist'].http_status };
    const mobileHome = await capture(mobile, origin + '/', 'fixture-mobile');
    const fields = ['main_text', 'links', 'canonicals', 'robots', 'json_ld'];
    for (const field of fields) assert.deepEqual(mobileHome[field], captures['/'][field]);
    const mobileGap = await capture(mobile, origin + '/mobile-gap', 'fixture-mobile-gap');
    assert.notEqual(mobileGap.main_text, captures['/mobile-gap'].main_text);
    report.checks.mobile = { outcome: 'passed', equivalent_fields: fields, intentional_missing_primary_content_detected: true, desktop_user_agent: captures['/'].user_agent, mobile_user_agent: mobileHome.user_agent, desktop_viewport: captures['/'].viewport, mobile_viewport: mobileHome.viewport };
    function reciprocal(source, target) {
      return source.hreflang.some(a => a.url === target.url) && target.hreflang.some(a => a.url === source.url);
    }
    assert.equal(reciprocal(captures['/en'], captures['/zh']), true);
    assert.equal(reciprocal(captures['/bad/en'], captures['/bad/zh']), false);
    for (const route of ['/en', '/zh']) {
      const p = captures[route];
      assert(p.hreflang.some(a => a.url === p.url));
      assert.deepEqual(p.canonicals, [p.url]);
      assert.equal(p.http_status, 200);
    }
    report.checks.hreflang = { outcome: 'passed', reciprocal_self_canonical_http_200: true, intentional_missing_return_detected: true };
    const reachable = new Set(['/']);
    const queue = ['/'];
    while (queue.length) {
      for (const link of captures[queue.shift()].links) {
        const u = new URL(link);
        if (u.origin === origin && inventory.includes(u.pathname) && !reachable.has(u.pathname)) {
          reachable.add(u.pathname); queue.push(u.pathname);
        }
      }
    }
    const sitemap = await (await desktop.request.get(origin + '/sitemap.xml')).text();
    const independent = [...sitemap.matchAll(/<loc>(.*?)<\/loc>/g)].map(m => new URL(m[1]).pathname);
    const orphans = independent.filter(p => !reachable.has(p));
    assert.deepEqual(orphans, ['/orphan']);
    assert.equal(captures['/orphan'].http_status, 200);
    assert.deepEqual(captures['/orphan'].robots, ['index,follow']);
    report.checks.orphans = { outcome: 'passed', scope: 'Complete six-page fixture inventory; normal entry /; rendered link traversal; no caps or exclusions', independent_inventory: independent, reachable: [...reachable], confirmed_within_scope: orphans, candidate_status: 200, candidate_robots_meta: 'index,follow', search_index_status: 'unknown' };
    const root = captures['/'];
    assert.equal(root.images.length, 2);
    assert.equal(root.images[0].alt, 'Blue diagram');
    assert.equal(root.images[1].alt, '');
    assert(root.images.every(i => i.natural_width === 32));
    assert.equal(root.videos.length, 1);
    assert.equal(root.videos[0].error, null);
    assert(root.videos[0].ready_state >= 1);
    const schema = JSON.parse(root.json_ld[0]);
    assert.equal(schema['@type'], 'VideoObject');
    assert.equal(schema.contentUrl, root.videos[0].src);
    assert.equal(schema.thumbnailUrl, root.videos[0].poster);
    assert(root.main_text.includes(schema.name));
    for (const url of [root.images[0].src, root.videos[0].src, root.videos[0].poster]) {
      const response = await desktop.request.get(url);
      assert.equal(response.status(), 200);
    }
    report.checks.media = { outcome: 'passed', informative_alt: root.images[0].alt, decorative_alt: root.images[1].alt, image_and_video_and_thumbnail_status: 200, video_metadata_loaded: true, json_ld_matches_visible_video_and_thumbnail: true, rich_result_eligibility: 'not tested by Google Rich Results Test', video_search_appearance: 'unknown' };
    report.public = [];
    const publicTargets = fixturesOnly ? [] : [['python-en', 'https://docs.python.org/3/'], ['python-zh', 'https://docs.python.org/zh-cn/3/'], ['python-turtle', 'https://docs.python.org/3/library/turtle.html']];
    for (const [name, url] of publicTargets) {
      const d = await capture(desktop, url, name, false);
      const m = await capture(mobile, url, `${name}-mobile`, false);
      assert.equal(d.http_status, 200);
      assert.equal(m.http_status, 200);
      assert(d.main_text.length > 100);
      assert(d.h1.length > 0);
      const equivalence = Object.fromEntries(fields.map(f => [f, JSON.stringify(d[f]) === JSON.stringify(m[f])]));
      const rawEquivalence = Object.fromEntries(['title', 'links', 'canonicals', 'robots', 'json_ld'].map(f => [f, JSON.stringify(d[f]) === JSON.stringify(d.raw_snapshot[f])]));
      if (name === 'python-turtle') assert(d.images.some(i => i.natural_width > 0));
      report.public.push({ url: d.url, status: d.http_status, title: d.title, main_text_length: d.main_text.length, mobile_equivalence: equivalence, raw_rendered_equivalence: rawEquivalence, raw_main_text_length: d.raw_snapshot.main_text.length, hreflang: d.hreflang, canonicals: d.canonicals, images: d.images, failed_resources: d.failed_resources,
        desktop_capture: { user_agent: d.user_agent, viewport: d.viewport, wait_condition: d.wait_condition },
        mobile_capture: { status: m.http_status, user_agent: m.user_agent, viewport: m.viewport, wait_condition: m.wait_condition, failed_resources: m.failed_resources },
        desktop_artifacts: [d.raw_file, d.rendered_file], mobile_artifacts: [m.raw_file, m.rendered_file] });
    }
    report.fixture_captures = Object.fromEntries(Object.entries(captures).map(([route, value]) => {
      const { raw, ...evidence } = value;
      return [route, evidence];
    }));
    await fs.writeFile(path.join(output, 'acceptance.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ checks: report.checks, public: report.public, report: path.join(output, 'acceptance.json') }, null, 2));
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
