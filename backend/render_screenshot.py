"""Headless Chromium screenshot rendering for Code Forge JSX output."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BACKEND_DIR = Path(__file__).resolve().parent
RENDER_DIR = BACKEND_DIR / "tmp" / "render"
SCREENSHOT_DIR = RENDER_DIR / "screenshots"

REACT_HOOKS = ("useState", "useEffect", "useMemo", "useCallback", "useRef")


class RenderScreenshotError(Exception):
    """Raised when JSX fails to render in headless Chromium."""


def _prepare_code_for_browser(code: str) -> str:
    """Strip ESM imports/exports so Babel standalone + React UMD can run the component."""
    # 1. Extract hooks first from imports of 'react' using global regex
    used_hooks: set[str] = set()
    react_import_matches = re.findall(r'import\s+(?:React\s*,\s*)?\{([^}]+)\}\s+from\s+[\'"]react[\'"]', code)
    for match in react_import_matches:
        for part in match.split(','):
            name = part.strip().split(' as ')[0].strip()
            if name in REACT_HOOKS:
                used_hooks.add(name)

    # 2. Strip imports from any packages globally (handles multiline imports)
    prepared = re.sub(r'import\s+[\s\S]*?\s+from\s+[\'"].*?[\'"];?', '', code)

    # 3. Process remaining lines to clean up exports
    lines = prepared.splitlines()
    out_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        # rewrite export default function App
        if stripped.startswith("export default function "):
            out_lines.append(re.sub(r"^export default function ", "function ", line))
            continue
        if stripped == "export default App;" or stripped == "export default App":
            continue
        out_lines.append(line)

    hook_destructure = ", ".join(sorted(used_hooks)) if used_hooks else "useState"
    preamble = (
        f"const {{ {hook_destructure} }} = React;\n"
        f"const {{ MemoryRouter, Routes, Route, Link, NavLink, useNavigate, useParams, useLocation }} = window.ReactRouterDOM || {{}};\n"
        f"const BrowserRouter = MemoryRouter;"
    )
    body = "\n".join(out_lines).strip()
    return f"{preamble}\n\n{body}\n\nconst root = ReactDOM.createRoot(document.getElementById('root'));\nroot.render(<App />);"


def _build_html(component_code: str) -> str:
    bundled = json.dumps(component_code)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <script src="https://cdn.tailwindcss.com"></script>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script crossorigin src="https://cdn.jsdelivr.net/npm/@remix-run/router@1.6.2/dist/router.umd.min.js"></script>
  <script crossorigin src="https://cdn.jsdelivr.net/npm/react-router@6.13.0/dist/umd/react-router.production.min.js"></script>
  <script crossorigin src="https://cdn.jsdelivr.net/npm/react-router-dom@6.13.0/dist/umd/react-router-dom.production.min.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>
    html, body {{ margin: 0; padding: 0; background: #f3f4f6; }}
    #root {{ min-height: 100vh; }}
  </style>
</head>
<body>
  <div id="root"></div>
  <script>
    (function boot() {{
      if (typeof Babel === 'undefined' || typeof React === 'undefined' || typeof ReactDOM === 'undefined' || typeof ReactRouterDOM === 'undefined') {{
        setTimeout(boot, 50);
        return;
      }}
      try {{
        const source = {bundled};
        const transformed = Babel.transform(source, {{ presets: [['react', {{ runtime: 'classic' }}]] }}).code;
        eval(transformed);
      }} catch (err) {{
        console.error('RENDER_ERROR:', err.message);
        document.getElementById('root').innerHTML = '<pre style="color:red">' + err.message + '</pre>';
      }}
    }})();
  </script>
</body>
</html>
"""


def render_jsx_to_screenshot(
    code: str,
    *,
    viewport_width: int = 1280,
    viewport_height: int = 800,
) -> bytes:
    """Render JSX via CDN React/Babel/Tailwind in headless Chromium; return PNG bytes."""
    if not code.strip():
        raise RenderScreenshotError("Empty code string")

    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    prepared = _prepare_code_for_browser(code)
    html = _build_html(prepared)
    html_path = RENDER_DIR / f"render_{int(time.time() * 1000)}.html"
    html_path.write_text(html, encoding="utf-8")

    page_errors: list[str] = []
    console_logs: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": viewport_width, "height": viewport_height})
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on("console", lambda msg: console_logs.append(f"{msg.type}: {msg.text}"))

            page.set_content(html, wait_until="load", timeout=30_000)
            page.wait_for_function(
                "() => document.getElementById('root') && document.getElementById('root').children.length > 0",
                timeout=20_000,
            )
            page.wait_for_timeout(500)

            root_text = page.locator("#root").inner_text(timeout=5_000)
            if not root_text.strip():
                raise RenderScreenshotError(
                    "Root element rendered empty"
                    + (f"; page errors: {'; '.join(page_errors)}" if page_errors else "")
                )

            png_bytes = page.screenshot(full_page=True, type="png")
        finally:
            browser.close()

    if page_errors:
        raise RenderScreenshotError(f"Page errors during render: {'; '.join(page_errors)}")
    render_errors = [l for l in console_logs if "RENDER_ERROR" in l or l.startswith("error:")]
    if render_errors:
        raise RenderScreenshotError(f"Console errors: {'; '.join(render_errors)}")

    screenshot_path = SCREENSHOT_DIR / f"screenshot_{int(time.time() * 1000)}.png"
    screenshot_path.write_bytes(png_bytes)
    return png_bytes
