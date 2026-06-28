import type { VisionParseResult, UnifiedIssue, AgentMap } from '../types';

export interface RunHistoryItem {
  id: string;
  timestamp: string;
  sketchThumbnail: string;
  previewThumbnail?: string;
  summary: string;
  code: string;
  vision: VisionParseResult | null;
  issues: UnifiedIssue[];
  agents: AgentMap;
}

interface Props {
  history: RunHistoryItem[];
  activeId: string | null;
  onSelect: (item: RunHistoryItem) => void;
}

export default function HistoryBar({ history, activeId, onSelect }: Props) {
  if (history.length === 0) return null;

  return (
    <div className="bg-white border-t border-slate-200 shrink-0 select-none shadow-sm">
      <div className="px-3.5 py-1.5 bg-slate-50 border-b border-slate-150 flex items-center justify-between">
        <span className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse" />
          Generation History ({history.length})
        </span>
        <span className="text-[9px] text-slate-400 font-medium italic">
          Click any tile to instantly restore that run's design & state
        </span>
      </div>
      <div className="flex gap-3 overflow-x-auto py-2.5 px-3.5 scrollbar-thin scrollbar-thumb-slate-200 scrollbar-track-transparent">
        {history.map(item => {
          const isActive = item.id === activeId;
          return (
            <button
              key={item.id}
              onClick={() => onSelect(item)}
              className={`flex items-center gap-3 shrink-0 p-1.5 rounded-lg border text-left transition-all duration-200 w-64 max-w-xs group relative
                ${
                  isActive
                    ? 'bg-indigo-50/50 border-indigo-500 shadow-sm ring-1 ring-indigo-500/30'
                    : 'bg-slate-50 hover:bg-white border-slate-200 hover:border-indigo-300 hover:shadow-sm'
                }
              `}
            >
              {/* Sketch Thumbnail */}
              <div className="w-10 h-10 rounded bg-slate-200 overflow-hidden shrink-0 border border-slate-200/60 shadow-inner relative flex items-center justify-center">
                <img
                  src={item.sketchThumbnail}
                  alt="Sketch"
                  className="w-full h-full object-cover transition-transform group-hover:scale-105"
                />
              </div>

              {/* Text metadata */}
              <div className="flex-1 min-w-0 pr-1">
                <div className="flex items-center justify-between gap-1 mb-0.5">
                  <span className="text-[9px] font-extrabold text-indigo-600/90 uppercase tracking-wide truncate">
                    {item.summary}
                  </span>
                  <span className="text-[8px] font-mono text-slate-400 shrink-0">
                    {item.timestamp}
                  </span>
                </div>
                <p className="text-[10px] text-slate-500 truncate font-medium">
                  {item.vision?.screen_title || 'Restored Component Layout'}
                </p>
              </div>

              {/* Active Badge indicator */}
              {isActive && (
                <span className="absolute top-1 right-1 flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
