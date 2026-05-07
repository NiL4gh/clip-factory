"use client";

import { useState, useEffect, useRef, useMemo } from 'react';
import { 
  Play, Scissors, Sparkles,
  Activity, Zap, CheckCircle2,
  Clock, TrendingUp, Music, Type, Download,
  Film, RefreshCw, Eye, EyeOff, ArrowRight, Settings2, Volume2, StopCircle, Trash2, Tag
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

// Ensure API calls bypass the ngrok free-tier warning page
axios.defaults.headers.common["ngrok-skip-browser-warning"] = "true";

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
  const [targetPlatform, setTargetPlatform] = useState("TikTok / Shorts (Vertical)");
  const [progress, setProgress] = useState<{percent: number; message: string} | null>(null);

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
  const handleCancel = async () => {
    try {
      await axios.post(`${API_BASE}/cancel_strategize`);
      setStatus("idle");
      setProgress(null);
      setLogs(prev => [...prev, "❌ Analysis cancelled by user."]);
    } catch {}
  };

  const handleReset = async () => {
    try {
      await axios.post(`${API_BASE}/reset`);
      setUrl("");
      setStatus("idle");
      setLogs([]);
      setResults(null);
      setSelectedClip(null);
      setProgress(null);
    } catch {}
  };

  const handleStrategize = async () => {
    if (!url) return;
    setStatus("strategizing");
    setLogs(["Initializing AI Director Pipeline..."]);
    setSelectedClip(null);

    const ws = new WebSocket(wsUrl());
    ws.onmessage = (event) => {
      if (event.data.startsWith("PROGRESS|")) {
        const parts = event.data.split("|");
        if (parts.length >= 3) {
          setProgress({ percent: parseInt(parts[1], 10), message: parts[2] });
        }
      } else {
        setLogs(prev => [...prev, event.data]);
      }
    };

    try {
      await axios.post(`${API_BASE}/strategize`, { url, llm_label: llmLabel, whisper_label: whisperLabel, target_platform: targetPlatform });
      const poll = setInterval(async () => {
        const res = await axios.get(`${API_BASE}/results`);
        if (res.data.status === "done") {
          clearInterval(poll);
          setResults(res.data);
          setStatus("done");
          ws.close();
        }
      }, 2000);
    } catch (error: any) {
      const msg = error.response?.data?.detail || error.message || "Unknown error";
      console.error(error);
      setLogs(prev => [...prev, `❌ Error starting strategize phase: ${msg}`]);
      setStatus("error");
      ws.close();
    }
  };

  const renderClip = async (index: number) => {
    setStatus("rendering");
    const ws = new WebSocket(wsUrl());
    ws.onmessage = (event) => {
      if (event.data.startsWith("PROGRESS|")) {
        const parts = event.data.split("|");
        if (parts.length >= 3) {
          setProgress({ percent: parseInt(parts[1], 10), message: parts[2] });
        }
      } else {
        setLogs(prev => [...prev, event.data]);
      }
    };

    try {
      const settings = getSettings(index);
      // Convert excluded sentences from our editor state to the format the backend expects
      const exSentences = (excludedSentences[index] || []).map(s => `[WID:${s.start_idx}-${s.end_idx}] ${s.text}`);

      const res = await axios.post(`${API_BASE}/render`, {
        clip_id: index,
        ...settings,
        excluded_sentences: exSentences
      });
      
      const taskId = res.data.task_id;
      const poll = setInterval(async () => {
        const statusRes = await axios.get(`${API_BASE}/render_status?task_id=${taskId}`);
        if (statusRes.data.status === "done") {
          clearInterval(poll);
          setStatus("done");
          setProgress(null);
          ws.close();
          fetchGallery();
          setActiveView("gallery");
        } else if (statusRes.data.status === "error") {
          clearInterval(poll);
          setStatus("error");
          setLogs(prev => [...prev, `❌ Render Error: ${statusRes.data.error}`]);
          ws.close();
        }
      }, 2000);
    } catch {
      setStatus("error");
      ws.close();
    }
  };

  /* ── Transcript Editor Logic ──────────────────────── */
  const [excludedSentences, setExcludedSentences] = useState<Record<number, {text: string, start_idx: number, end_idx: number}[]>>({});

  const getClipSentences = useMemo(() => (clipIdx: number) => {
    if (!results?.clips?.[clipIdx] || !results?.word_timestamps) return [];
    const clip = results.clips[clipIdx];
    const words = results.word_timestamps;
    
    // Find words in clip range
    const clipSt = parseFloat(clip.start_time || 0);
    const clipEt = parseFloat(clip.end_time || 0);
    const clipWords = words.map((w: any, i: number) => ({ ...w, idx: i }))
      .filter((w: any) => {
        if (clip.is_stitched && clip.segments && clip.segments.length > 0) {
          return clip.segments.some((seg: any) => 
            w.start >= parseFloat(seg.start_time) - 0.5 && 
            w.end <= parseFloat(seg.end_time) + 0.5
          );
        }
        return w.start >= clipSt - 0.5 && w.end <= clipEt + 0.5;
      });

    // Group into "sentences" (~12 words each)
    const sentences = [];
    for (let i = 0; i < clipWords.length; i += 12) {
      const chunk = clipWords.slice(i, i + 12);
      sentences.push({
        text: chunk.map((w: any) => w.word).join(" "),
        start_idx: chunk[0].idx,
        end_idx: chunk[chunk.length - 1].idx
      });
    }
    return sentences;
  }, [results]);

  const toggleSentence = (clipIdx: number, sentence: any) => {
    setExcludedSentences(prev => {
      const current = prev[clipIdx] || [];
      const exists = current.find(s => s.start_idx === sentence.start_idx);
      if (exists) {
        return { ...prev, [clipIdx]: current.filter(s => s.start_idx !== sentence.start_idx) };
      } else {
        return { ...prev, [clipIdx]: [...current, sentence] };
      }
    });
  };

  return (
    <div className="min-h-screen custom-scrollbar flex flex-col bg-slate-50 text-slate-900">
      {/* ── Sticky Navbar ────────────────────────────────── */}
      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-md border-b border-slate-200 py-3 px-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 bg-indigo-500 rounded-xl flex items-center justify-center shadow-md shadow-indigo-500/10">
            <Film className="w-5 h-5 text-white" />
          </div>
          <h1 className="text-xl font-bold tracking-tight text-slate-800">
            ClipFactory<span className="text-indigo-500">.ai</span>
          </h1>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex bg-slate-100 p-1 rounded-lg border border-slate-200">
            <button
              onClick={() => setActiveView("workspace")}
              className={`px-4 py-1.5 rounded-md text-xs font-semibold transition-all ${
                activeView === "workspace" ? "bg-white text-indigo-600 shadow-sm border border-slate-200/50" : "text-slate-500 hover:text-slate-800"
              }`}
            >
              Workspace
            </button>
            <button
              onClick={() => setActiveView("gallery")}
              className={`px-4 py-1.5 rounded-md text-xs font-semibold transition-all ${
                activeView === "gallery" ? "bg-white text-indigo-600 shadow-sm border border-slate-200/50" : "text-slate-500 hover:text-slate-800"
              }`}
            >
              Gallery
            </button>
          </div>
          <div className={`w-3 h-3 rounded-full ${status === "idle" ? "bg-slate-300" : "bg-green-500 animate-pulse"}`} />
        </div>
      </header>

      <main className="flex-1 w-full max-w-5xl mx-auto px-6 py-10">
        
        {activeView === "workspace" ? (
          <div className="animate-fadeIn">
            {/* ── Project Setup Card ─────────────────────────── */}
            <div className="bg-white border border-slate-200 rounded-2xl p-8 mb-10 shadow-sm backdrop-blur-sm">
              <div className="max-w-2xl mx-auto text-center mb-8">
                <h2 className="text-3xl font-bold mb-3 text-slate-900">Create New Project</h2>
                <p className="text-slate-500 text-sm">Paste a YouTube URL to let the AI Director strategize your viral shorts.</p>
              </div>

              <div className="flex flex-col gap-6 max-w-3xl mx-auto">
                <div className="relative group">
                  <input
                    type="text"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://youtube.com/watch?v=..."
                    className="w-full bg-slate-50 border border-slate-200 focus:border-indigo-400 focus:ring-4 focus:ring-indigo-500/10 rounded-xl py-4 px-5 pl-14 text-slate-800 placeholder:text-slate-400 transition-all text-lg shadow-inner"
                  />
                  <Film className="absolute left-5 top-4.5 w-6 h-6 text-slate-400 group-focus-within:text-indigo-500 transition-colors" />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div className="bg-slate-50 p-4 rounded-xl border border-slate-200">
                    <label className="model-selector-label text-slate-500">Target Platform</label>
                    <select
                      value={targetPlatform}
                      onChange={(e) => setTargetPlatform(e.target.value)}
                      className="w-full bg-transparent text-slate-700 text-sm font-medium outline-none cursor-pointer"
                    >
                      {["TikTok / Shorts (Vertical)", "Instagram Reels", "YouTube Longform (Horizontal)"].map((m: any) => (
                        <option key={m} value={m} className="bg-white">{m}</option>
                      ))}
                    </select>
                  </div>
                  <div className="bg-slate-50 p-4 rounded-xl border border-slate-200">
                    <label className="model-selector-label text-slate-500">Main AI Director</label>
                    <select
                      value={llmLabel}
                      onChange={(e) => setLlmLabel(e.target.value)}
                      className="w-full bg-transparent text-slate-700 text-sm font-medium outline-none cursor-pointer"
                    >
                      {catalogData.llm_catalog.map((m: any) => (
                        <option key={m.label} value={m.label} className="bg-white">{m.label}</option>
                      ))}
                    </select>
                  </div>
                  <div className="bg-slate-50 p-4 rounded-xl border border-slate-200">
                    <label className="model-selector-label text-slate-500">Transcription Engine</label>
                    <select
                      value={whisperLabel}
                      onChange={(e) => setWhisperLabel(e.target.value)}
                      className="w-full bg-transparent text-slate-700 text-sm font-medium outline-none cursor-pointer"
                    >
                      {catalogData.whisper_catalog.map((m: any) => (
                        <option key={m.label} value={m.label} className="bg-white">{m.label}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="flex gap-4">
                  <button
                    onClick={handleStrategize}
                    disabled={status !== "idle" || !url}
                    className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-300 disabled:opacity-50 text-white font-bold py-4 rounded-xl flex items-center justify-center gap-3 transition-all shadow-md shadow-indigo-600/10 active:scale-[0.98]"
                  >
                    {status === "strategizing" ? <RefreshCw className="w-5 h-5 animate-spin" /> : <Sparkles className="w-5 h-5" />}
                    {status === "strategizing" ? "Strategizing..." : "Analyze & Strategize"}
                  </button>
                  {status === "strategizing" && (
                    <button
                      onClick={handleCancel}
                      className="bg-rose-50 hover:bg-rose-100 text-rose-600 border border-rose-200 font-bold py-4 px-6 rounded-xl flex items-center justify-center gap-2 transition-all active:scale-[0.98]"
                    >
                      <StopCircle className="w-5 h-5" />
                      Stop
                    </button>
                  )}
                  {(status === "done" || status === "error") && (
                    <button
                      onClick={handleReset}
                      className="bg-slate-100 hover:bg-slate-200 text-slate-600 border border-slate-200 font-bold py-4 px-6 rounded-xl flex items-center justify-center gap-2 transition-all active:scale-[0.98]"
                    >
                      <Trash2 className="w-5 h-5" />
                      Start Over
                    </button>
                  )}
                </div>
              </div>
            </div>

            {status === "strategizing" && progress && (
              <div className="bg-white border border-slate-200 rounded-xl p-5 mb-10 shadow-sm">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-sm font-bold text-slate-800">{progress.message}</span>
                  <span className="text-sm font-bold text-indigo-600">{progress.percent}%</span>
                </div>
                <div className="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden">
                  <div 
                    className="bg-indigo-600 h-2.5 rounded-full transition-all duration-500 ease-out" 
                    style={{ width: `${progress.percent}%` }} 
                  />
                </div>
              </div>
            )}

            {/* ── Activity Console ───────────────────────────── */}
            {(logs.length > 0 || status !== "idle") && (
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-10 font-mono text-[11px] leading-relaxed max-h-[160px] overflow-y-auto custom-scrollbar shadow-inner">
                <div className="flex items-center gap-2 mb-3 text-slate-400 font-sans uppercase tracking-widest font-bold">
                  <Activity className="w-3 h-3" /> System Logs
                </div>
                {logs.map((log, i) => (
                  <div key={i} className="text-slate-300 mb-1 flex gap-3">
                    <span className="text-slate-500 shrink-0">[{new Date().toLocaleTimeString()}]</span>
                    <span className={log.includes("✅") ? "text-emerald-400" : log.includes("❌") ? "text-rose-400" : ""}>{log}</span>
                  </div>
                ))}
                <div ref={logEndRef} />
              </div>
            )}

            {/* ── Results Canvas ─────────────────────────────── */}
            {results ? (
              <div className="space-y-8 animate-fadeIn">
                <div className="flex items-center justify-between border-b border-slate-200 pb-4">
                  <div>
                    <h3 className="text-xl font-bold text-slate-800">Clip Strategy Result</h3>
                    <p className="text-slate-500 text-xs">Persona: <span className="text-indigo-600 font-semibold">{results.persona?.type || "General"}</span></p>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="bg-indigo-50 text-indigo-600 px-3 py-1 rounded-full text-xs font-bold border border-indigo-100">
                      {results.clips?.length || 0} Clips Found
                    </div>
                    {results.estimated_clips > 0 && (
                      <div className="bg-slate-100 text-slate-500 px-3 py-1 rounded-full text-xs font-bold border border-slate-200">
                        ~{results.estimated_clips} Estimated Potential
                      </div>
                    )}
                  </div>
                </div>

                <div className="gallery-grid">
                  {results.clips.map((clip: any, i: number) => (
                    <div key={i} className="gallery-card group flex flex-col border border-slate-200 bg-white hover:border-indigo-300 transition-all duration-300 shadow-sm hover:shadow-md">
                      <div className="gallery-preview bg-slate-900 aspect-[9/16] relative overflow-hidden">
                        <div className="absolute inset-0 flex flex-col items-center justify-center p-6 text-center space-y-4">
                          <div className="w-12 h-12 rounded-full bg-white/10 flex items-center justify-center text-white group-hover:scale-110 transition-transform backdrop-blur-sm border border-white/20">
                            <Scissors className="w-6 h-6" />
                          </div>
                          <div>
                            <div className="text-white font-bold text-sm mb-1 leading-tight drop-shadow-md">{clip.title || "Untitled Clip"}</div>
                            <div className="text-white/80 text-[10px] uppercase tracking-widest font-bold">
                              {Math.round(clip.duration || (parseFloat(clip.end_time || 0) - parseFloat(clip.start_time || 0)))}s Duration
                            </div>
                          </div>
                        </div>
                        <div className="gallery-play-overlay bg-indigo-900/40 backdrop-blur-[2px]">
                          <button 
                            onClick={() => setSelectedClip(i)}
                            className="bg-white text-indigo-600 w-12 h-12 rounded-full flex items-center justify-center shadow-xl hover:scale-110 transition-all active:scale-95"
                          >
                            <Settings2 className="w-5 h-5" />
                          </button>
                        </div>
                        <div className="absolute top-3 left-3 bg-white/90 backdrop-blur text-[10px] font-bold text-slate-800 px-2 py-1 rounded border border-white/20 uppercase tracking-tighter shadow-sm flex items-center gap-1">
                          <TrendingUp className="w-3 h-3 text-emerald-500" />
                          Virality Score: {Math.round(clip.score || 0)}
                        </div>
                      </div>

                      <div className="p-4 flex-1 flex flex-col justify-between bg-white">
                        <p className="text-slate-600 text-xs line-clamp-2 italic mb-3 leading-relaxed">
                          "{clip.description || clip.hook_sentence || "No description generated."}"
                        </p>
                        {clip.virality_reason && (
                          <div className="mb-3 bg-indigo-50 border border-indigo-100 text-indigo-700 text-[10px] font-medium px-2 py-1.5 rounded-md flex items-start gap-1.5">
                            <Tag className="w-3 h-3 mt-0.5 shrink-0" />
                            <span className="leading-snug">{clip.virality_reason}</span>
                          </div>
                        )}
                        {clip.source_topic && (
                          <div className="mb-3 bg-slate-50 border border-slate-200 text-slate-500 text-[10px] font-medium px-2 py-1 rounded-md truncate">
                            📌 {clip.source_topic}
                          </div>
                        )}
                        
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => setSelectedClip(i)}
                            className="flex-1 bg-slate-50 hover:bg-slate-100 text-indigo-600 text-[11px] font-bold py-2.5 rounded-lg border border-slate-200 transition-all flex items-center justify-center gap-2"
                          >
                            <Settings2 className="w-3.5 h-3.5" />
                            Settings
                          </button>
                          <button
                            onClick={() => renderClip(i)}
                            disabled={status === "rendering"}
                            className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-300 text-white text-[11px] font-bold py-2.5 rounded-lg transition-all flex items-center justify-center gap-2 shadow-sm"
                          >
                            <Zap className="w-3.5 h-3.5" />
                            Render
                          </button>
                        </div>
                      </div>

                      {/* Expanded Settings */}
                      {selectedClip === i && (
                        <div className="p-4 pt-0 border-t border-slate-100 bg-slate-50 animate-fadeIn">
                          <div className="render-settings border-none p-0 bg-transparent space-y-4">
                            <div className="render-settings-grid !grid-cols-1">
                              <div className="setting-row !bg-white border border-slate-200">
                                <span className="setting-label text-[10px] text-slate-500">Caption Style</span>
                                <select 
                                  value={getSettings(i).caption_style}
                                  onChange={(e) => updateSetting(i, "caption_style", e.target.value)}
                                  className="setting-select !bg-slate-50 !text-slate-800 !text-[10px] border border-slate-200"
                                >
                                  {["Hormozi", "Modern", "Beast", "Bold", "Minimal"].map(s => <option key={s} value={s}>{s}</option>)}
                                </select>
                              </div>
                              <div className="setting-row !bg-white border border-slate-200">
                                <span className="setting-label text-[10px] text-slate-500">Music</span>
                                <select 
                                  value={getSettings(i).bg_music_genre}
                                  onChange={(e) => updateSetting(i, "bg_music_genre", e.target.value)}
                                  className="setting-select !bg-slate-50 !text-slate-800 !text-[10px] border border-slate-200"
                                >
                                  {["None", "Lofi", "Energy", "Suspense", "Corporate"].map(s => <option key={s} value={s}>{s}</option>)}
                                </select>
                              </div>
                              <div className="setting-row !bg-white border border-slate-200">
                                <span className="setting-label text-[10px] text-slate-500">B-Roll Intensity</span>
                                <select 
                                  value={getSettings(i).broll_intensity}
                                  onChange={(e) => updateSetting(i, "broll_intensity", e.target.value)}
                                  className="setting-select !bg-slate-50 !text-slate-800 !text-[10px] border border-slate-200"
                                >
                                  {["None", "Low", "Medium", "High"].map(s => <option key={s} value={s}>{s}</option>)}
                                </select>
                              </div>
                              <div className="setting-row !bg-white border border-slate-200">
                                <span className="setting-label text-[10px] text-slate-500">Caption Position</span>
                                <select 
                                  value={getSettings(i).caption_pos}
                                  onChange={(e) => updateSetting(i, "caption_pos", e.target.value)}
                                  className="setting-select !bg-slate-50 !text-slate-800 !text-[10px] border border-slate-200"
                                >
                                  {["Top", "Center", "Bottom"].map(s => <option key={s} value={s}>{s}</option>)}
                                </select>
                              </div>
                              
                              <div className="flex flex-col gap-2 px-1">
                                <div className="flex items-center justify-between px-3 py-1 bg-white rounded-lg border border-slate-100">
                                  <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest flex items-center gap-2">
                                    <Eye className="w-3 h-3 text-indigo-400" /> Face Tracking
                                  </span>
                                  <label className="setting-toggle">
                                    <input type="checkbox" checked={getSettings(i).face_center} onChange={(e) => updateSetting(i, "face_center", e.target.checked)} />
                                    <div className="toggle-track bg-slate-300 before:bg-white checked:bg-indigo-500" />
                                  </label>
                                </div>
                                <div className="flex items-center justify-between px-3 py-1 bg-white rounded-lg border border-slate-100">
                                  <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest flex items-center gap-2">
                                    <Sparkles className="w-3 h-3 text-amber-400" /> Magic Hook
                                  </span>
                                  <label className="setting-toggle">
                                    <input type="checkbox" checked={getSettings(i).magic_hook} onChange={(e) => updateSetting(i, "magic_hook", e.target.checked)} />
                                    <div className="toggle-track bg-slate-300 before:bg-white checked:bg-indigo-500" />
                                  </label>
                                </div>
                                <div className="flex items-center justify-between px-3 py-1 bg-white rounded-lg border border-slate-100">
                                  <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest flex items-center gap-2">
                                    <Zap className="w-3 h-3 text-indigo-400" /> Remove Silences
                                  </span>
                                  <label className="setting-toggle">
                                    <input type="checkbox" checked={getSettings(i).remove_silence} onChange={(e) => updateSetting(i, "remove_silence", e.target.checked)} />
                                    <div className="toggle-track bg-slate-300 before:bg-white checked:bg-indigo-500" />
                                  </label>
                                </div>
                              </div>

                                <div className="mt-4 pt-4 border-t border-slate-200">
                                  <div className="flex items-center justify-between mb-3">
                                    <span className="text-[10px] font-bold text-slate-800 uppercase tracking-widest flex items-center gap-2">
                                      <Type className="w-3 h-3 text-indigo-500" /> Transcript Editor
                                    </span>
                                    <div className="flex items-center gap-3">
                                      <button 
                                        onClick={() => setExcludedSentences(prev => ({...prev, [i]: []}))} 
                                        className="text-[9px] text-slate-400 hover:text-indigo-500 font-bold uppercase transition-colors"
                                      >
                                        Reset Cuts
                                      </button>
                                      <span className="text-[8px] text-slate-400 uppercase">Click to cut</span>
                                    </div>
                                  </div>
                                  <div className="flex flex-wrap gap-2 max-h-[250px] overflow-y-auto custom-scrollbar p-2 bg-slate-50 rounded-lg border border-slate-200">
                                    {getClipSentences(i).map((s: any, si: number) => {
                                      const isExcluded = (excludedSentences[i] || []).some(ex => ex.start_idx === s.start_idx);
                                      return (
                                        <button
                                          key={si}
                                          onClick={() => toggleSentence(i, s)}
                                          className={`text-left text-xs px-2.5 py-1.5 rounded-md border transition-all ${
                                            isExcluded 
                                              ? "bg-rose-50 text-rose-400 border-rose-200 line-through" 
                                              : "bg-white text-slate-700 border-slate-200 hover:border-indigo-300 hover:shadow-sm"
                                          }`}
                                        >
                                          {s.text}
                                        </button>
                                      );
                                    })}
                                  </div>
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
              <div className="h-64 border border-dashed border-slate-300 rounded-2xl flex flex-col items-center justify-center text-slate-400 bg-white">
                <Scissors className="w-12 h-12 mb-4 opacity-20" />
                <p className="font-medium">Ready for a URL. The AI Director is standing by.</p>
              </div>
            )}
          </div>
        ) : (
          <div className="animate-fadeIn">
            <div className="flex items-center justify-between mb-8">
              <div>
                <h2 className="text-2xl font-bold text-slate-800">Render Gallery</h2>
                <p className="text-slate-500 text-sm">Your completed viral shorts, ready for download.</p>
              </div>
              <button 
                onClick={fetchGallery}
                className="p-2 bg-white border border-slate-200 hover:bg-slate-50 rounded-lg text-slate-500 transition-colors shadow-sm"
              >
                <RefreshCw className={`w-5 h-5 ${status === "rendering" ? "animate-spin" : ""}`} />
              </button>
            </div>

            <div className="gallery-grid">
              {gallery.map((video, i) => (
                <div key={i} className="gallery-card bg-white border border-slate-200 shadow-sm flex flex-col overflow-hidden rounded-2xl">
                  <div className="gallery-preview bg-slate-900 aspect-[9/16] relative">
                    <video
                      className="w-full h-full object-cover"
                      src={video.url}
                      muted
                      onMouseOver={e => (e.target as HTMLVideoElement).play()}
                      onMouseOut={e => (e.target as HTMLVideoElement).pause()}
                    />
                    <div className="absolute inset-0 flex items-center justify-center bg-black/20 opacity-0 hover:opacity-100 transition-opacity">
                      <Play className="w-10 h-10 text-white fill-white shadow-xl" />
                    </div>
                  </div>
                  <div className="p-4 bg-white">
                    <div className="truncate mb-1 text-xs font-bold text-slate-800">{video.filename}</div>
                    <div className="text-[10px] text-slate-500 mb-4 uppercase tracking-wider">{(video.size_mb).toFixed(1)} MB • {new Date(video.created_at).toLocaleDateString()}</div>
                    <a 
                      href={video.url} 
                      download 
                      className="w-full bg-slate-50 hover:bg-slate-100 text-indigo-600 text-[11px] font-bold py-2.5 rounded-lg border border-slate-200 transition-all flex items-center justify-center gap-2"
                    >
                      <Download className="w-4 h-4" />
                      Download MP4
                    </a>
                  </div>
                </div>
              ))}
              {gallery.length === 0 && (
                <div className="col-span-full py-20 text-center bg-white rounded-2xl border border-dashed border-slate-300 shadow-sm">
                  <Film className="w-12 h-12 text-slate-300 mx-auto mb-4" />
                  <p className="text-slate-500 font-medium">No rendered clips yet. Start by strategizing a video.</p>
                </div>
              )}
            </div>
          </div>
        )}
      </main>

      <footer className="py-6 border-t border-slate-200 text-center bg-white">
        <p className="text-slate-400 text-[10px] font-bold uppercase tracking-widest">
          Powered by ClipFactory v4.1 — SaaS Stability Engine
        </p>
      </footer>
    </div>
  );
}
