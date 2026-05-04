"use client";

import { useState, useEffect, useRef } from 'react';
import { 
  Play, Pause, Scissors, Sparkles, MessageSquare, 
  Settings, ChevronRight, Activity, Zap, CheckCircle2,
  Clock, TrendingUp, Music, Type
} from 'lucide-react';
import axios from 'axios';

const API_BASE = "http://localhost:8000/api";

export default function Dashboard() {
  const [url, setUrl] = useState("");
  const [status, setStatus] = useState("idle");
  const [logs, setLogs] = useState<string[]>([]);
  const [results, setResults] = useState<any>(null);
  const [selectedClip, setSelectedClip] = useState<number | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const handleStrategize = async () => {
    if (!url) return;
    setStatus("strategizing");
    setLogs(["Initializing AI Director Pipeline..."]);
    
    // Connect WebSocket for logs
    const ws = new WebSocket("ws://localhost:8000/api/logs");
    ws.onmessage = (event) => {
      setLogs(prev => [...prev, event.data]);
    };

    try {
      await axios.post(`${API_BASE}/strategize`, { url });
      
      // Poll for completion
      const poll = setInterval(async () => {
        const res = await axios.get(`${API_BASE}/results`);
        if (res.data.status === "done") {
          clearInterval(poll);
          setResults(res.data);
          setStatus("done");
          ws.close();
        }
      }, 2000);
      
    } catch (e) {
      setLogs(prev => [...prev, "Error starting strategize phase."]);
      setStatus("error");
      ws.close();
    }
  };

  const renderClip = async (index: number) => {
    setStatus("rendering");
    const ws = new WebSocket("ws://localhost:8000/api/logs");
    ws.onmessage = (event) => setLogs(prev => [...prev, event.data]);
    
    try {
      await axios.post(`${API_BASE}/render`, { clip_id: index });
      
      const poll = setInterval(async () => {
        const res = await axios.get(`${API_BASE}/status`);
        if (!res.data.is_rendering) {
          clearInterval(poll);
          setStatus("done");
          ws.close();
          alert("Render Complete! Check Output directory or Gallery.");
        }
      }, 2000);
      
    } catch (e) {
      setLogs(prev => [...prev, "Error rendering clip."]);
      setStatus("done");
      ws.close();
    }
  };

  return (
    <div className="min-h-screen bg-[#0A0A0B] text-slate-200 font-sans selection:bg-indigo-500/30">
      {/* Navbar */}
      <nav className="border-b border-white/5 bg-black/20 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
              <Scissors className="w-4 h-4 text-white" />
            </div>
            <span className="font-bold text-xl tracking-tight text-white">ClipFactory<span className="text-indigo-400">.ai</span></span>
            <span className="ml-3 px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-[10px] font-medium text-slate-400 uppercase tracking-wider">
              Director Phase 4
            </span>
          </div>
          <div className="flex items-center gap-4 text-sm font-medium">
            <button className="text-slate-400 hover:text-white transition-colors">Workspace</button>
            <button className="text-slate-400 hover:text-white transition-colors">Gallery</button>
            <div className="w-8 h-8 rounded-full bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
              U
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-6 py-8">
        
        {/* Input Section */}
        <div className="bg-white/[0.02] border border-white/5 rounded-2xl p-6 mb-8 relative overflow-hidden group">
          <div className="absolute inset-0 bg-gradient-to-r from-indigo-500/5 to-purple-500/5 opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
          <div className="relative z-10 flex gap-4">
            <div className="flex-1 relative">
              <input 
                type="text" 
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="Paste YouTube URL here to engage the AI Director..."
                className="w-full bg-black/40 border border-white/10 rounded-xl px-6 py-4 text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/50 transition-all text-lg"
                disabled={status === "strategizing" || status === "rendering"}
              />
            </div>
            <button 
              onClick={handleStrategize}
              disabled={status === "strategizing" || status === "rendering" || !url}
              className="bg-indigo-600 hover:bg-indigo-500 text-white px-8 py-4 rounded-xl font-semibold shadow-lg shadow-indigo-500/20 transition-all active:scale-95 disabled:opacity-50 disabled:active:scale-100 flex items-center gap-2 whitespace-nowrap"
            >
              {status === "strategizing" ? (
                <><Activity className="w-5 h-5 animate-pulse" /> Analyzing...</>
              ) : (
                <><Sparkles className="w-5 h-5" /> Strategize Video</>
              )}
            </button>
          </div>
        </div>

        {/* Dual Pane Layout */}
        {results ? (
          <div className="grid grid-cols-12 gap-8">
            
            {/* Left Pane: Intelligence & Preview */}
            <div className="col-span-12 lg:col-span-4 space-y-6">
              
              {/* Intelligence Panel */}
              <div className="bg-indigo-950/20 border border-indigo-500/20 rounded-2xl p-6 backdrop-blur-sm relative overflow-hidden">
                <div className="absolute top-0 right-0 p-4 opacity-10">
                  <Zap className="w-24 h-24 text-indigo-400" />
                </div>
                <h3 className="flex items-center gap-2 text-indigo-400 font-semibold mb-6">
                  <Activity className="w-4 h-4" /> AI Video Intelligence
                </h3>
                
                <div className="space-y-4 relative z-10">
                  <div>
                    <div className="text-[10px] text-indigo-300/60 uppercase tracking-widest font-semibold mb-1">Detected Persona</div>
                    <div className="text-white font-medium flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-emerald-400" />
                      {results.persona.genre} • {results.persona.tone}
                    </div>
                  </div>
                  
                  <div>
                    <div className="text-[10px] text-indigo-300/60 uppercase tracking-widest font-semibold mb-1">Target Audience</div>
                    <div className="text-slate-300 text-sm leading-relaxed">
                      {results.persona.target_audience}
                    </div>
                  </div>

                  <div className="pt-4 border-t border-indigo-500/10">
                    <div className="text-[10px] text-indigo-300/60 uppercase tracking-widest font-semibold mb-2">Auto-Selected Kit</div>
                    <div className="flex gap-2">
                      <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-black/40 border border-indigo-500/20 text-xs font-medium text-indigo-300">
                        <Type className="w-3.5 h-3.5" /> {results.persona.suggested_brand_kit}
                      </span>
                      <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-black/40 border border-indigo-500/20 text-xs font-medium text-indigo-300">
                        <Music className="w-3.5 h-3.5" /> {results.persona.suggested_bgm}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Console Logs */}
              <div className="bg-black/60 border border-white/5 rounded-2xl p-4 h-64 flex flex-col font-mono text-[11px] leading-relaxed relative">
                <div className="text-slate-500 mb-2 font-semibold uppercase tracking-wider sticky top-0 bg-black/60 backdrop-blur pb-2">Terminal Logs</div>
                <div className="overflow-y-auto flex-1 space-y-1 text-slate-400 custom-scrollbar pr-2">
                  {logs.map((log, i) => (
                    <div key={i}>{log}</div>
                  ))}
                  <div ref={logEndRef} />
                </div>
              </div>
            </div>

            {/* Right Pane: Strategies & Transcript */}
            <div className="col-span-12 lg:col-span-8 space-y-6">
              <div className="flex items-center justify-between mb-2">
                <h2 className="text-2xl font-bold text-white">Extracted Strategies</h2>
                <div className="flex items-center gap-2 text-sm text-slate-400">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  {results.clips.length} Clips Ready
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4">
                {results.clips.map((clip: any, i: number) => (
                  <div 
                    key={i}
                    onClick={() => setSelectedClip(i)}
                    className={`p-5 rounded-2xl border transition-all cursor-pointer group
                      ${selectedClip === i 
                        ? 'bg-indigo-600/10 border-indigo-500/50' 
                        : 'bg-white/[0.02] border-white/5 hover:border-white/20'}`}
                  >
                    <div className="flex justify-between items-start mb-3">
                      <div className="flex items-center gap-3">
                        <div className={`px-2.5 py-1 rounded text-xs font-bold tracking-wider uppercase
                          ${clip.badge.includes('Stitched') ? 'bg-purple-500/20 text-purple-400 border border-purple-500/30' : 'bg-slate-800 text-slate-300 border border-slate-700'}`}>
                          {clip.badge}
                        </div>
                        <div className="flex items-center gap-1.5 text-slate-400 text-sm font-medium">
                          <Clock className="w-4 h-4" />
                          {Math.floor(clip.duration / 60)}:{(clip.duration % 60).toFixed(0).padStart(2, '0')}
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5 bg-emerald-500/10 text-emerald-400 px-2 py-1 rounded text-xs font-bold border border-emerald-500/20">
                        <TrendingUp className="w-3.5 h-3.5" />
                        Score: {clip.score}/100
                      </div>
                    </div>
                    
                    <h4 className="text-lg font-semibold text-white mb-2">{clip.title}</h4>
                    <p className="text-slate-400 text-sm leading-relaxed mb-4 line-clamp-2">"{clip.hook_sentence}"</p>
                    
                    {selectedClip === i && (
                      <div className="mt-4 pt-4 border-t border-white/10 space-y-4 animate-in fade-in slide-in-from-top-2 duration-300">
                        <div className="bg-black/40 rounded-xl p-4 border border-white/5">
                          <div className="text-[10px] text-slate-500 uppercase tracking-widest font-semibold mb-2">Director's Reasoning</div>
                          <p className="text-sm text-slate-300 leading-relaxed">{clip.virality_reason}</p>
                        </div>
                        
                        {/* Fluff Visualization Indicator */}
                        {clip.segments && clip.segments.length > 1 && (
                          <div className="text-xs text-purple-400 flex items-center gap-2 bg-purple-500/10 p-3 rounded-lg border border-purple-500/20">
                            <Sparkles className="w-4 h-4" />
                            <span>AI removed {clip.segments.length - 1} fluff segment(s) to optimize pacing.</span>
                          </div>
                        )}

                        <div className="flex justify-end pt-2">
                          <button 
                            onClick={(e) => { e.stopPropagation(); renderClip(i); }}
                            className="bg-white text-black hover:bg-slate-200 px-6 py-2.5 rounded-lg font-semibold flex items-center gap-2 transition-all active:scale-95"
                          >
                            <Play className="w-4 h-4" /> Render Clip
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

          </div>
        ) : (
          <div className="h-64 border border-dashed border-white/10 rounded-2xl flex flex-col items-center justify-center text-slate-500">
            <Scissors className="w-12 h-12 mb-4 opacity-20" />
            <p>Ready for a URL. The AI Director is standing by.</p>
          </div>
        )}

      </main>
    </div>
  );
}
