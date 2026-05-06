import React, { useState, useEffect } from 'react';
import { Users, MessageSquare, BarChart3, Bug, Database, Activity, ArrowLeft, RefreshCw, Clock, Mail, ChevronDown, ChevronUp } from 'lucide-react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '';

/* ── Stat Card ─────────────────────────────────────────────────────────── */
function StatCard({ icon: Icon, label, value, color, delay = 0 }) {
  return (
    <div
      className="relative overflow-hidden rounded-2xl border border-white/[0.06] bg-white/[0.025] backdrop-blur-xl p-5 transition-all duration-300 hover:border-white/[0.12] hover:bg-white/[0.04] group"
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
      <div className="mt-1 w-2 h-2 rounded-full flex-shrink-0" style={{ background: color, boxShadow: `0 0 8px ${color}60` }} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-black tracking-[0.15em] uppercase px-2 py-0.5 rounded-md" style={{ color, background: `${color}12`, border: `1px solid ${color}20` }}>
            {event.type}
          </span>
          <span className="text-[10px] text-slate-600 font-mono truncate">{event.email || 'anonymous'}</span>
        </div>
        {event.data && <p className="text-xs text-slate-400 mt-1 truncate">{event.data}</p>}
      </div>
      <span className="text-[10px] text-slate-600 font-mono flex-shrink-0 flex items-center gap-1">
        <Clock className="w-3 h-3" /> {ts}
      </span>
    </div>
  );
}

