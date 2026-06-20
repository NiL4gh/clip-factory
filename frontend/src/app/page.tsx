"use client";

import { useState, useEffect, useRef, useMemo } from 'react';
import { 
  Play, Scissors, Sparkles,
  Activity, Zap, CheckCircle2,
  Clock, TrendingUp, Music, Type, Download,
  Film, RefreshCw, Eye, EyeOff, ArrowRight, Settings2, Volume2, StopCircle, Trash2, Tag, Copy
} from 'lucide-react';
import axios from 'axios';
import { ClipPreview } from '@/components/ClipPreview';
import { DarkModeToggle } from '@/components/DarkModeToggle';
import { ErrorBoundary } from '@/components/ErrorBoundary';

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

// Bypass tunnel warning pages (localtunnel + ngrok)
axios.defaults.headers.common["Bypass-Tunnel-Reminder"] = "true";
axios.defaults.headers.common["ngrok-skip-browser-warning"] = "true";

const SESSION_URL_KEY = "cf_last_url";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */
interface GalleryItem {
  filename: string;
  url: string;
  size_mb: number;
  created_at: string;
  created_at_ts?: number;
  duration?: number;
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

function formatEta(seconds: number | undefined | null): string {
  if (seconds === undefined || seconds === null || isNaN(seconds) || seconds < 0) return "";
  if (seconds < 60) return `${seconds}s remaining`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s remaining`;
}

/* ------------------------------------------------------------------ */
/*  Main Dashboard                                                     */
/* ------------------------------------------------------------------ */
// Defaults match the "viral" preset so clips look intentional out of the box.
// Fields not exposed in the simplified UI keep these sensible values and are still
// sent to the backend (which supports all of them) — see STYLE_PRESETS below.
const DEFAULT_SETTINGS = {
  face_center: true,
  magic_hook: true,
  remove_silence: true,
  caption_style: "Pop",
  caption_pos: "bottom",
  bg_music_genre: "None",
  bg_music_vol: 0.5,
  bg_style: "brand",
  layout_mode: "box",
  hook_position: "top",
  hook_display: "3s",
  hook_style: "BlackOnWhiteBox",
  show_outro: false,
  title_style: "Impact",
  template: "viral",
  header_font: "montserrat-black",
  caption_font: "montserrat",
  hook_font: "montserrat",
  header_style: "card",
};

// Proven style combinations. Picking a preset writes the individual fields below
// (the backend reads those, not `template`); `template` is remembered only so the
// dropdown can show which preset is active. No more silent overwrites — each preset
// states exactly what it changes.
const STYLE_PRESETS: Record<string, { label: string; summary: string; changes: Record<string, string> }> = {
  viral: {
    label: "🔥 Viral",
    summary: "Bold Pop captions, brand background, hook header for the first 5s. Best for talking-head clips.",
    changes: { layout_mode: "box", bg_style: "brand", caption_style: "Pop", title_style: "Impact", hook_display: "5s", header_style: "stroke" },
  },
  clean: {
    label: "✨ Clean",
    summary: "Classic captions on a white background, simple boxed header, hook for 5s.",
    changes: { layout_mode: "box", bg_style: "white", caption_style: "Classic", title_style: "Box", hook_display: "5s", header_style: "card" },
  },
  cinematic: {
    label: "🎬 Cinematic",
    summary: "Full-frame blurred background, cinematic captions, hook for 5s.",
    changes: { layout_mode: "box", bg_style: "blur", caption_style: "CinematicSlate", title_style: "None", hook_display: "5s", header_style: "card" },
  },
};

const FONT_MAP: Record<string, string> = {
  'bebas': 'Bebas Neue',
  'bebas neue': 'Bebas Neue',
  'montserrat': 'Montserrat',
  'montserrat-black': 'Montserrat Black',
  'inter': 'Inter',
  'roboto': 'Roboto',
  'poppins': 'Poppins'
};

/* ------------------------------------------------------------------ */
/*  Style Seeds — curated combinations for per-clip randomisation     */
/* ------------------------------------------------------------------ */
type StyleSeed = {
  id: string;
  label: string;
  badgeColor: string; // Tailwind classes for badge background + text + border
  changes: Record<string, string>;
};

const STYLE_SEEDS: StyleSeed[] = [
  {
    id: "viral_stroke",
    label: "🔥 Viral",
    badgeColor: "bg-orange-100 text-orange-700 border-orange-200",
    changes: { layout_mode: "box", bg_style: "brand", caption_style: "Pop", title_style: "Impact", hook_display: "5s", header_style: "stroke", header_font: "montserrat-black", caption_font: "montserrat", hook_font: "montserrat" },
  },
  {
    id: "viral_dark",
    label: "🌑 Dark Pop",
    badgeColor: "bg-slate-800 text-slate-100 border-slate-700",
    changes: { layout_mode: "box", bg_style: "black", caption_style: "Pop", title_style: "Impact", hook_display: "5s", header_style: "card", header_font: "montserrat-black", caption_font: "montserrat", hook_font: "montserrat" },
  },
  {
    id: "clean_white",
    label: "✨ Clean",
    badgeColor: "bg-slate-100 text-slate-700 border-slate-300",
    changes: { layout_mode: "box", bg_style: "white", caption_style: "Classic", title_style: "Box", hook_display: "5s", header_style: "card", header_font: "montserrat-black", caption_font: "poppins", hook_font: "poppins" },
  },
  {
    id: "brand_minimal",
    label: "🎯 Minimal",
    badgeColor: "bg-blue-100 text-blue-700 border-blue-200",
    changes: { layout_mode: "box", bg_style: "brand", caption_style: "Classic", title_style: "None", hook_display: "5s", header_style: "card", header_font: "inter", caption_font: "roboto", hook_font: "roboto" },
  },
  {
    id: "blur_punch",
    label: "💥 Punch",
    badgeColor: "bg-purple-100 text-purple-700 border-purple-200",
    changes: { layout_mode: "box", bg_style: "blur", caption_style: "Pop", title_style: "Impact", hook_display: "5s", header_style: "stroke", header_font: "montserrat-black", caption_font: "montserrat", hook_font: "montserrat" },
  },
  {
    id: "cinematic",
    label: "🎬 Cinematic",
    badgeColor: "bg-rose-100 text-rose-700 border-rose-200",
    changes: { layout_mode: "box", bg_style: "blur", caption_style: "CinematicSlate", title_style: "None", hook_display: "5s", header_style: "card", header_font: "inter", caption_font: "poppins", hook_font: "poppins" },
  },
];

/** Shuffle 6 seeds into a no-adjacent-duplicate assignment for `count` clips. */
function assignSeedsToClips(count: number): Record<number, string> {
  const ids = STYLE_SEEDS.map(s => s.id);
  const shuffle = (arr: string[]) => {
    const a = [...arr];
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  };
  // Build pool: repeated shuffles, fixing seam duplicates between cycles
  let pool: string[] = [];
  while (pool.length < count) {
    let next = shuffle(ids);
    if (pool.length > 0 && next[0] === pool[pool.length - 1]) {
      [next[0], next[1]] = [next[1], next[0]];
    }
    pool = pool.concat(next);
  }
  const result: Record<number, string> = {};
  for (let i = 0; i < count; i++) result[i] = pool[i];
  return result;
}

export default function Dashboard() {
  const [url, setUrl] = useState("");
  const sessionId = useMemo(() => crypto.randomUUID(), []);
  const [backendStatus, setBackendStatus] = useState<'connected' | 'disconnected'>('disconnected');

  useEffect(() => {
    const check = async () => {
      try {
        // Try relative URL first (same origin), then fallback
        const res = await fetch('/health', { 
          signal: AbortSignal.timeout(5000),
          cache: 'no-store'
        });
        setBackendStatus(res.ok ? 'connected' : 'disconnected');
      } catch (err) {
        console.warn('Health check failed:', err);
        setBackendStatus('disconnected');
        bootstrapDoneRef.current = false;
      }
    };
    check();
    const interval = setInterval(check, 10000);
    return () => clearInterval(interval);
  }, []);
  const [status, setStatus] = useState("idle");
  const APP_VERSION = "v2.1.0-FINAL-OPUS";
  const [logs, setLogs] = useState<string[]>([]);
  const [results, setResults] = useState<any>(null);
  const [backendVersion, setBackendVersion] = useState<string | null>(null);
  const [selectedClip, setSelectedClip] = useState<number | null>(null);
  const [activeView, setActiveView] = useState<"workspace" | "gallery">("workspace");
  const [gallery, setGallery] = useState<GalleryItem[]>([]);
  const [gallerySessionMode, setGallerySessionMode] = useState<"current" | "all">("current");
  const logEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const strategizePollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const renderPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const bootstrapDoneRef = useRef(false);
  const [progress, setProgress] = useState<{percent: number; message: string; eta?: number | null} | null>(null);
  const [recoveryBanner, setRecoveryBanner] = useState<string | null>(null);
  const [backendJobRunning, setBackendJobRunning] = useState({ is_strategizing: false, is_rendering: false });
  const [showPreview, setShowPreview] = useState(false);

  // Model selectors
  const [llmLabel, setLlmLabel] = useState("🦙 LLaMA 3.1 8B Instruct Q4");
  const [whisperLabel, setWhisperLabel] = useState("⭐ medium");
  const [catalogData, setCatalogData] = useState<{llm_catalog:{label:string}[], whisper_catalog:{label:string}[], bgm_genres:string[]}>({llm_catalog:[], whisper_catalog:[], bgm_genres:[]});
  const [renderSettings, setRenderSettings] = useState<Record<number, typeof DEFAULT_SETTINGS>>({});

  // New UI states
  const [globalSettings, setGlobalSettings] = useState(DEFAULT_SETTINGS);
  const [cardRenderStates, setCardRenderStates] = useState<Record<number, "idle" | "queued" | "rendering" | "done" | "error">>({});
  const [sortBy, setSortBy] = useState<"score" | "energy" | "duration" | "hook">("score");
  const [showRestoreModal, setShowRestoreModal] = useState(false);
  const [pendingRestoreUrl, setPendingRestoreUrl] = useState("");
  const [selectedForRender, setSelectedForRender] = useState<Record<number, boolean>>({});
  const [editedTitles, setEditedTitles] = useState<Record<number, string>>({});
  const [editingTitleIdx, setEditingTitleIdx] = useState<number | null>(null);
  const [tempTitle, setTempTitle] = useState("");
  const [galleryFilter, setGalleryFilter] = useState<"all" | "today" | "over30" | "under30">("all");
  const [clipSeedIds, setClipSeedIds] = useState<Record<number, string>>({});

  const [showSettings, setShowSettings] = useState(false);
  const [settingsTab, setSettingsTab] = useState<"api" | "storage">("api");
  const [storageInfo, setStorageInfo] = useState<{models: any[], sessions: any[]}>({models: [], sessions: []});
  const [apiKeys, setApiKeys] = useState({GEMINI_API_KEY: "", GROQ_API_KEY: "", OPENROUTER_API_KEY: "", GLM_API_KEY: "", NVIDIA_API_KEY: ""});

  useEffect(() => {
    if (showSettings) {
      axios.get(`${API_BASE}/settings`)
        .then(res => {
          if (res.data?.api_keys) {
            setApiKeys(res.data.api_keys);
          }
        })
        .catch(() => {});

      if (settingsTab === "storage") {
        axios.get(`${API_BASE}/storage`).then(res => setStorageInfo(res.data)).catch(() => {});
      }
    }
  }, [showSettings, settingsTab]);

  // Detect Colab tunnel URL changes and reload so the new API base takes effect.
  // The watchdog in colab_launcher.ipynb writes /_tunnel_url.json on every restart.
  useEffect(() => {
    const knownUrl = (window as any).__NEXT_PUBLIC_API_URL as string | undefined;
    if (!knownUrl) return; // dev / localhost — skip
    const check = setInterval(async () => {
      try {
        const res = await fetch("/_tunnel_url.json?t=" + Date.now());
        if (!res.ok) return;
        const { url } = await res.json();
        if (url && url !== knownUrl) window.location.reload();
      } catch {}
    }, 15000);
    return () => clearInterval(check);
  }, []);

  const saveSettings = async () => {
    try {
      await axios.post(`${API_BASE}/settings`, { api_keys: apiKeys });
      alert("Settings saved securely!");
    } catch (e: any) {
      alert("Failed to save settings: " + (e.response?.data?.detail || e.message));
    }
  };

  const deleteModel = async (filename: string) => {
    if (!confirm("Delete model " + filename + "?")) return;
    try {
      await axios.delete(`${API_BASE}/models/${encodeURIComponent(filename)}`);
      setStorageInfo(prev => ({ ...prev, models: prev.models.filter(m => m.filename !== filename) }));
    } catch {}
  };

  const deleteSession = async (video_id: string) => {
    if (!confirm("Delete session " + video_id + "?")) return;
    try {
      await axios.delete(`${API_BASE}/sessions/${encodeURIComponent(video_id)}`);
      setStorageInfo(prev => ({ ...prev, sessions: prev.sessions.filter(s => s.video_id !== video_id) }));
    } catch {}
  };

  const addLog = (message: string) => {
    const timestampRegex = /^\[\d{2}:\d{2}:\d{2}\]/;
    if (timestampRegex.test(message)) {
      setLogs(prev => [...prev, message]);
    } else {
      const now = new Date();
      const hh = now.getHours().toString().padStart(2, '0');
      const mm = now.getMinutes().toString().padStart(2, '0');
      const ss = now.getSeconds().toString().padStart(2, '0');
      setLogs(prev => [...prev, `[${hh}:${mm}:${ss}] ${message}`]);
    }
  };

  const selectedCount = useMemo(() => {
    return Object.values(selectedForRender).filter(Boolean).length;
  }, [selectedForRender]);

  const filteredGallery = useMemo(() => {
    return gallery.filter(video => {
      if (galleryFilter === "all") return true;
      if (galleryFilter === "today") {
        const midnight = new Date();
        midnight.setHours(0, 0, 0, 0);
        const midnightTs = midnight.getTime() / 1000;
        return (video as any).created_at_ts >= midnightTs;
      }
      if (galleryFilter === "over30") {
        return ((video as any).duration || 0) >= 30;
      }
      if (galleryFilter === "under30") {
        return ((video as any).duration || 0) < 30;
      }
      return true;
    });
  }, [gallery, galleryFilter]);

  const clearGallery = async () => {
    if (!confirm("Are you sure you want to clear all rendered clips from the gallery? This cannot be undone.")) return;
    try {
      await axios.post(`${API_BASE}/clear_gallery`);
      addLog("🗑️ Gallery cleared.");
      fetchGallery();
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || "Unknown error";
      addLog(`❌ Failed to clear gallery: ${msg}`);
    }
  };

  const clearCurrentRenders = async () => {
    if (!confirm("Are you sure you want to clear rendered clips for the CURRENT active video? This cannot be undone.")) return;
    try {
      await axios.post(`${API_BASE}/clear_gallery?project_only=true`);
      addLog("🗑️ Current video renders cleared.");
      
      // Update state locally so the UI updates immediately
      if (results?.clips) {
        const updatedClips = results.clips.map((c: any) => {
          const { rendered_filename, ...rest } = c;
          return rest;
        });
        setResults({ ...results, clips: updatedClips });
      }
      
      fetchGallery();
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || "Unknown error";
      addLog(`❌ Failed to clear current renders: ${msg}`);
    }
  };


  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  useEffect(() => {
    if (activeView === "gallery") fetchGallery();
  }, [activeView, gallerySessionMode, results?.video_id]);

  useEffect(() => {
    axios.get(`${API_BASE}/heartbeat`)
      .then(res => setBackendVersion(res.data.version))
      .catch(() => setBackendVersion("Offline"));
    axios.get(`${API_BASE}/config`)
      .then(res => {
        setCatalogData(res.data);
        if (res.data.gemini_active) {
          setLlmLabel("♊ Google Gemini 2.5 Flash (API)");
        }
      })
      .catch(() => {});
  }, []);

  // Auto-populate render settings from persona
  useEffect(() => {
    if (results?.clips?.length && results?.persona) {
      const base = {
        ...globalSettings,
        bg_music_genre: results.persona.suggested_bgm || "None",
      };
      const init: Record<number, typeof DEFAULT_SETTINGS> = {};
      results.clips.forEach((_: any, idx: number) => { init[idx] = { ...base }; });

      // Auto-assign a distinct seed style to every clip
      const seedAssignment = assignSeedsToClips(results.clips.length);
      results.clips.forEach((_: any, idx: number) => {
        const seed = STYLE_SEEDS.find(s => s.id === seedAssignment[idx]);
        if (seed) init[idx] = { ...init[idx], ...(seed.changes as any) };
      });
      setRenderSettings(init);
      setClipSeedIds(seedAssignment);

      // Pre-select top 5 clips by composite score (clip.score or clip.virality_score)
      const sortedIdxs = results.clips
        .map((c: any, i: number) => ({ idx: i, score: c.virality_score || c.score || 0 }))
        .sort((a: any, b: any) => b.score - a.score)
        .slice(0, 5)
        .map((item: any) => item.idx);
      
      const newSelected: Record<number, boolean> = {};
      results.clips.forEach((_: any, idx: number) => {
        newSelected[idx] = sortedIdxs.includes(idx);
      });
      setSelectedForRender(newSelected);
    }
  }, [results]);

  const fetchGallery = async () => {
    try {
      let query = "";
      if (gallerySessionMode === "current" && results?.video_id) {
        query = `?video_id=${results.video_id}`;
      }
      const res = await axios.get(`${API_BASE}/gallery${query}`);
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
  const updateGlobalSetting = (key: string, value: any) => {
    setGlobalSettings(prev => {
      const updated = { ...prev, [key]: value };
      if (results?.clips?.length) {
        setRenderSettings(rPrev => {
          const rUpdated = { ...rPrev };
          results.clips.forEach((_: any, idx: number) => {
            rUpdated[idx] = { ...(rUpdated[idx] || DEFAULT_SETTINGS), [key]: value };
          });
          return rUpdated;
        });
      }
      return updated;
    });
  };
  const handleCancel = async () => {
    try {
      await axios.post(`${API_BASE}/cancel_strategize`);
      setStatus("idle");
      setProgress(null);
      setBackendJobRunning({ is_strategizing: false, is_rendering: false });
      clearAllConnections();
      addLog("❌ Analysis cancelled by user.");
    } catch {}
  };

  const handleReset = async () => {
    // Reset UI immediately — don't let a failed backend call leave the UI frozen
    setUrl("");
    setStatus("idle");
    setLogs([]);
    setResults(null);
    setSelectedClip(null);
    setProgress(null);
    setCardRenderStates({});
    setSelectedForRender({});
    setEditedTitles({});
    setRecoveryBanner(null);
    setBackendJobRunning({ is_strategizing: false, is_rendering: false });
    sessionStorage.removeItem(SESSION_URL_KEY);
    bootstrapDoneRef.current = false;
    clearAllConnections();
    // Best-effort backend reset — if the tunnel is down this still won't block
    try { await axios.post(`${API_BASE}/reset`); } catch {}
  };

  const clearAllConnections = () => {
    if (strategizePollRef.current) {
      clearInterval(strategizePollRef.current);
      strategizePollRef.current = null;
    }
    if (renderPollRef.current) {
      clearInterval(renderPollRef.current);
      renderPollRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  };

  const connectWebSocket = () => {
    wsRef.current?.close();
    const ws = new WebSocket(wsUrl());
    ws.onmessage = handleWsMessage;
    ws.onclose = () => {
      // Tunnel WebSocket drops are common during long renders. If this is still
      // the active socket and a job is being tracked, reconnect so the live
      // progress/log stream resumes instead of silently freezing.
      const jobActive = !!(strategizePollRef.current || renderPollRef.current);
      if (wsRef.current === ws && jobActive) {
        setTimeout(() => {
          if (strategizePollRef.current || renderPollRef.current) connectWebSocket();
        }, 1500);
      }
    };
    wsRef.current = ws;
  };

  const persistSessionUrl = (targetUrl: string) => {
    if (targetUrl) sessionStorage.setItem(SESSION_URL_KEY, targetUrl);
  };

  const applyResults = (data: any, banner?: string | null) => {
    setResults(data);
    setStatus("done");
    setBackendJobRunning({ is_strategizing: false, is_rendering: false });
    if (data.current_url) {
      setUrl(data.current_url);
      persistSessionUrl(data.current_url);
    }
    if (banner) setRecoveryBanner(banner);
    // The heavy word-level transcript is no longer in /api/results (it stalled
    // the tunnel on long videos). Fetch it once, on demand, and merge it in so
    // the sentence-exclusion panel keeps working.
    if (data.clips?.length) {
      axios.get(`${API_BASE}/word_timestamps`)
        .then(res => {
          setResults((prev: any) => prev ? { ...prev, word_timestamps: res.data.word_timestamps } : prev);
        })
        .catch(() => { /* sentence-exclusion degrades to empty; not fatal */ });
    }
  };

  const startStrategizePolling = () => {
    if (strategizePollRef.current) clearInterval(strategizePollRef.current);
    let inFlight = false;
    strategizePollRef.current = setInterval(async () => {
      // Skip this tick if the previous poll hasn't returned yet. Without this,
      // a slow response lets requests pile up faster than they complete and
      // stampede the tunnel into a stall.
      if (inFlight) return;
      inFlight = true;
      try {
        const [statusRes, resultsRes] = await Promise.all([
          axios.get(`${API_BASE}/status`),
          axios.get(`${API_BASE}/results`),
        ]);
        setBackendJobRunning({
          is_strategizing: !!statusRes.data.is_strategizing,
          is_rendering: !!statusRes.data.is_rendering,
        });
        if (resultsRes.data.status === "done") {
          if (strategizePollRef.current) clearInterval(strategizePollRef.current);
          strategizePollRef.current = null;
          wsRef.current?.close();
          wsRef.current = null;
          applyResults(
            resultsRes.data,
            resultsRes.data.clips?.length
              ? `Recovered your session — ${resultsRes.data.clips.length} clips ready`
              : null
          );
        }
      } catch {
        /* poll again */
      } finally {
        inFlight = false;
      }
    }, 2000);
  };

  const startRenderPolling = () => {
    if (renderPollRef.current) clearInterval(renderPollRef.current);
    let inFlight = false;
    renderPollRef.current = setInterval(async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const statusRes = await axios.get(`${API_BASE}/status`);
        setBackendJobRunning({
          is_strategizing: !!statusRes.data.is_strategizing,
          is_rendering: !!statusRes.data.is_rendering,
        });
        if (!statusRes.data.is_rendering) {
          if (renderPollRef.current) clearInterval(renderPollRef.current);
          renderPollRef.current = null;
          wsRef.current?.close();
          wsRef.current = null;
          const resultsRes = await axios.get(`${API_BASE}/results`);
          if (resultsRes.data.status === "done") {
            applyResults(resultsRes.data);
          } else {
            setStatus("done");
          }
          setProgress(null);
          fetchGallery();
        }
      } catch {
        /* poll again */
      } finally {
        inFlight = false;
      }
    }, 2000);
  };

  const beginStrategizeTracking = (targetUrl: string, options?: { clearLogs?: boolean; reconnected?: boolean }) => {
    const clearLogs = options?.clearLogs !== false;
    const reconnected = options?.reconnected === true;
    if (clearLogs) {
      setLogs([]);
      addLog("Initializing AI Director Pipeline...");
    } else if (reconnected) {
      addLog("Reconnected to running strategize job after page refresh...");
    }
    setStatus("strategizing");
    setSelectedClip(null);
    if (!reconnected) setProgress(null);
    setShowRestoreModal(false);
    if (targetUrl) {
      setUrl(targetUrl);
      persistSessionUrl(targetUrl);
    }
    setBackendJobRunning({ is_strategizing: true, is_rendering: false });
    connectWebSocket();
    startStrategizePolling();
  };

  const beginRenderTracking = (options?: { clearLogs?: boolean; reconnected?: boolean }) => {
    if (options?.clearLogs) setLogs([]);
    else if (options?.reconnected) addLog("Reconnected to running render job after page refresh...");
    setStatus("rendering");
    setBackendJobRunning(prev => ({ ...prev, is_rendering: true }));
    connectWebSocket();
    startRenderPolling();
  };

  useEffect(() => {
    let cancelled = false;

    const bootstrap = async () => {
      try {
        const [statusRes, resultsRes] = await Promise.all([
          axios.get(`${API_BASE}/status`),
          axios.get(`${API_BASE}/results`),
        ]);
        if (cancelled) return;

        const isStrategizing = !!statusRes.data.is_strategizing;
        const isRendering = !!statusRes.data.is_rendering;
        const currentUrl =
          statusRes.data.current_url ||
          resultsRes.data.current_url ||
          sessionStorage.getItem(SESSION_URL_KEY) ||
          "";
        setBackendJobRunning({ is_strategizing: isStrategizing, is_rendering: isRendering });

        if (isStrategizing) {
          beginStrategizeTracking(currentUrl, { clearLogs: false, reconnected: true });
          setRecoveryBanner("Job still running — reconnected after refresh");
          bootstrapDoneRef.current = true;
          return;
        }

        if (isRendering) {
          if (currentUrl) {
            setUrl(currentUrl);
            persistSessionUrl(currentUrl);
          }
          beginRenderTracking({ clearLogs: false, reconnected: true });
          setRecoveryBanner("Render in progress — reconnected after refresh");
          bootstrapDoneRef.current = true;
          return;
        }

        if (resultsRes.data.status === "done" && resultsRes.data.clips?.length > 0) {
          applyResults(
            resultsRes.data,
            `Recovered your session — ${resultsRes.data.clips.length} clips ready`
          );
          addLog("Session recovered automatically after page refresh.");
          bootstrapDoneRef.current = true;
          return;
        }

        const savedUrl = sessionStorage.getItem(SESSION_URL_KEY);
        if (savedUrl) {
          setUrl(savedUrl);
          try {
            const checkRes = await axios.post(`${API_BASE}/check_session`, { url: savedUrl });
            if (!cancelled && checkRes.data.exists) {
              setPendingRestoreUrl(savedUrl);
              setShowRestoreModal(true);
            }
          } catch {
            /* ignore */
          }
        }
        bootstrapDoneRef.current = true;
      } catch {
        /* backend unreachable — disconnect banner handles it; retry when connected */
      }
    };

    bootstrap();
    return () => {
      cancelled = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-bootstrap when backend comes back after a tunnel reconnect (502 → connected)
  useEffect(() => {
    if (backendStatus !== "connected" || bootstrapDoneRef.current) return;
    const retry = async () => {
      try {
        const [statusRes, resultsRes] = await Promise.all([
          axios.get(`${API_BASE}/status`),
          axios.get(`${API_BASE}/results`),
        ]);
        const isStrategizing = !!statusRes.data.is_strategizing;
        const isRendering = !!statusRes.data.is_rendering;
        if (isStrategizing) {
          beginStrategizeTracking(statusRes.data.current_url || url, { clearLogs: false, reconnected: true });
          setRecoveryBanner("Job still running — reconnected after refresh");
        } else if (isRendering) {
          beginRenderTracking({ clearLogs: false, reconnected: true });
          setRecoveryBanner("Render in progress — reconnected after refresh");
        } else if (resultsRes.data.status === "done" && resultsRes.data.clips?.length > 0) {
          applyResults(
            resultsRes.data,
            `Recovered your session — ${resultsRes.data.clips.length} clips ready`
          );
          addLog("Session recovered after backend reconnected.");
        }
        bootstrapDoneRef.current = true;
      } catch {
        /* ignore */
      }
    };
    retry();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendStatus]);

  useEffect(() => () => clearAllConnections(), []);

  // Blocklist regex — reject raw backend noise from the log console
  const LOG_BLOCKLIST = /DEBUG|ffmpeg|whisper|model_load|frame=|bitrate=|speed=|Lsize=|muxing overhead|Stream #|libx26|matroska|ggml|llama_|llm_load|VRAM|size=\s*\d|cublas|metal|cuda|opengl|vulkan/i;

  const handleWsMessage = (event: MessageEvent) => {
    try {
      const entry = JSON.parse(event.data);
      if (entry.type === "progress") {
        setProgress({ percent: entry.percent || 0, message: entry.message || "", eta: entry.eta });
      } else if (entry.type === "error") {
        addLog(`❌ ERROR: ${entry.message}`);
      } else if (entry.type === "render_status") {
        setCardRenderStates(prev => ({ ...prev, [entry.clip_id]: entry.status }));
      } else if (entry.type === "status") {
        if (!LOG_BLOCKLIST.test(entry.message)) {
          addLog(entry.message);
        }
      }
    } catch {
      // Legacy fallback — plain string, still filter
      if (!LOG_BLOCKLIST.test(event.data)) {
        addLog(event.data);
      }
    }
  };

  const startStrategize = async (targetUrl: string) => {
    beginStrategizeTracking(targetUrl);
    try {
      await axios.post(`${API_BASE}/strategize`, { 
        url: targetUrl, 
        llm_label: llmLabel, 
        whisper_label: whisperLabel,
        angle: "multi-angle",
        session_id: sessionId
      });
    } catch (error: any) {
      const msg = error.response?.data?.detail || error.message || "Unknown error";
      console.error(error);
      addLog(`❌ Error starting strategize phase: ${msg}`);
      setStatus("error");
      setBackendJobRunning({ is_strategizing: false, is_rendering: false });
      clearAllConnections();
    }
  };

  const restoreSession = async (targetUrl: string) => {
    setShowRestoreModal(false);
    setStatus("loading");
    setLogs([]);
    addLog("Restoring session from Google Drive...");
    
    try {
      const res = await axios.post(`${API_BASE}/restore_session`, { url: targetUrl });
      if (res.data.status === "success") {
        const resultsRes = await axios.get(`${API_BASE}/results`);
        applyResults(resultsRes.data, `Restored from Google Drive — ${resultsRes.data.clips?.length || 0} clips ready`);
        addLog("✅ Session successfully restored from Google Drive.");
      }
    } catch (error: any) {
      const msg = error.response?.data?.detail || error.message || "Unknown error";
      addLog(`❌ Failed to restore session: ${msg}`);
      setStatus("error");
    }
  };

  const handleStrategize = async () => {
    if (!url) return;
    try {
      const statusRes = await axios.get(`${API_BASE}/status`);
      if (statusRes.data.is_strategizing || statusRes.data.is_rendering) {
        addLog("A task is already running on the backend — reconnecting...");
        if (statusRes.data.is_strategizing) {
          beginStrategizeTracking(statusRes.data.current_url || url.trim(), {
            clearLogs: false,
            reconnected: true,
          });
        } else {
          beginRenderTracking({ clearLogs: false, reconnected: true });
        }
        return;
      }
    } catch {
      /* proceed */
    }
    try {
      const checkRes = await axios.post(`${API_BASE}/check_session`, { url: url.trim() });
      if (checkRes.data.exists) {
        setPendingRestoreUrl(url);
        setShowRestoreModal(true);
        return;
      }
    } catch (err) {
      // Ignore and proceed
    }
    await startStrategize(url);
  };

  const renderClip = async (index: number) => {
    beginRenderTracking({ clearLogs: true });

    try {
      const settings = getSettings(index);
      const exSentences = (excludedSentences[index] || []).map(s => `[WID:${s.start_idx}-${s.end_idx}] ${s.text}`);

      const res = await axios.post(`${API_BASE}/render`, {
        clip_id: index,
        ...settings,
        excluded_sentences: exSentences,
        title: editedTitles[index] || undefined,
        session_id: sessionId
      });

      const taskId = res.data.task_id;
      if (renderPollRef.current) clearInterval(renderPollRef.current);
      renderPollRef.current = setInterval(async () => {
        try {
          const statusRes = await axios.get(`${API_BASE}/render_status?task_id=${taskId}`);
          if (statusRes.data.status === "done") {
            if (renderPollRef.current) clearInterval(renderPollRef.current);
            renderPollRef.current = null;
            wsRef.current?.close();
            wsRef.current = null;
            setStatus("done");
            setProgress(null);
            setBackendJobRunning({ is_strategizing: false, is_rendering: false });
            fetchGallery();
            setActiveView("gallery");
            window.location.href = `${API_BASE}/download_all?project_only=true`;
          } else if (statusRes.data.status === "error") {
            if (renderPollRef.current) clearInterval(renderPollRef.current);
            renderPollRef.current = null;
            wsRef.current?.close();
            wsRef.current = null;
            setStatus("error");
            setBackendJobRunning({ is_strategizing: false, is_rendering: false });
            addLog(`❌ Render Error: ${statusRes.data.error}`);
          }
        } catch {
          /* poll again */
        }
      }, 2000);
    } catch {
      setStatus("error");
      setBackendJobRunning({ is_strategizing: false, is_rendering: false });
      clearAllConnections();
    }
  };

  const renderAllClips = async () => {
    beginRenderTracking({ clearLogs: true });

    const selectedIds = Object.entries(selectedForRender)
      .filter(([_, checked]) => checked)
      .map(([idxStr]) => parseInt(idxStr));

    const clipSettingsMap: Record<number, any> = {};
    const targetIds = selectedIds.length > 0 ? selectedIds : (results?.clips || []).map((_: any, i: number) => i);
    targetIds.forEach((id: number) => {
      clipSettingsMap[id] = getSettings(id);
    });

    try {
      await axios.post(`${API_BASE}/render_all`, {
        ...globalSettings,
        clip_ids: selectedIds.length > 0 ? selectedIds : undefined,
        titles: editedTitles,
        clip_settings: clipSettingsMap,
        session_id: sessionId
      });

      if (renderPollRef.current) clearInterval(renderPollRef.current);
      renderPollRef.current = setInterval(async () => {
        try {
          const statusRes = await axios.get(`${API_BASE}/status`);
          setBackendJobRunning({
            is_strategizing: !!statusRes.data.is_strategizing,
            is_rendering: !!statusRes.data.is_rendering,
          });
          if (!statusRes.data.is_rendering) {
            if (renderPollRef.current) clearInterval(renderPollRef.current);
            renderPollRef.current = null;
            wsRef.current?.close();
            wsRef.current = null;
            setStatus("done");
            setProgress(null);
            fetchGallery();
            setActiveView("gallery");
            window.location.href = `${API_BASE}/download_all?project_only=true`;
          }
        } catch {
          /* poll again */
        }
      }, 2000);
    } catch {
      setStatus("error");
      setBackendJobRunning({ is_strategizing: false, is_rendering: false });
      clearAllConnections();
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

    // Group into sentences by punctuation and pauses
    const sentences = [];
    let currentSentence: any[] = [];

    for (let i = 0; i < clipWords.length; i++) {
      const w = clipWords[i];
      currentSentence.push(w);
      const endsSentence = /[.!?।|]/.test(w.word);
      let pauseAfter = false;
      if (i + 1 < clipWords.length) {
        pauseAfter = (clipWords[i+1].start - w.end) > 0.5;
      }

      if (endsSentence || pauseAfter || currentSentence.length >= 20) {
        sentences.push({
          text: currentSentence.map((cw: any) => cw.word).join(" "),
          start_idx: currentSentence[0].idx,
          end_idx: currentSentence[currentSentence.length - 1].idx
        });
        currentSentence = [];
      }
    }
    if (currentSentence.length > 0) {
      sentences.push({
        text: currentSentence.map((cw: any) => cw.word).join(" "),
        start_idx: currentSentence[0].idx,
        end_idx: currentSentence[currentSentence.length - 1].idx
      });
    }
    return sentences;
  }, [results]);

  const sortedClips = useMemo(() => {
    if (!results?.clips) return [];
    const list = results.clips.map((clip: any, idx: number) => ({ ...clip, originalIdx: idx }));
    if (sortBy === "score") {
      list.sort((a: any, b: any) => (b.virality_score || b.score || 0) - (a.virality_score || a.score || 0));
    } else if (sortBy === "energy") {
      list.sort((a: any, b: any) => (b.energy_score || 0) - (a.energy_score || 0));
    } else if (sortBy === "duration") {
      const getDur = (c: any) => c.duration || (parseFloat(c.end_time || 0) - parseFloat(c.start_time || 0));
      list.sort((a: any, b: any) => getDur(b) - getDur(a));
    } else if (sortBy === "hook") {
      list.sort((a: any, b: any) => (b.hook_score || 0) - (a.hook_score || 0));
    }
    return list;
  }, [results?.clips, sortBy]);

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

  const activeSettings = selectedClip !== null ? getSettings(selectedClip) : globalSettings;

  // Unified setter: writes to the selected clip if one is open, otherwise to the
  // global defaults. Replaces the two duplicate settings panels with one.
  const applySetting = (key: string, value: any) => {
    if (selectedClip !== null) updateSetting(selectedClip, key, value);
    else updateGlobalSetting(key, value);
  };
  const applyPreset = (presetKey: string) => {
    applySetting("template", presetKey);
    const preset = STYLE_PRESETS[presetKey];
    if (!preset) return;
    Object.entries(preset.changes).forEach(([k, v]) => applySetting(k, v));
  };

  const randomizeAllSeeds = () => {
    if (!results?.clips?.length) return;
    const seedAssignment = assignSeedsToClips(results.clips.length);
    setClipSeedIds(seedAssignment);
    setRenderSettings(prev => {
      const updated = { ...prev };
      results.clips.forEach((_: any, idx: number) => {
        const seed = STYLE_SEEDS.find(s => s.id === seedAssignment[idx]);
        if (seed) updated[idx] = { ...(updated[idx] || DEFAULT_SETTINGS), ...(seed.changes as any) };
      });
      return updated;
    });
  };

  const randomizeClipSeed = (clipIdx: number, e: React.MouseEvent) => {
    e.stopPropagation();
    const currentId = clipSeedIds[clipIdx];
    const others = STYLE_SEEDS.filter(s => s.id !== currentId);
    const newSeed = others[Math.floor(Math.random() * others.length)];
    setClipSeedIds(prev => ({ ...prev, [clipIdx]: newSeed.id }));
    setRenderSettings(prev => ({
      ...prev,
      [clipIdx]: { ...(prev[clipIdx] || DEFAULT_SETTINGS), ...(newSeed.changes as any) },
    }));
  };

  const deleteRenderedClip = async (clipIdx: number, e: React.MouseEvent) => {
    e.stopPropagation();
    const clip = results?.clips?.[clipIdx];
    if (!clip?.rendered_filename) return;
    const parts = (clip.rendered_filename as string).split("/");
    if (parts.length < 2) {
      alert("Cannot delete: clip path is missing video ID.");
      return;
    }
    const videoId = parts[parts.length - 2];
    const filename = parts[parts.length - 1];
    if (!confirm(`Delete "${filename}"?\nThis removes it from Drive and cannot be undone.`)) return;
    try {
      const res = await fetch(`${API_BASE}/clips/${videoId}/${encodeURIComponent(filename)}`, { method: "DELETE" });
      if (!res.ok) { alert("Delete failed — check Drive connection."); return; }
      setResults((prev: any) => {
        if (!prev) return prev;
        const clips = prev.clips.map((c: any, i: number) =>
          i === clipIdx ? { ...c, rendered_filename: undefined } : c
        );
        return { ...prev, clips };
      });
    } catch {
      alert("Delete failed — check Drive connection.");
    }
  };

  return (
    <ErrorBoundary>
      <div className="flex flex-col h-screen overflow-hidden bg-slate-50 text-slate-900">
        <header className="flex items-center justify-between px-4 py-3 bg-white border-b border-gray-200 dark:bg-gray-900 dark:border-gray-800 flex-shrink-0">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-bold tracking-tight text-gray-900 dark:text-white">ClipFactory.ai</h1>
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${backendStatus === 'connected' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'}`}>
              {backendStatus}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <DarkModeToggle />
            <button onClick={() => setShowSettings(true)} className="p-2 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors">
              <Settings2 className="w-5 h-5" />
            </button>
          </div>
        </header>

