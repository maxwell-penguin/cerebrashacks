import { useCallback, useEffect, useRef, useState } from 'react';
import { MessageSquare, AlertTriangle, Clock } from 'lucide-react';
import AgentColumns from './components/AgentColumns';
import ChatPanel from './components/ChatPanel';
import EditorPane from './components/EditorPane';
import LandingScreen from './components/LandingScreen';
import UploadPane from './components/UploadPane';
import IssuesPanel from './components/IssuesPanel';
import HistoryBar, { RunHistoryItem } from './components/HistoryBar';
import DesignHistory from './components/DesignHistory';
import { usePipeline } from './hooks/usePipeline';
import { useResize } from './hooks/useResize';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
const WS_URL = API_BASE.replace(/^http/, 'ws') + '/ws';

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
    cancelOperation,
  } = usePipeline(WS_URL);
  const [description, setDescription] = useState('');
  const [pendingImage, setPendingImage] = useState<{ base64: string; mime: string } | null>(null);
  const [rightTab, setRightTab] = useState<'issues' | 'chat' | 'history'>('chat');
  const [inputMode, setInputMode] = useState<'sketch' | 'text'>('sketch');
  
  const [history, setHistory] = useState<RunHistoryItem[]>([]);
  const [activeHistoryId, setActiveHistoryId] = useState<string | null>(null);
  const isRecordingRun = useRef<boolean>(false);

  // Design edit history
  const [designEdits, setDesignEdits] = useState<Array<{
    id: string;
    region: string;
    prompt: string;
    mode: string;
    time: string;
  }>>([]);
  const addDesignEdit = useCallback((region: string, prompt: string, mode: string) => {
    const now = new Date();
    const time = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    setDesignEdits(prev => [{ id: `edit-${Date.now()}`, region, prompt, mode, time }, ...prev]);
  }, []);

  // Resizable panels
  const leftPanel = useResize(288, 200, 500, 'x');   // default 288px (w-72)
  const rightPanel = useResize(320, 220, 600, 'x', true);  // invert: drag right = right panel wider
  const copilotHeight = useResize(180, 100, 500, 'y', true); // invert: handle on top edge

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
            aria-label={isRunning ? 'Pipeline running' : 'Generate app from sketch'}
          >
            {isRunning ? 'Running…' : 'Generate'}
          </button>
        </div>

        {/* Status badge */}
        {isRunning && (
          <div className="flex items-center gap-1.5 text-xs font-semibold text-blue-700 bg-blue-100/60 border border-blue-200 px-2.5 py-1 rounded-full" role="status">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
            Pipeline running
          </div>
        )}
        {isDone && (
          <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-700 bg-emerald-100/60 border border-emerald-200 px-2.5 py-1 rounded-full" role="status">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            Complete
          </div>
        )}
        {isError && (
          <div className="flex items-center gap-1.5 text-xs font-semibold text-rose-700 bg-rose-100/60 border border-rose-200 px-2.5 py-1 rounded-full" title={state.errorMsg} role="alert">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
            {state.errorMsg || 'Error'}
          </div>
        )}
      </header>

      {/* Three-pane layout */}
      <div className="flex flex-1" style={{ overflow: 'clip' }}>
        {/* Left: upload + vision overlay */}
        <div className="shrink-0 overflow-hidden" style={{ width: leftPanel.value }}>
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

        {/* Resize handle: left | center */}
        <div
          {...leftPanel.handleProps}
          className="w-1 shrink-0 bg-slate-200 hover:bg-indigo-400 cursor-col-resize transition-colors active:bg-indigo-500 z-20"
        />

        {/* Center: Monaco editor + iframe preview */}
        <div className="flex-1 overflow-hidden min-w-0">
          <EditorPane
            streamingCode={state.streamingCode}
            finalCode={state.finalCode}
            onChangeCode={updateFinalCode}
            criticState={state.agents['vision_critic']}
            isRunning={isRunning}
            refineRegion={refineRegion}
            cancelRefine={cancelOperation}
            onDesignEdit={addDesignEdit}
            errorMsg={state.errorMsg}
          />
        </div>

        {/* Resize handle: center | right sidebar */}
        <div
          {...rightPanel.handleProps}
          className="w-1 shrink-0 bg-slate-200 hover:bg-indigo-400 cursor-col-resize transition-colors active:bg-indigo-500 z-20"
        />

        {/* Right: agent columns + chat/issues */}
        <div className="shrink-0 border-l border-slate-200 flex flex-col bg-slate-100" style={{ width: rightPanel.value }}>
          <div className="flex-1 min-h-0 overflow-hidden">
            <AgentColumns
              agents={state.agents}
              tps={state.tps}
              issues={state.issues}
              onRerunQA={() => rerunVisualCheck(state.finalCode)}
              onAutoRefine={() => autoRefine(state.finalCode, description)}
              onCancelRefine={cancelOperation}
              isRefining={isRefining}
            />
          </div>

          {/* Resize handle: agents | chat */}
          <div
            {...copilotHeight.handleProps}
            className="h-1 shrink-0 bg-slate-200 hover:bg-indigo-400 cursor-row-resize transition-colors active:bg-indigo-500 z-20"
          />

          {/* Tab bar + content (resizable) */}
          <div className="shrink-0 flex flex-col overflow-hidden" style={{ height: copilotHeight.value }}>
            <div className="flex border-t border-slate-200 bg-slate-50 shrink-0 select-none">
              <button
                onClick={() => setRightTab('chat')}
                className={`flex-1 text-[11px] font-bold py-2 transition-colors uppercase tracking-wider ${
                  rightTab === 'chat'
                    ? 'text-indigo-600 border-b-2 border-indigo-600 bg-white font-extrabold'
                    : 'text-slate-500 hover:text-slate-700 hover:bg-slate-100'
                }`}
              >
                <div className="flex items-center justify-center gap-1.5">
                  <MessageSquare className="w-3.5 h-3.5" />
                  <span>Co-pilot</span>
                </div>
              </button>
              <button
                onClick={() => setRightTab('issues')}
                className={`flex-1 text-[11px] font-bold py-2 transition-colors uppercase tracking-wider flex items-center justify-center gap-1.5 ${
                  rightTab === 'issues'
                    ? 'text-indigo-600 border-b-2 border-indigo-600 bg-white font-extrabold'
                    : 'text-slate-500 hover:text-slate-700 hover:bg-slate-100'
                }`}
              >
                <div className="flex items-center justify-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
                  <span>Issues</span>
                  {state.issues.length > 0 && (
                    <span className="text-[9px] font-mono px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-800 font-bold">
                      {state.issues.length}
                    </span>
                  )}
                </div>
              </button>
              <button
                onClick={() => setRightTab('history')}
                className={`flex-1 text-[11px] font-bold py-2 transition-colors uppercase tracking-wider flex items-center justify-center gap-1.5 ${
                  rightTab === 'history'
                    ? 'text-indigo-600 border-b-2 border-indigo-600 bg-white font-extrabold'
                    : 'text-slate-500 hover:text-slate-700 hover:bg-slate-100'
                }`}
              >
                <div className="flex items-center justify-center gap-1.5">
                  <Clock className="w-3.5 h-3.5" />
                  <span>History</span>
                  {designEdits.length > 0 && (
                    <span className="text-[9px] font-mono px-1.5 py-0.5 rounded-full bg-slate-200 text-slate-600 font-bold">
                      {designEdits.length}
                    </span>
                  )}
                </div>
              </button>
            </div>
            <div className="flex-1 min-h-0 overflow-hidden">
              {rightTab === 'history' ? (
                <DesignHistory edits={designEdits} />
              ) : rightTab === 'issues' ? (
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
      </div>

      <HistoryBar
        history={history}
        activeId={activeHistoryId}
        onSelect={handleSelectHistory}
      />
    </div>
  );
}
