interface DesignEdit {
  id: string;
  region: string;
  prompt: string;
  mode: string;
  time: string;
}

interface Props {
  edits: DesignEdit[];
}

export default function DesignHistory({ edits }: Props) {
  if (edits.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-400 p-4 text-center select-none">
        <span className="text-2xl mb-2">🕒</span>
        <p className="text-xs leading-relaxed">
          No design edits yet. Use <strong>Design Mode</strong> to refine the generated page — each change will appear here.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <div className="px-2 py-2 border-b border-slate-200 bg-slate-50 shrink-0">
        <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
          Edit History
        </span>
      </div>
      <div className="flex-1 overflow-y-auto p-1.5 space-y-1">
        {edits.map((edit) => (
          <div
            key={edit.id}
            className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 shadow-sm"
          >
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-[10px] font-bold text-indigo-600 uppercase tracking-wider">
                {edit.region}
              </span>
              <span className="text-[9px] text-slate-400 font-mono">{edit.time}</span>
            </div>
            <p className="text-[11px] text-slate-700 leading-relaxed line-clamp-2">
              {edit.prompt || <span className="italic text-slate-400">Sketch only</span>}
            </p>
            <span className="text-[9px] text-slate-400 mt-0.5 inline-block">
              {edit.mode === 'draw' ? '✏️ Drawn' : edit.mode === 'upload' ? '📎 Uploaded' : '💬 Described'}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
