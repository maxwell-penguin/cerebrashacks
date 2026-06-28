import { chromium } from 'playwright';
import fs from 'fs';

const OUT = '/private/tmp/claude-501/-Users-max-cerebrashacks/ab1f8186-04ff-4d0c-b4aa-3d06ee4eb482/scratchpad';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.setViewportSize({ width: 1400, height: 900 });

// Capture console errors
const consoleErrors = [];
page.on('console', msg => {
  if (msg.type() === 'error') consoleErrors.push(msg.text());
});

// Capture the pipeline_complete WS message to get the actual code
let capturedCode = '';
page.on('websocket', ws => {
  ws.on('framereceived', frame => {
    try {
      const msg = JSON.parse(frame.payload);
      if (msg.type === 'pipeline_complete' && msg.code) {
        capturedCode = msg.code;
      }
    } catch {}
  });
});

await page.goto('http://localhost:5175/', { waitUntil: 'networkidle' });

// Load dashboard sketch
await page.click('#mock-sketch-btn-2');
await page.waitForTimeout(400);

// Generate
await page.click('button:has-text("Generate")');
console.log('Generating...');

// Wait for completion
await page.waitForSelector('button:has-text("New")', { timeout: 90000 });
await page.waitForTimeout(1500);

// Get the Monaco editor content (the actual code being rendered)
const editorCode = await page.evaluate(() => {
  // Try to get code from Monaco editor model
  if (window.monaco) {
    const models = window.monaco.editor.getModels();
    if (models.length > 0) return models[0].getValue();
  }
  return null;
});

// Also check if there's an error visible in preview
await page.click('button:has-text("Preview")');
await page.waitForTimeout(500);

const previewError = await page.evaluate(() => {
  const iframe = document.querySelector('iframe[title="Live preview"]');
  if (!iframe) return null;
  try {
    const body = iframe.contentDocument?.body?.innerText;
    return body || null;
  } catch { return 'cross-origin'; }
});

fs.writeFileSync(`${OUT}/generated_code.txt`, capturedCode || editorCode || 'not captured');
fs.writeFileSync(`${OUT}/preview_error.txt`, previewError || 'none');
fs.writeFileSync(`${OUT}/console_errors.txt`, consoleErrors.join('\n') || 'none');

console.log('Code length:', (capturedCode || editorCode || '').length);
console.log('Preview content:', (previewError || '').slice(0, 200));
console.log('Console errors:', consoleErrors.slice(0, 3));

await browser.close();
