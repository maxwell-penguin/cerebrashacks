import React from 'react';
import {
  PenLine,
  Bot,
  Code2,
  Eye,
  LayoutGrid,
  Zap,
  Search,
  Accessibility,
  Sparkles,
} from 'lucide-react';

const AGENTS: { icon: React.ComponentType<{ className?: string }>; name: string; bg: string; border: string; text: string }[] = [
  { icon: Eye,           name: 'Vision',     bg: 'bg-violet-50',  border: 'border-violet-200',  text: 'text-violet-700'  },
  { icon: LayoutGrid,    name: 'Architect',  bg: 'bg-blue-50',    border: 'border-blue-200',    text: 'text-blue-700'    },
  { icon: Zap,           name: 'Code Forge', bg: 'bg-amber-50',   border: 'border-amber-200',   text: 'text-amber-700'   },
  { icon: Search,        name: 'Auditor',    bg: 'bg-rose-50',    border: 'border-rose-200',    text: 'text-rose-700'    },
  { icon: Accessibility, name: 'A11y',       bg: 'bg-emerald-50', border: 'border-emerald-200', text: 'text-emerald-700' },
  { icon: Sparkles,      name: 'Critic',     bg: 'bg-fuchsia-50', border: 'border-fuchsia-200', text: 'text-fuchsia-700' },
];

interface Props {
  onGetStarted: () => void;
}

