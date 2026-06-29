import { useCallback, useRef, useState } from 'react';
import type {
  AgentMap,
  AgentName,
  AgentState,
  AgentStatus,
  UnifiedIssue,
  VisionParseResult,
  VisualCheckResponse,
  WSMessage,
} from '../types';

const AGENT_NAMES: AgentName[] = [
  'vision_parser',
  'architect',
  'code_forge',
  'auditor',
  'accessibility',
  'vision_critic',
];

const defaultAgentState = (): AgentState => ({ status: 'idle', message: '' });

const defaultAgentMap = (): AgentMap =>
  Object.fromEntries(AGENT_NAMES.map(n => [n, defaultAgentState()])) as AgentMap;

export type PipelinePhase = 'idle' | 'running' | 'done' | 'error';

export interface PipelineState {
  phase: PipelinePhase;
  agents: AgentMap;
  streamingCode: string;
  finalCode: string;
  vision: VisionParseResult | null;
  errorMsg: string;
  tps: number | null;
  issues: UnifiedIssue[];
}


export function usePipeline(wsUrl: string) {
  const wsRef = useRef<WebSocket | null>(null);
  const descriptionRef = useRef<string>('');
  const finalCodeRef = useRef<string>('');
  const apiBase = useRef(
    wsUrl.replace(/^ws:/, 'http:').replace(/^wss:/, 'https:').replace(/\/ws$/, ''),
  ).current;
  const [state, setState] = useState<PipelineState>({
    phase: 'idle',
    agents: defaultAgentMap(),
    streamingCode: '',
    finalCode: '',
    vision: null,
    errorMsg: '',
    tps: null,
    issues: [],
  });

  // token arrival tracking for manual TPS computation
  const tokenTimestamps = useRef<number[]>([]);

  const [isRefining, setIsRefining] = useState(false);
  const [refineProgress, setRefineProgress] = useState('');
  const abortControllerRef = useRef<AbortController | null>(null);

  const cancelOperation = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsRefining(false);
    setRefineProgress('');
  }, []);

  const reset = useCallback(() => {
    cancelOperation();
    setState({
      phase: 'idle',
      agents: defaultAgentMap(),
      streamingCode: '',
      finalCode: '',
      vision: null,
      errorMsg: '',
      tps: null,
      issues: [],
    });
    tokenTimestamps.current = [];
    finalCodeRef.current = '';
  }, []);

  const runVisualCheck = useCallback(
    async (code: string, description: string) => {
      const contract =
        description.trim() ||
        'Check for layout alignment, overflow, missing elements, and contrast issues.';
      try {
        const res = await fetch(`${apiBase}/visual-check`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code, design_contract: contract, description }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as VisualCheckResponse;

        // Map Critic issues to UnifiedIssue
        const criticIssues: UnifiedIssue[] = (data.issues || []).map(issue => ({
          agent: 'Critic',
          severity: issue.severity === 'critical' ? 'error' : (issue.severity === 'major' ? 'warn' : 'info'),
          description: issue.description + (issue.suggestion ? ` (Suggestion: ${issue.suggestion})` : ''),
          code_region: issue.category || undefined,
        }));

        setState(prev => {
          const agents = { ...prev.agents };
          const status = data.status || (data.passed ? (data.issues.length > 0 ? 'pass_with_warnings' : 'pass') : 'fail');
          const agentStatus: AgentStatus = status === 'pass' ? 'done' : (status === 'pass_with_warnings' ? 'warn' : 'error');
          const msgText = data.summary || (data.passed ? 'Visual QA: OK' : 'Visual check did not pass');
          agents['vision_critic'] = { status: agentStatus, message: msgText };

          const cleanIssues = (prev.issues || []).filter(i => i.agent !== 'Critic');
          const newIssues = [...cleanIssues, ...criticIssues];

          return { ...prev, agents, issues: newIssues };
        });
      } catch (err) {
        setState(prev => {
          const agents = { ...prev.agents };
          agents['vision_critic'] = {
            status: 'error',
            message: err instanceof Error ? err.message : 'Visual check failed',
          };
          const cleanIssues = (prev.issues || []).filter(i => i.agent !== 'Critic');
          return { ...prev, agents, issues: cleanIssues };
        });
      }
    },
    [apiBase],
  );

  const run = useCallback(
    (imageBase64: string | null, mimeType: string | null, description: string) => {
      if (wsRef.current) {
        wsRef.current.close();
      }

      descriptionRef.current = description;
      reset();

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setState(s => ({ ...s, phase: 'running' }));
        const payload: any = {
          type: 'generate',
          description,
          run_audit: true,
          run_accessibility: true,
          screenshot_base64: '',
          screenshot_mime_type: 'image/png',
          design_contract: '',
        };
        if (imageBase64) {
          payload.image_base64 = imageBase64;
          payload.mime_type = mimeType || 'image/jpeg';
        }
        ws.send(JSON.stringify(payload));
      };

      ws.onmessage = event => {
        let msg: WSMessage;
        try {
          msg = JSON.parse(event.data as string);
        } catch {
          return;
        }

        // Track final code outside setState so it's available for visual-check
        if (msg.type === 'final_code' && msg.code) {
          finalCodeRef.current = msg.code;
        }
        if (msg.type === 'pipeline_complete' && msg.code) {
          finalCodeRef.current = msg.code;
        }

        setState(prev => {
          const agents = { ...prev.agents };

          switch (msg.type) {
            case 'agent_status': {
              agents[msg.agent] = {
                ...agents[msg.agent],
                status: msg.status,
                message: msg.message ?? '',
              };
              return { ...prev, agents };
            }

            case 'agent_token': {
              // track token arrival for TPS display
              if (msg.agent === 'code_forge') {
                const now = Date.now();
                tokenTimestamps.current = [
                  ...tokenTimestamps.current.filter(t => now - t < 2000),
                  now,
                ];
                const windowedTps =
                  tokenTimestamps.current.length > 1
                    ? (tokenTimestamps.current.length /
                        ((now - tokenTimestamps.current[0]) / 1000))
                    : null;
                return {
                  ...prev,
                  agents,
                  streamingCode: prev.streamingCode + msg.token,
                  tps: windowedTps,
                };
              }
              return { ...prev, agents, streamingCode: prev.streamingCode + msg.token };
            }

            case 'agent_output': {
              agents[msg.agent] = { ...agents[msg.agent] };
              const nextState: Partial<PipelineState> = { agents };
              if (msg.agent === 'vision_parser' && msg.output) {
                nextState.vision = msg.output as unknown as VisionParseResult;
              }
              return { ...prev, ...nextState };
            }

            case 'final_code': {
              return { ...prev, finalCode: msg.code };
            }

            case 'tps': {
              if (msg.agent === 'code_forge') {
                return { ...prev, tps: msg.tokens_per_second };
              }
              return prev;
            }

            case 'error': {
              if (msg.agent) {
                agents[msg.agent] = {
                  ...agents[msg.agent],
                  status: 'error',
                  message: msg.message,
                };
              }
              return { ...prev, agents, phase: 'error', errorMsg: msg.message };
            }

            case 'pipeline_complete': {
              const finalAgents = { ...agents };
              // snapshot final code if different
              const finalCode = msg.code || prev.finalCode;
              let vision = prev.vision;
              if (msg.vision) {
                vision = msg.vision as unknown as VisionParseResult;
              }
              if (msg.success) {
                finalAgents['vision_critic'] = { status: 'thinking', message: 'Running visual QA…' };
              }

              const initialIssues: UnifiedIssue[] = (msg.issues || []).map(i => ({
                agent: i.agent,
                severity: i.severity,
                description: i.description,
                code_region: i.code_region,
              }));

              return {
                ...prev,
                agents: finalAgents,
                phase: msg.success ? 'done' : 'error',
                finalCode,
                vision,
                issues: initialIssues,
                errorMsg: msg.success ? '' : (msg.message || 'Pipeline finished with errors'),
              };
            }

            default:
              return prev;
          }
        });

        if (msg.type === 'pipeline_complete' && msg.success) {
          void runVisualCheck(finalCodeRef.current, descriptionRef.current);
        }
      };

      ws.onerror = () => {
        setState(s => ({
          ...s,
          phase: 'error',
          errorMsg: 'WebSocket connection failed. Is the backend running?',
        }));
      };

      ws.onclose = ev => {
        // only treat unexpected close as error
        if (ev.code !== 1000 && ev.code !== 1001) {
          setState(s => {
            if (s.phase === 'running') {
              return { ...s, phase: 'error', errorMsg: 'Connection closed unexpectedly' };
            }
            return s;
          });
        }
      };
    },
    [wsUrl, reset, runVisualCheck],
  );

  const abort = useCallback(() => {
    wsRef.current?.close(1000);
    setState(s => ({ ...s, phase: 'idle' }));
  }, []);

  const updateFinalCode = useCallback((code: string) => {
    setState(prev => ({ ...prev, finalCode: code }));
    finalCodeRef.current = code;
  }, []);

  const rerunVisualCheck = useCallback(
    async (code: string) => {
      setState(prev => {
        const agents = { ...prev.agents };
        agents['vision_critic'] = { status: 'thinking', message: 'Running visual QA…' };
        return { ...prev, agents };
      });
      await runVisualCheck(code, descriptionRef.current);
    },
    [runVisualCheck],
  );

  const autoRefine = useCallback(
    async (code: string, description: string) => {
      // Cancel any in-flight operation
      cancelOperation();

      const controller = new AbortController();
      abortControllerRef.current = controller;

      setIsRefining(true);
      setRefineProgress('Iteration 1 of 3...');

      let currentIter = 1;
      const progressInterval = setInterval(() => {
        if (currentIter < 3) {
          currentIter += 1;
          setRefineProgress(`Iteration ${currentIter} of 3...`);
          setState(prev => {
            const agents = { ...prev.agents };
            agents['vision_critic'] = {
              status: 'thinking',
              message: `Auto-refining: Iteration ${currentIter} of 3...`,
            };
            return { ...prev, agents };
          });
        }
      }, 20000);

      setState(prev => {
        const agents = { ...prev.agents };
        agents['vision_critic'] = {
          status: 'thinking',
          message: 'Auto-refining: Iteration 1 of 3...',
        };
        return { ...prev, agents };
      });

      const contract =
        description.trim() ||
        'Check for layout alignment, overflow, missing elements, and contrast issues.';

      try {
        const res = await fetch(`${apiBase}/auto-refine`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code, design_contract: contract, description }),
          signal: controller.signal,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        const lastIssuesList = data.issues_per_iteration?.[data.issues_per_iteration.length - 1] || [];
        const criticIssues: UnifiedIssue[] = lastIssuesList.map((issue: any) => ({
          agent: 'Critic',
          severity: issue.severity === 'critical' ? 'error' : (issue.severity === 'major' ? 'warn' : 'info'),
          description: issue.description + (issue.suggestion ? ` (Suggestion: ${issue.suggestion})` : ''),
          code_region: issue.category || undefined,
        }));

        setState(prev => {
          const agents = { ...prev.agents };
          
          const hasSerious = lastIssuesList.some((i: any) => i.severity === 'critical' || i.severity === 'major');
          let agentStatus: AgentStatus = 'done';
          if (data.stopped_reason === 'error') {
            agentStatus = 'error';
          } else if (hasSerious) {
            agentStatus = 'error';
          } else if (lastIssuesList.length > 0) {
            agentStatus = 'warn';
          }
          
          let statusMsg = '';
          if (data.stopped_reason === 'passed') {
            statusMsg = `Visual QA passed. Refined over ${data.iterations_run} iteration${data.iterations_run !== 1 ? 's' : ''}.`;
          } else if (data.stopped_reason === 'error') {
            statusMsg = `Refinement stopped early due to an error. Iterations: ${data.iterations_run}.`;
          } else {
            statusMsg = `Visual QA completed. Refined over ${data.iterations_run} iteration${data.iterations_run !== 1 ? 's' : ''}.`;
          }

          agents['vision_critic'] = { status: agentStatus, message: statusMsg };

          const cleanIssues = (prev.issues || []).filter(i => i.agent !== 'Critic');
          const newIssues = [...cleanIssues, ...criticIssues];

          return {
            ...prev,
            finalCode: data.final_code,
            agents,
            issues: newIssues,
          };
        });

        if (finalCodeRef) {
          finalCodeRef.current = data.final_code;
        }

      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          // User cancelled — nothing to do
        } else {
          console.error('Auto-refine failed:', err);
          setState(prev => {
            const agents = { ...prev.agents };
            agents['vision_critic'] = {
              status: 'error',
              message: `Auto-refine failed: ${err instanceof Error ? err.message : String(err)}`,
            };
            return { ...prev, agents };
          });
        }
      } finally {
        clearInterval(progressInterval);
        setIsRefining(false);
        abortControllerRef.current = null;
      }
    },
    [apiBase],
  );

  const refineRegion = useCallback(
    async (code: string, regionDescription: string, refinementRequest: string, sketchBase64?: string) => {
      // Cancel any in-flight operation and create a fresh controller
      cancelOperation();
      const controller = new AbortController();
      abortControllerRef.current = controller;

      const res = await fetch(`${apiBase}/refine-region`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code,
          region_description: regionDescription,
          refinement_request: refinementRequest,
          sketch_image_base64: sketchBase64 ?? '',
        }),
        signal: controller.signal,
      });
      if (!res.ok) {
        let errMsg = 'Region refinement failed';
        try {
          const errData = await res.json();
          errMsg = errData.detail || errMsg;
        } catch (_) {}
        throw new Error(errMsg);
      }
      return await res.json();
    },
    [apiBase],
  );

  return {
    state,
    setState,
    run,
    reset,
    abort,
    updateFinalCode,
    rerunVisualCheck,
    autoRefine,
    isRefining,
    refineProgress,
    refineRegion,
    cancelOperation,
  };
}
