import { useCallback, useEffect, useRef, useState } from 'react';
import AgentColumns from './components/AgentColumns';
import ChatPanel from './components/ChatPanel';
import EditorPane from './components/EditorPane';
import LandingScreen from './components/LandingScreen';
import UploadPane from './components/UploadPane';
import IssuesPanel from './components/IssuesPanel';
import HistoryBar, { RunHistoryItem } from './components/HistoryBar';
import { usePipeline } from './hooks/usePipeline';

const WS_URL = 'ws://localhost:8000/ws';

export default function App() {
  const [showLanding, setShowLanding] = useState(true);

  if (showLanding) {
    return <LandingScreen onGetStarted={() => setShowLanding(false)} />;
  }

  return <Studio />;
}

function Studio() {
  const {
    state,
    setState,
    run,
    reset,
    updateFinalCode,
    rerunVisualCheck,
    autoRefine,
    isRefining,
    refineRegion,
  } = usePipeline(WS_URL);
  const [description, setDescription] = useState('');
  const [pendingImage, setPendingImage] = useState<{ base64: string; mime: string } | null>(null);
  const [rightTab, setRightTab] = useState<'issues' | 'chat'>('chat');
  const [inputMode, setInputMode] = useState<'sketch' | 'text'>('sketch');
  
  const [history, setHistory] = useState<RunHistoryItem[]>([]);
  const [activeHistoryId, setActiveHistoryId] = useState<string | null>(null);
  const isRecordingRun = useRef<boolean>(false);

  const handleImage = useCallback((base64: string, mimeType: string) => {
    setPendingImage({ base64, mime: mimeType });
  }, []);

  const handleGenerate = () => {
    isRecordingRun.current = true;
    if (inputMode === 'sketch') {
      if (!pendingImage) return;
      run(pendingImage.base64, pendingImage.mime, description);
    } else {
      run(null, null, description);
    }
  };

  const handleReset = () => {
    reset();
    setPendingImage(null);
    setDescription('');
    setActiveHistoryId(null);
    setInputMode('sketch');
  };

  // Capture run history after pipeline + visual QA completes successfully
  useEffect(() => {
    const isQAThinking = state.agents['vision_critic']?.status === 'thinking';
    if (state.phase === 'done' && state.finalCode && isRecordingRun.current && !isQAThinking) {
      isRecordingRun.current = false;
      const now = new Date();
      const timestamp = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

      const componentCount = state.vision?.components?.length ?? 0;
      const summary = componentCount > 0
        ? `${componentCount} components`
        : (description.trim() || 'Custom run');

      const newRun: RunHistoryItem = {
        id: `run-${Date.now()}`,
        timestamp,
        sketchThumbnail: pendingImage?.base64 || '',
        summary,
        code: state.finalCode,
        vision: state.vision,
        issues: state.issues,
        agents: state.agents,
      };

      setHistory(prev => [newRun, ...prev]);
      setActiveHistoryId(newRun.id);
    }
  }, [state.phase, state.finalCode, state.vision, state.issues, state.agents, description, pendingImage, reset]);

  const handleSelectHistory = useCallback((item: RunHistoryItem) => {
    setActiveHistoryId(item.id);
    setPendingImage(item.sketchThumbnail ? { base64: item.sketchThumbnail, mime: 'image/png' } : null);
    setInputMode(item.sketchThumbnail ? 'sketch' : 'text');
    setState({
      phase: 'done',
      agents: item.agents,
      streamingCode: '',
      finalCode: item.code,
      vision: item.vision,
      errorMsg: '',
      tps: null,
      issues: item.issues,
    });
  }, [setState]);

  const isRunning = state.phase === 'running';
  const isDone = state.phase === 'done';
  const isError = state.phase === 'error';

  // Build chat context from current pipeline state
  return (
    <div className="flex flex-col h-screen bg-slate-50 text-slate-700">
      {/* Header */}
      <header className="shrink-0 flex items-center justify-between px-4 py-2.5 bg-white border-b border-slate-200 shadow-sm z-10">
        <div className="flex items-center gap-3">
          <div className="flex flex-col leading-tight">
            <span className="text-lg font-bold tracking-tight text-slate-800">⚡ SketchStorm Studio</span>
            <span className="text-[10px] text-slate-400 font-medium tracking-wide">Sketch it. Watch six AI agents build it live.</span>
          </div>
          <span className="text-[10px] font-bold px-2 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-700 flex items-center gap-1 shrink-0">
            ⚡ Powered by Gemma 4 on Cerebras
          </span>
        </div>

        <div className="flex items-center gap-2">
          {(isDone || isError) && (
            <button
              onClick={handleReset}
              className="text-xs px-3 py-1.5 rounded bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 shadow-sm transition-colors"
            >
              New
            </button>
          )}

          <button
            onClick={handleGenerate}
            disabled={isRunning || (inputMode === 'sketch' ? !pendingImage : !description.trim())}
            className="text-xs px-4 py-1.5 rounded font-semibold transition-colors
                       bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed text-white shadow-sm"
          >
            {isRunning ? 'Running…' : 'Generate'}
          </button>
        </div>

        {/* Status badge */}
        {isRunning && (
          <div className="flex items-center gap-1.5 text-xs font-semibold text-blue-700 bg-blue-100/60 border border-blue-200 px-2.5 py-1 rounded-full">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
            Pipeline running
          </div>
        )}
        {isDone && (
          <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-700 bg-emerald-100/60 border border-emerald-200 px-2.5 py-1 rounded-full">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            Complete
          </div>
        )}
        {isError && (
          <div className="flex items-center gap-1.5 text-xs font-semibold text-rose-700 bg-rose-100/60 border border-rose-200 px-2.5 py-1 rounded-full" title={state.errorMsg}>
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
            {state.errorMsg || 'Error'}
          </div>
        )}
      </header>

      {/* Three-pane layout */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: upload + vision overlay */}
        <div className="w-72 shrink-0 overflow-hidden">
          <UploadPane
            inputMode={inputMode}
            setInputMode={setInputMode}
            description={description}
            setDescription={setDescription}
            onImage={handleImage}
            vision={state.vision}
            disabled={isRunning}
            previewUrl={pendingImage?.base64 || null}
          />
        </div>

        {/* Center: Monaco editor + iframe preview */}
        <div className="flex-1 overflow-hidden">
          <EditorPane
            streamingCode={state.streamingCode}
            finalCode={state.finalCode}
            onChangeCode={updateFinalCode}
            criticState={state.agents['vision_critic']}
            isRunning={isRunning}
            refineRegion={refineRegion}
            errorMsg={state.errorMsg}
          />
        </div>

        {/* Right: agent columns + tabs (Issues / Chat) */}
        <div className="w-80 shrink-0 border-l border-slate-200 flex flex-col bg-slate-100 overflow-hidden">
          <div className="flex-1 min-h-0">
            <AgentColumns
              agents={state.agents}
              tps={state.tps}
              issues={state.issues}
              onRerunQA={() => rerunVisualCheck(state.finalCode)}
              onAutoRefine={() => autoRefine(state.finalCode, description)}
              isRefining={isRefining}
            />
          </div>

          {/* Tab bar */}
          <div className="flex border-t border-slate-200 bg-slate-50 shrink-0 select-none">
            <button
              onClick={() => setRightTab('chat')}
              className={`flex-1 text-[11px] font-bold py-2 transition-colors uppercase tracking-wider ${
                rightTab === 'chat'
                  ? 'text-indigo-600 border-b-2 border-indigo-600 bg-white font-extrabold'
                  : 'text-slate-500 hover:text-slate-700 hover:bg-slate-100'
              }`}
            >
              💬 Co-pilot
            </button>
            <button
              onClick={() => setRightTab('issues')}
              className={`flex-1 text-[11px] font-bold py-2 transition-colors uppercase tracking-wider flex items-center justify-center gap-1.5 ${
                rightTab === 'issues'
                  ? 'text-indigo-600 border-b-2 border-indigo-600 bg-white font-extrabold'
                  : 'text-slate-500 hover:text-slate-700 hover:bg-slate-100'
              }`}
            >
              <span>⚠️ Issues</span>
              <span className={`text-[9px] font-mono px-1 rounded-full ${
                state.issues.length > 0 ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-800'
              }`}>
                {state.issues.length}
              </span>
            </button>
          </div>

          {/* Tab content */}
          <div className="shrink-0 flex flex-col min-h-0">
            {rightTab === 'issues' ? (
              <IssuesPanel issues={state.issues} />
            ) : (
              <ChatPanel
                apiBase={WS_URL.replace(/^ws:/, 'http:').replace(/^wss:/, 'https:').replace(/\/ws$/, '')}
                vision={state.vision}
                finalCode={state.finalCode}
              />
            )}
          </div>
        </div>
      </div>

      <HistoryBar
        history={history}
        activeId={activeHistoryId}
        onSelect={handleSelectHistory}
      />
    </div>
  );
}