        {backendStatus === "disconnected" && (
          <div className="bg-rose-50 border-b border-rose-200 px-4 py-3 text-sm text-rose-900 flex-shrink-0">
            <strong>Cannot reach the Colab backend.</strong>{" "}
            The tunnel may have expired (502 Bad Gateway). Go to your Colab notebook, re-run{" "}
            <strong>Cell 2</strong>, and open the <strong>new</strong> Dashboard URL it prints.
            Do not reuse an old bookmark — Localtunnel URLs die after long runs.
          </div>
        )}

        {recoveryBanner && backendStatus === "connected" && (
          <div className="bg-indigo-50 border-b border-indigo-200 px-4 py-2.5 text-sm text-indigo-900 flex items-center justify-between gap-4 flex-shrink-0">
            <span>{recoveryBanner}</span>
            <button
              type="button"
              onClick={() => setRecoveryBanner(null)}
              className="text-indigo-600 hover:text-indigo-800 font-semibold text-xs shrink-0"
            >
              Dismiss
            </button>
          </div>
        )}

        <div className="grid grid-cols-[320px_1fr_300px] flex-1 overflow-hidden">
          
          {/* ── Left Sidebar ────────────────────────────────── */}
          <div className="flex flex-col h-full relative p-6 border-r border-slate-200">
            <div className="flex-shrink-0">

          
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
                disabled={status !== "idle" || !url || backendJobRunning.is_strategizing || backendJobRunning.is_rendering}
                className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-300 disabled:opacity-50 text-white font-bold py-3 rounded-xl flex items-center justify-center gap-2 transition-all text-sm shadow-md active:scale-[0.98]"
              >
                {status === "strategizing" ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                {status === "strategizing" ? "Strategizing..." : "Generate"}
              </button>
              {(status === "strategizing" || backendJobRunning.is_strategizing) && (
                <button
                  onClick={handleCancel}
                  className="bg-rose-50 hover:bg-rose-100 text-rose-600 border border-rose-200 font-bold py-3 px-4 rounded-xl flex items-center justify-center transition-all active:scale-[0.98]"
                >
                  <StopCircle className="w-4 h-4" />
                </button>
              )}
            </div>
            {status !== "idle" && status !== "loading" && (
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

        {/* System Log — live summary of what the app is doing (websocket-driven). */}
        <div className="absolute bottom-6 left-6 right-6 top-[340px] overflow-y-auto bg-black rounded-md p-2 border border-gray-800 custom-scrollbar">
          <div className="shrink-0 px-2 pt-1 pb-2 flex items-center gap-2 text-slate-400 font-sans uppercase tracking-widest font-bold text-[10px] border-b border-slate-800 mb-2">
            <Activity className="w-3 h-3" /> System Log
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
              <div className="flex items-center gap-2">
                {progress.eta !== undefined && progress.eta !== null && (
                  <span className="text-xs text-slate-500 font-medium">({formatEta(progress.eta)})</span>
                )}
                <span className="text-sm font-bold text-indigo-600">{progress.percent}%</span>
              </div>
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
              <div className="flex items-center gap-3">
                {/* SORT CONTROLS DROPDOWN */}
                <div className="flex items-center gap-1.5 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 shadow-sm text-xs">
                  <span className="font-bold text-slate-500">Sort:</span>
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value as any)}
                    className="font-bold text-slate-800 outline-none bg-transparent cursor-pointer"
                  >
                    <option value="score">Virality Score</option>
                    <option value="energy">Energy Score</option>
                    <option value="duration">Duration</option>
                    <option value="hook">Hook Score</option>
                  </select>
                </div>

                {/* RANDOMIZE ALL STYLES BUTTON */}
                <button
                  onClick={randomizeAllSeeds}
                  disabled={!results?.clips?.length}
                  className="bg-white hover:bg-slate-50 disabled:opacity-40 border border-slate-200 text-slate-700 text-xs font-bold py-1.5 px-3 rounded-lg transition-all flex items-center gap-1.5 shadow-sm"
                  title="Shuffle a unique visual style onto every clip"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  Randomize Styles
                </button>

                {/* BULK RENDER ALL BUTTON */}
                <button
                  onClick={renderAllClips}
                  disabled={status === "rendering" || status === "strategizing"}
                  className="bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-300 disabled:opacity-50 text-white text-xs font-bold py-1.5 px-3 rounded-lg transition-all flex items-center gap-1.5 shadow-sm"
                >
                  <Sparkles className="w-3.5 h-3.5 fill-white" />
                  {selectedCount > 0 ? `Render Selected (${selectedCount})` : "Render All"}
                </button>

                <div className="bg-indigo-50 text-indigo-600 px-3 py-1.5 rounded-lg text-xs font-bold border border-indigo-100 shadow-sm">
                  {selectedCount} Selected / {results.clips?.length || 0} Clips
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              {sortedClips.map((clip: any) => {
                const clipIdx = clip.originalIdx;
                return (
                  <div key={clipIdx} onClick={() => setSelectedClip(clipIdx)} className={`cursor-pointer group flex flex-col border transition-all duration-300 shadow-sm overflow-hidden rounded-2xl ${selectedClip === clipIdx ? 'border-indigo-500 ring-2 ring-indigo-500/20 bg-indigo-50/30' : 'border-slate-200 bg-white hover:border-indigo-300 hover:shadow-md'}`}>
                    <div className="flex h-40">
                      {/* Left Thumbnail Column */}
                      <div className="bg-slate-900 w-28 shrink-0 relative overflow-hidden flex items-center justify-center">
                        {clip.thumbnail_url && (
                          <img 
                            src={clip.thumbnail_url || ""} 
                            alt="" 
                            className="absolute inset-0 w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity" 
                          />
                        )}
                        
                        {/* CHECKBOX FOR BULK SELECTION (Top-Left of Thumbnail) */}
                        <div className="absolute top-2 left-2 z-10" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={!!selectedForRender[clipIdx]}
                            onChange={(e) => {
                              setSelectedForRender(prev => ({ ...prev, [clipIdx]: e.target.checked }));
                            }}
                            className="w-4 h-4 cursor-pointer accent-indigo-600 rounded"
                          />
                        </div>

                        {/* CLEAN FLOATING DURATION BADGE (Bottom-Right of Thumbnail) */}
                        <div className="absolute bottom-2 right-2 bg-black/75 text-white text-[9px] font-mono font-bold px-1.5 py-0.5 rounded flex items-center gap-1 shadow-sm z-10">
                          <Clock className="w-2.5 h-2.5" />
                          {formatTime(clip.duration || (parseFloat(clip.end_time || 0) - parseFloat(clip.start_time || 0)))}
                        </div>

                        {/* PER-CARD RENDERING STATUS OVERLAY WITH ESTIMATES */}
                        {cardRenderStates[clipIdx] && cardRenderStates[clipIdx] !== "idle" && (
                          <div className="absolute inset-0 bg-black/80 backdrop-blur-xs flex flex-col items-center justify-center p-2 z-20 text-center">
                            {cardRenderStates[clipIdx] === "queued" && (
                              <>
                                <Clock className="w-5 h-5 text-slate-400 animate-pulse mb-1" />
                                <span className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Queued</span>
                                <span className="text-[9px] text-slate-400 mt-1 font-semibold">~{Math.round((clip.duration || 30) * 4)}s</span>
                              </>
                            )}
                            {cardRenderStates[clipIdx] === "rendering" && (
                              <>
                                <RefreshCw className="w-5 h-5 text-indigo-400 animate-spin mb-1" />
                                <span className="text-[9px] font-bold text-indigo-400 uppercase tracking-wider">Rendering</span>
                                <span className="text-[9px] text-indigo-400 mt-1 font-semibold">~{Math.round((clip.duration || 30) * 4)}s</span>
                              </>
                            )}
                            {cardRenderStates[clipIdx] === "done" && (
                              <>
                                <CheckCircle2 className="w-5 h-5 text-emerald-400 mb-1" />
                                <span className="text-[9px] font-bold text-emerald-400 uppercase tracking-wider">Done</span>
                              </>
                            )}
                            {cardRenderStates[clipIdx] === "error" && (
                              <>
                                <StopCircle className="w-5 h-5 text-rose-500 mb-1" />
                                <span className="text-[9px] font-bold text-rose-500 uppercase tracking-wider">Failed</span>
                              </>
                            )}
                          </div>
                        )}
                      </div>

                      {/* Right-Hand Content Column */}
                      <div className="p-4 flex-1 flex flex-col justify-between overflow-hidden">
                        <div className="space-y-1.5">
                          {/* INLINE EDITABLE CLIP TITLE */}
                          <div className="flex items-center justify-between gap-2">
                            {editingTitleIdx === clipIdx ? (
                              <input
                                type="text"
                                value={tempTitle}
                                onChange={(e) => setTempTitle(e.target.value)}
                                onBlur={() => {
                                  if (tempTitle.trim()) {
                                    setEditedTitles(prev => ({ ...prev, [clipIdx]: tempTitle.trim() }));
                                  }
                                  setEditingTitleIdx(null);
                                }}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') {
                                    if (tempTitle.trim()) {
                                      setEditedTitles(prev => ({ ...prev, [clipIdx]: tempTitle.trim() }));
                                    }
                                    setEditingTitleIdx(null);
                                  } else if (e.key === 'Escape') {
                                    setEditingTitleIdx(null);
                                  }
                                }}
                                onClick={(e) => e.stopPropagation()}
                                autoFocus
                                className="bg-slate-100 text-slate-900 text-xs font-bold px-2 py-0.5 rounded border border-indigo-500 w-full outline-none"
                              />
                            ) : (
                              <div 
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setEditingTitleIdx(clipIdx);
                                  setTempTitle(editedTitles[clipIdx] || clip.title || "Untitled Clip");
                                }}
                                className="text-slate-800 font-bold text-xs hover:underline cursor-text hover:text-indigo-600 transition-colors truncate"
                                title="Click to edit title"
                              >
                                {editedTitles[clipIdx] || clip.title || "Untitled Clip"}
                              </div>
                            )}
                            {/* SEED STYLE BADGE */}
                            {clipSeedIds[clipIdx] && (() => {
                              const seed = STYLE_SEEDS.find(s => s.id === clipSeedIds[clipIdx]);
                              return seed ? (
                                <span className={`shrink-0 text-[9px] font-bold px-1.5 py-0.5 rounded-full border ${seed.badgeColor}`}>
                                  {seed.label}
                                </span>
                              ) : null;
                            })()}
                          </div>

