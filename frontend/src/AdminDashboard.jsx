/* eslint-disable no-unused-vars, react-hooks/set-state-in-effect */
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Users, MessageSquare, BarChart3, Bug, Database, Activity, ArrowLeft, RefreshCw, Clock, Mail, ChevronDown, ChevronUp, LogOut, Cpu, DollarSign } from 'lucide-react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '';

/* ── Stat Card ─────────────────────────────────────────────────────────── */
function StatCard({ icon: Icon, label, value, color, delay = 0 }) {
  return (
    <div
      className="relative overflow-hidden rounded-2xl border border-white/[0.06] bg-white/[0.025] backdrop-blur-xl p-5 transition-all duration-300 hover:border-white/[0.12] hover:bg-white/[0.04] group shadow-lg"
      style={{ animationDelay: `${delay}ms` }}
    >
      {/* Glow accent */}
      <div className={`absolute -top-8 -right-8 w-24 h-24 rounded-full opacity-[0.07] blur-2xl group-hover:opacity-[0.14] transition-opacity duration-500`} style={{ background: color }} />
      <div className="flex items-center gap-3 mb-3">
        <div className="p-2 rounded-xl" style={{ background: `${color}15`, border: `1px solid ${color}25` }}>
          <Icon className="w-4 h-4" style={{ color }} />
        </div>
        <span className="text-[10px] font-bold tracking-[0.2em] text-slate-500 uppercase">{label}</span>
      </div>
      <div className="text-3xl font-black text-white tracking-tight tabular-nums">
        {value !== null ? value.toLocaleString() : <span className="text-slate-600 text-lg animate-pulse">...</span>}
      </div>
    </div>
  );
}

/* ── Timeline Event ────────────────────────────────────────────────────── */
function TimelineEvent({ event, idx }) {
  const typeColors = {
    login: '#22c55e',
    page_view: '#3b82f6',
    chat: '#f59e0b',
    feedback: '#ef4444',
    register: '#a855f7'
  };
  const color = typeColors[event.type] || '#64748b';
  const ts = event.ts ? new Date(event.ts * 1000).toLocaleString() : '—';

  return (
    <div className="flex items-start gap-3 py-3 border-b border-white/[0.04] last:border-0 animate-fade-in" style={{ animationDelay: `${idx * 50}ms` }}>
      <div className="mt-1.5 w-2 h-2 rounded-full flex-shrink-0" style={{ background: color, boxShadow: `0 0 8px ${color}60` }} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-black tracking-[0.15em] uppercase px-2 py-0.5 rounded-full" style={{ color, background: `${color}12`, border: `1px solid ${color}20` }}>
            {event.type}
          </span>
          <span className="text-[10px] text-slate-500 font-mono truncate">{event.email || 'anonymous'}</span>
        </div>
        {event.data && <p className="text-xs text-slate-400 mt-1 truncate">{event.data}</p>}
      </div>
      <span className="text-[10px] text-slate-500 font-mono flex-shrink-0 flex items-center gap-1">
        <Clock className="w-3 h-3 text-slate-600" /> {ts}
      </span>
    </div>
  );
}

/* ── Feedback Card ─────────────────────────────────────────────────────── */
function FeedbackCard({ item, idx }) {
  const ts = item.ts ? new Date(item.ts * 1000).toLocaleString() : '—';
  return (
    <div className="p-4 rounded-2xl border border-red-500/10 bg-red-950/10 animate-fade-in" style={{ animationDelay: `${idx * 80}ms` }}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Mail className="w-3 h-3 text-red-400" />
          <span className="text-xs text-red-300 font-mono">{item.email || 'anonymous'}</span>
        </div>
        <span className="text-[10px] text-slate-500 font-mono">{ts}</span>
      </div>
      <p className="text-sm text-slate-300 leading-relaxed">{item.report}</p>
    </div>
  );
}

