import React, { useState, useEffect, useRef } from 'react';

interface LogEntry {
  timestamp: string;
  type: 'app' | 'llm' | 'ffmpeg';
  stage?: string;
  status?: string;
  model?: string;
  reasoning?: string;
  error?: string;
  latency_ms?: number;
  return_code?: number;
  duration_sec?: number;
  details?: Record<string, unknown>;
}

export const LogViewer: React.FC<{ sessionId: string }> = ({ sessionId }) => {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [filter, setFilter] = useState<'all' | 'app' | 'llm' | 'ffmpeg'>('all');
  const [autoScroll, setAutoScroll] = useState(true);
  const [isConnected, setIsConnected] = useState(false);
  const [selectedEntry, setSelectedEntry] = useState<LogEntry | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let es: EventSource;
    const connect = () => {
      es = new EventSource(`/api/logs/${sessionId}/stream`);
      es.onopen = () => setIsConnected(true);
      es.onmessage = (e) => {
        const entry = JSON.parse(e.data);
        setLogs(prev => [...prev, entry]);
      };
      es.onerror = () => {
        setIsConnected(false);
        es.close();
        setTimeout(connect, 3000);
      };
    };
    connect();
    return () => es?.close();
  }, [sessionId]);

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  const filtered = filter === 'all' ? logs : logs.filter(l => l.type === filter);

  const getSummary = (entry: LogEntry): string => {
    switch (entry.type) {
      case 'app':
        if (entry.error) return `App error in ${entry.stage}: ${entry.error}`;
        if (entry.stage === 'render' && entry.status === 'completed') return '✅ Video rendered successfully';
        if (entry.stage === 'extraction' && entry.status === 'completed') return `✅ Found ${entry.details?.clips_found || 'some'} clips`;
        if (entry.stage === 'input_check') return `📹 Input video: ${entry.details?.width || '?'}x${entry.details?.height || '?'}`;
        return `${entry.stage}: ${entry.status}`;
      case 'llm':
        if (entry.error) return `❌ LLM failed: ${entry.error}`;
        return `🤖 ${entry.model} responded in ${entry.latency_ms ? Math.round(entry.latency_ms) + 'ms' : '...'}`;
      case 'ffmpeg':
        return entry.return_code === 0 
          ? `🎬 Encoding done (${entry.duration_sec ? entry.duration_sec.toFixed(1) + 's' : ''})`
          : `❌ Encoding failed (code ${entry.return_code})`;
      default:
        return 'Unknown event';
    }
  };

  const getIcon = (entry: LogEntry) => {
    if (entry.error) return '🔴';
    switch (entry.type) {
      case 'app': return entry.status === 'completed' ? '🟢' : entry.status === 'started' ? '🔵' : '🟡';
      case 'llm': return '🟣';
      case 'ffmpeg': return entry.return_code === 0 ? '🟢' : '🔴';
      default: return '⚪';
    }
  };

  return (
    <div className="flex flex-col h-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--border-color)] bg-[var(--bg-tertiary)] shrink-0">
        <span className="text-xs font-bold tracking-wider text-[var(--text-muted)] uppercase">System Log</span>
        <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
        <select
          value={filter}
          onChange={e => setFilter(e.target.value as any)}
          className="bg-[var(--bg-primary)] text-xs rounded px-2 py-1 border border-[var(--border-color)] text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-blue-500"
        >
          <option value="all">All Events</option>
          <option value="app">App Activity</option>
          <option value="llm">AI Thinking</option>
          <option value="ffmpeg">Video Encoding</option>
        </select>
        <label className="flex items-center gap-2 text-xs text-[var(--text-muted)] ml-auto cursor-pointer">
          <input type="checkbox" checked={autoScroll} onChange={e => setAutoScroll(e.target.checked)} className="rounded" />
          Auto-scroll
        </label>
      </div>

      {/* Log List */}
      <div className="flex-1 overflow-y-auto p-3 space-y-1">
        {filtered.length === 0 && (
          <div className="text-center text-[var(--text-muted)] py-12 text-sm">Waiting for activity...</div>
        )}
        {filtered.map((entry, i) => (
          <button
            key={i}
            onClick={() => setSelectedEntry(entry)}
            className={`w-full text-left p-2.5 rounded-lg border transition-all hover:opacity-80 ${
              selectedEntry === entry 
                ? 'bg-blue-500/10 border-blue-500/40' 
                : 'bg-[var(--bg-primary)] border-[var(--border-color)]'
            }`}
          >
            <div className="flex items-start gap-2">
              <span className="text-sm mt-0.5">{getIcon(entry)}</span>
              <div className="flex-1 min-w-0">
                <p className="text-xs text-[var(--text-primary)] font-medium leading-snug">{getSummary(entry)}</p>
                <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{new Date(entry.timestamp).toLocaleTimeString()}</p>
              </div>
            </div>
          </button>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Detail Panel */}
      {selectedEntry && (
        <div className="shrink-0 border-t border-[var(--border-color)] bg-[var(--bg-tertiary)] p-4 max-h-[200px] overflow-y-auto">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">Details</span>
            <button onClick={() => setSelectedEntry(null)} className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-xs">Close</button>
          </div>
          {selectedEntry.reasoning && (
            <div className="mb-2">
              <span className="text-[10px] font-bold text-purple-400 uppercase">AI Reasoning</span>
              <p className="text-xs text-[var(--text-secondary)] mt-1 whitespace-pre-wrap">{selectedEntry.reasoning}</p>
            </div>
          )}
          {selectedEntry.error && (
            <div className="mb-2 p-2 bg-red-950/30 rounded border border-red-900/40">
              <span className="text-[10px] font-bold text-red-400 uppercase">Error</span>
              <p className="text-xs text-red-300 mt-1">{selectedEntry.error}</p>
            </div>
          )}
          {selectedEntry.details && Object.keys(selectedEntry.details).length > 0 && (
            <pre className="text-[10px] text-[var(--text-muted)] overflow-x-auto">{JSON.stringify(selectedEntry.details, null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  );
};