                          {/* HOOK DESCRIPTION */}
                          <div className="flex items-start justify-between gap-2">
                            <p className="text-[11px] text-slate-600 border-l-2 border-indigo-200 pl-2 italic line-clamp-3 leading-snug">
                              <span className="font-bold text-indigo-500 mr-1 not-italic">Hook:</span> 
                              "{clip.hook_sentence || clip.description}"
                            </p>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                navigator.clipboard.writeText(clip.hook_sentence || clip.description || "");
                                addLog("Hook copied to clipboard!");
                              }}
                              className="p-1 hover:bg-slate-100 rounded text-slate-400 hover:text-indigo-600 transition-colors shrink-0"
                              title="Copy Hook"
                            >
                              <Copy className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>

                        {/* BOTTOM ACTIONS AND SCORES ROW */}
                        <div className="flex items-center justify-between gap-2 pt-2 border-t border-slate-100">
                          {/* Scores & Subscore Badges */}
                          <div className="flex flex-col gap-1 min-w-0">
                            {/* Main Scores */}
                            <div className="flex items-center gap-1.5">
                              <div className="bg-emerald-50 text-emerald-700 text-[9px] font-bold px-1.5 py-0.5 rounded border border-emerald-200/50 flex items-center gap-0.5 shadow-sm shrink-0">
                                <TrendingUp className="w-2.5 h-2.5 text-emerald-500" /> V: {Math.round(clip.virality_score || clip.score || 0)}
                              </div>
                              <div className="bg-indigo-50 text-indigo-700 text-[9px] font-bold px-1.5 py-0.5 rounded border border-indigo-200/50 flex items-center gap-0.5 shadow-sm shrink-0">
                                <Zap className="w-2.5 h-2.5 text-indigo-500" /> E: {Math.round(clip.energy_score || 0)}
                              </div>
                            </div>
                            {/* Sub-Badges (H, En, Va, Sh) */}
                            {(clip.hook_score || clip.engagement_score || clip.value_score || clip.shareability_score) ? (
                              <div className="flex gap-1 flex-wrap shrink-0">
                                <span className="text-[8px] font-semibold text-slate-500 bg-slate-100 rounded px-1 py-0.2" title="Hook Score">
                                  H:{clip.hook_score ?? 0}
                                </span>
                                <span className="text-[8px] font-semibold text-slate-500 bg-slate-100 rounded px-1 py-0.2" title="Energy/Engagement Score">
                                  E:{clip.engagement_score ?? 0}
                                </span>
                                <span className="text-[8px] font-semibold text-slate-500 bg-slate-100 rounded px-1 py-0.2" title="Value Score">
                                  V:{clip.value_score ?? 0}
                                </span>
                                <span className="text-[8px] font-semibold text-slate-500 bg-slate-100 rounded px-1 py-0.2" title="Shareability Score">
                                  S:{clip.shareability_score ?? 0}
                                </span>
                              </div>
                            ) : null}
                          </div>

                          {/* PER-CLIP DICE — re-roll this clip's style */}
                          <button
                            onClick={(e) => randomizeClipSeed(clipIdx, e)}
                            className="p-1.5 hover:bg-slate-100 rounded-lg border border-slate-200 text-slate-400 hover:text-indigo-600 transition-colors shrink-0"
                            title="Re-roll style for this clip"
                          >
                            <RefreshCw className="w-3.5 h-3.5" />
                          </button>
                          {/* DELETE RENDERED CLIP */}
                          {results?.clips?.[clipIdx]?.rendered_filename && (
                            <button
                              onClick={(e) => deleteRenderedClip(clipIdx, e)}
                              className="p-1.5 hover:bg-rose-50 rounded-lg border border-slate-200 text-slate-400 hover:text-rose-600 transition-colors shrink-0"
                              title="Delete this rendered clip from Drive"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          )}
                          {/* RENDER BUTTON */}
                          <button
                            onClick={(e) => { e.stopPropagation(); renderClip(clipIdx); }}
                            disabled={status === "rendering"}
                            className="bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-300 text-white text-[10px] font-bold py-1.5 px-3 rounded-lg transition-all flex items-center gap-1 shadow-sm shrink-0"
                          >
                            <Zap className="w-3 h-3" />
                            Render
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}

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
            <div className="flex items-center gap-2">
              {/* GALLERY SESSION FILTER DROPDOWN */}
              <div className="flex items-center gap-1 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 shadow-sm text-xs">
                <span className="font-bold text-slate-500">Session:</span>
                <select
                  value={gallerySessionMode}
                  onChange={(e) => setGallerySessionMode(e.target.value as any)}
                  className="font-bold text-slate-800 outline-none bg-transparent cursor-pointer"
                >
                  <option value="current">Current Session Only</option>
                  <option value="all">All Sessions</option>
                </select>
              </div>

              {/* GALLERY FILTER DROPDOWN */}
              <div className="flex items-center gap-1 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 shadow-sm text-xs">
                <span className="font-bold text-slate-500">Filter:</span>
                <select
                  value={galleryFilter}
                  onChange={(e) => setGalleryFilter(e.target.value as any)}
                  className="font-bold text-slate-800 outline-none bg-transparent cursor-pointer"
                >
                  <option value="all">All</option>
                  <option value="today">Rendered Today</option>
                  <option value="over30">&gt; 30s</option>
                  <option value="under30">&lt; 30s</option>
                </select>
              </div>

              {/* EXPORT CSV BUTTON */}
              {gallery.length > 0 && (
                <a
                  href={`${API_BASE}/export_csv`}
                  className="bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold py-1.5 px-3 rounded-lg transition-all flex items-center gap-1.5 shadow-sm"
                >
                  <Tag className="w-3.5 h-3.5" />
                  Export CSV
                </a>
              )}

              {/* DOWNLOAD BUTTONS */}
              {gallery.length > 0 && (
                gallerySessionMode === "current" && results?.video_id ? (
                  <a
                    href={`${API_BASE}/download_all?video_id=${results.video_id}`}
                    className="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold py-1.5 px-3 rounded-lg transition-all flex items-center gap-1.5 shadow-sm"
                  >
                    <Download className="w-3.5 h-3.5" />
                    Download Session (ZIP)
                  </a>
                ) : (
                  <a
                    href={`${API_BASE}/download_all`}
                    className="bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold py-1.5 px-3 rounded-lg transition-all flex items-center gap-1.5 shadow-sm"
                  >
                    <Download className="w-3.5 h-3.5" />
                    Download All (ZIP)
                  </a>
                )
              )}

              {/* CLEAR BUTTONS */}
              {gallery.length > 0 && (
                gallerySessionMode === "current" && results?.video_id ? (
                  <button
                    onClick={clearCurrentRenders}
                    className="bg-rose-50 hover:bg-rose-100 text-rose-600 border border-rose-200 text-xs font-bold py-1.5 px-3 rounded-lg transition-all flex items-center gap-1.5 shadow-sm active:scale-[0.98]"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    Clear Session Renders
                  </button>
                ) : (
                  <button
                    onClick={clearGallery}
                    className="bg-rose-50 hover:bg-rose-100 text-rose-600 border border-rose-200 text-xs font-bold py-1.5 px-3 rounded-lg transition-all flex items-center gap-1.5 shadow-sm active:scale-[0.98]"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    Clear All Gallery
                  </button>
                )
              )}

              <button 
                onClick={fetchGallery}
                className="p-1.5 bg-white border border-slate-200 hover:bg-slate-50 rounded-lg text-slate-500 transition-colors shadow-sm"
              >
                <RefreshCw className={`w-4 h-4 ${status === "rendering" ? "animate-spin" : ""}`} />
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {filteredGallery.map((video, i) => (
              <div key={i} className="bg-white border border-slate-200 shadow-sm flex flex-col overflow-hidden rounded-xl animate-fadeIn">
                <div className="bg-slate-900 aspect-[9/16] relative group">
                  <video
                    className="w-full h-full object-cover cursor-pointer"
                    src={video.url}
                    muted
                    playsInline
                    onMouseOver={e => (e.currentTarget as HTMLVideoElement).play()}
                    onMouseOut={e => (e.currentTarget as HTMLVideoElement).pause()}
                    onClick={e => {
                      const v = e.currentTarget as HTMLVideoElement;
                      v.paused ? v.play() : v.pause();
                    }}
                  />
                  <div className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
                    <Play className="w-8 h-8 text-white fill-white shadow-xl" />
                  </div>
                </div>
                <div className="p-3 bg-white">
                  <div className="truncate mb-1 text-[10px] font-bold text-slate-800">{video.filename}</div>
                  <div className="text-[9px] text-slate-500 mb-3 uppercase tracking-wider">{(video.size_mb).toFixed(1)} MB</div>
                  <a 
                    href={`${API_BASE}/download_single?filename=${encodeURIComponent(video.filename)}`} 
                    download
                    className="w-full bg-slate-50 hover:bg-slate-100 text-indigo-600 text-[10px] font-bold py-2 rounded-lg border border-slate-200 transition-all flex items-center justify-center gap-1.5"
                  >
                    <Download className="w-3.5 h-3.5" />
                    Download
                  </a>
                </div>
              </div>
            ))}
            {filteredGallery.length === 0 && (
              <div className="col-span-full py-12 text-center bg-white rounded-2xl border border-dashed border-slate-300 shadow-sm">
                <Film className="w-10 h-10 text-slate-300 mx-auto mb-3 text-slate-400 opacity-30" />
                <p className="text-slate-500 font-medium text-sm">No matching rendered clips found.</p>
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
            {selectedClip !== null ? "Advanced Settings" : "Global Defaults"}
          </h3>
        </div>

        <div className="p-4 border-b border-slate-200">
          <button
            onClick={() => setShowPreview(v => !v)}
            className="w-full flex items-center justify-between text-xs font-bold uppercase tracking-wider text-slate-500 hover:text-indigo-600 transition-colors"
          >
            <span className="flex items-center gap-1.5"><Eye className="w-3.5 h-3.5" /> Preview</span>
            {showPreview ? <EyeOff className="w-3.5 h-3.5" /> : <ArrowRight className="w-3.5 h-3.5" />}
          </button>
          {showPreview && (
            <div className="mt-3">
              <ClipPreview
                headerText={selectedClip !== null && results?.clips[selectedClip] ? results.clips[selectedClip].title : ''}
                headerFont={FONT_MAP[activeSettings.header_font] || 'Bebas Neue'}
                captionText={selectedClip !== null && results?.clips[selectedClip] ? results.clips[selectedClip].caption : ''}
                captionFont={FONT_MAP[activeSettings.caption_font] || 'Bebas Neue'}
                hookText={selectedClip !== null && results?.clips[selectedClip] ? results.clips[selectedClip].hook : ''}
                hookFont={FONT_MAP[activeSettings.hook_font] || 'Bebas Neue'}
                bgStyle={(activeSettings.bg_style || 'black') as 'black' | 'brand' | 'blur' | 'white'}
              />
            </div>
          )}
        </div>

        {/* Unified render settings — edits the selected clip, or all clips
            (Global Defaults) when none is selected. One panel, no duplicates. */}
        <div className="p-5 space-y-6 animate-fadeIn">
          <div className="bg-indigo-50 border border-indigo-100 p-3 rounded-xl">
            <span className="text-[10px] font-bold text-indigo-500 uppercase tracking-widest block mb-1">
              {selectedClip !== null ? "Editing Clip" : "Global Defaults"}
            </span>
            <p className="text-xs font-bold text-indigo-900 line-clamp-1">
              {selectedClip !== null && results?.clips[selectedClip]
                ? (results.clips[selectedClip].title || "Selected Clip")
                : "Applies to all clips"}
            </p>
          </div>

          <div className="flex-shrink-0 space-y-4">
            <div className="space-y-1">
              <span className="text-[10px] uppercase font-bold text-slate-500">Style Preset</span>
              <select
                value={activeSettings.template || ""}
                onChange={(e) => applyPreset(e.target.value)}
                className="w-full bg-slate-50 text-slate-800 text-sm border border-slate-200 rounded-lg p-2.5 outline-none font-bold"
              >
                <option value="">Custom</option>
                {Object.entries(STYLE_PRESETS).map(([key, p]) => (
                  <option key={key} value={key}>{p.label}</option>
                ))}
              </select>
              {activeSettings.template && STYLE_PRESETS[activeSettings.template] && (
                <p className="text-[10px] text-slate-500 mt-1">{STYLE_PRESETS[activeSettings.template].summary}</p>
              )}
            </div>

            <div className="space-y-1">
              <span className="text-xs font-bold text-slate-500">Caption Style</span>
              <select
                value={activeSettings.caption_style}
                onChange={(e) => applySetting("caption_style", e.target.value)}
                className="w-full bg-slate-50 text-slate-800 text-sm border border-slate-200 rounded-lg p-2.5 outline-none font-medium"
              >
                <option value="Pop">Pop — white + magenta</option>
                <option value="Classic">Classic — white + yellow</option>
                <option value="Fire">Fire — yellow + orange</option>
                <option value="Glow">Glow</option>
                <option value="CinematicSlate">Cinematic</option>
                <option value="Minimal">Minimal</option>
                <option value="None">No captions</option>
              </select>
            </div>

            {/* Header style — visual thumbnail picker */}
            <div className="space-y-1">
              <span className="text-xs font-bold text-slate-500">Header Style</span>
              <div className="grid grid-cols-2 gap-2">
                {(["card", "stroke"] as const).map((s) => (
                  <button key={s} type="button" onClick={() => applySetting("header_style", s)}
                    className={`rounded-lg overflow-hidden border-2 transition-colors ${(activeSettings as any).header_style === s ? "border-indigo-500" : "border-slate-200"}`}>
                    <img src={`/headers/${s}.png`} alt={s} className="w-full h-auto block" />
                    <span className="block text-[10px] font-bold text-slate-600 py-0.5 capitalize">{s}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Header font — expressive / display typefaces */}
            <div className="space-y-1">
              <span className="text-xs font-bold text-slate-500">Header Font</span>
              <select
                value={activeSettings.header_font || "montserrat-black"}
                onChange={(e) => applySetting("header_font", e.target.value)}
                className="w-full bg-slate-50 text-slate-800 text-sm border border-slate-200 rounded-lg p-2.5 outline-none font-medium"
              >
                <option value="montserrat-black">Montserrat Black — heavy</option>
                <option value="inter">Inter — clean modern</option>
                <option value="poppins">Poppins — rounded</option>
              </select>
            </div>

            {/* Caption font — readable body typefaces only */}
            <div className="space-y-1">
              <span className="text-xs font-bold text-slate-500">Caption Font</span>
              <select
                value={activeSettings.caption_font || "montserrat"}
                onChange={(e) => { applySetting("caption_font", e.target.value); applySetting("hook_font", e.target.value); }}
                className="w-full bg-slate-50 text-slate-800 text-sm border border-slate-200 rounded-lg p-2.5 outline-none font-medium"
              >
                <option value="montserrat">Montserrat — clean bold</option>
                <option value="poppins">Poppins — rounded geometric</option>
                <option value="roboto">Roboto — neutral sans</option>
              </select>
            </div>

            {/* Background */}
            <div className="space-y-1">
              <span className="text-xs font-bold text-slate-500">Background</span>
              <select
                value={activeSettings.bg_style || "brand"}
                onChange={(e) => applySetting("bg_style", e.target.value)}
                className="w-full bg-slate-50 text-slate-800 text-sm border border-slate-200 rounded-lg p-2.5 outline-none font-medium"
              >
                <option value="brand">Brand color</option>
                <option value="blur">Blurred video</option>
                <option value="black">Black</option>
                <option value="white">White</option>
              </select>
            </div>

            <div className="space-y-1">
              <span className="text-xs font-bold text-slate-500">Caption Position</span>
              <select
                value={activeSettings.caption_pos}
                onChange={(e) => applySetting("caption_pos", e.target.value)}
                className="w-full bg-slate-50 text-slate-800 text-sm border border-slate-200 rounded-lg p-2.5 outline-none"
              >
                <option value="bottom">Inside Bottom</option>
                <option value="top">Inside Top</option>
              </select>
            </div>

            <div className="space-y-1">
              <span className="text-xs font-bold text-slate-500">Music</span>
              <select
                value={activeSettings.bg_music_genre}
                onChange={(e) => applySetting("bg_music_genre", e.target.value)}
                className="w-full bg-slate-50 text-slate-800 text-sm border border-slate-200 rounded-lg p-2.5 outline-none"
              >
                <option value="None">None</option>
                {(catalogData.bgm_genres || []).map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          </div>

          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between p-3.5 bg-white rounded-xl border border-slate-200 shadow-sm">
              <span className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-amber-500" /> Hook Duration
              </span>
              <select
                value={activeSettings.hook_display || "5s"}
                onChange={(e) => applySetting("hook_display", e.target.value)}
                className="text-xs font-semibold border border-slate-200 rounded-lg px-2 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-400"
              >
                <option value="off">Off</option>
                <option value="3s">3 seconds</option>
                <option value="5s">5 seconds</option>
                <option value="full">Full clip</option>
              </select>
            </div>
            <div className="flex items-center justify-between p-3.5 bg-white rounded-xl border border-slate-200 shadow-sm">
              <span className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                <Zap className="w-3.5 h-3.5 text-indigo-500" /> Remove Silences
              </span>
              <label className="setting-toggle">
                <input
                  type="checkbox"
                  checked={activeSettings.remove_silence}
                  onChange={(e) => applySetting("remove_silence", e.target.checked)}
                />
                <div className="toggle-track bg-slate-300 before:bg-white checked:bg-indigo-500" />
              </label>
            </div>
          </div>

          {selectedClip !== null && results?.clips[selectedClip] && (
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
          )}

          {selectedClip !== null ? (
            <button
              onClick={() => renderClip(selectedClip)}
              className="w-full mt-4 py-3.5 rounded-xl font-bold text-white bg-indigo-600 hover:bg-indigo-500 transition-colors shadow-md shadow-indigo-600/20 flex items-center justify-center gap-2 active:scale-[0.98]"
            >
              <Zap className="w-4 h-4 fill-white" />
              Render This Clip
            </button>
          ) : (results?.clips?.length > 0 && (
            <button
              onClick={renderAllClips}
              disabled={status === "rendering" || status === "strategizing"}
              className="w-full mt-4 py-3.5 rounded-xl font-bold text-white bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:bg-slate-300 transition-colors shadow-md shadow-indigo-600/20 flex items-center justify-center gap-2 active:scale-[0.98]"
            >
              <Sparkles className="w-4 h-4 fill-white" />
              Render All Clips
            </button>
          ))}
        </div>
      </div>

      {/* PREMIUM GOOGLE DRIVE SESSION RESTORE MODAL */}
      {showRestoreModal && (
        <div className="fixed inset-0 bg-slate-900/50 z-50 flex items-center justify-center p-4">
          <div className="bg-white border border-slate-200 rounded-2xl shadow-md max-w-md w-full p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 bg-indigo-50 rounded-xl flex items-center justify-center">
                <Sparkles className="w-5 h-5 text-indigo-600" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-slate-800">Restore Session?</h3>
                <p className="text-xs text-slate-500">Google Drive session found</p>
              </div>
            </div>
            <p className="text-sm text-slate-600 mb-6">
              A previously completed strategy session for this video exists on Google Drive. Would you like to restore it to save processing time and API usage?
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => restoreSession(pendingRestoreUrl)}
                className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-2.5 rounded-xl text-sm transition-all shadow-md flex items-center justify-center gap-2"
              >
                <CheckCircle2 className="w-4 h-4" />
                Yes, Restore
              </button>
              <button
                onClick={() => {
                  setShowRestoreModal(false);
                  startStrategize(pendingRestoreUrl);
                }}
                className="flex-1 bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold py-2.5 rounded-xl text-sm transition-all border border-slate-200 flex items-center justify-center gap-2"
              >
                <RefreshCw className="w-4 h-4" />
                No, Start Fresh
              </button>
            </div>
          </div>
        </div>
      )}

      {showSettings && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-[200] flex items-center justify-center p-4" onClick={() => setShowSettings(false)}>
          <div className="bg-white rounded-2xl shadow-xl w-[600px] overflow-hidden flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="p-6 pb-4 border-b border-slate-100 flex items-center justify-between">
              <h3 className="text-xl font-bold text-slate-800 flex items-center gap-2">
                <Settings2 className="w-5 h-5 text-indigo-500" />
                Settings & Storage
              </h3>
              <div className="flex bg-slate-100 p-1 rounded-lg">
                <button 
                  onClick={() => setSettingsTab("api")}
                  className={`px-4 py-1.5 rounded-md text-sm font-bold transition-all ${settingsTab === "api" ? "bg-white text-indigo-600 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}
                >
                  API Models
                </button>
                <button 
                  onClick={() => setSettingsTab("storage")}
                  className={`px-4 py-1.5 rounded-md text-sm font-bold transition-all ${settingsTab === "storage" ? "bg-white text-indigo-600 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}
                >
                  Storage
                </button>
              </div>
            </div>
            
            <div className="p-6 h-[400px] overflow-y-auto">
              {settingsTab === "api" && (
                <div className="space-y-4">
                  <div className="bg-blue-50 text-blue-700 p-3 rounded-lg text-xs font-medium border border-blue-100">
                    Enter multiple keys separated by commas for built-in automatic fallback rotation. Keys are saved to your Google Drive <code>.env</code> file.
                  </div>
                  
                  <div>
                    <label className="text-xs font-bold text-slate-600 uppercase">Gemini API Key</label>
                    <input type="text" value={apiKeys.GEMINI_API_KEY} onChange={e => setApiKeys(prev => ({...prev, GEMINI_API_KEY: e.target.value}))} placeholder="AIzaSy..." className="w-full mt-1 border border-slate-200 rounded-lg p-2 text-sm" />
                  </div>
                  <div>
                    <label className="text-xs font-bold text-slate-600 uppercase">Groq API Key (Llama 3.1)</label>
                    <input type="text" value={apiKeys.GROQ_API_KEY} onChange={e => setApiKeys(prev => ({...prev, GROQ_API_KEY: e.target.value}))} placeholder="gsk_..." className="w-full mt-1 border border-slate-200 rounded-lg p-2 text-sm" />
                  </div>
                  <div>
                    <label className="text-xs font-bold text-slate-600 uppercase">OpenRouter API Key</label>
                    <input type="text" value={apiKeys.OPENROUTER_API_KEY} onChange={e => setApiKeys(prev => ({...prev, OPENROUTER_API_KEY: e.target.value}))} placeholder="sk-or-v1-..." className="w-full mt-1 border border-slate-200 rounded-lg p-2 text-sm" />
                  </div>
                  <div>
                    <label className="text-xs font-bold text-slate-600 uppercase">GLM API Key (Zhipu)</label>
                    <input type="text" value={apiKeys.GLM_API_KEY} onChange={e => setApiKeys(prev => ({...prev, GLM_API_KEY: e.target.value}))} className="w-full mt-1 border border-slate-200 rounded-lg p-2 text-sm" />
                  </div>
                  <div>
                    <label className="text-xs font-bold text-slate-600 uppercase">NVIDIA API Key (NIM)</label>
                    <input type="text" value={apiKeys.NVIDIA_API_KEY} onChange={e => setApiKeys(prev => ({...prev, NVIDIA_API_KEY: e.target.value}))} placeholder="nvapi-..." className="w-full mt-1 border border-slate-200 rounded-lg p-2 text-sm" />
                  </div>
                  <button onClick={saveSettings} className="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-2.5 rounded-lg mt-4 transition-colors">
                    Save API Keys
                  </button>
                </div>
              )}
              
              {settingsTab === "storage" && (
                <div className="space-y-6">
                  <div>
                    <h4 className="text-sm font-bold text-slate-800 border-b pb-2 mb-3">Local GGUF Models</h4>
                    {storageInfo.models.length === 0 && <p className="text-sm text-slate-500 italic">No local models found.</p>}
                    <div className="space-y-2">
                      {storageInfo.models.map(m => (
                        <div key={m.filename} className="flex items-center justify-between bg-slate-50 border border-slate-100 p-2.5 rounded-lg">
                          <div>
                            <div className="text-sm font-semibold text-slate-700">{m.filename}</div>
                            <div className="text-xs text-slate-500">{m.size_mb} MB</div>
                          </div>
                          <button onClick={() => deleteModel(m.filename)} className="text-rose-500 hover:bg-rose-50 p-1.5 rounded text-xs font-bold">Delete</button>
                        </div>
                      ))}
                    </div>
                  </div>
                  
                  <div>
                    <h4 className="text-sm font-bold text-slate-800 border-b pb-2 mb-3">Saved Sessions</h4>
                    {storageInfo.sessions.length === 0 && <p className="text-sm text-slate-500 italic">No saved sessions found.</p>}
                    <div className="space-y-3">
                      {storageInfo.sessions.map(s => (
                        <div key={s.video_id} className="flex flex-col bg-slate-50 border border-slate-100 p-3 rounded-xl gap-2 shadow-sm">
                          <div className="flex justify-between items-start">
                            <div className="max-w-[80%] space-y-1">
                              <div className="text-sm font-semibold text-slate-700 truncate" title={s.url || s.video_id}>
                                {s.url ? s.url : `Session: ${s.video_id}`}
                              </div>
                              <div className="flex gap-3 text-[11px] text-slate-500 font-medium">
                                <span>📁 {s.size_mb} MB</span>
                                <span>🎬 {s.clips_count} Clips</span>
                                <span>⏱️ {s.duration ? `${Math.round(s.duration)}s` : 'Unknown'}</span>
                              </div>
                            </div>
                            <button onClick={() => deleteSession(s.video_id)} className="text-rose-500 hover:bg-rose-50 p-1.5 rounded-lg text-xs font-bold transition-all">
                              Delete
                            </button>
                          </div>
                          {s.url && (
                            <button
                              onClick={async () => {
                                setShowSettings(false);
                                setUrl(s.url);
                                await restoreSession(s.url);
                              }}
                              className="w-full py-2 px-3 bg-indigo-50 hover:bg-indigo-100 text-indigo-600 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 shadow-sm"
                            >
                              <RefreshCw className="w-3.5 h-3.5" />
                              Restore Session
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
            
            <div className="p-4 border-t border-slate-100 flex justify-end">
              <button onClick={() => setShowSettings(false)} className="px-6 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold rounded-lg transition-colors">
                Close
              </button>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
    </ErrorBoundary>
  );
}
