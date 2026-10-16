import { useEffect, useMemo, useRef, useState } from 'react';

// Runs untrusted generated code. Babel + eval live ONLY inside this sandboxed iframe
// (sandbox="allow-scripts", no allow-same-origin => opaque origin, no parent cookies/storage).

const REACT_HOOKS = ['useState', 'useEffect', 'useMemo', 'useCallback', 'useRef', 'useContext'];

function prepareCodeForBrowser(code: string): string {
  // 1. Extract hooks first from imports of 'react' using global regex
  const usedHooks = new Set<string>();
  const reactImportRegex = /import\s+(?:React\s*,\s*)?\{([^}]+)\}\s+from\s+['"]react['"]/g;
  let match;
  while ((match = reactImportRegex.exec(code)) !== null) {
    match[1].split(',').forEach(part => {
      const name = part.trim().split(' as ')[0].trim();
      if (REACT_HOOKS.includes(name)) usedHooks.add(name);
    });
  }

  // 2. Strip imports from 'react' and 'react-router-dom' globally (handles multiline imports)
  let prepared = code;
  prepared = prepared.replace(/import\s+[\s\S]*?\s+from\s+['"]react['"];?/g, '');
  prepared = prepared.replace(/import\s+[\s\S]*?\s+from\s+['"]react-router-dom['"];?/g, '');

  // 3. Process remaining lines to clean up exports
  const lines = prepared.split('\n');
  const outLines: string[] = [];
  for (const line of lines) {
    const stripped = line.trim();
    // rewrite export default function App
    if (stripped.startsWith('export default function ')) {
      outLines.push(line.replace('export default function ', 'function '));
      continue;
    }
    if (stripped === 'export default App;' || stripped === 'export default App') continue;
    outLines.push(line);
  }

  const body = outLines.join('\n').trim();

  // Capture the App component to avoid naming collisions with sub-components
  // Instead of renaming, we alias the main App after the code runs
  const hooks = usedHooks.size > 0 ? [...usedHooks].sort().join(', ') : 'useState';
  const preamble = `const { ${hooks} } = React;
const { MemoryRouter, Routes, Route, Link, NavLink, useNavigate, useParams, useLocation } = window.ReactRouterDOM || {};
const BrowserRouter = MemoryRouter;`;
  // After eval, capture whatever the default-exported component is.
  // The LLM always exports a default component; if it's not named App, we fall back.
  return `${preamble}\n\n${body}\n
var _defaultExport = (typeof App !== 'undefined') ? App : (typeof exports !== 'undefined' && exports.default) || null;
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(_defaultExport ? React.createElement(_defaultExport) : React.createElement(function(){ return React.createElement('div', null, 'No default export found'); }));`;
}

function buildSrcdoc(componentCode: string): string {
  const bundled = JSON.stringify(componentCode);
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <script src="https://cdn.tailwindcss.com"></script>
  <script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/react/18.3.1/umd/react.production.min.js"></script>
  <script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.3.1/umd/react-dom.production.min.js"></script>
  <script crossorigin src="https://cdn.jsdelivr.net/npm/@remix-run/router@1.6.2/dist/router.umd.min.js"></script>
  <script crossorigin src="https://cdn.jsdelivr.net/npm/react-router@6.13.0/dist/umd/react-router.production.min.js"></script>
  <script crossorigin src="https://cdn.jsdelivr.net/npm/react-router-dom@6.13.0/dist/umd/react-router-dom.production.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.5/babel.min.js"></script>
  <style>html,body{margin:0;padding:0;background:#f3f4f6}</style>
</head>
<body>
  <div id="root"></div>
  <script>
    // Report content height to the parent so the iframe can grow with it.
    new ResizeObserver(function(){
      parent.postMessage({type:'sketchstorm:resize',height:Math.ceil(document.documentElement.getBoundingClientRect().height)},'*');
    }).observe(document.documentElement);
  </script>
  <script>
    (function boot(){
      if(typeof Babel==='undefined'||typeof React==='undefined'||typeof ReactDOM==='undefined'||typeof ReactRouterDOM==='undefined'){
        setTimeout(boot,50);return;
      }
      // Block all navigation — keep the preview self-contained
      var _origPushState = history.pushState;
      var _origReplaceState = history.replaceState;
      history.pushState = function(state, title, url) {
        if (typeof url === 'string' && (url.startsWith('http') || url.startsWith('//'))) return;
        return _origPushState.apply(this, arguments);
      };
      history.replaceState = function(state, title, url) {
        if (typeof url === 'string' && (url.startsWith('http') || url.startsWith('//'))) return;
        return _origReplaceState.apply(this, arguments);
      };
      window.addEventListener('click', function(e){
        var a = e.target.closest('a');
        if (a && a.href && !a.href.startsWith('javascript:')) { e.preventDefault(); e.stopPropagation(); }
      }, true);
      var _origAssign = window.location.assign;
      var _origReplace = window.location.replace;
      window.location.assign = function(){};
      window.location.replace = function(){};
      try{
        var source=${bundled};
        var transformed=Babel.transform(source,{presets:[['react',{runtime:'classic'}]]}).code;
        eval(transformed);
      }catch(err){
        document.getElementById('root').innerHTML='<pre style="color:red;padding:16px">'+err.message+'</pre>';
      }
    })();
  </script>
</body>
</html>`;
}

interface Props {
  code: string;
}

export default function SandboxedPreview({ code }: Props) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(0);
  const srcDoc = useMemo(() => buildSrcdoc(prepareCodeForBrowser(code)), [code]);

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      // The sandboxed frame's origin is "null", so identify it by window instead.
      if (e.source !== iframeRef.current?.contentWindow) return;
      const d = e.data;
      if (d && d.type === 'sketchstorm:resize' && Number.isFinite(d.height)) {
        setHeight(Math.min(Math.max(0, d.height), 20000));
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  return (
    <div className="h-full w-full overflow-auto bg-white">
      <iframe
        ref={iframeRef}
        srcDoc={srcDoc}
        sandbox="allow-scripts"
        title="Live preview"
        className="block w-full border-0"
        style={{ height, minHeight: '100%' }}
      />
    </div>
  );
}
