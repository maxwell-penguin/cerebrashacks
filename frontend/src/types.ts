export type AgentName =
  | 'vision_parser'
  | 'architect'
  | 'code_forge'
  | 'auditor'
  | 'accessibility'
  | 'vision_critic';

export type AgentStatus = 'idle' | 'thinking' | 'streaming' | 'done' | 'error' | 'skipped' | 'warn';

export interface VisionComponent {
  type: string;
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface VisionParseResult {
  screen_title: string;
  components: VisionComponent[];
  notes: string;
}

// WebSocket server → client messages
export interface NormalizedIssue {
  agent: 'Auditor' | 'A11y';
  severity: 'error' | 'warn' | 'info';
  description: string;
  code_region?: string;
}

export type WSMessage =
  | { type: 'agent_status'; agent: AgentName; status: AgentStatus; message?: string }
  | { type: 'agent_token'; agent: AgentName; token: string }
  | { type: 'agent_output'; agent: AgentName; output: Record<string, unknown> }
  | { type: 'final_code'; code: string }
  | { type: 'tps'; agent: AgentName; tokens_per_second: number }
  | { type: 'error'; message: string; agent?: AgentName }
  | {
      type: 'pipeline_complete';
      success: boolean;
      code: string;
      issues?: NormalizedIssue[];
      vision?: Record<string, unknown>;
      architecture?: Record<string, unknown>;
      message?: string;
    };

export interface UnifiedIssue {
  agent: string;
  severity: 'error' | 'warn' | 'info';
  description: string;
  code_region?: string;
}

export interface VisualCheckResponse {
  passed: boolean;
  status?: 'pass' | 'pass_with_warnings' | 'fail';
  summary: string;
  issues: Array<{
    description: string;
    severity?: string;
    category?: string;
    suggestion?: string;
  }>;
}

export interface AgentState {
  status: AgentStatus;
  message: string;
  tps?: number;
}

export type AgentMap = Record<AgentName, AgentState>;

// CHAT

export type ChatAgent = 'architect' | 'design_advisor' | 'critic';

export interface ChatContext {
  route: string;
  layout_summary: string;
  code_summary: string;
}

export interface ChatRequest {
  agent: ChatAgent;
  message: string;
  context: ChatContext;
}

export interface ChatResponse {
  reply: string;
  suggested_changes?: Record<string, unknown> | null;
}

export interface ChatMessage {
  sender: 'user' | 'agent';
  text: string;
  agent?: ChatAgent;
}

