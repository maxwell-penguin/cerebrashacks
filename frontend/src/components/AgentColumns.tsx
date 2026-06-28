import { useState } from 'react';
import type { AgentMap, AgentName, AgentStatus, UnifiedIssue } from '../types';

const AGENTS: { name: AgentName; label: string; icon: string }[] = [
  { name: 'vision_parser', label: 'Vision', icon: '👁' },
  { name: 'architect', label: 'Architect', icon: '🏗' },
  { name: 'code_forge', label: 'Code Forge', icon: '⚡' },
  { name: 'auditor', label: 'Auditor', icon: '🔍' },
  { name: 'accessibility', label: 'A11y', icon: '♿' },
  { name: 'vision_critic', label: 'Critic', icon: '🎨' },
];

const STATUS_CONFIG: Record<AgentStatus, { bg: string; text: string; label: string; pulse: boolean }> = {
  idle:      { bg: 'bg-white border-slate-200', text: 'text-slate-500', label: 'idle',      pulse: false },
  thinking:  { bg: 'bg-purple-100/70 border-purple-200', text: 'text-purple-800',  label: 'thinking', pulse: true  },
  streaming: { bg: 'bg-blue-100/70 border-blue-200',  text: 'text-blue-800',   label: 'streaming',pulse: true  },
  done:      { bg: 'bg-emerald-100/70 border-emerald-200',text: 'text-emerald-800',label: 'done',     pulse: false },
  error:     { bg: 'bg-rose-100/70 border-rose-200',   text: 'text-rose-800 font-bold',    label: 'error',    pulse: false },
  skipped:   { bg: 'bg-slate-200/50 border-slate-200', text: 'text-slate-500',  label: 'skipped',  pulse: false },
  warn:      { bg: 'bg-amber-100/75 border-amber-200',text: 'text-amber-800 font-bold', label: 'warn',     pulse: false },
};

// Cards default to collapsed; warn/error auto-expand
function defaultExpanded(status: AgentStatus): boolean {
  return status === 'warn' || status === 'error';
}

const StatusDot = ({ status }: { status: AgentStatus }) => {
  const { text, pulse } = STATUS_CONFIG[status];
  const dotColor = text.split(' ')[0].replace('text-', 'bg-');
  return (
    <span className={`inline-block w-2 h-2 rounded-full mr-1.5 ${dotColor} ${pulse ? 'animate-pulse' : ''}`} />
  );
};

interface Props {
  agents: AgentMap;
  tps: number | null;
  issues: UnifiedIssue[];
  onRerunQA?: () => void;
  onAutoRefine?: () => void;
  isRefining?: boolean;
}

export default function AgentColumns({ agents, tps, issues, onRerunQA, onAutoRefine, isRefining }: Props) {
  const criticIssues = issues.filter(i => i.agent === 'Critic');

  // Track expanded state per agent; initialise lazily on first interaction
  const [expanded, setExpanded] = useState<Partial<Record<AgentName, boolean>>>({});

  const isExpanded = (name: AgentName, status: AgentStatus) => {
    if (name in expanded) return expanded[name]!;
    return defaultExpanded(status);
  };

  const toggle = (name: AgentName, status: AgentStatus) => {
    setExpanded(prev => ({ ...prev, [name]: !isExpanded(name, status) }));
  };

  return (
    <div className="flex flex-col h-full bg-slate-100 border-l border-slate-200 overflow-hidden">
      <div className="px-3 py-2 border-b border-slate-200 bg-slate-50 flex items-center justify-between shadow-sm z-10">
        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Agents</span>
        {tps !== null && (
          <span className="text-xs font-mono font-semibold text-indigo-700 bg-indigo-100/80 border border-indigo-200 px-2 py-0.5 rounded">
            {tps.toFixed(1)} tok/s
          </span>
        )}
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
        {AGENTS.map(({ name, label, icon }) => {
          const { status, message } = agents[name];
          const cfg = STATUS_CONFIG[status];
          const open = isExpanded(name, status);

          return (
            <div
              key={name}
              className={`rounded-lg border transition-colors duration-300 shadow-sm overflow-hidden ${cfg.bg}`}
            >
              {/* Compact row — always visible */}
              <button
                type="button"
                onClick={() => toggle(name, status)}
                className="w-full flex items-center justify-between px-3 py-2 text-left"
              >
                <span className="text-sm font-semibold flex items-center gap-1.5">
                  <span>{icon}</span>
                  <span className="text-slate-800">{label}</span>
                </span>
                <div className="flex items-center gap-1.5">
                  <span className={`text-[10px] font-bold flex items-center uppercase tracking-wide ${cfg.text}`}>
                    <StatusDot status={status} />
                    {cfg.label}
                  </span>
                  <span className="text-slate-400 text-[10px] font-mono">{open ? '▴' : '▾'}</span>
                </div>
              </button>

              {/* Expanded detail */}
              {open && (
                <div className="px-3 pb-2.5 flex flex-col gap-1.5 border-t border-black/5">
                  {message && (
                    <p className="text-xs text-slate-600 mt-1.5 leading-relaxed line-clamp-4">
                      {message}
                    </p>
                  )}
                  {name === 'vision_critic' && criticIssues.length > 0 && (
                    <p className="text-[10px] font-semibold text-slate-500">
                      {criticIssues.length} issue{criticIssues.length !== 1 ? 's' : ''} found
                    </p>
                  )}
                  {name === 'vision_critic' && ['done', 'warn', 'error'].includes(status) && onRerunQA && (
                    <div className="flex gap-1.5 mt-1">
                      <button
                        disabled={isRefining}
                        onClick={(e) => {
                          e.stopPropagation();
                          onRerunQA();
                        }}
                        className="text-[10px] flex-1 py-1.5 px-2 rounded bg-white hover:bg-slate-50 disabled:opacity-50 text-slate-700 font-bold transition-all border border-slate-300/80 flex items-center justify-center gap-1 shadow-sm active:scale-[0.98]"
                      >
                        🔄 Re-run
                      </button>
                      {onAutoRefine && (
                        <button
                          disabled={isRefining}
                          onClick={(e) => {
                            e.stopPropagation();
                            onAutoRefine();
                          }}
                          className="text-[10px] flex-1 py-1.5 px-2 rounded bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-bold transition-all border border-indigo-700 flex items-center justify-center gap-1 shadow-sm active:scale-[0.98]"
                        >
                          ⚡ {isRefining ? 'Refining...' : 'Auto-refine'}
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
