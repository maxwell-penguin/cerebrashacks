import { useState } from 'react';
import type { UnifiedIssue } from '../types';

interface Props {
  issues: UnifiedIssue[];
}

export default function IssuesPanel({ issues }: Props) {
  const [isOpen, setIsOpen] = useState(true);

  // Group issues by agent
  const grouped = issues.reduce((acc, issue) => {
    if (!acc[issue.agent]) {
      acc[issue.agent] = [];
    }
    acc[issue.agent].push(issue);
    return acc;
  }, {} as Record<string, UnifiedIssue[]>);

  const getSeverityBadgeClass = (severity: 'error' | 'warn' | 'info') => {
    switch (severity) {
      case 'error':
        return 'bg-rose-100 text-rose-800 border-rose-200/80';
      case 'warn':
        return 'bg-amber-100 text-amber-800 border-amber-200/80';
      case 'info':
        return 'bg-sky-100 text-sky-800 border-sky-200/80';
      default:
        return 'bg-slate-100 text-slate-600 border-slate-200';
    }
  };

  return (
    <div className="flex flex-col border-t border-slate-200 bg-slate-100 shadow-lg">
      {/* Header bar */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-3.5 py-2.5 bg-slate-200/50 hover:bg-slate-200/80 border-b border-slate-200 transition-colors select-none text-left shadow-sm z-10"
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-slate-600 uppercase tracking-wider">
            {issues.length > 0 ? '⚠️' : '✨'} Issues
          </span>
          <span className={`text-[10px] font-semibold font-mono px-1.5 py-0.5 rounded border ${
            issues.length > 0
              ? 'bg-amber-100 text-amber-800 border-amber-200/60'
              : 'bg-emerald-100 text-emerald-800 border-emerald-200/60'
          }`}>
            {issues.length}
          </span>
        </div>
        <span className="text-slate-550 text-xs font-bold font-mono">
          {isOpen ? '▼' : '▲'}
        </span>
      </button>

      {/* Collapsible Content */}
      {isOpen && (
        <div className="flex-1 overflow-y-auto max-h-72 p-3 space-y-3 min-h-0 bg-slate-50">
          {issues.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-6 text-center text-slate-450">
              <span className="text-2xl mb-1.5 animate-bounce">✨</span>
              <p className="text-xs font-bold text-slate-700">No issues found</p>
              <p className="text-[10px] text-slate-400 mt-0.5">Clean build & visual QA!</p>
            </div>
          ) : (
            Object.entries(grouped).map(([agent, agentIssues]) => (
              <div key={agent} className="space-y-1.5 animate-fade-in">
                {/* Agent Group Title */}
                <div className="text-[10px] font-extrabold text-slate-500 uppercase tracking-wider px-1">
                  {agent}
                </div>
                {/* Issues List */}
                <div className="space-y-1.5">
                  {agentIssues.map((issue, idx) => (
                    <div
                      key={idx}
                      className="text-xs rounded-lg p-2.5 bg-white border border-slate-200 flex flex-col gap-1.5 hover:border-slate-300 shadow-sm transition-all hover:shadow-md"
                    >
                      <div className="flex items-start justify-between gap-2">
                        {/* Description */}
                        <p className="text-slate-700 leading-normal flex-1 font-medium">
                          {issue.description}
                        </p>
                        {/* Severity Pill */}
                        <span className={`text-[9px] font-extrabold uppercase tracking-wider px-1.5 py-0.5 rounded border shrink-0 ${getSeverityBadgeClass(issue.severity)}`}>
                          {issue.severity}
                        </span>
                      </div>
                      {/* Code Region if present */}
                      {issue.code_region && (
                        <div className="mt-0.5">
                          <code className="text-[10px] text-slate-600 font-semibold font-mono bg-slate-100 px-1.5 py-0.5 rounded break-all border border-slate-200 inline-block shadow-sm">
                            {issue.code_region}
                          </code>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
