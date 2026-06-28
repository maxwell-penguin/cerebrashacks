import { useCallback, useEffect, useRef, useState } from 'react';
import type { VisionComponent, VisionParseResult } from '../types';

interface Props {
  inputMode: 'sketch' | 'text';
  setInputMode: (mode: 'sketch' | 'text') => void;
  description: string;
  setDescription: (desc: string) => void;
  onImage: (base64: string, mimeType: string) => void;
  vision: VisionParseResult | null;
  disabled: boolean;
  previewUrl?: string | null;
}

export default function UploadPane({
  inputMode,
  setInputMode,
  description,
  setDescription,
  onImage,
  vision,
  disabled,
  previewUrl = null,
}: Props) {
  const [preview, setPreview] = useState<string | null>(previewUrl);
  const [dragging, setDragging] = useState(false);
  const [imgSize, setImgSize] = useState<{ w: number; h: number } | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setPreview(previewUrl);
  }, [previewUrl]);

  const [error, setError] = useState<string | null>(null);

  const handleFile = useCallback(
    (file: File) => {
      if (!file.type.startsWith('image/')) {
        setError('Please upload an image file (JPG, PNG).');
        return;
      }
      setError(null);
      const reader = new FileReader();
      reader.onload = e => {
        const dataUri = e.target?.result as string;
        setPreview(dataUri);
        onImage(dataUri, file.type || 'image/jpeg');
      };
      reader.readAsDataURL(file);
    },
    [onImage],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const onImgLoad = () => {
    if (imgRef.current) {
      setImgSize({ w: imgRef.current.offsetWidth, h: imgRef.current.offsetHeight });
    }
  };

  const components: VisionComponent[] = vision?.components ?? [];

  return (
    <div className="flex flex-col h-full bg-slate-100 border-r border-slate-200 overflow-hidden">
      {/* Input Mode Toggle tabs */}
      <div className="flex border-b border-slate-200 bg-slate-50 p-1.5 gap-1.5 select-none shrink-0">
        <button
          type="button"
          disabled={disabled}
          onClick={() => setInputMode('sketch')}
          className={`flex-1 text-[10px] font-extrabold py-2 px-1 rounded transition-all uppercase tracking-wider text-center ${
            inputMode === 'sketch'
              ? 'bg-white text-indigo-600 shadow-sm border border-slate-200/50'
              : 'text-slate-500 hover:text-slate-800'
          } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
        >
          🖼️ Sketch
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={() => setInputMode('text')}
          className={`flex-1 text-[10px] font-extrabold py-2 px-1 rounded transition-all uppercase tracking-wider text-center ${
            inputMode === 'text'
              ? 'bg-white text-indigo-600 shadow-sm border border-slate-200/50'
              : 'text-slate-500 hover:text-slate-800'
          } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
        >
          ✍️ Describe
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3 min-h-0">
        {inputMode === 'sketch' ? (
          <>
            {/* Drop zone */}
            <div
              className={`relative rounded-xl border-2 border-dashed transition-all cursor-pointer shadow-sm
                ${dragging ? 'border-indigo-400 bg-indigo-50/50' : 'border-slate-300 hover:border-indigo-300 bg-white hover:bg-slate-50/50'}
                ${disabled ? 'pointer-events-none opacity-50' : ''}
              `}
              onDragOver={e => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => !disabled && inputRef.current?.click()}
            >
              {preview ? (
                <div className="relative">
                  <img
                    ref={imgRef}
                    src={preview}
                    alt="Uploaded sketch"
                    className="w-full rounded-xl object-contain"
                    onLoad={onImgLoad}
                  />
                  {/* Bounding box overlay */}
                  {imgSize && components.length > 0 && (
                    <svg
                      className="absolute inset-0 w-full h-full"
                      viewBox={`0 0 ${imgSize.w} ${imgSize.h}`}
                      style={{ pointerEvents: 'none' }}
                    >
                      {components.map((c, i) => {
                        // coords may be 0-1 normalized or pixel coords
                        const maxCoord = Math.max(c.x + c.width, c.y + c.height);
                        const scale = maxCoord <= 1.5 ? imgSize.w : 1;
                        const x = c.x * scale;
                        const y = c.y * scale;
                        const w = c.width * scale;
                        const h = c.height * scale;
                        if (w < 2 || h < 2) return null;
                        return (
                          <g key={i}>
                            <rect
                              x={x} y={y} width={w} height={h}
                              fill="rgba(79,70,229,0.06)"
                              stroke="#4f46e5"
                              strokeWidth="1.5"
                              rx="3"
                            />
                            <rect x={x} y={y - 16} width={Math.max(w, 60)} height={16} fill="#4f46e5" rx="2" />
                            <text x={x + 4} y={y - 4} fill="#ffffff" fontSize="10" fontFamily="monospace" fontWeight="bold">
                              {c.label || c.type}
                            </text>
                          </g>
                        );
                      })}
                    </svg>
                  )}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
                  <div className="text-4xl mb-3">✏️</div>
                  <p className="text-sm text-slate-700 font-semibold">Drop your sketch here</p>
                  <p className="text-xs text-slate-400 mt-1">or click to browse</p>
                </div>
              )}
            </div>

            <input
              ref={inputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
            />

            {error && (
              <div className="text-rose-500 text-xs font-semibold px-2.5 py-1.5 bg-rose-50 border border-rose-100 rounded-lg flex items-center gap-1.5 shadow-sm">
                <span>⚠️</span>
                <span>{error}</span>
              </div>
            )}

             {/* Demo Sketch Quick-loaders (for testing & presentation) */}
            {!preview && (
              <div className="flex flex-col gap-2 w-full shrink-0">
                <div className="flex gap-2 w-full">
                  <button
                    type="button"
                    id="mock-sketch-btn-1"
                    onClick={async (e) => {
                      e.stopPropagation();
                      setError(null);
                      try {
                        const res = await fetch('/test_sketch.jpg');
                        const blob = await res.blob();
                        const reader = new FileReader();
                        reader.onloadend = () => {
                          const dataUrl = reader.result as string;
                          onImage(dataUrl, 'image/jpeg');
                        };
                        reader.readAsDataURL(blob);
                      } catch (err) {
                        console.error('Failed to load test sketch 1', err);
                      }
                    }}
                    className="flex-1 text-[10px] font-bold py-1.5 px-2 bg-indigo-50/70 hover:bg-indigo-100/70 text-indigo-700 border border-indigo-200/50 rounded transition-all shadow-sm"
                  >
                    🖼️ Login Sketch
                  </button>
                  <button
                    type="button"
                    id="mock-sketch-btn-2"
                    onClick={async (e) => {
                      e.stopPropagation();
                      setError(null);
                      try {
                        const res = await fetch('/test_sketch_dashboard.jpg');
                        const blob = await res.blob();
                        const reader = new FileReader();
                        reader.onloadend = () => {
                          const dataUrl = reader.result as string;
                          onImage(dataUrl, 'image/jpeg');
                        };
                        reader.readAsDataURL(blob);
                      } catch (err) {
                        console.error('Failed to load test sketch 2', err);
                      }
                    }}
                    className="flex-1 text-[10px] font-bold py-1.5 px-2 bg-indigo-50/70 hover:bg-indigo-100/70 text-indigo-700 border border-indigo-200/50 rounded transition-all shadow-sm"
                  >
                    🖼️ Dashboard Sketch
                  </button>
                </div>
                <button
                  type="button"
                  id="mock-sketch-btn-3"
                  onClick={async (e) => {
                    e.stopPropagation();
                    setError(null);
                    try {
                      const res = await fetch('/test_sketch_list.jpg');
                      const blob = await res.blob();
                      const reader = new FileReader();
                      reader.onloadend = () => {
                        const dataUrl = reader.result as string;
                        onImage(dataUrl, 'image/jpeg');
                      };
                      reader.readAsDataURL(blob);
                    } catch (err) {
                      console.error('Failed to load test sketch 3', err);
                    }
                  }}
                  className="w-full text-[10px] font-bold py-1.5 px-2 bg-indigo-50/70 hover:bg-indigo-100/70 text-indigo-700 border border-indigo-200/50 rounded transition-all shadow-sm"
                >
                  🖼️ List Sketch
                </button>
              </div>
            )}
          </>
        ) : (
          <div className="flex-1 flex flex-col min-h-0 bg-white rounded-xl border border-slate-200 p-3 shadow-sm focus-within:border-indigo-400 focus-within:ring-1 focus-within:ring-indigo-400 transition-all">
            <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5 select-none">
              App Specification
            </label>
            <textarea
              disabled={disabled}
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Describe the app you want, e.g. a dashboard with a sidebar, two stat cards, and a chart area..."
              className="flex-1 w-full text-xs text-slate-800 placeholder:text-slate-400 focus:outline-none resize-none bg-transparent leading-relaxed"
            />
          </div>
        )}

        {/* Vision output summary */}
        {inputMode === 'sketch' && vision && (
          <div className="rounded-lg bg-white border border-slate-200 p-3 text-xs space-y-1.5 shadow-sm">
            <p className="font-bold text-slate-800">{vision.screen_title}</p>
            <p className="text-slate-500 font-medium">{components.length} component{components.length !== 1 ? 's' : ''} detected</p>
            {vision.notes && <p className="text-slate-400 italic text-[11px]">{vision.notes}</p>}
            <ul className="mt-2 space-y-1 border-t border-slate-100 pt-1.5">
              {components.map((c, i) => (
                <li key={i} className="text-slate-600 flex items-center justify-between">
                  <span className="text-indigo-600 font-semibold">{c.type}</span>
                  {c.label ? <span className="text-slate-400 text-[11px]">{c.label}</span> : ''}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