/* ── User Row ──────────────────────────────────────────────────────────── */
function UserRow({ user, idx }) {
  const ts = user.created_at ? new Date(user.created_at * 1000).toLocaleString() : '—';
  return (
    <tr className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors animate-fade-in" style={{ animationDelay: `${idx * 40}ms` }}>
      <td className="px-4 py-3 text-xs font-mono text-amber-400">{user.email}</td>
      <td className="px-4 py-3 text-xs text-slate-300">{user.name}</td>
      <td className="px-4 py-3 text-[10px] text-slate-600 font-mono">{ts}</td>
    </tr>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   ADMIN DASHBOARD — Main Export
   ══════════════════════════════════════════════════════════════════════════ */
export default function AdminDashboard({ adminToken, onBack, onLogout }) {
  const [summary, setSummary] = useState(null);
  const [events, setEvents] = useState([]);
  const [feedback, setFeedback] = useState([]);
  const [users, setUsers] = useState([]);
  const [activeTab, setActiveTab] = useState('overview');
  const [loading, setLoading] = useState(true);

  // Tracks mount state so in-flight requests don't setState after unmount (fix 2c).
  const isMountedRef = useRef(true);
  useEffect(() => () => { isMountedRef.current = false; }, []);

  // Stable ref for onBack — keeps it out of fetchAll's dep array so a
  // non-memoised parent prop doesn't trigger an infinite refetch loop (fix 2b).
  const onBackRef = useRef(onBack);
  useEffect(() => { onBackRef.current = onBack; }, [onBack]);

  // Stable ref for onLogout — used on 401 to clear the stale token so the
  // PIN gate is shown on the next Admin click instead of looping indefinitely.
  const onLogoutRef = useRef(onLogout);
  useEffect(() => { onLogoutRef.current = onLogout; }, [onLogout]);

  const fetchAll = useCallback(async () => {
    if (!adminToken) return;
    setLoading(true);
    try {
      const config = { headers: { Authorization: `Bearer ${adminToken}` } };
      const [sumRes, evtRes, fbRes, usrRes] = await Promise.all([
        axios.get(`${API_URL}/api/admin/summary`, config),
        axios.get(`${API_URL}/api/admin/analytics`, config),
        axios.get(`${API_URL}/api/admin/feedback`, config),
        axios.get(`${API_URL}/api/admin/users`, config),
      ]);
      if (!isMountedRef.current) return;
      setSummary(sumRes.data);
      setEvents(evtRes.data?.events || []);
      setFeedback(fbRes.data?.feedback || []);
      setUsers(usrRes.data?.users || []);
    } catch (e) {
      console.error('Admin fetch error:', e);
      if (e.response?.status === 401) onLogoutRef.current?.();
    } finally {
      if (isMountedRef.current) setLoading(false);
    }
  }, [adminToken]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const tabs = [
    { id: 'overview', label: 'Overview', icon: BarChart3 },
    { id: 'activity', label: 'Activity', icon: Activity },
    { id: 'feedback', label: 'Feedback', icon: Bug },
    { id: 'users', label: 'Users', icon: Users },
  ];

  return (
    <div className="h-screen flex flex-col bg-[#050507] overflow-hidden">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className="flex-shrink-0 border-b border-white/[0.06] bg-[#0a0a0c]/80 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-6 py-5 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button onClick={onBack} className="p-2.5 rounded-xl border border-white/[0.06] bg-white/[0.03] hover:bg-white/[0.08] transition-all hover:scale-105 active:scale-95">
              <ArrowLeft className="w-4 h-4 text-slate-400" />
            </button>
            <div>
              <h1 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
                <BarChart3 className="w-5 h-5 text-amber-400" />
                Admin Dashboard
              </h1>
              <p className="text-[10px] text-slate-500 font-mono tracking-[0.15em] uppercase mt-0.5">
                PRC SCAL AI Pipeline — Command Center
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {summary?.storage_type && (
              <div className={`px-3 py-1 rounded-full text-[10px] font-bold tracking-wider uppercase border ${
                summary.storage_type.includes('PostgreSQL') 
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20 shadow-[0_0_10px_rgba(16,185,129,0.1)]' 
                  : 'bg-amber-500/10 text-amber-400 border-amber-500/20 shadow-[0_0_10px_rgba(245,158,11,0.1)]'
              }`}>
                {summary.storage_type}
              </div>
            )}
            <button
              onClick={fetchAll}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2 rounded-full border border-amber-500/20 bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 text-xs font-bold tracking-wider uppercase transition-all hover:scale-105 active:scale-95 disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
            
            <div className="h-6 w-px bg-white/[0.06] mx-1" />

            <button
              onClick={onLogout}
              className="flex items-center gap-2 px-4 py-2 rounded-full border border-red-500/20 bg-red-500/10 hover:bg-red-500/20 text-red-400 text-xs font-bold tracking-wider uppercase transition-all hover:scale-105 active:scale-95"
            >
              <LogOut className="w-3.5 h-3.5" />
              Logout
            </button>
          </div>
        </div>

        {/* ── Tab Nav ─────────────────────────────────────────────────── */}
        <div className="max-w-7xl mx-auto px-6 pb-3 flex gap-2">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-5 py-2.5 text-xs font-black tracking-widest uppercase rounded-full transition-all duration-300 ${
                activeTab === tab.id
                  ? 'bg-amber-400/15 text-amber-400 border border-amber-400/30 shadow-[0_0_15px_rgba(251,191,36,0.15)]'
                  : 'text-slate-500 hover:text-slate-300 hover:bg-white/[0.04] border border-transparent'
              }`}
            >
              <tab.icon className="w-3.5 h-3.5" />
              {tab.label}
            </button>
          ))}
        </div>
      </header>

      {/* ── Content ────────────────────────────────────────────────────── */}
      <main className="flex-1 overflow-y-auto p-6">
        <div className="max-w-7xl mx-auto">

          {/* ── OVERVIEW TAB ─────────────────────────────────────────── */}
          {activeTab === 'overview' && (
            <div className="space-y-6 animate-fade-in">
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-4">
                <StatCard icon={Users}         label="Users"        value={summary?.total_users ?? null}      color="#a855f7" delay={0} />
                <StatCard icon={MessageSquare}  label="Messages"     value={summary?.total_messages ?? null}   color="#3b82f6" delay={40} />
                <StatCard icon={Activity}       label="Sessions"     value={summary?.total_sessions ?? null}   color="#22c55e" delay={80} />
                <StatCard icon={Database}       label="KB Chunks"    value={summary?.total_kb_chunks ?? null}  color="#38bdf8" delay={120} />
                <StatCard icon={Bug}            label="Feedback"     value={summary?.total_feedback ?? null}   color="#ef4444" delay={160} />
                <StatCard icon={Cpu}            label="AI Tokens"    value={summary?.total_tokens ?? null} color="#06b6d4" delay={200} />
                <StatCard icon={DollarSign}     label="AI API Cost"  value={summary?.total_cost_usd != null ? "$" + summary.total_cost_usd.toFixed(2) : null} color="#10b981" delay={240} />
                <StatCard icon={Users}          label="AI Engineers" value={summary?.total_engineers ?? null}  color="#f59e0b" delay={280} />
              </div>

              {/* API Usage & Token Analytics Row */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                
                {/* AI Token Breakdown by Engineer */}
                <div className="lg:col-span-2 rounded-[2rem] border border-white/[0.06] bg-[#0c0c12]/50 backdrop-blur-xl shadow-xl overflow-hidden">
                  <div className="px-6 py-4 border-b border-white/[0.06] flex items-center justify-between bg-white/[0.01]">
                    <span className="text-[10px] font-black tracking-[0.2em] text-slate-500 uppercase flex items-center gap-2">
                      <Users className="w-4 h-4 text-purple-400" />
                      AI Engineer Token Consumption
                    </span>
                  </div>
                  <div className="overflow-x-auto max-h-80 overflow-y-auto">
                    <table className="w-full text-left">
                      <thead>
                        <tr className="border-b border-white/[0.04]">
                          <th className="px-6 py-3 text-[10px] font-bold text-slate-500 uppercase tracking-widest">Engineer</th>
                          <th className="px-6 py-3 text-[10px] font-bold text-slate-500 uppercase tracking-widest text-right">Sessions</th>
                          <th className="px-6 py-3 text-[10px] font-bold text-slate-500 uppercase tracking-widest text-right">Tokens Consumed</th>
                          <th className="px-6 py-3 text-[10px] font-bold text-slate-500 uppercase tracking-widest text-right">Estimated Cost</th>
                        </tr>
                      </thead>
                      <tbody>
                        {summary?.engineer_breakdown?.map((eng, idx) => (
                          <tr key={idx} className="border-b border-white/[0.02] hover:bg-white/[0.01] transition-colors">
                            <td className="px-6 py-3.5 text-xs font-mono text-slate-300">{eng.email}</td>
                            <td className="px-6 py-3.5 text-xs text-right text-slate-400 tabular-nums">{eng.sessions}</td>
                            <td className="px-6 py-3.5 text-xs font-bold text-right text-cyan-400 tabular-nums">{eng.tokens?.toLocaleString()}</td>
                            <td className="px-6 py-3.5 text-xs font-bold text-right text-emerald-400 tabular-nums">${eng.cost?.toFixed(4)}</td>
                          </tr>
                        ))}
                        {(!summary?.engineer_breakdown || summary.engineer_breakdown.length === 0) && (
                          <tr>
                            <td colSpan={4} className="px-6 py-12 text-center text-slate-600 italic text-sm">
                              No engineer AI usage recorded yet
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Model Split Distribution */}
                <div className="rounded-[2rem] border border-white/[0.06] bg-[#0c0c12]/50 backdrop-blur-xl shadow-xl overflow-hidden p-6 flex flex-col justify-between">
                  <div>
                    <span className="text-[10px] font-black tracking-[0.2em] text-slate-500 uppercase block mb-6">Model Distribution</span>
                    <div className="space-y-5">
                      {summary?.model_breakdown?.map((m, idx) => {
                        const colors = m.model.includes('pro') ? { text: 'text-purple-400', bg: 'bg-purple-500/25', bar: 'bg-purple-500' } : { text: 'text-cyan-400', bg: 'bg-cyan-500/25', bar: 'bg-cyan-500' };
                        const total = summary.total_tokens || 1;
                        const pct = Math.min(100, Math.round((m.tokens / total) * 100));
                        return (
                          <div key={idx} className="space-y-2">
                            <div className="flex justify-between items-center text-xs">
                              <span className="font-mono text-slate-300">{m.model}</span>
                              <span className={`font-bold ${colors.text}`}>{pct}%</span>
                            </div>
                            <div className={`h-2 rounded-full ${colors.bg} overflow-hidden`}>
                              <div className={`h-full rounded-full ${colors.bar}`} style={{ width: `${pct}%` }} />
                            </div>
                            <div className="flex justify-between text-[10px] text-slate-500 font-mono">
                              <span>{m.tokens?.toLocaleString()} tkn</span>
                              <span>${m.cost?.toFixed(2)}</span>
                            </div>
                          </div>
                        );
                      })}
                      {(!summary?.model_breakdown || summary.model_breakdown.length === 0) && (
                        <p className="text-sm text-slate-600 italic py-12 text-center">No model analytics available</p>
                      )}
                    </div>
                  </div>
                  
                  {/* Subtle Cost Warning */}
                  <div className="mt-6 p-4 rounded-xl border border-white/[0.04] bg-white/[0.01] text-[10px] text-slate-500 leading-relaxed font-mono">
                    <span className="text-slate-400 font-bold block mb-1">Telemetry Pricing Rules:</span>
                    • gemini-2.5-flash: $0.075 / $0.30 per 1M<br/>
                    • gemini-2.5-pro: $1.25 / $5.00 per 1M
                  </div>
                </div>
              </div>

              {/* Recent Activity Preview */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="rounded-[2rem] border border-white/[0.06] bg-[#0c0c12]/50 backdrop-blur-xl shadow-xl overflow-hidden">
                  <div className="px-6 py-4 border-b border-white/[0.06] flex items-center justify-between bg-white/[0.01]">
                    <span className="text-[10px] font-black tracking-[0.2em] text-slate-500 uppercase">Recent Activity</span>
                    <button onClick={() => setActiveTab('activity')} className="text-[10px] text-amber-500 hover:text-amber-400 font-bold uppercase tracking-wider transition-colors">View All →</button>
                  </div>
                  <div className="px-6 py-3 max-h-64 overflow-y-auto">
                    {events.slice(0, 5).map((e, i) => <TimelineEvent key={i} event={e} idx={i} />)}
                    {events.length === 0 && <p className="text-sm text-slate-600 py-6 text-center italic">No events recorded yet</p>}
                  </div>
                </div>

                <div className="rounded-[2rem] border border-white/[0.06] bg-[#0c0c12]/50 backdrop-blur-xl shadow-xl overflow-hidden">
                  <div className="px-6 py-4 border-b border-white/[0.06] flex items-center justify-between bg-white/[0.01]">
                    <span className="text-[10px] font-black tracking-[0.2em] text-slate-500 uppercase">Recent Feedback</span>
                    <button onClick={() => setActiveTab('feedback')} className="text-[10px] text-amber-500 hover:text-amber-400 font-bold uppercase tracking-wider transition-colors">View All →</button>
                  </div>
                  <div className="px-6 py-4 max-h-64 overflow-y-auto space-y-3">
                    {feedback.slice(0, 3).map((f, i) => <FeedbackCard key={i} item={f} idx={i} />)}
                    {feedback.length === 0 && <p className="text-sm text-slate-600 py-6 text-center italic">No feedback received yet</p>}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── ACTIVITY TAB ──────────────────────────────────────────── */}
          {activeTab === 'activity' && (
            <div className="rounded-[2rem] border border-white/[0.06] bg-[#0c0c12]/50 backdrop-blur-xl shadow-xl overflow-hidden animate-fade-in">
              <div className="px-6 py-4 border-b border-white/[0.06] bg-white/[0.01]">
                <span className="text-[10px] font-black tracking-[0.2em] text-slate-500 uppercase">All Activity Events ({events.length})</span>
              </div>
              <div className="px-6 py-3 max-h-[calc(100vh-260px)] overflow-y-auto">
                {events.map((e, i) => <TimelineEvent key={i} event={e} idx={i} />)}
                {events.length === 0 && <p className="text-sm text-slate-600 py-12 text-center italic">No events recorded yet</p>}
              </div>
            </div>
          )}

          {/* ── FEEDBACK TAB ──────────────────────────────────────────── */}
          {activeTab === 'feedback' && (
            <div className="space-y-4 animate-fade-in">
              <div className="text-[10px] font-black tracking-[0.2em] text-slate-500 uppercase px-1">
                All Feedback Reports ({feedback.length})
              </div>
              <div className="max-h-[calc(100vh-220px)] overflow-y-auto space-y-3">
                {feedback.map((f, i) => <FeedbackCard key={i} item={f} idx={i} />)}
                {feedback.length === 0 && (
                  <div className="rounded-[2rem] border border-white/[0.06] bg-[#0c0c12]/50 backdrop-blur-xl p-12 text-center shadow-xl">
                    <Bug className="w-8 h-8 text-slate-800 mx-auto mb-3" />
                    <p className="text-sm text-slate-700 italic">No feedback reports submitted yet</p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── USERS TAB ─────────────────────────────────────────────── */}
          {activeTab === 'users' && (
            <div className="rounded-[2rem] border border-white/[0.06] bg-[#0c0c12]/50 backdrop-blur-xl shadow-xl overflow-hidden animate-fade-in">
              <div className="px-6 py-4 border-b border-white/[0.06] bg-white/[0.01]">
                <span className="text-[10px] font-black tracking-[0.2em] text-slate-500 uppercase">Registered Users ({users.length})</span>
              </div>
              <div className="overflow-x-auto max-h-[calc(100vh-260px)] overflow-y-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-white/[0.06]">
                      <th className="px-6 py-4 text-[10px] font-bold text-slate-500 uppercase tracking-widest">Email</th>
                      <th className="px-6 py-4 text-[10px] font-bold text-slate-500 uppercase tracking-widest">Name</th>
                      <th className="px-6 py-4 text-[10px] font-bold text-slate-500 uppercase tracking-widest">Registered</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u, i) => <UserRow key={i} user={u} idx={i} />)}
                  </tbody>
                </table>
                {users.length === 0 && (
                  <div className="p-12 text-center">
                    <Users className="w-8 h-8 text-slate-800 mx-auto mb-3" />
                    <p className="text-sm text-slate-700 italic">No registered users yet</p>
                  </div>
                )}
              </div>
            </div>
          )}

        </div>
      </main>
    </div>
  );
}
