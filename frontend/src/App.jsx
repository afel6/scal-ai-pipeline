import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Paperclip, Bot, User, Download, FileText, Database, Circle, PlusCircle, Trash2, MessageSquare, X, Wifi, WifiOff, Loader, LogOut, Menu, BookOpen, Upload, CheckCircle } from 'lucide-react';
import axios from 'axios';
import SidebarTabs from './SidebarTabs';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const WELCOME_MSG = { role: 'model', text: 'Hello, I am Hviel — your dedicated PRC Senior AI Petrophysical Specialist.\n\nI have been trained on the PRC petroleum engineering library and am ready to assist with SCAL analysis, petrophysical interpretation, and professional report generation.\n\nPlease state your Well Name, paste lab data, or attach Excel / PDF files to begin.' };

function timeAgo(ts) {
  const diff = Date.now() / 1000 - ts;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function App() {
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem('prc_user');
    return saved ? JSON.parse(saved) : null;
  });
  const [messages, setMessages] = useState([WELCOME_MSG]);
  const [input, setInput] = useState('');
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState('');
  const [sessionId, setSessionId] = useState(() => localStorage.getItem('prc_session_id') || '');
  const [lastMessage, setLastMessage] = useState(null);
  const [retryCooldown, setRetryCooldown] = useState(0);
  const [sessions, setSessions] = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(false); // default closed on mobile
  const [serverStatus, setServerStatus] = useState('waking');
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Store session id
  useEffect(() => {
    if (sessionId) localStorage.setItem('prc_session_id', sessionId);
  }, [sessionId]);

  // Wake the server
  useEffect(() => {
    const wake = async () => {
      try {
        await axios.get(`${API_URL}/`, { timeout: 180000 });
        setServerStatus('online');
      } catch {
        setServerStatus('offline');
      }
    };
    wake();
    // On desktop, open sidebar by default
    if (window.innerWidth >= 768) setSidebarOpen(true);
    
    // Auto-load last active session
    const saved = localStorage.getItem('prc_session_id');
    if (saved) handleLoadSession(saved);
  }, []);

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
    setLastMessage(null);
    if (window.innerWidth < 768) setSidebarOpen(false);
  };

  async function handleLoadSession(sid) {
    if (sid === sessionId && messages.length > 1) {
      if (window.innerWidth < 768) setSidebarOpen(false);
      return;
    }
    try {
      const { data } = await axios.get(`${API_URL}/api/session/${sid}`);
      if (data.status === 'ok') {
        setSessionId(sid);
        localStorage.setItem('prc_session_id', sid);
        setMessages([WELCOME_MSG, ...data.messages.map(m => ({ role: m.role, text: m.text, download_url: m.download_url }))]);
        setLastMessage(null);
      }
    } catch {}
    if (window.innerWidth < 768) setSidebarOpen(false);
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

  const handleSend = async (retryObj = null) => {
    const msgText = retryObj ? retryObj.text : input;
    const msgFiles = retryObj ? retryObj.files : files;
    if (!msgText.trim() && msgFiles.length === 0) return;
    if (serverStatus === 'offline') {
      setMessages(prev => [...prev, { role: 'model', text: '⚠️ The AI server is offline. Please retry in a moment.' }]);
      return;
    }
    if (!retryObj) {
      const fileNames = msgFiles.map(f => f.name).join(', ');
      setMessages(prev => [...prev, { role: 'user', text: msgText, fileName: fileNames || null }]);
      setLastMessage({ text: msgText, files: msgFiles });
      setInput('');
      setFiles([]);
      if (inputRef.current) inputRef.current.style.height = 'auto';
    }
    const formData = new FormData();
    formData.append('message', msgText);
    formData.append('session_id', sessionId);
    formData.append('engineer_name', user?.name || 'PRC Engineer');
    // Append all selected files
    msgFiles.forEach(f => formData.append('files', f));
    setLoading(true);
    setUploadStatus(msgFiles.length > 0 ? 'uploading' : 'thinking');
    try {
      const response = await axios.post(`${API_URL}/api/chat`, formData, {
        timeout: 120000,
        onUploadProgress: (e) => { if (e.progress >= 1) setUploadStatus('thinking'); }
      });
      if (response.data.session_id) setSessionId(response.data.session_id);
      setServerStatus('online');
      if (response.data.status === 'success') {
        setMessages(prev => [...prev, {
          role: 'model',
          text: response.data.reply,
          download_url: response.data.is_report_ready ? response.data.download_url : null
        }]);
      } else {
        setMessages(prev => [...prev, { role: 'model', text: `❌ ${response.data.reply}`, isError: true }]);
      }
      await refreshSessions();
    } catch (err) {
      setMessages(prev => [...prev, { role: 'model', text: '❌ Connection error. I am unable to reach the PRC Hub at this moment.', isError: true }]);
      setServerStatus('offline');
    } finally {
      setLoading(false);
      setUploadStatus('');
      if (retryObj) setRetryCooldown(15);
    }
  };

  useEffect(() => {
    if (retryCooldown > 0) {
      const t = setTimeout(() => setRetryCooldown(retryCooldown - 1), 1000);
      return () => clearTimeout(t);
    }
  }, [retryCooldown]);

  const statusConfig = {
    waking:  { icon: <Loader className="w-3 h-3 animate-spin" />, text: 'Connecting...', color: 'text-yellow-500' },
    online:  { icon: <Circle className="w-2 h-2 fill-green-500" />, text: 'Online',   color: 'text-green-400' },
    offline: { icon: <WifiOff className="w-3 h-3" />, text: 'Reconnecting...', color: 'text-red-400' },
  };
  const status = statusConfig[serverStatus];

  if (!user) {
    return <Login onLogin={(u) => {
      localStorage.setItem('prc_user', JSON.stringify(u));
      setUser(u);
    }} />;
  }

  return (
    <div className="flex h-screen w-screen bg-[#09090b] text-slate-100 overflow-hidden relative font-sans">
      
      {/* Mobile overlay backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-20 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside className={`
        fixed md:relative top-0 left-0 h-full z-30 flex flex-col
        bg-[#050505] border-r border-slate-800/60
        transition-transform duration-300 ease-in-out
        w-72
        ${sidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0 md:w-0 md:overflow-hidden md:border-0'}
      `}>
        {/* Sidebar header */}
        <div className="p-4 border-b border-slate-800/60 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <Database className="w-5 h-5 text-yellow-500 shrink-0" />
            <span className="text-sm font-black tracking-widest text-yellow-50">PRC STUDIES</span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={handleNewChat} className="flex items-center gap-1 text-xs text-yellow-400 hover:text-yellow-300 border border-yellow-800/50 hover:border-yellow-600 px-2 py-1.5 rounded-lg transition-all">
              <PlusCircle className="w-3.5 h-3.5" /> New
            </button>
            <button onClick={() => setSidebarOpen(false)} className="md:hidden p-1 text-slate-500 hover:text-white">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Tabs + Session list + Library — handled by SidebarTabs */}
        <SidebarTabs sessionId={sessionId} sessions={sessions} handleLoadSession={handleLoadSession} handleDeleteSession={handleDeleteSession} />

        <div className="p-4 border-t border-slate-800/60 shrink-0">
          <p className="text-[10px] text-slate-700 font-mono tracking-widest uppercase text-center">Petroleum Research Center · Libya</p>
        </div>
      </aside>

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0 h-full">

        {/* Header */}
        <header className="bg-[#050505] border-b border-slate-800/60 px-3 md:px-4 py-3 flex items-center justify-between shrink-0 gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <button
              onClick={() => setSidebarOpen(p => !p)}
              className="p-2 hover:bg-slate-800 rounded-lg transition-colors text-slate-400 hover:text-white shrink-0"
            >
              <Menu className="w-5 h-5" />
            </button>
            <span className="text-sm font-bold tracking-widest text-yellow-50 uppercase truncate hidden sm:block">
              {sessions.find(s => s.id === sessionId)?.title || 'New Study'}
            </span>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            {/* Status */}
            <div className={`flex items-center gap-1.5 ${status.color}`}>
              {status.icon}
              <span className="text-xs font-mono tracking-wide hidden sm:block">{status.text}</span>
            </div>
            <div className="h-4 w-px bg-slate-800 hidden sm:block" />
            {/* User info */}
            <div className="flex items-center gap-2">
              <div className="text-right hidden sm:block">
                <p className="text-[10px] text-slate-500 font-bold uppercase tracking-tighter leading-none">Engineer</p>
                <p className="text-xs text-white font-serif italic truncate max-w-[120px]">{user.name}</p>
              </div>
              <button
                onClick={() => { localStorage.removeItem('prc_user'); setUser(null); }}
                className="p-2 hover:bg-yellow-950/30 text-slate-500 hover:text-yellow-400 rounded-lg transition-colors"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          </div>
        </header>

        {/* Wake banner */}
        {serverStatus === 'waking' && (
          <div className="bg-yellow-950/40 border-b border-yellow-800/30 px-4 py-2 flex items-center gap-2 shrink-0">
            <Loader className="w-3.5 h-3.5 text-yellow-500 animate-spin shrink-0" />
            <p className="text-xs text-yellow-400/80">Waking up the AI server — please wait ~30 seconds…</p>
          </div>
        )}

        {/* Chat log */}
        <main className="flex-1 overflow-y-auto px-3 py-4 md:px-6 md:py-6 space-y-4">
          {messages.map((msg, idx) => (
            <div key={idx} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''} max-w-2xl ${msg.role === 'user' ? 'ml-auto' : 'mr-auto'} w-full`}>
              {/* Avatar */}
              <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 border
                ${msg.role === 'user'
                  ? 'bg-slate-800 border-slate-700'
                  : 'bg-yellow-950 border-yellow-800/50'
                }`}>
                {msg.role === 'user'
                  ? <User className="w-3.5 h-3.5 text-slate-300" />
                  : <Bot className="w-3.5 h-3.5 text-yellow-400" />
                }
              </div>
              {/* Bubble */}
              <div className={`px-4 py-3 rounded-2xl text-sm md:text-[15px] leading-relaxed shadow-lg max-w-[85%]
                ${msg.role === 'user'
                  ? 'bg-slate-800 text-slate-200 rounded-tr-none border border-slate-700/50'
                  : 'bg-[#111116] text-yellow-50/90 rounded-tl-none border border-yellow-900/30'
                }`}>
                {msg.fileName && (
                  <div className="flex items-center gap-2 mb-2 bg-black/40 p-2 rounded-lg border border-slate-700/50 w-fit">
                    <FileText className="w-3.5 h-3.5 text-yellow-400 shrink-0" />
                    <span className="text-xs font-mono text-yellow-300 truncate max-w-[160px]">{msg.fileName}</span>
                  </div>
                )}
                <p className="whitespace-pre-wrap font-serif leading-[1.75]">{msg.text}</p>
                {msg.download_url && (
                  <button onClick={() => window.open(`${API_URL}${msg.download_url}`, "_blank")}
                    className="mt-4 w-full bg-yellow-600/20 hover:bg-yellow-600/40 border border-yellow-500/50 text-yellow-300 font-bold tracking-widest uppercase px-4 py-3 rounded-xl flex items-center justify-center gap-2 text-xs transition-all active:scale-95">
                    <Download className="w-4 h-4" /> Download PRC Final Report
                  </button>
                )}
                {msg.isError && lastMessage && (
                  <button onClick={() => handleSend(lastMessage)} disabled={loading || retryCooldown > 0}
                    className="mt-3 w-full bg-amber-950/20 hover:bg-amber-950/40 border border-amber-600/50 text-amber-300 font-bold tracking-widest uppercase text-[10px] py-2.5 rounded-lg flex items-center justify-center gap-2 transition-all active:scale-95 disabled:opacity-30">
                    {loading ? <Loader className="w-3 h-3 animate-spin" /> : <Wifi className="w-3 h-3 text-yellow-500" />}
                    {loading ? 'RETRYING...' : retryCooldown > 0 ? `COOL DOWN (${retryCooldown}s)...` : 'RE-TRY (Wait 3 Minutes for Quota Reset)'}
                  </button>
                )}
              </div>
            </div>
          ))}

          {/* Typing indicator */}
          {loading && (
            <div className="flex gap-3 max-w-2xl w-full">
              <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 bg-yellow-950 border border-yellow-800/50">
                <Bot className="w-3.5 h-3.5 text-yellow-400" />
              </div>
              <div className="bg-[#111116] px-4 py-3 rounded-2xl rounded-tl-none border border-yellow-900/30 flex items-center gap-2">
                {uploadStatus === 'uploading' ? (
                  <>
                    <Loader className="w-4 h-4 text-yellow-400 animate-spin shrink-0" />
                    <span className="text-sm text-yellow-300/80 font-serif">Uploading file…</span>
                  </>
                ) : (
                  <>
                    <span className="w-2 h-2 bg-yellow-500 rounded-full animate-bounce" />
                    <span className="w-2 h-2 bg-yellow-500 rounded-full animate-bounce [animation-delay:0.15s]" />
                    <span className="w-2 h-2 bg-yellow-500 rounded-full animate-bounce [animation-delay:0.3s]" />
                  </>
                )}
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </main>

        {/* Input Footer */}
        <footer className="p-3 md:p-4 bg-[#050505] border-t border-slate-800/60 shrink-0">
          {/* File chips — one per selected file */}
          {files.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2">
              {files.map((f, i) => (
                <div key={i} className="flex items-center gap-1.5 bg-yellow-950/30 border border-yellow-800/40 rounded-xl px-3 py-1.5">
                  <FileText className="w-3 h-3 text-yellow-400 shrink-0" />
                  <span className="text-xs font-mono text-yellow-300 truncate max-w-[140px]">{f.name}</span>
                  <button
                    onClick={() => setFiles(prev => prev.filter((_, idx) => idx !== i))}
                    className="ml-1 text-slate-500 hover:text-red-400 transition-colors"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
          <div className="flex items-center gap-2 bg-[#111116] border border-slate-800 rounded-2xl p-2 pl-4 focus-within:border-yellow-500/40 transition-all">
            <label className="cursor-pointer shrink-0 p-1.5 hover:bg-slate-800 rounded-xl transition-colors">
              <input
                type="file"
                multiple
                className="hidden"
                onChange={(e) => {
                  const newFiles = Array.from(e.target.files);
                  setFiles(prev => {
                    const existingNames = prev.map(f => f.name);
                    const deduped = newFiles.filter(f => !existingNames.includes(f.name));
                    return [...prev, ...deduped];
                  });
                  e.target.value = '';
                }}
              />
              <Paperclip className={`w-5 h-5 ${files.length > 0 ? 'text-yellow-400' : 'text-slate-500'}`} />
            </label>
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                e.target.style.height = 'auto';
                e.target.style.height = `${Math.min(e.target.scrollHeight, 250)}px`;
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  if (input.trim() || files.length > 0) handleSend();
                }
              }}
              rows={1}
              disabled={serverStatus === 'waking'}
              placeholder={serverStatus === 'waking' ? 'Connecting to server...' : 'Ask Hviel or paste lab data...'}
              className="flex-1 bg-transparent border-none outline-none text-yellow-50 placeholder-slate-600 text-sm md:text-[15px] font-serif disabled:opacity-50 resize-none overflow-y-auto py-2.5 min-h-[44px] leading-relaxed block"
            />
            <button
              onClick={() => handleSend()}
              disabled={loading || serverStatus === 'waking' || (!input.trim() && files.length === 0)}
              className="bg-yellow-600 hover:bg-yellow-500 text-black p-3 rounded-xl shrink-0 transition-all active:scale-95 disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}

function Login({ onLogin }) {
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');

  const handleAuth = () => {
    if (id === '1509') {
      onLogin({ name, id });
    } else {
      setError('Invalid MFA Credentials. Access Denied.');
      setId('');
    }
  };

  return (
    <div className="min-h-screen bg-[#050505] flex items-center justify-center p-4 relative overflow-hidden">
      {/* Background glow */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden opacity-20">
        <div className="absolute -top-40 -left-60 w-[600px] h-[600px] bg-yellow-900/30 rounded-full blur-[140px]" />
        <div className="absolute -bottom-40 -right-60 w-[500px] h-[500px] bg-amber-900/20 rounded-full blur-[120px]" />
      </div>

      <div className="w-full max-w-sm space-y-6 animate-fade-in relative z-10">
        {/* Logo */}
        <div className="flex flex-col items-center">
          <div className="bg-white/95 p-5 rounded-3xl shadow-2xl shadow-yellow-900/10 mb-6 border border-white/10 hover:scale-[1.02] transition-transform duration-500">
            <img src="/prc_logo.jpg" alt="PRC Logo" className="w-40 h-auto object-contain" />
          </div>
          <h1 className="text-xl font-black tracking-widest text-white uppercase italic text-center">Hviel | PRC AI Hub</h1>
          <p className="text-slate-500 text-xs mt-2 font-mono tracking-widest uppercase text-center animate-pulse-slow">Senior AI Petrophysical Specialist</p>
        </div>

        {/* Form */}
        <div className="p-6 bg-gloss rounded-3xl border border-white/5 space-y-5 shadow-2xl backdrop-blur-3xl shadow-black/80">
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-[10px] font-bold text-slate-400 uppercase tracking-widest ml-2">Full Name & Profession</label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && name && id && handleAuth()}
                placeholder="e.g. Eng. Ahmed Al-Lafi" className="auth-input" />
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-bold text-slate-400 uppercase tracking-widest ml-2">PRC Access Code</label>
              <input type="password" value={id} onChange={(e) => { setId(e.target.value); setError(''); }}
                onKeyDown={(e) => e.key === 'Enter' && name && id && handleAuth()}
                placeholder="Enter Access Code" className="auth-input" />
            </div>
          </div>
          {error && <p className="text-yellow-500 text-[10px] text-center font-bold tracking-widest uppercase">{error}</p>}
          <button onClick={handleAuth} disabled={!name || !id} className="auth-button">
            Authenticate Session
          </button>
          <div className="pt-3 border-t border-white/5 text-center">
            <p className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">System Architect</p>
            <p className="text-xs text-yellow-400 font-serif italic mt-1 font-bold">Raouf Elkabir</p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
