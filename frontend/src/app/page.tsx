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

function formatTime(seconds: number): string {
  if (isNaN(seconds) || seconds < 0) return "00:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

/* ------------------------------------------------------------------ */
/*  Main Dashboard                                                     */
/* ------------------------------------------------------------------ */
const DEFAULT_SETTINGS = {
  face_center: true,
  magic_hook: true,
  remove_silence: true,
  caption_style: "Classic",
  caption_pos: "Bottom",
  bg_music_genre: "None",
  broll_intensity: "Medium",
};

export default function Dashboard() {
  const [url, setUrl] = useState("");
  const [status, setStatus] = useState("idle");
  const APP_VERSION = "v2.0.0-PRO-STRATEGY";
  const [logs, setLogs] = useState<string[]>([]);
  const [results, setResults] = useState<any>(null);
  const [backendVersion, setBackendVersion] = useState<string | null>(null);
  const [selectedClip, setSelectedClip] = useState<number | null>(null);
  const [activeView, setActiveView] = useState<"workspace" | "gallery">("workspace");
  const [gallery, setGallery] = useState<GalleryItem[]>([]);
  const logEndRef = useRef<HTMLDivElement>(null);
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
    axios.get(`${API_BASE}/heartbeat`)
      .then(res => setBackendVersion(res.data.version))
      .catch(() => setBackendVersion("Offline"));
    axios.get(`${API_BASE}/config`)
      .then(res => setCatalogData(res.data))
      .catch(() => {});
  }, []);

  // Auto-populate render settings from persona
  useEffect(() => {
    if (results?.clips?.length && results?.persona) {
      const base = {
        ...DEFAULT_SETTINGS,
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

  // Blocklist regex — reject raw backend noise from the log console
  const LOG_BLOCKLIST = /DEBUG|ffmpeg|whisper|model_load|frame=|bitrate=|speed=|Lsize=|muxing overhead|Stream #|libx26|matroska|ggml|llama_|llm_load|VRAM|size=\s*\d|cublas|metal|cuda|opengl|vulkan/i;

  const handleWsMessage = (event: MessageEvent) => {
    try {
      const entry = JSON.parse(event.data);
      if (entry.type === "progress") {
        setProgress({ percent: entry.percent || 0, message: entry.message || "" });
      } else if (entry.type === "error") {
        setLogs(prev => [...prev, `❌ ERROR: ${entry.message}`]);
      } else if (entry.type === "status") {
        if (!LOG_BLOCKLIST.test(entry.message)) {
          setLogs(prev => [...prev, entry.message]);
        }
      }
    } catch {
      // Legacy fallback — plain string, still filter
      if (!LOG_BLOCKLIST.test(event.data)) {
        setLogs(prev => [...prev, event.data]);
      }
    }
  };

  const handleStrategize = async () => {
    if (!url) return;
    setStatus("strategizing");
    setLogs(["Initializing AI Director Pipeline..."]);
    setSelectedClip(null);

    const ws = new WebSocket(wsUrl());
    ws.onmessage = handleWsMessage;

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
    ws.onmessage = handleWsMessage;

    try {
      const settings = getSettings(index);
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
    <div className="grid grid-cols-[320px_1fr_300px] h-screen overflow-hidden bg-slate-50 text-slate-900">
      
      {/* ── Left Sidebar ────────────────────────────────── */}
      <div className="flex flex-col h-full relative p-6">
        <div className="flex-shrink-0">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-indigo-500 rounded-xl flex items-center justify-center shadow-md shadow-indigo-500/10">
              <Film className="w-5 h-5 text-white" />
            </div>
            <h1 className="text-xl font-bold tracking-tight text-slate-800">
              ClipFactory<span className="text-indigo-500">.ai</span>
            </h1>
          </div>
          
          {/* URL Input & Generate */}
          <div className="flex-shrink-0 space-y-4">
            <div className="relative group">
              <input
                type="text"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://youtube.com/watch?v=..."
                className="w-full bg-slate-50 border border-slate-200 focus:border-indigo-400 focus:ring-4 focus:ring-indigo-500/10 rounded-xl py-3 px-4 pl-10 text-slate-800 placeholder:text-slate-400 transition-all text-sm shadow-inner"
              />
              <Film className="absolute left-3 top-3 w-4 h-4 text-slate-400 group-focus-within:text-indigo-500 transition-colors" />
            </div>

            <div className="bg-slate-50 p-3 rounded-xl border border-slate-200">
              <label className="text-[10px] uppercase font-bold text-slate-500 block mb-1">Target Platform</label>
              <div className="w-full bg-slate-100 text-slate-500 text-xs font-medium p-2 rounded border border-slate-200 cursor-not-allowed">
                Target: 9:16 Mobile Short-Form
              </div>
            </div>

            <div className="flex gap-2">
              <button
                onClick={handleStrategize}
                disabled={status !== "idle" || !url}
                className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-300 disabled:opacity-50 text-white font-bold py-3 rounded-xl flex items-center justify-center gap-2 transition-all text-sm shadow-md active:scale-[0.98]"
              >
                {status === "strategizing" ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                {status === "strategizing" ? "Strategizing..." : "Generate"}
              </button>
              {status === "strategizing" && (
                <button
                  onClick={handleCancel}
                  className="bg-rose-50 hover:bg-rose-100 text-rose-600 border border-rose-200 font-bold py-3 px-4 rounded-xl flex items-center justify-center transition-all active:scale-[0.98]"
                >
                  <StopCircle className="w-4 h-4" />
                </button>
              )}
            </div>
            {(status === "done" || status === "error") && (
              <button
                onClick={handleReset}
                className="w-full bg-slate-100 hover:bg-slate-200 text-slate-600 border border-slate-200 font-bold py-3 px-4 rounded-xl flex items-center justify-center gap-2 transition-all text-sm active:scale-[0.98]"
              >
                <Trash2 className="w-4 h-4" />
                Start Over
              </button>
            )}
          </div>
        </div>

        {/* Console */}
        <div className="absolute bottom-6 left-6 right-6 top-[340px] overflow-y-auto bg-black rounded-md p-2 border border-gray-800 custom-scrollbar">
          <div className="shrink-0 px-2 pt-1 pb-2 flex items-center gap-2 text-slate-400 font-sans uppercase tracking-widest font-bold text-[10px] border-b border-slate-800 mb-2">
            <Activity className="w-3 h-3" /> System Logs
          </div>
            <div className="text-white font-mono text-xs leading-relaxed pb-4">
              {logs.length === 0 && <div className="text-slate-500 italic">No activity yet.</div>}
              {logs.map((log, i) => (
                <div key={i} className="mb-1.5 flex gap-2">
                  <span className="text-slate-500 shrink-0 select-none">{String(i + 1).padStart(2, '0')}</span>
                  <span className={log.includes("✅") || log.includes("Complete") ? "text-emerald-400" : log.includes("❌") || log.includes("ERROR") ? "text-red-400" : log.includes("Phase") ? "text-indigo-400" : ""}>{log}</span>
                </div>
              ))}
              <div ref={logEndRef} />
            </div>
          </div>
      </div>

      {/* ── Center Main Area ────────────────────────────────── */}
      <div className="flex-1 h-full overflow-y-auto p-8 relative custom-scrollbar">
        {(status === "strategizing" || status === "rendering") && progress && (
          <div className="bg-white border border-slate-200 rounded-xl p-5 mb-8 shadow-sm">
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

        {/* AI Setup (if not generated yet) */}
        {!results && (
          <div className="flex gap-4 mb-8">
            <div className="flex-1 bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
              <label className="text-[11px] uppercase font-bold text-slate-500 block mb-1">Main AI Director</label>
              <select
                value={llmLabel}
                onChange={(e) => setLlmLabel(e.target.value)}
                className="w-full bg-slate-50 border border-slate-100 rounded-lg p-2 text-slate-700 text-sm font-medium outline-none cursor-pointer"
              >
                {catalogData.llm_catalog.map((m: any) => (
                  <option key={m.label} value={m.label}>{m.label}</option>
                ))}
              </select>
            </div>
            <div className="flex-1 bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
              <label className="text-[11px] uppercase font-bold text-slate-500 block mb-1">Transcription Engine</label>
              <select
                value={whisperLabel}
                onChange={(e) => setWhisperLabel(e.target.value)}
                className="w-full bg-slate-50 border border-slate-100 rounded-lg p-2 text-slate-700 text-sm font-medium outline-none cursor-pointer"
              >
                {catalogData.whisper_catalog.map((m: any) => (
                  <option key={m.label} value={m.label}>{m.label}</option>
                ))}
              </select>
            </div>
          </div>
        )}

        {/* Workspace / Extracted Clips */}
        {results ? (
          <div className="mb-12 animate-fadeIn">
            <div className="flex items-center justify-between border-b border-slate-200 pb-4 mb-6">
              <div>
                <h3 className="text-xl font-bold text-slate-800">Clip Strategy Result</h3>
                <p className="text-slate-500 text-xs">Persona: <span className="text-indigo-600 font-semibold">{results.persona?.type || "General"}</span></p>
              </div>
              <div className="flex items-center gap-2">
                <div className="bg-indigo-50 text-indigo-600 px-3 py-1 rounded-full text-xs font-bold border border-indigo-100">
                  {results.clips?.length || 0} Clips Found
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              {results.clips?.map((clip: any, i: number) => (
                <div key={i} onClick={() => setSelectedClip(i)} className={`cursor-pointer group flex flex-col border transition-all duration-300 shadow-sm overflow-hidden rounded-2xl ${selectedClip === i ? 'border-indigo-500 ring-2 ring-indigo-500/20 bg-indigo-50/30' : 'border-slate-200 bg-white hover:border-indigo-300 hover:shadow-md'}`}>
                  <div className="flex h-40">
                    <div className="bg-slate-900 w-28 shrink-0 relative overflow-hidden flex flex-col items-center justify-center text-center p-2">
                      <div className="text-white font-bold text-[10px] mb-1 leading-tight drop-shadow-md line-clamp-3">{clip.title || "Untitled Clip"}</div>
                      <div className="text-white/80 text-[9px] uppercase tracking-widest font-bold flex items-center justify-center gap-1 mt-2">
                        <Clock className="w-3 h-3" />
                        {formatTime(clip.duration || (parseFloat(clip.end_time || 0) - parseFloat(clip.start_time || 0)))}
                      </div>
                      <div className="absolute top-2 left-2 bg-white/90 backdrop-blur text-[9px] font-bold text-slate-800 px-1.5 py-0.5 rounded shadow-sm flex items-center gap-1">
                        <TrendingUp className="w-2.5 h-2.5 text-emerald-500" /> {Math.round(clip.score || 0)}
                      </div>
                    </div>

                    <div className="p-4 flex-1 flex flex-col justify-between">
                      <div className="space-y-2">
                        <p className="text-[11px] text-slate-700 border-l-2 border-indigo-200 pl-2 italic line-clamp-3">
                          <span className="font-bold text-indigo-500 mr-1 not-italic">Hook:</span> 
                          "{clip.hook_sentence || clip.description}"
                        </p>
                      </div>
                      <div className="flex items-center gap-2 mt-3">
                        <button
                          onClick={(e) => { e.stopPropagation(); renderClip(i); }}
                          disabled={status === "rendering"}
                          className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-300 text-white text-[10px] font-bold py-2 rounded-lg transition-all flex items-center justify-center gap-1.5 shadow-sm"
                        >
                          <Zap className="w-3 h-3" />
                          Render
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="h-40 border border-dashed border-slate-300 rounded-2xl flex flex-col items-center justify-center text-slate-400 bg-white mb-12">
            <Scissors className="w-10 h-10 mb-3 opacity-20" />
            <p className="font-medium text-sm">Ready for a URL. The AI Director is standing by.</p>
          </div>
        )}

        {/* Gallery Section */}
        <div className="animate-fadeIn">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-xl font-bold text-slate-800">Render Gallery</h2>
            </div>
            <button 
              onClick={fetchGallery}
              className="p-1.5 bg-white border border-slate-200 hover:bg-slate-50 rounded-lg text-slate-500 transition-colors shadow-sm"
            >
              <RefreshCw className={`w-4 h-4 ${status === "rendering" ? "animate-spin" : ""}`} />
            </button>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {gallery.map((video, i) => (
              <div key={i} className="bg-white border border-slate-200 shadow-sm flex flex-col overflow-hidden rounded-xl">
                <div className="bg-slate-900 aspect-[9/16] relative group">
                  <video
                    className="w-full h-full object-cover"
                    src={video.url}
                    muted
                    onMouseOver={e => (e.target as HTMLVideoElement).play()}
                    onMouseOut={e => (e.target as HTMLVideoElement).pause()}
                  />
                  <div className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Play className="w-8 h-8 text-white fill-white shadow-xl" />
                  </div>
                </div>
                <div className="p-3 bg-white">
                  <div className="truncate mb-1 text-[10px] font-bold text-slate-800">{video.filename}</div>
                  <div className="text-[9px] text-slate-500 mb-3 uppercase tracking-wider">{(video.size_mb).toFixed(1)} MB</div>
                  <a 
                    href={video.url} 
                    download 
                    className="w-full bg-slate-50 hover:bg-slate-100 text-indigo-600 text-[10px] font-bold py-2 rounded-lg border border-slate-200 transition-all flex items-center justify-center gap-1.5"
                  >
                    <Download className="w-3.5 h-3.5" />
                    Download
                  </a>
                </div>
              </div>
            ))}
            {gallery.length === 0 && (
              <div className="col-span-full py-12 text-center bg-white rounded-2xl border border-dashed border-slate-300 shadow-sm">
                <Film className="w-10 h-10 text-slate-300 mx-auto mb-3" />
                <p className="text-slate-500 font-medium text-sm">No rendered clips yet.</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Right Sidebar ────────────────────────────────── */}
      <div className="w-[300px] h-full overflow-y-auto bg-white border-l border-slate-200 z-10 custom-scrollbar shadow-sm">
        <div className="p-5 border-b border-slate-100 bg-slate-50 sticky top-0 z-20">
          <h3 className="font-bold text-slate-800 flex items-center gap-2">
            <Settings2 className="w-5 h-5 text-indigo-500" />
            Advanced Settings
          </h3>
        </div>
        
        {selectedClip !== null && results?.clips[selectedClip] ? (
          <div className="p-5 space-y-6 animate-fadeIn">
            <div className="bg-indigo-50 border border-indigo-100 p-3 rounded-xl mb-2">
              <span className="text-[10px] font-bold text-indigo-500 uppercase tracking-widest block mb-1">Editing Clip</span>
              <p className="text-xs font-bold text-indigo-900 line-clamp-1">{results.clips[selectedClip].title || "Selected Clip"}</p>
            </div>

            <div className="flex-shrink-0 space-y-4">
              <div className="space-y-1">
                <span className="text-xs font-bold text-slate-500">Caption Style</span>
                <select
                  value={getSettings(selectedClip).caption_style}
                  onChange={(e) => updateSetting(selectedClip, "caption_style", e.target.value)}
                  className="w-full bg-slate-50 text-slate-800 text-sm border border-slate-200 rounded-lg p-2.5 outline-none"
                >
                  {["Classic", "Pop", "Glow", "Outline", "Minimal", "Fire"].map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className="space-y-1">
                <span className="text-xs font-bold text-slate-500">Music</span>
                <select 
                  value={getSettings(selectedClip).bg_music_genre}
                  onChange={(e) => updateSetting(selectedClip, "bg_music_genre", e.target.value)}
                  className="w-full bg-slate-50 text-slate-800 text-sm border border-slate-200 rounded-lg p-2.5 outline-none"
                >
                  {["None", "Lofi", "Energy", "Suspense", "Corporate"].map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className="space-y-1">
                <span className="text-xs font-bold text-slate-500">B-Roll Intensity</span>
                <select 
                  value={getSettings(selectedClip).broll_intensity}
                  onChange={(e) => updateSetting(selectedClip, "broll_intensity", e.target.value)}
                  className="w-full bg-slate-50 text-slate-800 text-sm border border-slate-200 rounded-lg p-2.5 outline-none"
                >
                  {["None", "Low", "Medium", "High"].map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className="space-y-1">
                <span className="text-xs font-bold text-slate-500">Caption Position</span>
                <select 
                  value={getSettings(selectedClip).caption_pos}
                  onChange={(e) => updateSetting(selectedClip, "caption_pos", e.target.value)}
                  className="w-full bg-slate-50 text-slate-800 text-sm border border-slate-200 rounded-lg p-2.5 outline-none"
                >
                  {["Top", "Center", "Bottom"].map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            </div>
            
            <div className="flex flex-col gap-3">
              <div className="flex items-center justify-between p-3.5 bg-white rounded-xl border border-slate-200 shadow-sm">
                <div>
                  <span className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                    <Eye className="w-3.5 h-3.5 text-indigo-500" /> Face Tracking
                  </span>
                </div>
                <label className="setting-toggle">
                  <input type="checkbox" checked={getSettings(selectedClip).face_center} onChange={(e) => updateSetting(selectedClip, "face_center", e.target.checked)} />
                  <div className="toggle-track bg-slate-300 before:bg-white checked:bg-indigo-500" />
                </label>
              </div>
              <div className="flex items-center justify-between p-3.5 bg-white rounded-xl border border-slate-200 shadow-sm">
                <div>
                  <span className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                    <Sparkles className="w-3.5 h-3.5 text-amber-500" /> Magic Hook
                  </span>
                </div>
                <label className="setting-toggle">
                  <input type="checkbox" checked={getSettings(selectedClip).magic_hook} onChange={(e) => updateSetting(selectedClip, "magic_hook", e.target.checked)} />
                  <div className="toggle-track bg-slate-300 before:bg-white checked:bg-indigo-500" />
                </label>
              </div>
              <div className="flex items-center justify-between p-3.5 bg-white rounded-xl border border-slate-200 shadow-sm">
                <div>
                  <span className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                    <Zap className="w-3.5 h-3.5 text-indigo-500" /> Remove Silences
                  </span>
                </div>
                <label className="setting-toggle">
                  <input type="checkbox" checked={getSettings(selectedClip).remove_silence} onChange={(e) => updateSetting(selectedClip, "remove_silence", e.target.checked)} />
                  <div className="toggle-track bg-slate-300 before:bg-white checked:bg-indigo-500" />
                </label>
              </div>
            </div>

            <div className="pt-4 border-t border-slate-200">
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                  <Type className="w-3.5 h-3.5 text-indigo-500" /> Transcript Cuts
                </span>
                <button 
                  onClick={() => setExcludedSentences(prev => ({...prev, [selectedClip]: []}))} 
                  className="text-[9px] text-indigo-500 hover:text-indigo-600 font-bold uppercase transition-colors"
                >
                  Reset
                </button>
              </div>
              <div className="flex flex-col gap-1.5 max-h-[250px] overflow-y-auto custom-scrollbar p-2 bg-slate-50 rounded-xl border border-slate-200 shadow-inner">
                {getClipSentences(selectedClip).map((s: any, si: number) => {
                  const isExcluded = (excludedSentences[selectedClip] || []).some(ex => ex.start_idx === s.start_idx);
                  return (
                    <button
                      key={si}
                      onClick={() => toggleSentence(selectedClip, s)}
                      className={`text-left text-xs px-3 py-2 rounded-lg border transition-all ${
                        isExcluded 
                          ? "bg-rose-50 text-rose-500 border-rose-200 line-through opacity-75" 
                          : "bg-white text-slate-700 border-slate-200 hover:border-indigo-300 hover:shadow-sm"
                      }`}
                    >
                      {s.text}
                    </button>
                  );
                })}
              </div>
            </div>

            <button 
              onClick={() => renderClip(selectedClip)} 
              className="w-full mt-4 py-3.5 rounded-xl font-bold text-white bg-indigo-600 hover:bg-indigo-500 transition-colors shadow-md shadow-indigo-600/20 flex items-center justify-center gap-2 active:scale-[0.98]"
            >
              <Zap className="w-4 h-4 fill-white" />
              Render This Clip
            </button>
          </div>
        ) : (
          <div className="p-8 text-center text-slate-400 mt-10">
            <Settings2 className="w-10 h-10 mx-auto mb-3 opacity-20" />
            <p className="text-xs font-medium">Select a clip from the workspace to edit its settings.</p>
          </div>
        )}
      </div>

    </div>
  );
}
