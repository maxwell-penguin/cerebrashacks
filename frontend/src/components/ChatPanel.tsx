import React, { useState, useRef, useEffect } from 'react';
import type { VisionParseResult } from '../types';

interface Message {
  sender: 'user' | 'agent';
  agentName?: string;
  text: string;
  suggested_changes?: any;
}

interface Props {
  apiBase: string;
  vision: VisionParseResult | null;
  finalCode: string;
}

export default function ChatPanel({ apiBase, vision, finalCode }: Props) {
  const [agent, setAgent] = useState<'architect' | 'design_advisor' | 'critic'>('architect');
  const [messages, setMessages] = useState<Message[]>([
    {
      sender: 'agent',
      agentName: 'System',
      text: 'Welcome to SketchStorm Co-pilot! Select an agent above and ask for architectural suggestions, layout design refinements, or feedback on visual issues.',
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const handleSend = async () => {
    const userMessage = input.trim();
    if (!userMessage || loading) return;

    setInput('');
    setMessages(prev => [...prev, { sender: 'user', text: userMessage }]);
    setLoading(true);

    // 1. Build layout summary
    let layoutSummary = 'Standard layout.';
    if (vision) {
      const cmpList = vision.components.map(c => `${c.type} (${c.label})`).join(', ');
      layoutSummary = `Screen Title: "${vision.screen_title}". Detected components: [${cmpList}]. ${vision.notes || ''}`;
    }

    // 2. Build code summary (grab first 2000 chars of code containing imports and component structure)
    const codeSummary = finalCode ? finalCode.slice(0, 2000) : 'No code generated yet.';

    try {
      const response = await fetch(`${apiBase}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent,
          message: userMessage,
          context: {
            route: '/dashboard',
            layout_summary: layoutSummary,
            code_summary: codeSummary,
          },
        }),
      });

      if (!response.ok) {
        throw new Error(`Server returned HTTP ${response.status}`);
      }

      const data = await response.json();
      setMessages(prev => [
        ...prev,
        {
          sender: 'agent',
          agentName: agent === 'architect' ? 'Architect' : agent === 'design_advisor' ? 'Design Advisor' : 'Vision Critic',
          text: data.reply,
          suggested_changes: data.suggested_changes,
        },
      ]);
    } catch (err: any) {
      setMessages(prev => [
        ...prev,
        {
          sender: 'agent',
          agentName: 'System',
          text: `Error connecting to agent: ${err.message || err}`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    handleSend();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const getAgentLabel = (a: string) => {
    switch (a) {
      case 'architect':
        return 'Architect 🏛️';
      case 'design_advisor':
        return 'Design Advisor 🎨';
      case 'critic':
        return 'Vision Critic 👁️';
      default:
        return 'Agent';
    }
  };

  return (
    <div className="flex flex-col h-72 min-h-0 bg-slate-50 border-t border-slate-200">
      {/* Selector Area */}
      <div className="px-3 py-2 border-b border-slate-200 bg-white flex items-center justify-between shadow-sm shrink-0 z-10">
        <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Co-pilot</span>
        <select
          value={agent}
          onChange={e => setAgent(e.target.value as any)}
          disabled={loading}
          className="text-[10px] bg-slate-50 border border-slate-300 rounded px-2.5 py-1 text-slate-700 focus:outline-none focus:border-indigo-500 font-bold transition-all shadow-sm cursor-pointer"
        >
          <option value="architect">Architect 🏛️</option>
          <option value="design_advisor">Design Advisor 🎨</option>
          <option value="critic">Vision Critic 👁️</option>
        </select>
      </div>

      {/* Messages Stream */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-3 space-y-2.5 min-h-0 bg-slate-50 scrollbar-thin"
      >
        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={`flex flex-col ${msg.sender === 'user' ? 'items-end' : 'items-start'} animate-fade-in`}
          >
            {msg.sender === 'agent' && msg.agentName && (
              <span className="text-[9px] uppercase tracking-wider font-extrabold text-slate-450 ml-1 mb-0.5">
                {msg.agentName}
              </span>
            )}
            <div
              className={`text-xs rounded-lg p-2.5 shadow-sm max-w-[85%] border leading-relaxed ${
                msg.sender === 'user'
                  ? 'bg-indigo-600 border-indigo-700 text-white font-medium ml-auto rounded-tr-none'
                  : 'bg-white border-slate-200 text-slate-700 mr-auto rounded-tl-none'
              }`}
            >
              <p className="whitespace-pre-wrap">{msg.text}</p>

              {/* Display suggested_changes dynamically */}
              {msg.suggested_changes && (
                <div className="mt-2.5 pt-2 border-t border-slate-100 text-[10px] space-y-1.5 text-slate-600">
                  <div className="font-bold text-slate-500 uppercase tracking-wider text-[9px] mb-0.5">
                    ⚙️ Suggested Changes
                  </div>
                  {msg.suggested_changes.layout && (
                    <div className="bg-slate-50 p-1.5 rounded border border-slate-150">
                      <span className="font-semibold text-slate-700 block mb-0.5">Layout Adjustments:</span>
                      {msg.suggested_changes.layout.routes_to_add?.length > 0 && (
                        <div className="text-slate-500">
                          ➕ Routes: <code className="bg-slate-200 px-1 py-0.2 rounded font-mono text-[9px]">{msg.suggested_changes.layout.routes_to_add.join(', ')}</code>
                        </div>
                      )}
                      {msg.suggested_changes.layout.regions_to_update?.length > 0 && (
                        <div className="text-slate-500 mt-0.5">
                          🔄 Regions: <code className="bg-slate-200 px-1 py-0.2 rounded font-mono text-[9px]">{msg.suggested_changes.layout.regions_to_update.join(', ')}</code>
                        </div>
                      )}
                    </div>
                  )}
                  {msg.suggested_changes.components?.length > 0 && (
                    <div className="bg-slate-50 p-1.5 rounded border border-slate-150">
                      <span className="font-semibold text-slate-700 block mb-0.5">New Components:</span>
                      <ul className="list-disc pl-4 space-y-0.5 text-slate-500">
                        {msg.suggested_changes.components.map((c: any, cIdx: number) => (
                          <li key={cIdx}>
                            <span className="font-bold text-slate-600">{c.name}</span> <span className="text-[9px] text-slate-450">({c.type})</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {msg.suggested_changes.theme && (
                    <div className="bg-slate-50 p-1.5 rounded border border-slate-150">
                      <span className="font-semibold text-slate-700 block mb-0.5">Theme Config:</span>
                      <pre className="text-[9px] font-mono text-indigo-700 bg-indigo-50/50 p-1 rounded overflow-x-auto border border-indigo-100">
                        {JSON.stringify(msg.suggested_changes.theme, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex flex-col items-start animate-pulse">
            <span className="text-[9px] uppercase tracking-wider font-extrabold text-slate-450 ml-1 mb-0.5">
              {getAgentLabel(agent)}
            </span>
            <div className="bg-white border border-slate-200 text-slate-450 rounded-lg rounded-tl-none p-2.5 shadow-sm flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
          </div>
        )}
      </div>

      {/* Input Area */}
      <form
        onSubmit={handleSubmit}
        className="p-2 border-t border-slate-200 bg-white flex gap-1.5 items-center shrink-0 shadow-inner"
      >
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
          placeholder="Ask the co-pilot for suggestions..."
          className="flex-1 text-xs bg-slate-50 border border-slate-200 rounded px-2.5 py-2 focus:outline-none focus:border-indigo-500 focus:bg-white text-slate-800 placeholder:text-slate-400 transition-all shadow-sm"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="bg-indigo-600 hover:bg-indigo-700 active:scale-[0.98] text-white font-bold text-xs py-2 px-3 rounded shadow-sm disabled:opacity-40 disabled:scale-100 disabled:cursor-not-allowed transition-all"
        >
          Send
        </button>
      </form>
    </div>
  );
}
