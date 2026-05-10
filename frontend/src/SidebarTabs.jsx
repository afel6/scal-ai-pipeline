import React, { useState, useEffect } from 'react';
import { MessageSquare, Trash2, BookOpen, Upload, CheckCircle, Loader, FileText, Zap, Camera, Database } from 'lucide-react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '';

function timeAgo(ts) {
  const diff = Date.now() / 1000 - ts;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function SidebarTabs({ sessionId, sessions, handleLoadSession, handleDeleteSession, handleRenameSession, tab, setTab }) {
  const [editingId, setEditingId] = useState(null);
  const [editingTitle, setEditingTitle] = useState('');

  const [books, setBooks] = useState([]);
  const [skills, setSkills] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState('');
  const [bookPassword, setBookPassword] = useState('');

  const loadBooks = async () => {
    try {
      const { data } = await axios.get(`${API_URL}/api/kb/status`);
      setBooks(data.books || []);
    } catch {}
  };

  const loadSkills = async () => {
    try {
      const { data } = await axios.get(`${API_URL}/api/skills/list`);
      setSkills(data.skills || []);
    } catch (err) {
      console.error("Failed to load skills:", err);
    }
  };

  useEffect(() => { 
    if (tab === 'library') {
      loadBooks();
      loadSkills();
    } 
  }, [tab]);

  const handleBookUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    if (bookPassword !== '1509') {
      alert("Invalid Admin Password.");
      e.target.value = '';
      return;
    }

    setUploading(true);
    setUploadMsg('');
    const form = new FormData();
    form.append('file', file);
    form.append('password', bookPassword);
    try {
      const { data } = await axios.post(`${API_URL}/api/kb/ingest`, form, { timeout: 120000 });
      if (data.status === 'success') {
        setUploadMsg(`✅ "${data.book}" — ${data.chunks_stored} chunks (${(data.words/1000).toFixed(1)}k words)`);
        await loadBooks();
      } else {
        setUploadMsg(`❌ ${data.message || 'Upload failed'}`);
      }
    } catch (err) {
      setUploadMsg('❌ Upload failed. Try again.');
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  return (
    <>
      {/* Tabs */}
      <div className="flex border-b border-slate-800/60 shrink-0">
        <button
          onClick={() => setTab('chats')}
          className={`sidebar-tab flex-1 py-2.5 text-[11px] font-bold tracking-widest uppercase flex items-center justify-center gap-1.5
            ${tab === 'chats' ? 'text-yellow-400 active' : 'text-slate-500 hover:text-slate-300'}`}
        >
          <MessageSquare className="w-3.5 h-3.5" /> Chats
        </button>
        <button
          onClick={() => setTab('library')}
          className={`sidebar-tab flex-1 py-2.5 text-[11px] font-bold tracking-widest uppercase flex items-center justify-center gap-1.5
            ${tab === 'library' ? 'text-yellow-400 active' : 'text-slate-500 hover:text-slate-300'}`}
        >
          <Database className="w-3.5 h-3.5" /> Library
        </button>
        <button
          onClick={() => setTab('audit')}
          className={`sidebar-tab flex-1 py-2.5 text-[11px] font-bold tracking-widest uppercase flex items-center justify-center gap-1.5
            ${tab === 'audit' ? 'text-yellow-400 active' : 'text-slate-500 hover:text-slate-300'}`}
        >
          <Camera className="w-3.5 h-3.5" /> Auditor
        </button>
      </div>

      {/* Chats tab */}
      {tab === 'chats' && (
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {sessions.length === 0 && (
            <p className="text-slate-600 text-xs text-center mt-8 px-4 leading-relaxed">
              No past conversations yet.<br />Start a new SCAL study above.
            </p>
          )}
          {sessions.map(s => (
            <div key={s.id} onClick={() => handleLoadSession(s.id)}
              className={`session-item group flex items-start gap-3 px-3 py-3 rounded-xl cursor-pointer
                ${s.id === sessionId
                  ? 'active text-yellow-100'
                  : 'text-slate-400 hover:text-slate-200'
                }`}>
              <MessageSquare className="w-4 h-4 mt-0.5 shrink-0 text-yellow-500/60" />
              <div className="flex-1 min-w-0">
                {editingId === s.id ? (
                  <input
                    autoFocus
                    className="w-full bg-black/50 border border-yellow-500/50 rounded px-1.5 py-0.5 text-sm text-yellow-100 outline-none"
                    value={editingTitle}
                    onChange={(e) => setEditingTitle(e.target.value)}
                    onBlur={() => {
                      handleRenameSession(s.id, editingTitle);
                      setEditingId(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        handleRenameSession(s.id, editingTitle);
                        setEditingId(null);
                      }
                      if (e.key === 'Escape') setEditingId(null);
                    }}
                    onClick={(e) => e.stopPropagation()}
                  />
                ) : (
                  <p 
                    className="text-sm font-medium truncate"
                    onDoubleClick={(e) => {
                      e.stopPropagation();
                      setEditingId(s.id);
                      setEditingTitle(s.title);
                    }}
                  >
                    {s.title}
                  </p>
                )}
                <p className="text-[10px] text-slate-600 mt-0.5">{timeAgo(s.created_at)}</p>
              </div>
              <button onClick={(e) => handleDeleteSession(e, s.id)} className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-400 transition-all shrink-0">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Library tab */}
      {tab === 'library' && (
        <div className="flex-1 overflow-y-auto p-3 space-y-4 custom-scrollbar">
          <div className="bg-gradient-to-br from-yellow-500/5 to-transparent border border-yellow-500/10 rounded-2xl p-4 space-y-3">
            <p className="text-[10px] text-yellow-500 font-black uppercase tracking-[0.2em] flex items-center gap-2">
              <BookOpen className="w-3 h-3" /> Core Ingestion
            </p>
            <p className="text-[10px] text-slate-500 font-mono leading-relaxed">Admin portal for training Hviel on proprietary laboratory manuals.</p>
            
            <div className="space-y-2">
              <input 
                type="password" 
                placeholder="Admin PIN"
                value={bookPassword}
                onChange={(e) => setBookPassword(e.target.value)}
                className="w-full bg-black border border-slate-800 rounded-xl px-3 py-2.5 text-xs text-slate-200 outline-none focus:border-yellow-500/50 placeholder:text-slate-700 transition-all"
              />
              <label className={`upload-zone flex flex-col items-center justify-center gap-3 w-full rounded-2xl py-6 cursor-pointer
                ${uploading ? 'border-yellow-500 bg-yellow-500/5 !border-solid !border-2' : ''}`}>
                <input type="file" className="hidden" onChange={handleBookUpload} disabled={uploading}
                  accept=".html,.htm,.txt,.pdf,.docx" />
                {uploading ? (
                  <>
                    <div className="relative">
                      <Loader className="w-6 h-6 text-yellow-500 animate-spin" />
                      <div className="absolute inset-0 blur-lg bg-yellow-500/20 animate-pulse" />
                    </div>
                    <span className="text-[10px] text-yellow-500 font-black uppercase tracking-widest italic">Indexing Chunks...</span>
                  </>
                ) : (
                  <>
                    <div className="w-10 h-10 rounded-xl bg-slate-900 border border-slate-800 flex items-center justify-center text-slate-500 group-hover:text-yellow-500 transition-colors">
                      <Upload className="w-5 h-5" />
                    </div>
                    <div className="text-center">
                      <span className="text-[11px] text-slate-400 font-bold uppercase tracking-widest block">Deploy Knowledge</span>
                      <span className="text-[9px] text-slate-600 font-mono uppercase mt-1">PDF, DOCX, HTML</span>
                    </div>
                  </>
                )}
              </label>
            </div>

            {uploadMsg && (
              <div className={`text-[10px] font-bold p-3 rounded-xl border leading-relaxed animate-in fade-in slide-in-from-top-2
                ${uploadMsg.includes('✅') ? 'bg-green-500/5 border-green-500/20 text-green-400' : 'bg-red-500/5 border-red-500/20 text-red-400'}`}>
                {uploadMsg}
              </div>
            )}
          </div>

          <div className="space-y-3 pt-2">
            <div className="flex items-center justify-between px-1">
              <p className="text-[10px] text-yellow-500 font-black uppercase tracking-[0.2em] flex items-center gap-2 italic">
                <Zap className="w-3 h-3 fill-yellow-500" /> Agent Capabilities
              </p>
              <div className="flex gap-1">
                <div className="w-1 h-1 bg-yellow-500 rounded-full animate-pulse" />
                <div className="w-1 h-1 bg-yellow-500 rounded-full animate-pulse [animation-delay:0.2s]" />
              </div>
            </div>

            <div className="space-y-2.5">
              {skills.map((s, i) => (
                <div key={i} className="group relative overflow-hidden rounded-2xl bg-[#0c0c10] border border-slate-800 hover:border-yellow-900/40 transition-all p-4 shadow-xl">
                  <div className="absolute top-0 right-0 w-24 h-24 bg-yellow-500/5 blur-3xl opacity-0 group-hover:opacity-100 transition-opacity" />
                  <div className="relative flex items-center gap-2 mb-2">
                    <span className="text-[8px] font-black text-yellow-600 bg-yellow-950/30 px-1.5 py-0.5 rounded uppercase tracking-[0.15em] border border-yellow-900/20">{s.category}</span>
                    <span className="text-xs font-black text-slate-200 uppercase tracking-wider">{s.name}</span>
                  </div>
                  <p className="relative text-[10px] text-slate-500 leading-relaxed font-medium group-hover:text-slate-400 transition-colors">{s.desc}</p>
                </div>
              ))}
            </div>
          </div>

          {books.length > 0 && (
            <div className="space-y-3 pt-4 pb-10 border-t border-slate-800/40">
              <p className="text-[10px] text-slate-500 font-black uppercase tracking-[0.2em] px-1 italic">Knowledge Base Status</p>
              <div className="space-y-2">
                {books.map((b, i) => (
                  <div key={i} className="kb-item flex items-center gap-3 bg-black/40 rounded-xl px-3 py-3 group">
                    <div className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.4)]" />
                    <div className="flex-1 min-w-0">
                      <p className="text-[11px] text-slate-300 font-bold truncate group-hover:text-white transition-colors">{b.name}</p>
                      <p className="text-[9px] text-slate-600 font-mono mt-0.5 uppercase tracking-tighter">{b.chunks} Data Shards Active</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );
}
