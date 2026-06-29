import JSZip from 'jszip';
import Editor from '@monaco-editor/react';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import type { AgentState } from '../types';

interface Props {
  streamingCode: string;
  finalCode: string;
  onChangeCode?: (code: string) => void;
  criticState?: AgentState;
  isRunning?: boolean;
  refineRegion?: (code: string, regionDescription: string, refinementRequest: string, sketchBase64?: string) => Promise<{
    patched_code: string;
    changed_regions_summary: string;
    diff_stats: { lines_changed: number; lines_total: number; change_ratio: number };
    warning: string | null;
  }>;
  cancelRefine?: () => void;
  errorMsg?: string;
}

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

  const hooks = usedHooks.size > 0 ? [...usedHooks].sort().join(', ') : 'useState';
  const preamble = `const { ${hooks} } = React;
const { MemoryRouter, Routes, Route, Link, NavLink, useNavigate, useParams, useLocation } = window.ReactRouterDOM || {};
const BrowserRouter = MemoryRouter;`;
  const body = outLines.join('\n').trim();
  return `${preamble}\n\n${body}\n\nconst root = ReactDOM.createRoot(document.getElementById('root'));\nroot.render(<App />);`;
}

function buildSrcdoc(componentCode: string): string {
  const bundled = JSON.stringify(componentCode);
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <script src="https://cdn.tailwindcss.com"></script>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script crossorigin src="https://cdn.jsdelivr.net/npm/@remix-run/router@1.6.2/dist/router.umd.min.js"></script>
  <script crossorigin src="https://cdn.jsdelivr.net/npm/react-router@6.13.0/dist/umd/react-router.production.min.js"></script>
  <script crossorigin src="https://cdn.jsdelivr.net/npm/react-router-dom@6.13.0/dist/umd/react-router-dom.production.min.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>html,body{margin:0;padding:0;background:#f3f4f6}#root{min-height:100vh}</style>
</head>
<body>
  <div id="root"></div>
  <script>
    (function boot(){
      if(typeof Babel==='undefined'||typeof React==='undefined'||typeof ReactDOM==='undefined'||typeof ReactRouterDOM==='undefined'){
        setTimeout(boot,50);return;
      }
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

type Tab = 'editor' | 'preview';

export default function EditorPane({
  streamingCode,
  finalCode,
  onChangeCode,
  criticState,
  isRunning,
  refineRegion,
  cancelRefine,
  errorMsg,
}: Props) {
  const [tab, setTab] = useState<Tab>('editor');
  const [srcdoc, setSrcdoc] = useState('');
  const [hasAutoSwitched, setHasAutoSwitched] = useState(false);
  const [copied, setCopied] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Design Mode State
  const [isDesignMode, setIsDesignMode] = useState(false);
  const [selectedRegion, setSelectedRegion] = useState('Main content');
  const [refinementText, setRefinementText] = useState('');
  const [refinementLoading, setRefinementLoading] = useState(false);
  const [refinementError, setRefinementError] = useState<string | null>(null);
  const [pendingRefinement, setPendingRefinement] = useState<{
    patchedCode: string;
    warning: string | null;
    diffStats: { lines_changed: number; lines_total: number; change_ratio: number };
    summary: string;
  } | null>(null);
  const [refinementSuccess, setRefinementSuccess] = useState<{
    diffStats: { lines_changed: number; lines_total: number; change_ratio: number };
    summary: string;
  } | null>(null);

  // Draw Mode state
  const [drawMode, setDrawMode] = useState<'text' | 'draw' | 'upload'>('text');
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hasStrokes, setHasStrokes] = useState(false);
  const strokes = useRef<Array<Array<{ x: number; y: number }> >>([]);
  const isDrawingRef = useRef(false);
  const currentStroke = useRef<Array<{ x: number; y: number }>>([]);
  const [uploadedImageBase64, setUploadedImageBase64] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const redrawAll = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = '#1e293b';
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    for (const stroke of strokes.current) {
      if (stroke.length < 2) continue;
      ctx.beginPath();
      ctx.moveTo(stroke[0].x, stroke[0].y);
      for (let i = 1; i < stroke.length; i++) ctx.lineTo(stroke[i].x, stroke[i].y);
      ctx.stroke();
    }
  }, []);

  const getCanvasPos = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) * (canvas.width / rect.width),
      y: (e.clientY - rect.top) * (canvas.height / rect.height),
    };
  };

  const startDraw = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const pos = getCanvasPos(e);
    isDrawingRef.current = true;
    currentStroke.current = [pos];
    const ctx = canvasRef.current?.getContext('2d');
    if (!ctx) return;
    ctx.strokeStyle = '#1e293b';
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.beginPath();
    ctx.moveTo(pos.x, pos.y);
  };

  const continueDraw = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isDrawingRef.current) return;
    const pos = getCanvasPos(e);
    currentStroke.current.push(pos);
    const ctx = canvasRef.current?.getContext('2d');
    if (!ctx) return;
    ctx.lineTo(pos.x, pos.y);
    ctx.stroke();
  };

  const endDraw = () => {
    if (!isDrawingRef.current) return;
    isDrawingRef.current = false;
    if (currentStroke.current.length > 1) {
      strokes.current = [...strokes.current, [...currentStroke.current]];
      setHasStrokes(true);
    }
    currentStroke.current = [];
  };

  const clearCanvas = () => {
    strokes.current = [];
    setHasStrokes(false);
    redrawAll();
  };

  const undoStroke = () => {
    if (strokes.current.length === 0) return;
    strokes.current = strokes.current.slice(0, -1);
    setHasStrokes(strokes.current.length > 0);
    redrawAll();
  };

  const handleApplyRefinement = async () => {
    const hasText = refinementText.trim().length > 0;
    const hasImage = drawMode === 'upload' && !!uploadedImageBase64;
    if (!refineRegion || (!hasText && !hasStrokes && !hasImage)) return;
    setRefinementLoading(true);
    setRefinementError(null);
    setRefinementSuccess(null);

    let sketchBase64: string | undefined;
    if (hasImage) {
      sketchBase64 = uploadedImageBase64!;
    } else if (hasStrokes && canvasRef.current) {
      sketchBase64 = canvasRef.current.toDataURL('image/png');
    }

    try {
      const res = await refineRegion(finalCode, selectedRegion, refinementText, sketchBase64);
      console.log('Refinement result:', res);
      if (res.warning) {
        setPendingRefinement({
          patchedCode: res.patched_code,
          warning: res.warning,
          diffStats: res.diff_stats,
          summary: res.changed_regions_summary,
        });
      } else {
        if (onChangeCode) {
          onChangeCode(res.patched_code);
        }
        setRefinementSuccess({
          diffStats: res.diff_stats,
          summary: res.changed_regions_summary,
        });
        setRefinementText('');
      }
    } catch (err: any) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // User cancelled — do nothing
      } else {
        console.error('Refinement failed:', err);
        setRefinementError(err.message || 'Failed to refine region.');
      }
    } finally {
      setRefinementLoading(false);
    }
  };

  const handleKeepRefinement = () => {
    if (pendingRefinement && onChangeCode) {
      onChangeCode(pendingRefinement.patchedCode);
      setRefinementSuccess({
        diffStats: pendingRefinement.diffStats,
        summary: pendingRefinement.summary,
      });
    }
    setPendingRefinement(null);
    setRefinementText('');
  };

  const handleDiscardRefinement = () => {
    setPendingRefinement(null);
  };

  useEffect(() => {
    setRefinementText('');
    setRefinementError(null);
    setRefinementSuccess(null);
    setPendingRefinement(null);
    setDrawMode('text');
    strokes.current = [];
    setHasStrokes(false);
    setUploadedImageBase64(null);
  }, [isDesignMode]);

  useEffect(() => {
    if (drawMode !== 'draw') return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    redrawAll();
  }, [drawMode, redrawAll]);

  // when finalCode arrives, build preview and auto-switch
  useEffect(() => {
    if (!finalCode) {
      setHasAutoSwitched(false);
      return;
    }
    const prepared = prepareCodeForBrowser(finalCode);
    setSrcdoc(buildSrcdoc(prepared));
    if (!hasAutoSwitched) {
      setTab('preview');
      setHasAutoSwitched(true);
    }
  }, [finalCode, hasAutoSwitched]);

  const displayCode = streamingCode || finalCode || '';

  const handleCopy = useCallback(async () => {
    if (!displayCode) return;
    try {
      await navigator.clipboard.writeText(displayCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback for older browsers
      const textarea = document.createElement('textarea');
      textarea.value = displayCode;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [displayCode]);

  const handleDownloadZip = useCallback(async () => {
    if (!finalCode) return;

    const zip = new JSZip();

    // 1. Add config files
    zip.file('package.json', `{
  "name": "sketchstorm-export",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.13.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.3",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.47",
    "tailwindcss": "^3.4.14",
    "typescript": "^5.6.3",
    "vite": "^5.4.10"
  }
}`);

    zip.file('vite.config.ts', `import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
});`);

    zip.file('tailwind.config.js', `/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}`);

    zip.file('postcss.config.js', `export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}`);

    zip.file('tsconfig.json', `{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ScriptHost", "ES2020"],
    "module": "ESNext",
    "skipLibCheck": true,

    /* Bundler mode */
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",

    /* Linting */
    "strict": false,
    "noImplicitAny": false,
    "strictNullChecks": false,
    "noUnusedLocals": false,
    "noUnusedParameters": false,
    "noFallthroughCasesInSwitch": false
  },
  "include": ["src"]
}`);

    zip.file('index.html', `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>SketchStorm App</title>
  </head>
  <body class="bg-slate-50 text-slate-700">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>`);

    // Add src files
    const src = zip.folder('src');
    if (src) {
      src.file('main.tsx', `import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)`);

      src.file('index.css', `@tailwind base;
@tailwind components;
@tailwind utilities;`);

      src.file('App.tsx', finalCode);
    }

    try {
      const content = await zip.generateAsync({ type: 'blob' });
      const url = URL.createObjectURL(content);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'sketchstorm-export.zip';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to create project ZIP export:', err);
    }
  }, [finalCode]);

  return (
    <div className="flex flex-col h-full bg-slate-50 overflow-hidden">
      {/* Tabs */}
      <div className="flex items-center justify-between border-b border-slate-200 shrink-0 bg-slate-100 pr-4">
        <div className="flex items-center gap-3">
          <div className="flex">
            <button
              className={`px-4 py-2 text-xs font-semibold transition-colors ${tab === 'editor' ? 'text-indigo-600 border-b-2 border-indigo-500 bg-white shadow-sm' : 'text-slate-550 hover:text-slate-705 hover:bg-slate-200/40'}`}
              onClick={() => setTab('editor')}
            >
              Code
            </button>
            <button
              className={`px-4 py-2 text-xs font-semibold transition-colors ${tab === 'preview' ? 'text-emerald-700 border-b-2 border-emerald-500 bg-white shadow-sm' : 'text-slate-550 hover:text-slate-705 hover:bg-slate-200/40'}`}
              onClick={() => setTab('preview')}
            >
              Preview
              {finalCode && <span className="ml-1.5 w-1.5 h-1.5 inline-block rounded-full bg-emerald-500 animate-pulse" />}
            </button>
          </div>

          {finalCode && (
            <button
              onClick={() => setIsDesignMode(!isDesignMode)}
              className={`text-xs px-2.5 py-1 rounded border font-semibold flex items-center gap-1.5 transition-all ${isDesignMode ? 'bg-indigo-50 border-indigo-200 text-indigo-700 shadow-sm' : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50'}`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${isDesignMode ? 'bg-indigo-600 animate-pulse' : 'bg-slate-400'}`} />
              🎨 Design Mode
            </button>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Visual QA Badge */}
          {criticState && (() => {
            const { status } = criticState;
            if (status === 'done') {
              return (
                <span className="text-[10px] font-extrabold px-2.5 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200/60 animate-fade-in uppercase tracking-wider">
                  QA: done
                </span>
              );
            }
            if (status === 'warn') {
              return (
                <span className="text-[10px] font-extrabold px-2.5 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-200/60 animate-fade-in uppercase tracking-wider">
                  QA: warn
                </span>
              );
            }
            if (status === 'error') {
              return (
                <span className="text-[10px] font-extrabold px-2.5 py-0.5 rounded-full bg-rose-100 text-rose-800 border border-rose-200/60 animate-fade-in uppercase tracking-wider">
                  QA: error
                </span>
              );
            }
            if (status === 'thinking') {
              return (
                <span className="text-[10px] font-extrabold px-2.5 py-0.5 rounded-full bg-indigo-100 text-indigo-800 border border-indigo-200/60 animate-pulse uppercase tracking-wider">
                  QA: thinking
                </span>
              );
            }
            return null;
          })()}
        </div>
      </div>

      {/* Content area — relative so floating Design Mode toolbar can anchor to it */}
      <div className="flex-1 overflow-hidden relative">
        {/* Editor */}
        <div className={`overflow-hidden ${tab === 'editor' ? 'absolute inset-0 flex flex-col' : 'hidden'}`}>
          {errorMsg ? (
            <div className="flex-1 flex flex-col items-center justify-center p-6 bg-slate-50 text-center select-none animate-fade-in">
              <div className="max-w-md bg-white rounded-xl border border-slate-200 p-6 shadow-md">
                <div className="text-4xl mb-3">⚠️</div>
                <h3 className="text-base font-bold text-slate-800 mb-2">Generation Stopped</h3>
                <p className="text-sm text-slate-600 leading-relaxed">
                  {errorMsg}
                </p>
              </div>
            </div>
          ) : displayCode ? (
            <>
              <div className="flex-1 min-h-0">
                <Editor
                  height="100%"
                  defaultLanguage="typescript"
                  value={displayCode}
                  theme="vs-dark"
                  onChange={(val) => {
                    if (onChangeCode && val !== undefined) {
                      onChangeCode(val);
                    }
                  }}
                  options={{
                    readOnly: isRunning || !finalCode,
                    minimap: { enabled: false },
                    fontSize: 12,
                    lineNumbers: 'on',
                    scrollBeyondLastLine: false,
                    wordWrap: 'on',
                    automaticLayout: true,
                    fontFamily: '"Fira Code", "Cascadia Code", monospace',
                  }}
                />
              </div>
              {/* Copy and Download buttons */}
              <div className="shrink-0 px-3 py-2 border-t border-slate-200 bg-slate-100 flex justify-end gap-2">
                <button
                  onClick={handleDownloadZip}
                  className="text-[11px] px-3 py-1 rounded font-semibold transition-all
                             bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200
                             shadow-sm flex items-center gap-1.5 active:scale-[0.97]"
                >
                  <span>📦</span> Download starter project
                </button>
                <button
                  onClick={handleCopy}
                  className="text-[11px] px-3 py-1 rounded font-semibold transition-all
                             bg-white hover:bg-slate-50 text-slate-600 border border-slate-300
                             shadow-sm flex items-center gap-1.5 active:scale-[0.97]"
                >
                  {copied ? (
                    <>
                      <span className="text-emerald-600">✓</span> Copied!
                    </>
                  ) : (
                    <>
                      <span>📋</span> Copy code
                    </>
                  )}
                </button>
              </div>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center bg-slate-50" role="status" aria-label="Waiting for code generation">
              {isRunning ? (
                <div className="flex flex-col items-center gap-3 animate-pulse">
                  <div className="w-8 h-8 border-3 border-indigo-200 border-t-indigo-500 rounded-full animate-spin" />
                  <span className="text-sm text-slate-500 font-medium">Generating code…</span>
                  <div className="flex flex-col gap-2 w-64">
                    <div className="h-3 bg-slate-200 rounded w-full" />
                    <div className="h-3 bg-slate-200 rounded w-3/4" />
                    <div className="h-3 bg-slate-200 rounded w-1/2" />
                  </div>
                </div>
              ) : (
                <span className="text-sm text-slate-400">Waiting for code generation…</span>
              )}
            </div>
          )}
        </div>

        {/* Preview iframe */}
        <div className={`overflow-hidden ${tab === 'preview' ? 'absolute inset-0 flex flex-col' : 'hidden'}`}>
          {errorMsg ? (
            <div className="flex-1 flex flex-col items-center justify-center p-6 bg-slate-50 text-center select-none animate-fade-in">
              <div className="max-w-md bg-white rounded-xl border border-slate-200 p-6 shadow-md">
                <div className="text-4xl mb-3">⚠️</div>
                <h3 className="text-base font-bold text-slate-800 mb-2">Generation Stopped</h3>
                <p className="text-sm text-slate-600 leading-relaxed">
                  {errorMsg}
                </p>
              </div>
            </div>
          ) : srcdoc ? (
            <iframe
              ref={iframeRef}
              srcDoc={srcdoc}
              className="w-full h-full border-0 bg-white"
              sandbox="allow-scripts"
              title="Live preview"
            />
          ) : (
            <div className="flex-1 flex items-center justify-center text-slate-450 bg-slate-50 text-sm">
              Preview will appear here once generation completes
            </div>
          )}
        </div>

        {/* Design Mode — floating toolbar pinned to bottom, overlays content */}
        {isDesignMode && finalCode && (
          <div className="absolute bottom-0 inset-x-0 z-20 animate-fade-in">
            {/* Pending Confirmation Safety Net — sits above the toolbar */}
            {pendingRefinement && (
              <div className="mx-3 mb-1 bg-amber-50 border border-amber-200 rounded-lg p-3 flex flex-col gap-2 shadow-lg animate-fade-in">
                <div className="flex items-start gap-2">
                  <span className="text-base">⚠️</span>
                  <div className="flex-1">
                    <h4 className="text-xs font-bold text-amber-900">{pendingRefinement.warning || "Review refinement changes"}</h4>
                    <p className="text-[11px] text-amber-800 mt-0.5 font-medium">
                      Changed <strong>{pendingRefinement.diffStats.lines_changed}</strong> of <strong>{pendingRefinement.diffStats.lines_total}</strong> lines ({(pendingRefinement.diffStats.change_ratio * 100).toFixed(1)}% change ratio)
                    </p>
                  </div>
                </div>
                <div className="flex items-center justify-end gap-2">
                  <button
                    onClick={handleDiscardRefinement}
                    className="text-[11px] font-semibold px-3 py-1 rounded bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 transition-colors"
                  >
                    Discard
                  </button>
                  <button
                    onClick={handleKeepRefinement}
                    className="text-[11px] font-semibold px-3 py-1 rounded bg-amber-600 hover:bg-amber-700 text-white shadow-sm transition-colors"
                  >
                    Keep this change
                  </button>
                </div>
              </div>
            )}

            {/* Uploaded image preview */}
            {drawMode === 'upload' && uploadedImageBase64 && (
              <div className="bg-white border-t border-slate-200">
                <div className="flex items-center justify-between px-3 py-1 border-b border-slate-100">
                  <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
                    📎 Uploaded sketch
                  </span>
                  <button
                    onClick={() => { setUploadedImageBase64(null); setDrawMode('text'); }}
                    className="text-[10px] px-2 py-0.5 rounded font-semibold bg-slate-100 hover:bg-slate-200 text-slate-600 transition-colors"
                  >
                    Remove
                  </button>
                </div>
                <div className="flex justify-center p-2 bg-slate-50">
                  <img src={uploadedImageBase64} alt="Uploaded sketch" className="max-h-32 rounded border border-slate-200 object-contain" />
                </div>
              </div>
            )}

            {/* Canvas panel — shown when draw mode is active */}
            {drawMode === 'draw' && (
              <div className="bg-white border-t border-slate-200 shadow-[0_-2px_8px_rgba(0,0,0,0.06)]">
                <div className="flex items-center justify-between px-3 py-1 border-b border-slate-100">
                  <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
                    Draw your change
                    {hasStrokes && (
                      <span className="ml-2 font-normal normal-case text-indigo-500">
                        {strokes.current.length} stroke{strokes.current.length !== 1 ? 's' : ''}
                      </span>
                    )}
                  </span>
                  <div className="flex gap-1.5">
                    <button
                      onClick={undoStroke}
                      disabled={!hasStrokes}
                      className="text-[10px] px-2 py-0.5 rounded font-semibold bg-slate-100 hover:bg-slate-200 text-slate-600 disabled:opacity-40 transition-colors"
                    >
                      Undo
                    </button>
                    <button
                      onClick={clearCanvas}
                      disabled={!hasStrokes}
                      className="text-[10px] px-2 py-0.5 rounded font-semibold bg-slate-100 hover:bg-slate-200 text-slate-600 disabled:opacity-40 transition-colors"
                    >
                      Clear
                    </button>
                  </div>
                </div>
                <canvas
                  ref={canvasRef}
                  width={1200}
                  height={160}
                  className="w-full h-40 cursor-crosshair touch-none block"
                  style={{ background: '#fff' }}
                  onMouseDown={startDraw}
                  onMouseMove={continueDraw}
                  onMouseUp={endDraw}
                  onMouseLeave={endDraw}
                />
              </div>
            )}

            {/* Main toolbar row */}
            <div className="bg-white/95 backdrop-blur border-t border-slate-200 shadow-[0_-2px_12px_rgba(0,0,0,0.08)] px-3 py-2 flex items-center gap-2">
              <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider shrink-0 flex items-center gap-1">
                🎨 Region
              </span>

              <select
                value={selectedRegion}
                onChange={e => setSelectedRegion(e.target.value)}
                disabled={refinementLoading || !!pendingRefinement}
                className="text-xs bg-slate-50 border border-slate-200 rounded px-2 py-1 text-slate-800 focus:outline-none focus:border-indigo-500 w-32 shrink-0"
              >
                <option value="Header">Header</option>
                <option value="Sidebar">Sidebar</option>
                <option value="Main content">Main content</option>
                <option value="Footer">Footer</option>
              </select>

              {/* Describe / Draw / Upload toggle */}
              <div className="flex rounded border border-slate-200 overflow-hidden shrink-0">
                <button
                  onClick={() => { setDrawMode('text'); setUploadedImageBase64(null); }}
                  disabled={refinementLoading || !!pendingRefinement}
                  className={`text-[10px] px-2 py-1 font-semibold transition-colors ${drawMode === 'text' ? 'bg-indigo-600 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}`}
                >
                  Describe
                </button>
                <button
                  onClick={() => { setDrawMode('draw'); setUploadedImageBase64(null); }}
                  disabled={refinementLoading || !!pendingRefinement}
                  className={`text-[10px] px-2 py-1 font-semibold border-l border-slate-200 transition-colors ${drawMode === 'draw' ? 'bg-indigo-600 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}`}
                >
                  ✏️ Draw
                </button>
                <button
                  onClick={() => { setDrawMode('upload'); fileInputRef.current?.click(); }}
                  disabled={refinementLoading || !!pendingRefinement}
                  className={`text-[10px] px-2 py-1 font-semibold border-l border-slate-200 transition-colors ${drawMode === 'upload' ? 'bg-indigo-600 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}`}
                >
                  📎 Upload
                </button>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  const reader = new FileReader();
                  reader.onload = () => {
                    setUploadedImageBase64(reader.result as string);
                    setDrawMode('upload');
                  };
                  reader.readAsDataURL(file);
                }}
              />

              <input
                type="text"
                value={refinementText}
                onChange={e => setRefinementText(e.target.value)}
                disabled={refinementLoading || !!pendingRefinement}
                placeholder={drawMode === 'draw' ? 'Optional: add context for your drawing…' : drawMode === 'upload' ? 'Describe the change based on your uploaded sketch…' : 'Describe the change you want…'}
                className="flex-1 text-xs bg-slate-50 border border-slate-200 rounded px-2.5 py-1 text-slate-800 focus:outline-none focus:border-indigo-500 min-w-0"
              />

              {refinementError && (
                <span className="text-[10px] text-rose-600 font-semibold shrink-0">⚠️ {refinementError}</span>
              )}
              {refinementSuccess && !refinementError && (
                <span className="text-[10px] text-emerald-600 font-semibold shrink-0 animate-fade-in">
                  ✓ {refinementSuccess.diffStats.lines_changed} lines changed
                </span>
              )}

              <div className="flex items-center gap-1.5">
                <button
                  onClick={handleApplyRefinement}
                  disabled={refinementLoading || !!pendingRefinement || (!refinementText.trim() && !hasStrokes && !uploadedImageBase64)}
                  className="text-xs px-3 py-1 rounded font-semibold transition-colors bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed text-white shadow-sm flex items-center gap-1.5 shrink-0"
                >
                  {refinementLoading ? (
                    <>
                      <span className="w-3 h-3 border-2 border-white/35 border-t-white rounded-full animate-spin" />
                      Refining…
                    </>
                  ) : (
                    'Apply'
                  )}
                </button>
                {refinementLoading && cancelRefine && (
                  <button
                    onClick={cancelRefine}
                    className="text-xs px-2.5 py-1 rounded font-semibold transition-colors bg-slate-200 hover:bg-slate-300 text-slate-700 shadow-sm shrink-0"
                  >
                    Cancel
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
