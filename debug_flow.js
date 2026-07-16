const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const logs = [];
  page.on('console', msg => logs.push(msg.type() + ': ' + msg.text()));
  page.on('pageerror', err => logs.push('PAGEERROR: ' + err.message));
  await page.goto('http://127.0.0.1:8765/index.html', { waitUntil: 'networkidle', timeout: 120000 });
  await page.waitForTimeout(8000);
  const flow = await page.textContent('#flow-readout');
  const ml = await page.textContent('#ml-readout');
  console.log('FLOW:', flow);
  console.log('ML:', ml);
  console.log('LOGS:');
  logs.forEach(l => console.log(l));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
