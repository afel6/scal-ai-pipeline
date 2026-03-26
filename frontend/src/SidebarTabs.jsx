import React, { useState, useEffect } from 'react';
import { MessageSquare, Trash2, BookOpen, Upload, CheckCircle, Loader, FileText } from 'lucide-react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function timeAgo(ts) {
  const diff = Date.now() / 1000 - ts;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function SidebarTabs({ sessionId, sessions, handleLoadSession, handleDeleteSession }) {
  const [tab, setTab] = useState('chats');
  const [books, setBooks] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState('');

  const loadBooks = async () => {
    try {
      const { data } = await axios.get(`${API_URL}/api/kb/status`);
      setBooks(data.books || []);
    } catch {}
  };

  useEffect(() => { if (tab === 'library') loadBooks(); }, [tab]);

  const handleBookUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    setUploadMsg('');
    const form = new FormData();
    form.append('file', file);
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
          className={`flex-1 py-2.5 text-[11px] font-bold tracking-widest uppercase flex items-center justify-center gap-1.5 transition-all
            ${tab === 'chats' ? 'text-yellow-400 border-b-2 border-yellow-500' : 'text-slate-500 hover:text-slate-300'}`}
        >
          <MessageSquare className="w-3.5 h-3.5" /> Chats
        </button>
        <button
          onClick={() => setTab('library')}
          className={`flex-1 py-2.5 text-[11px] font-bold tracking-widest uppercase flex items-center justify-center gap-1.5 transition-all
            ${tab === 'library' ? 'text-yellow-400 border-b-2 border-yellow-500' : 'text-slate-500 hover:text-slate-300'}`}
        >
          <BookOpen className="w-3.5 h-3.5" /> Library
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
              className={`group flex items-start gap-3 px-3 py-3 rounded-xl cursor-pointer transition-all border
                ${s.id === sessionId
                  ? 'bg-yellow-950/40 border-yellow-800/50 text-yellow-100'
                  : 'border-transparent hover:bg-slate-900 hover:border-slate-800 text-slate-400 hover:text-slate-200'
                }`}>
              <MessageSquare className="w-4 h-4 mt-0.5 shrink-0 text-yellow-500/60" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{s.title}</p>
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
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          <p className="text-[10px] text-slate-500 font-mono uppercase tracking-widest">Upload books to teach Hviel</p>
          
          {/* Upload button */}
          <label className={`flex items-center justify-center gap-2 w-full border-2 border-dashed rounded-xl py-4 cursor-pointer transition-all
            ${uploading ? 'border-yellow-700 bg-yellow-950/20' : 'border-slate-700 hover:border-yellow-600 hover:bg-yellow-950/10'}`}>
            <input type="file" className="hidden" onChange={handleBookUpload} disabled={uploading}
              accept=".html,.htm,.txt,.pdf" />
            {uploading ? (
              <><Loader className="w-4 h-4 text-yellow-400 animate-spin" /><span className="text-xs text-yellow-400 font-bold">Processing…</span></>
            ) : (
              <><Upload className="w-4 h-4 text-slate-400" /><span className="text-xs text-slate-400 font-medium">Click to upload book<br/><span className="text-[10px] text-slate-600">HTML, TXT, PDF</span></span></>
            )}
          </label>

          {/* Upload result message */}
          {uploadMsg && (
            <p className="text-[11px] text-yellow-300 bg-yellow-950/30 border border-yellow-800/30 rounded-lg px-3 py-2 leading-relaxed">{uploadMsg}</p>
          )}

          {/* Loaded books */}
          {books.length > 0 ? (
            <div className="space-y-2">
              <p className="text-[10px] text-slate-600 uppercase tracking-widest font-bold">Knowledge Base</p>
              {books.map((b, i) => (
                <div key={i} className="flex items-center gap-2 bg-slate-900/60 border border-slate-800 rounded-xl px-3 py-2.5">
                  <CheckCircle className="w-3.5 h-3.5 text-green-500 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-slate-200 font-medium truncate">{b.name}</p>
                    <p className="text-[10px] text-slate-600">{b.chunks} chunks loaded</p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-600 text-center mt-4">No books uploaded yet.</p>
          )}
        </div>
      )}
    </>
  );
}
