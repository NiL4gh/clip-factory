"use client";

import { useState, useEffect, useRef, useMemo } from 'react';
import { 
  Play, Scissors, Sparkles,
  Activity, Zap, CheckCircle2,
  Clock, TrendingUp, Music, Type, Download,
  Film, RefreshCw, Eye, EyeOff, ArrowRight, Settings2, Volume2
} from 'lucide-react';
import axios from 'axios';

/* ------------------------------------------------------------------ */
/*  API / WS base — configurable for Colab via NEXT_PUBLIC_API_URL    */
/* ------------------------------------------------------------------ */
const API_BASE =
  (typeof window !== "undefined" && (window as any).__NEXT_PUBLIC_API_URL) ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000/api";

function wsUrl(): string {
  const base = API_BASE.replace(/\/api\/?$/, "");
  const proto = base.startsWith("https") ? "wss" : "ws";
  return `${proto}://${base.replace(/^https?:\/\//, "")}/api/logs`;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */
interface GalleryItem {
  filename: string;
  url: string;
  size_mb: number;
  created_at: string;
}

interface WordTimestamp {
  word: string;
  start: number;
  end: number;
}

/* ------------------------------------------------------------------ */
/*  Main Dashboard                                                     */
/* ------------------------------------------------------------------ */
const DEFAULT_SETTINGS = {
  face_center: true,
  magic_hook: true,
  remove_silence: true,
  caption_style: "Hormozi",
  caption_pos: "Center",
  bg_music_genre: "None",
  broll_intensity: "Medium",
};

export default function Dashboard() {
  const [url, setUrl] = useState("");
  const [status, setStatus] = useState("idle");
  const [logs, setLogs] = useState<string[]>([]);
  const [results, setResults] = useState<any>(null);
  const [selectedClip, setSelectedClip] = useState<number | null>(null);
  const [activeView, setActiveView] = useState<"workspace" | "gallery">("workspace");
  const [gallery, setGallery] = useState<GalleryItem[]>([]);
  const logEndRef = useRef<HTMLDivElement>(null);

  // Model selectors
  const [llmLabel, setLlmLabel] = useState("🦙 LLaMA 3 8B Instruct Q4");
  const [whisperLabel, setWhisperLabel] = useState("⭐ medium");
  const [catalogData, setCatalogData] = useState<{llm_catalog:{label:string}[], whisper_catalog:{label:string}[]}>({llm_catalog:[], whisper_catalog:[]});
  const [renderSettings, setRenderSettings] = useState<Record<number, typeof DEFAULT_SETTINGS>>({});

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  useEffect(() => {
    if (activeView === "gallery") fetchGallery();
  }, [activeView]);

  useEffect(() => {
    axios.get(`${API_BASE}/config`).then(res => setCatalogData(res.data)).catch(() => {});
  }, []);

  // Auto-populate render settings from persona
  useEffect(() => {
    if (results?.clips?.length && results?.persona) {
      const base = {
        ...DEFAULT_SETTINGS,
        caption_style: results.persona.suggested_brand_kit || "Hormozi",
        bg_music_genre: results.persona.suggested_bgm || "None",
      };
      const init: Record<number, typeof DEFAULT_SETTINGS> = {};
      results.clips.forEach((_: any, idx: number) => { init[idx] = { ...base }; });
      setRenderSettings(init);
    }
  }, [results]);

  const fetchGallery = async () => {
    try {
      const res = await axios.get(`${API_BASE}/gallery`);
      setGallery(res.data);
    } catch { /* silently fail */ }
  };

  const getSettings = (clipIdx: number) => renderSettings[clipIdx] || DEFAULT_SETTINGS;
  const updateSetting = (clipIdx: number, key: string, value: any) => {
    setRenderSettings(prev => ({
      ...prev,
      [clipIdx]: { ...(prev[clipIdx] || DEFAULT_SETTINGS), [key]: value }
    }));
  };

  const handleStrategize = async () => {
    if (!url) return;
    setStatus("strategizing");
    setLogs(["Initializing AI Director Pipeline..."]);
    setSelectedClip(null);

    const ws = new WebSocket(wsUrl());
    ws.onmessage = (event) => setLogs(prev => [...prev, event.data]);

    try {
      await axios.post(`${API_BASE}/strategize`, { url, llm_label: llmLabel, whisper_label: whisperLabel });
      const poll = setInterval(async () => {
        const res = await axios.get(`${API_BASE}/results`);
        if (res.data.status === "done") {
          clearInterval(poll);
          setResults(res.data);
          setStatus("done");
          ws.close();
        }
      }, 2000);
    } catch {
      setLogs(prev => [...prev, "Error starting strategize phase."]);
      setStatus("error");
      ws.close();
    }
  };

  const renderClip = async (index: number) => {
    setStatus("rendering");
    const ws = new WebSocket(wsUrl());
    ws.onmessage = (event) => setLogs(prev => [...prev, event.data]);

    try {
      const settings = getSettings(index);
      await axios.post(`${API_BASE}/render`, {
        url,
        clip_index: index,
        ...settings
      });
      
      const poll = setInterval(async () => {
        const res = await axios.get(`${API_BASE}/render_status?url=${encodeURIComponent(url)}&index=${index}`);
        if (res.data.status === "done") {
          clearInterval(poll);
          setStatus("done");
          ws.close();
          fetchGallery();
          setActiveView("gallery");
        }
      }, 2000);
    } catch {
      setStatus("error");
      ws.close();
    }
  };

  return (
    <div className="min-h-screen custom-scrollbar flex flex-col">
      {/* ── Sticky Navbar ────────────────────────────────── */}
      <header className="sticky top-0 z-50 bg-slate-900/80 backdrop-blur-md border-b border-white/5 py-3 px-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 bg-indigo-500 rounded-xl flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <Film className="w-5 h-5 text-white" />
          </div>
          <h1 className="text-xl font-bold tracking-tight text-slate-100">
            ClipFactory<span className="text-indigo-400">.ai</span>
          </h1>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex bg-slate-950/50 p-1 rounded-lg border border-white/5">
            <button
              onClick={() => setActiveView("workspace")}
              className={`px-4 py-1.5 rounded-md text-xs font-semibold transition-all ${
                activeView === "workspace" ? "bg-slate-800 text-indigo-400 shadow-sm" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Workspace
            </button>
            <button
              onClick={() => setActiveView("gallery")}
              className={`px-4 py-1.5 rounded-md text-xs font-semibold transition-all ${
                activeView === "gallery" ? "bg-slate-800 text-indigo-400 shadow-sm" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Gallery
            </button>
          </div>
          <div className={`w-3 h-3 rounded-full ${status === "idle" ? "bg-slate-600" : "bg-green-500 animate-pulse"}`} />
        </div>
      </header>

      <main className="flex-1 w-full max-w-5xl mx-auto px-6 py-10">
        
        {activeView === "workspace" ? (
          <div className="animate-fadeIn">
            {/* ── Project Setup Card ─────────────────────────── */}
            <div className="bg-slate-800/50 border border-white/5 rounded-2xl p-8 mb-10 shadow-xl backdrop-blur-sm">
              <div className="max-w-2xl mx-auto text-center mb-8">
                <h2 className="text-3xl font-bold mb-3 text-white">Create New Project</h2>
                <p className="text-slate-400 text-sm">Paste a YouTube URL to let the AI Director strategize your viral shorts.</p>
              </div>

              <div className="flex flex-col gap-6 max-w-3xl mx-auto">
                <div className="relative group">
                  <input
                    type="text"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://youtube.com/watch?v=..."
                    className="w-full bg-slate-950 border border-slate-700 focus:border-indigo-500/50 focus:ring-4 focus:ring-indigo-500/10 rounded-xl py-4 px-5 pl-14 text-slate-100 placeholder:text-slate-600 transition-all text-lg"
                  />
                  <Film className="absolute left-5 top-4.5 w-6 h-6 text-slate-500 group-focus-within:text-indigo-400 transition-colors" />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="bg-slate-900/50 p-4 rounded-xl border border-white/5">
                    <label className="model-selector-label">Main AI Director</label>
                    <select
                      value={llmLabel}
                      onChange={(e) => setLlmLabel(e.target.value)}
                      className="w-full bg-transparent text-slate-200 text-sm font-medium outline-none cursor-pointer"
                    >
                      {catalogData.llm_catalog.map((m: any) => (
                        <option key={m.label} value={m.label} className="bg-slate-900">{m.label}</option>
                      ))}
                    </select>
                  </div>
                  <div className="bg-slate-900/50 p-4 rounded-xl border border-white/5">
                    <label className="model-selector-label">Transcription Engine</label>
                    <select
                      value={whisperLabel}
                      onChange={(e) => setWhisperLabel(e.target.value)}
                      className="w-full bg-transparent text-slate-200 text-sm font-medium outline-none cursor-pointer"
                    >
                      {catalogData.whisper_catalog.map((m: any) => (
                        <option key={m.label} value={m.label} className="bg-slate-900">{m.label}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <button
                  onClick={handleStrategize}
                  disabled={status !== "idle" || !url}
                  className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 disabled:opacity-50 text-white font-bold py-4 rounded-xl flex items-center justify-center gap-3 transition-all shadow-lg shadow-indigo-600/20 active:scale-[0.98]"
                >
                  {status === "strategizing" ? <RefreshCw className="w-5 h-5 animate-spin" /> : <Sparkles className="w-5 h-5" />}
                  {status === "strategizing" ? "Strategizing..." : "Analyze & Strategize"}
                </button>
              </div>
            </div>

            {/* ── Activity Console ───────────────────────────── */}
            {(logs.length > 0 || status !== "idle") && (
              <div className="bg-slate-950 border border-white/5 rounded-xl p-5 mb-10 font-mono text-[11px] leading-relaxed max-h-[160px] overflow-y-auto custom-scrollbar">
                <div className="flex items-center gap-2 mb-3 text-slate-500 font-sans uppercase tracking-widest font-bold">
                  <Activity className="w-3 h-3" /> System Logs
                </div>
                {logs.map((log, i) => (
                  <div key={i} className="text-slate-400 mb-1 flex gap-3">
                    <span className="text-slate-700 shrink-0">[{new Date().toLocaleTimeString()}]</span>
                    <span className={log.includes("✅") ? "text-green-400" : log.includes("❌") ? "text-red-400" : ""}>{log}</span>
                  </div>
                ))}
                <div ref={logEndRef} />
              </div>
            )}

            {/* ── Results Canvas ─────────────────────────────── */}
            {results ? (
              <div className="space-y-8 animate-fadeIn">
                <div className="flex items-center justify-between border-b border-white/5 pb-4">
                  <div>
                    <h3 className="text-xl font-bold text-white">Clip Strategy Result</h3>
                    <p className="text-slate-400 text-xs">Persona: <span className="text-indigo-400 font-semibold">{results.persona?.type || "General"}</span></p>
                  </div>
                  <div className="bg-indigo-500/10 text-indigo-400 px-3 py-1 rounded-full text-xs font-bold border border-indigo-500/20">
                    {results.clips?.length || 0} Clips Identified
                  </div>
                </div>

                <div className="gallery-grid">
                  {results.clips.map((clip: any, i: number) => (
                    <div key={i} className="gallery-card group flex flex-col border border-white/5 bg-slate-900/40 backdrop-blur-sm hover:border-indigo-500/40 transition-all duration-300">
                      <div className="gallery-preview bg-slate-950 aspect-[9/16] relative overflow-hidden">
                        <div className="absolute inset-0 flex flex-col items-center justify-center p-6 text-center space-y-4">
                          <div className="w-12 h-12 rounded-full bg-indigo-500/20 flex items-center justify-center text-indigo-400 group-hover:scale-110 transition-transform">
                            <Scissors className="w-6 h-6" />
                          </div>
                          <div>
                            <div className="text-white font-bold text-sm mb-1 leading-tight">{clip.title || "Untitled Clip"}</div>
                            <div className="text-slate-500 text-[10px] uppercase tracking-widest font-bold">
                              {Math.round(clip.end - clip.start)}s Duration
                            </div>
                          </div>
                        </div>
                        <div className="gallery-play-overlay bg-indigo-900/40 backdrop-blur-[2px]">
                          <button 
                            onClick={() => setSelectedClip(i)}
                            className="bg-white text-slate-900 w-12 h-12 rounded-full flex items-center justify-center shadow-2xl hover:scale-110 transition-all active:scale-95"
                          >
                            <Settings2 className="w-5 h-5" />
                          </button>
                        </div>
                        <div className="absolute top-3 left-3 bg-slate-900/80 backdrop-blur text-[10px] font-bold text-white px-2 py-1 rounded border border-white/10 uppercase tracking-tighter">
                          AI Rank: {Math.round(clip.score || 0)}
                        </div>
                      </div>

                      <div className="p-4 flex-1 flex flex-col justify-between">
                        <p className="text-slate-400 text-xs line-clamp-2 italic mb-4 leading-relaxed">
                          "{clip.description || "No description generated."}"
                        </p>
                        
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => setSelectedClip(i)}
                            className="flex-1 bg-slate-800 hover:bg-slate-700 text-indigo-400 text-[11px] font-bold py-2.5 rounded-lg border border-indigo-500/20 transition-all flex items-center justify-center gap-2"
                          >
                            <Settings2 className="w-3.5 h-3.5" />
                            Settings
                          </button>
                          <button
                            onClick={() => renderClip(i)}
                            disabled={status === "rendering"}
                            className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 text-white text-[11px] font-bold py-2.5 rounded-lg transition-all flex items-center justify-center gap-2 shadow-lg shadow-indigo-600/10"
                          >
                            <Zap className="w-3.5 h-3.5" />
                            Render
                          </button>
                        </div>
                      </div>

                      {/* Expanded Settings */}
                      {selectedClip === i && (
                        <div className="p-4 pt-0 border-t border-white/5 animate-fadeIn">
                          <div className="render-settings border-none p-0 bg-transparent space-y-4">
                            <div className="render-settings-grid !grid-cols-1">
                              <div className="setting-row !bg-slate-950/50">
                                <span className="setting-label text-[10px]">Caption Style</span>
                                <select 
                                  value={getSettings(i).caption_style}
                                  onChange={(e) => updateSetting(i, "caption_style", e.target.value)}
                                  className="setting-select !bg-slate-900 !text-[10px]"
                                >
                                  {["Hormozi", "Modern", "Beast", "Bold", "Minimal"].map(s => <option key={s} value={s}>{s}</option>)}
                                </select>
                              </div>
                              <div className="setting-row !bg-slate-950/50">
                                <span className="setting-label text-[10px]">Music</span>
                                <select 
                                  value={getSettings(i).bg_music_genre}
                                  onChange={(e) => updateSetting(i, "bg_music_genre", e.target.value)}
                                  className="setting-select !bg-slate-900 !text-[10px]"
                                >
                                  {["None", "Lofi", "Energy", "Suspense", "Corporate"].map(s => <option key={s} value={s}>{s}</option>)}
                                </select>
                              </div>
                              <div className="flex items-center justify-between px-3 py-1">
                                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Face Tracking</span>
                                <label className="setting-toggle">
                                  <input type="checkbox" checked={getSettings(i).face_center} onChange={(e) => updateSetting(i, "face_center", e.target.checked)} />
                                  <div className="toggle-track" />
                                </label>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="h-64 border border-dashed border-white/10 rounded-2xl flex flex-col items-center justify-center text-slate-500">
                <Scissors className="w-12 h-12 mb-4 opacity-20" />
                <p>Ready for a URL. The AI Director is standing by.</p>
              </div>
            )}
          </div>
        ) : (
          <div className="animate-fadeIn">
            <div className="flex items-center justify-between mb-8">
              <div>
                <h2 className="text-2xl font-bold text-white">Render Gallery</h2>
                <p className="text-slate-400 text-sm">Your completed viral shorts, ready for download.</p>
              </div>
              <button 
                onClick={fetchGallery}
                className="p-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-slate-400 transition-colors"
              >
                <RefreshCw className={`w-5 h-5 ${status === "rendering" ? "animate-spin" : ""}`} />
              </button>
            </div>

            <div className="gallery-grid">
              {gallery.map((video, i) => (
                <div key={i} className="gallery-card bg-slate-900/60 border border-white/5 flex flex-col">
                  <div className="gallery-preview bg-slate-950 aspect-[9/16]">
                    <video
                      className="gallery-video"
                      src={video.url}
                      muted
                      onMouseOver={e => (e.target as HTMLVideoElement).play()}
                      onMouseOut={e => (e.target as HTMLVideoElement).pause()}
                    />
                    <div className="gallery-play-overlay">
                      <Play className="w-10 h-10 text-white fill-white shadow-xl" />
                    </div>
                  </div>
                  <div className="p-4">
                    <div className="gallery-name truncate mb-1 text-xs font-bold text-white">{video.filename}</div>
                    <div className="text-[10px] text-slate-500 mb-4 uppercase tracking-wider">{(video.size_mb).toFixed(1)} MB • {new Date(video.created_at).toLocaleDateString()}</div>
                    <a 
                      href={video.url} 
                      download 
                      className="w-full bg-slate-800 hover:bg-slate-700 text-indigo-400 text-[11px] font-bold py-2.5 rounded-lg border border-indigo-500/20 transition-all flex items-center justify-center gap-2"
                    >
                      <Download className="w-4 h-4" />
                      Download MP4
                    </a>
                  </div>
                </div>
              ))}
              {gallery.length === 0 && (
                <div className="col-span-full py-20 text-center bg-slate-800/30 rounded-2xl border border-dashed border-white/5">
                  <Film className="w-12 h-12 text-slate-700 mx-auto mb-4" />
                  <p className="text-slate-500 font-medium">No rendered clips yet. Start by strategizing a video.</p>
                </div>
              )}
            </div>
          </div>
        )}
      </main>

      <footer className="py-6 border-t border-white/5 text-center">
        <p className="text-slate-600 text-[10px] font-bold uppercase tracking-widest">
          Powered by ClipFactory v4.1 — SaaS Stability Engine
        </p>
      </footer>
    </div>
  );
}