export default function LandingScreen({ onGetStarted }: Props) {
  return (
    <div className="min-h-screen bg-white flex flex-col relative overflow-hidden">
      {/* Background decoration — subtle depth blobs */}
      <div className="absolute inset-0 pointer-events-none select-none">
        <div className="absolute -top-32 -right-32 w-[500px] h-[500px] bg-indigo-100/40 rounded-full blur-3xl" />
        <div className="absolute top-1/2 -left-24 w-72 h-72 bg-emerald-100/30 rounded-full blur-3xl" />
        <div className="absolute bottom-0 right-1/4 w-60 h-60 bg-violet-100/20 rounded-full blur-2xl" />
      </div>

      {/* Top gradient accent line */}
      <div className="h-[3px] bg-gradient-to-r from-indigo-500 via-violet-400 to-emerald-400 shrink-0" />

      {/* Nav */}
      <nav className="relative z-10 flex items-center justify-between px-8 py-5 shrink-0">
        <div className="flex items-baseline gap-1.5 select-none">
          <span className="text-lg font-black tracking-tight bg-gradient-to-r from-indigo-600 to-violet-500 bg-clip-text text-transparent">
            SketchStorm
          </span>
          <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-[0.2em]">
            Studio
          </span>
        </div>
        <a
          href="https://cerebras.ai"
          target="_blank"
          rel="noreferrer"
          className="text-[11px] text-slate-400 hover:text-slate-600 transition-colors font-medium"
        >
          cerebras.ai ↗
        </a>
      </nav>

      {/* Hero */}
      <main className="relative z-10 flex-1 flex flex-col items-center justify-center px-6 text-center pb-12">

        {/* Cerebras badge — unmissable */}
        <div className="mb-4 inline-flex items-center gap-2.5 bg-amber-50 border border-amber-300 text-amber-800 px-5 py-2.5 rounded-full shadow-sm">
          <span className="text-base leading-none">⚡</span>
          <span className="text-sm font-bold tracking-tight">Powered by Gemma 4 31B on Cerebras</span>
        </div>

        {/* Headline */}
        <h1 className="text-5xl sm:text-6xl font-extrabold tracking-tight text-slate-900 leading-[1.1] mb-5">
          Sketch a UI.<br />
          <span className="bg-gradient-to-r from-indigo-600 to-violet-500 bg-clip-text text-transparent">
            Watch AI build it live.
          </span>
        </h1>

        {/* Subhead */}
        <p className="text-lg text-slate-500 max-w-md leading-relaxed mb-8">
          Draw your layout by hand. Six specialized AI agents turn it into a{' '}
          <span className="text-slate-700 font-medium">working React component</span>{' '}
          in seconds — no code required.
        </p>

        {/* 3-step flow concept cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12 max-w-3xl w-full px-4 justify-center">
          <div className="bg-white/90 border border-slate-200/80 rounded-2xl p-6 shadow-md hover:shadow-lg hover:border-slate-350 transition-all text-center flex flex-col items-center">
            <div className="w-10 h-10 rounded-full bg-slate-50 flex items-center justify-center mb-3.5 border border-slate-100 shadow-sm">
              <PenLine className="w-5 h-5 text-slate-500" />
            </div>
            <h3 className="text-sm font-bold text-slate-800 mb-1.5 uppercase tracking-wide">1. Your Sketch</h3>
            <p className="text-xs text-slate-500 leading-relaxed">
              Upload a hand-drawn layout photo or write a description to seed your interface.
            </p>
          </div>

          <div className="bg-white/90 border border-indigo-200/80 rounded-2xl p-6 shadow-md hover:shadow-lg hover:border-indigo-350 transition-all text-center flex flex-col items-center">
            <div className="w-10 h-10 rounded-full bg-indigo-50 flex items-center justify-center mb-3.5 border border-indigo-100 shadow-sm">
              <Bot className="w-5 h-5 text-indigo-500" />
            </div>
            <h3 className="text-sm font-bold text-indigo-900 mb-1.5 uppercase tracking-wide">2. 6-Agent Pipeline</h3>
            <p className="text-xs text-slate-500 leading-relaxed">
              Six specialized agents collaborate live to architecture, build, audit, and critique your code.
            </p>
          </div>

          <div className="bg-white/90 border border-emerald-200/80 rounded-2xl p-6 shadow-md hover:shadow-lg hover:border-emerald-350 transition-all text-center flex flex-col items-center">
            <div className="w-10 h-10 rounded-full bg-emerald-50 flex items-center justify-center mb-3.5 border border-emerald-100 shadow-sm">
              <Code2 className="w-5 h-5 text-emerald-500" />
            </div>
            <h3 className="text-sm font-bold text-emerald-900 mb-1.5 uppercase tracking-wide">3. Working App</h3>
            <p className="text-xs text-slate-500 leading-relaxed">
              Witness your app render live in the browser, complete with clean React + Tailwind code.
            </p>
          </div>
        </div>

        {/* CTA */}
        <button
          onClick={onGetStarted}
          className="group mb-8 px-9 py-4 bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 text-white text-base font-bold rounded-xl shadow-lg hover:shadow-indigo-200 hover:shadow-xl transition-all duration-150 flex items-center gap-2"
        >
          Get Started
          <span className="transition-transform duration-150 group-hover:translate-x-1 inline-block">→</span>
        </button>

        {/* Agent roster */}
        <div className="w-full max-w-2xl">
          <p className="text-[10px] font-extrabold text-slate-400 uppercase tracking-[0.15em] mb-3">
            The Pipeline
          </p>
          <div className="flex items-center justify-center gap-1.5 flex-wrap">
            {AGENTS.map((agent, i) => (
              <React.Fragment key={agent.name}>
                <div
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold shadow-sm ${agent.bg} ${agent.border} ${agent.text}`}
                >
                  <agent.icon className="w-3.5 h-3.5" />
                  <span>{agent.name}</span>
                </div>
                {i < AGENTS.length - 1 && (
                  <span className="text-slate-300 font-bold text-xs">→</span>
                )}
              </React.Fragment>
            ))}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="relative z-10 shrink-0 text-center py-5 border-t border-slate-100">
        <p className="text-xs text-slate-400">
          Built at Cerebras Hackathon &nbsp;·&nbsp; Gemma 4 31B vision + text &nbsp;·&nbsp; React + Tailwind
        </p>
      </footer>
    </div>
  );
}
