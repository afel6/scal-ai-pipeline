import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Paperclip, Bot, User, Download, FileText, Database, Circle, PlusCircle, Trash2, MessageSquare, ChevronLeft, ChevronRight } from 'lucide-react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const WELCOME_MSG = { role: 'model', text: 'Welcome to the PRC Engineering Hub.\n\nI am your dedicated SCAL AI Co-Author. Tell me your Well Name, paste lab data, or attach Excel files and core photographs to begin our analysis.' };

function timeAgo(ts) {
  const diff = Date.now() / 1000 - ts;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function App() {
  const [messages, setMessages] = useState([WELCOME_MSG]);
  const [input, setInput] = useState('');
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState(() => localStorage.getItem('prc_session_id') || '');
  const [sessions, setSessions] = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (sessionId) localStorage.setItem('prc_session_id', sessionId);
  }, [sessionId]);

  // Poll session list for the sidebar
  const refreshSessions = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API_URL}/api/sessions`);
      setSessions(data);
    } catch {}
  }, []);

  useEffect(() => {
    refreshSessions();
    const interval = setInterval(refreshSessions, 5000);
    return () => clearInterval(interval);
  }, [refreshSessions]);

  const handleNewChat = async () => {
    if (sessionId) {
      try { await axios.delete(`${API_URL}/api/session/${sessionId}`); } catch {}
      await refreshSessions();
    }
    setSessionId('');
    localStorage.removeItem('prc_session_id');
    setMessages([WELCOME_MSG]);
  };

  const handleLoadSession = async (sid) => {
    if (sid === sessionId) return;
    try {
      const { data } = await axios.get(`${API_URL}/api/session/${sid}`);
      if (data.status === 'ok') {
        setSessionId(sid);
        // Reconstruct UI messages from stored history
        const uiMessages = [WELCOME_MSG, ...data.messages.map(m => ({ role: m.role, text: m.text }))];
        setMessages(uiMessages);
      }
    } catch {}
  };

  const handleDeleteSession = async (e, sid) => {
    e.stopPropagation();
    await axios.delete(`${API_URL}/api/session/${sid}`);
    await refreshSessions();
    if (sid === sessionId) {
      setSessionId('');
      localStorage.removeItem('prc_session_id');
      setMessages([WELCOME_MSG]);
    }
  };

  const handleSend = async () => {
    if (!input.trim() && !file) return;
    const userMessage = { role: 'user', text: input, fileName: file ? file.name : null };
    setMessages(prev => [...prev, userMessage]);

    const formData = new FormData();
    formData.append('message', input);
    formData.append('session_id', sessionId);
    if (file) formData.append('file', file);
    setInput('');
    setFile(null);
    setLoading(true);

    try {
      const response = await axios.post(`${API_URL}/api/chat`, formData, { timeout: 90000 });
      if (response.data.session_id) setSessionId(response.data.session_id);

      if (response.data.status === 'success') {
        setMessages(prev => [...prev, {
          role: 'model',
          text: response.data.reply,
          download_url: response.data.is_report_ready ? response.data.download_url : null
        }]);
      } else {
        setMessages(prev => [...prev, { role: 'model', text: `❌ ${response.data.reply}` }]);
      }
      await refreshSessions();
    } catch (err) {
      setMessages(prev => [...prev, { role: 'model', text: 'NETWORK ERROR: Python backend offline. Run run_pipeline.bat.' }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#09090b] text-slate-100 flex font-sans overflow-hidden h-screen">

      {/* ── Sidebar ── */}
      <aside className={`flex flex-col bg-[#050505] border-r border-slate-800/60 transition-all duration-300 ${sidebarOpen ? 'w-72' : 'w-0 overflow-hidden'}`}>
        {/* Sidebar Header */}
        <div className="p-4 border-b border-slate-800/60 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <Database className="w-5 h-5 text-emerald-500" />
            <span className="text-sm font-black tracking-widest text-emerald-50">PRC STUDIES</span>
          </div>
          <button
            onClick={handleNewChat}
            className="flex items-center gap-1.5 text-xs text-emerald-400 hover:text-emerald-300 border border-emerald-800/50 hover:border-emerald-600 px-2 py-1.5 rounded-lg transition-all"
          >
            <PlusCircle className="w-3.5 h-3.5" /> New
          </button>
        </div>

        {/* Session List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {sessions.length === 0 && (
            <p className="text-slate-600 text-xs text-center mt-8 px-4 leading-relaxed">
              No past conversations yet.<br />Start a new SCAL study above.
            </p>
          )}
          {sessions.map(s => (
            <div
              key={s.id}
              onClick={() => handleLoadSession(s.id)}
              className={`group flex items-start gap-3 px-3 py-3 rounded-xl cursor-pointer transition-all border ${
                s.id === sessionId
                  ? 'bg-emerald-950/40 border-emerald-800/50 text-emerald-100'
                  : 'border-transparent hover:bg-slate-900 hover:border-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              <MessageSquare className="w-4 h-4 mt-0.5 shrink-0 text-emerald-500/60" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{s.title}</p>
                <p className="text-[10px] text-slate-600 mt-0.5">{timeAgo(s.created_at)}</p>
              </div>
              <button
                onClick={(e) => handleDeleteSession(e, s.id)}
                className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-400 transition-all shrink-0"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>

        <div className="p-4 border-t border-slate-800/60 shrink-0">
          <p className="text-[10px] text-slate-700 font-mono tracking-widest uppercase text-center">Petroleum Research Center</p>
        </div>
      </aside>

      {/* ── Main Chat Area ── */}
      <div className="flex-1 flex flex-col min-w-0">

        {/* Top Bar */}
        <header className="bg-[#050505] border-b border-slate-800/60 p-4 flex items-center justify-between shrink-0 z-10">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(p => !p)}
              className="p-1.5 hover:bg-slate-800 rounded-lg transition-colors text-slate-400 hover:text-white"
            >
              {sidebarOpen ? <ChevronLeft className="w-5 h-5" /> : <ChevronRight className="w-5 h-5" />}
            </button>
            <span className="text-sm font-bold tracking-widest text-emerald-50 uppercase">
              {sessions.find(s => s.id === sessionId)?.title || 'New Study'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Circle className="w-2 h-2 text-emerald-500 fill-emerald-500 animate-pulse" />
            <span className="text-xs text-emerald-500/60 font-mono tracking-widest">GEMINI FLASH</span>
          </div>
        </header>

        {/* Chat Log */}
        <main className="flex-1 overflow-y-auto p-4 md:p-8 space-y-6 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-slate-900/10 via-[#09090b] to-[#09090b]">
          {messages.map((msg, idx) => (
            <div key={idx} className={`flex gap-4 max-w-3xl ${msg.role === 'user' ? 'ml-auto flex-row-reverse' : ''}`}>
              <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 border ${
                msg.role === 'user' ? 'bg-slate-800 border-slate-700' : 'bg-emerald-950 border-emerald-800/50'
              }`}>
                {msg.role === 'user' ? <User className="w-3.5 h-3.5 text-slate-300" /> : <Bot className="w-3.5 h-3.5 text-emerald-400" />}
              </div>
              <div className={`p-4 rounded-2xl text-[15px] leading-relaxed shadow-lg max-w-[85%] ${
                msg.role === 'user'
                  ? 'bg-slate-800 text-slate-200 rounded-tr-none border border-slate-700/50'
                  : 'bg-[#111116] text-emerald-50/90 rounded-tl-none border border-emerald-900/30'
              }`}>
                {msg.fileName && (
                  <div className="flex items-center gap-2 mb-3 bg-black/40 p-2 rounded-lg border border-slate-700/50 w-fit">
                    <FileText className="w-3.5 h-3.5 text-emerald-400" />
                    <span className="text-xs font-mono text-emerald-300">{msg.fileName}</span>
                  </div>
                )}
                <p className="whitespace-pre-wrap font-serif leading-[1.8]">{msg.text}</p>
                {msg.download_url && (
                  <button
                    onClick={() => window.open(`${API_URL}${msg.download_url}`, "_blank")}
                    className="mt-5 w-full bg-emerald-600/20 hover:bg-emerald-600/40 border border-emerald-500/50 text-emerald-300 font-bold tracking-widest uppercase px-5 py-3 rounded-xl flex items-center justify-center gap-3 transition-all hover:scale-[1.02]"
                  >
                    <Download className="w-4 h-4" /> Download PRC Final Report
                  </button>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex gap-4 max-w-3xl">
              <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 bg-emerald-950 border border-emerald-800/50">
                <Bot className="w-3.5 h-3.5 text-emerald-400" />
              </div>
              <div className="bg-[#111116] p-4 rounded-2xl rounded-tl-none border border-emerald-900/30 flex items-center gap-2">
                <span className="w-2 h-2 bg-emerald-500 rounded-full animate-bounce" />
                <span className="w-2 h-2 bg-emerald-500 rounded-full animate-bounce [animation-delay:0.15s]" />
                <span className="w-2 h-2 bg-emerald-500 rounded-full animate-bounce [animation-delay:0.3s]" />
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </main>

        {/* Input Bar */}
        <footer className="p-4 bg-[#050505] border-t border-slate-800/60 shrink-0">
          <div className="max-w-3xl mx-auto flex items-center gap-3 bg-[#111116] border border-slate-800 rounded-full p-2 pl-4 focus-within:border-emerald-500/40 transition-all shadow-2xl">
            <label className="cursor-pointer shrink-0 p-2 hover:bg-slate-800 rounded-full transition-colors relative">
              <input type="file" className="hidden" onChange={(e) => setFile(e.target.files[0])} />
              <Paperclip className={`w-5 h-5 ${file ? 'text-emerald-400' : 'text-slate-500'}`} />
              {file && <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-emerald-500 rounded-full border-2 border-[#111116]" />}
            </label>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
              placeholder={file ? `${file.name} — add a message...` : "Ask me anything or paste lab data..."}
              className="flex-1 bg-transparent border-none outline-none text-emerald-50 placeholder-slate-600 text-[15px] font-serif"
            />
            <button
              onClick={handleSend}
              disabled={loading || (!input.trim() && !file)}
              className="bg-emerald-600 hover:bg-emerald-500 text-white p-3 rounded-full shrink-0 transition-transform hover:scale-105 disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}

export default App;
