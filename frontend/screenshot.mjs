import { chromium } from 'playwright';

const OUT = '/private/tmp/claude-501/-Users-max-cerebrashacks/ab1f8186-04ff-4d0c-b4aa-3d06ee4eb482/scratchpad';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.setViewportSize({ width: 1400, height: 900 });
await page.goto('http://localhost:5175/', { waitUntil: 'networkidle' });

// Load dashboard sketch
await page.click('#mock-sketch-btn-2');
await page.waitForTimeout(600);
await page.screenshot({ path: `${OUT}/01_sketch_loaded.png` });
console.log('01: sketch loaded, Add context field visible');

// Generate
await page.click('button:has-text("Generate")');
console.log('Generate clicked, waiting for pipeline to complete (up to 90s)…');

// Wait for "New" button — only appears when isDone || isError
await page.waitForSelector('button:has-text("New")', { timeout: 90000 });
await page.waitForTimeout(800); // let Preview auto-switch settle
await page.screenshot({ path: `${OUT}/02_done_default.png` });
console.log('02: post-generation default view');

// Expand one agent card (click Vision row)
await page.locator('button').filter({ hasText: /^👁\s*Vision/ }).click();
await page.waitForTimeout(200);
await page.screenshot({ path: `${OUT}/03_agent_expanded.png` });
console.log('03: Vision card expanded');

// Issues tab — panel starts collapsed
await page.click('button:has-text("⚠️ Issues")');
await page.waitForTimeout(200);
await page.screenshot({ path: `${OUT}/04_issues_collapsed.png` });
console.log('04: Issues tab open, panel collapsed');

// Expand issues panel
const issueHeader = page.locator('button').filter({ hasText: /Issues/ }).last();
await issueHeader.click();
await page.waitForTimeout(200);
await page.screenshot({ path: `${OUT}/05_issues_expanded.png` });
console.log('05: Issues panel expanded with real data');

// Back to Preview tab, enable Design Mode
await page.click('button:has-text("Preview")');
await page.waitForTimeout(200);
await page.click('button:has-text("Design Mode")');
await page.waitForTimeout(400);
await page.screenshot({ path: `${OUT}/06_design_mode.png` });
console.log('06: Design Mode floating toolbar');

await browser.close();
console.log('Done.');
