const { chromium } = require('/home/shuhei2441/repo/dev-docs/.claude/worktrees/develop/node_modules/playwright');
(async () => {
  const b = await chromium.launch();
  const ids = ['dev-docs','claude-balancer','aituber','knowledge','mdmark','ai-monitor','voice-input','gui-support','mindstella','observability','project-index','alias-inject','rule-inject','shuhdev-gateway'];
  for (const round of [1, 2]) {
    for (const id of ids) {
      const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
      const errs = [];
      p.on('response', r => { if (r.status() >= 400) errs.push(r.status() + ' ' + r.url().replace('http://127.0.0.1:18781', '').slice(0, 90)); });
      const t0 = Date.now();
      let res = {};
      try {
        await p.goto('http://127.0.0.1:18781/' + id, { waitUntil: 'networkidle', timeout: 45000 });
        await p.waitForTimeout(800);
        res = await p.evaluate(() => {
          const tabs = [...document.querySelectorAll('nav a, [role=tablist] a, [role=tab]')].map(a => a.textContent.trim()).filter(Boolean);
          return { url: location.pathname + location.search, title: document.title.slice(0, 50), tabs: [...new Set(tabs)].slice(0, 30), head: document.querySelector('main')?.innerText.slice(0, 160).replace(/\n+/g, ' / ') };
        });
      } catch (e) { res = { error: String(e).slice(0, 120) }; }
      if (round === 1) await p.screenshot({ path: `${process.env.SHOTS}/p-${id}.png` });
      console.log(round, id, (Date.now() - t0) + 'ms', JSON.stringify(res), 'ERR', JSON.stringify(errs.slice(0, 5)));
      await p.close();
    }
  }
  await b.close();
})();