/* ── Feedback Card ─────────────────────────────────────────────────────── */
function FeedbackCard({ item, idx }) {
  const ts = item.ts ? new Date(item.ts * 1000).toLocaleString() : '—';
  return (
    <div className="p-4 rounded-xl border border-red-900/20 bg-red-950/10 animate-fade-in" style={{ animationDelay: `${idx * 80}ms` }}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Mail className="w-3 h-3 text-red-400" />
          <span className="text-xs text-red-300 font-mono">{item.email || 'anonymous'}</span>
        </div>
        <span className="text-[10px] text-slate-600 font-mono">{ts}</span>
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
export default function AdminDashboard({ onBack }) {
  const [summary, setSummary] = useState(null);
  const [events, setEvents] = useState([]);
  const [feedback, setFeedback] = useState([]);
  const [users, setUsers] = useState([]);
  const [activeTab, setActiveTab] = useState('overview');
  const [loading, setLoading] = useState(true);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [sumRes, evtRes, fbRes, usrRes] = await Promise.all([
        axios.get(`${API_URL}/api/admin/summary`),
        axios.get(`${API_URL}/api/admin/analytics`),
        axios.get(`${API_URL}/api/admin/feedback`),
        axios.get(`${API_URL}/api/admin/users`),
      ]);
      setSummary(sumRes.data);
      setEvents(evtRes.data?.events || []);
      setFeedback(fbRes.data?.feedback || []);
      setUsers(usrRes.data?.users || []);
    } catch (e) {
      console.error('Admin fetch error:', e);
    }
    setLoading(false);
  };

  useEffect(() => { fetchAll(); }, []);

  const tabs = [
    { id: 'overview', label: 'Overview', icon: BarChart3 },
    { id: 'activity', label: 'Activity', icon: Activity },
    { id: 'feedback', label: 'Feedback', icon: Bug },
    { id: 'users', label: 'Users', icon: Users },
  ];

  return (
    <div className="h-screen flex flex-col bg-[#050505] overflow-hidden">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className="flex-shrink-0 border-b border-white/[0.06] bg-white/[0.015] backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button onClick={onBack} className="p-2 rounded-xl border border-white/[0.06] bg-white/[0.03] hover:bg-white/[0.06] transition-colors">
              <ArrowLeft className="w-4 h-4 text-slate-400" />
            </button>
            <div>
              <h1 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
                <BarChart3 className="w-5 h-5 text-amber-400" />
                Admin Dashboard
              </h1>
              <p className="text-[10px] text-slate-600 font-mono tracking-[0.15em] uppercase mt-0.5">
                PRC SCAL AI Pipeline — Command Center
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {summary?.storage_type && (
              <div className={`px-3 py-1 rounded-full text-[10px] font-bold tracking-tighter uppercase border ${
                summary.storage_type.includes('PostgreSQL') 
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' 
                  : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
              }`}>
                {summary.storage_type}
              </div>
            )}
            <button
            onClick={fetchAll}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 rounded-xl border border-amber-900/30 bg-amber-950/20 text-amber-400 text-xs font-bold tracking-wider uppercase hover:bg-amber-950/40 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        {/* ── Tab Nav ─────────────────────────────────────────────────── */}
        <div className="max-w-7xl mx-auto px-6 flex gap-1">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-2.5 text-xs font-bold tracking-wider uppercase rounded-t-xl transition-all duration-200 ${
                activeTab === tab.id
                  ? 'bg-white/[0.05] text-amber-400 border-b-2 border-amber-400'
                  : 'text-slate-600 hover:text-slate-400 hover:bg-white/[0.02]'
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
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
                <StatCard icon={Users}        label="Users"        value={summary?.total_users ?? null}      color="#a855f7" delay={0} />
                <StatCard icon={MessageSquare} label="Messages"    value={summary?.total_messages ?? null}   color="#3b82f6" delay={60} />
                <StatCard icon={Activity}      label="Sessions"    value={summary?.total_sessions ?? null}   color="#22c55e" delay={120} />
                <StatCard icon={BarChart3}     label="Events"      value={summary?.total_events ?? null}     color="#f59e0b" delay={180} />
                <StatCard icon={Bug}           label="Feedback"    value={summary?.total_feedback ?? null}   color="#ef4444" delay={240} />
                <StatCard icon={Database}      label="KB Chunks"   value={summary?.total_kb_chunks ?? null}  color="#06b6d4" delay={300} />
              </div>

              {/* Recent Activity Preview */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] overflow-hidden">
                  <div className="px-5 py-3 border-b border-white/[0.06] flex items-center justify-between">
                    <span className="text-[10px] font-black tracking-[0.2em] text-slate-500 uppercase">Recent Activity</span>
                    <button onClick={() => setActiveTab('activity')} className="text-[10px] text-amber-500 hover:text-amber-400 font-bold uppercase tracking-wider">View All →</button>
                  </div>
                  <div className="px-5 py-2 max-h-64 overflow-y-auto">
                    {events.slice(0, 5).map((e, i) => <TimelineEvent key={i} event={e} idx={i} />)}
                    {events.length === 0 && <p className="text-sm text-slate-700 py-6 text-center italic">No events recorded yet</p>}
                  </div>
                </div>

                <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] overflow-hidden">
                  <div className="px-5 py-3 border-b border-white/[0.06] flex items-center justify-between">
                    <span className="text-[10px] font-black tracking-[0.2em] text-slate-500 uppercase">Recent Feedback</span>
                    <button onClick={() => setActiveTab('feedback')} className="text-[10px] text-amber-500 hover:text-amber-400 font-bold uppercase tracking-wider">View All →</button>
                  </div>
                  <div className="px-5 py-3 max-h-64 overflow-y-auto space-y-3">
                    {feedback.slice(0, 3).map((f, i) => <FeedbackCard key={i} item={f} idx={i} />)}
                    {feedback.length === 0 && <p className="text-sm text-slate-700 py-6 text-center italic">No feedback received yet</p>}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── ACTIVITY TAB ──────────────────────────────────────────── */}
          {activeTab === 'activity' && (
            <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] overflow-hidden animate-fade-in">
              <div className="px-5 py-3 border-b border-white/[0.06]">
                <span className="text-[10px] font-black tracking-[0.2em] text-slate-500 uppercase">All Activity Events ({events.length})</span>
              </div>
              <div className="px-5 py-2 max-h-[calc(100vh-260px)] overflow-y-auto">
                {events.map((e, i) => <TimelineEvent key={i} event={e} idx={i} />)}
                {events.length === 0 && <p className="text-sm text-slate-700 py-12 text-center italic">No events recorded yet</p>}
              </div>
            </div>
          )}

          {/* ── FEEDBACK TAB ──────────────────────────────────────────── */}
          {activeTab === 'feedback' && (
            <div className="space-y-4 animate-fade-in">
              <div className="text-[10px] font-black tracking-[0.2em] text-slate-500 uppercase">
                All Feedback Reports ({feedback.length})
              </div>
              <div className="max-h-[calc(100vh-220px)] overflow-y-auto space-y-3">
                {feedback.map((f, i) => <FeedbackCard key={i} item={f} idx={i} />)}
                {feedback.length === 0 && (
                  <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-12 text-center">
                    <Bug className="w-8 h-8 text-slate-800 mx-auto mb-3" />
                    <p className="text-sm text-slate-700 italic">No feedback reports submitted yet</p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── USERS TAB ─────────────────────────────────────────────── */}
          {activeTab === 'users' && (
            <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] overflow-hidden animate-fade-in">
              <div className="px-5 py-3 border-b border-white/[0.06]">
                <span className="text-[10px] font-black tracking-[0.2em] text-slate-500 uppercase">Registered Users ({users.length})</span>
              </div>
              <div className="overflow-x-auto max-h-[calc(100vh-260px)] overflow-y-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-white/[0.06]">
                      <th className="px-4 py-3 text-[10px] font-bold text-slate-600 uppercase tracking-widest">Email</th>
                      <th className="px-4 py-3 text-[10px] font-bold text-slate-600 uppercase tracking-widest">Name</th>
                      <th className="px-4 py-3 text-[10px] font-bold text-slate-600 uppercase tracking-widest">Registered</th>
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
