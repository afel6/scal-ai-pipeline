import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Paperclip, Bot, User, Download, FileText, Database, Circle, PlusCircle, Trash2, MessageSquare, ChevronLeft, ChevronRight, Wifi, WifiOff, Loader, LogOut } from 'lucide-react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const WELCOME_MSG = { role: 'model', text: 'Hello, I am Hviel, your dedicated PRC SCAL AI Specialist.\n\nI am ready to perform a high-level technical evaluation of your core laboratory data. Please state your Well Name, paste a data array, or attach Excel/image files to begin.' };

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
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState(''); // 'uploading' | 'thinking' | ''
  const [sessionId, setSessionId] = useState(() => localStorage.getItem('prc_session_id') || '');
  const [lastMessage, setLastMessage] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  // Server status: 'waking' | 'online' | 'offline'
  const [serverStatus, setServerStatus] = useState('waking');
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (sessionId) localStorage.setItem('prc_session_id', sessionId);
  }, [sessionId]);

  // Proactively wake the Render server the moment the page loads
  useEffect(() => {
    const wakeServer = async () => {
      try {
        await axios.get(`${API_URL}/`, { timeout: 180000 });
        setServerStatus('online');
      } catch {
        setServerStatus('offline');
      }
    };
    wakeServer();
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
  };

  const handleLoadSession = async (sid) => {
    if (sid === sessionId && messages.length > 1) return;
    try {
      const { data } = await axios.get(`${API_URL}/api/session/${sid}`);
      if (data.status === 'ok') {
        setSessionId(sid);
        localStorage.setItem('prc_session_id', sid);
        const uiMessages = [WELCOME_MSG, ...data.messages.map(m => ({ 
          role: m.role, 
          text: m.text, 
          download_url: m.download_url 
        }))];
        setMessages(uiMessages);
        setLastMessage(null);
      }
    } catch {}
  };

  // Auto-resume last session on mount
  useEffect(() => {
    if (sessionId && user) {
      handleLoadSession(sessionId);
    }
  }, []);

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
    const msgFile = retryObj ? retryObj.file : file;

    if (!msgText.trim() && !msgFile) return;
    if (serverStatus === 'offline') {
      setMessages(prev => [...prev, { role: 'model', text: '⚠️ The AI server is currently offline. Please try again in a moment.' }]);
      return;
    }
    
    if (!retryObj) {
      const userMessage = { role: 'user', text: msgText, fileName: msgFile ? msgFile.name : null };
      setMessages(prev => [...prev, userMessage]);
      setLastMessage({ text: msgText, file: msgFile });
    }

    const formData = new FormData();
    formData.append('message', msgText);
    formData.append('session_id', sessionId);
    formData.append('engineer_name', user?.name || 'PRC Engineering Staff');
    if (msgFile) formData.append('file', msgFile);
    
    if (!retryObj) {
      setInput('');
      setFile(null);
    }
    setLoading(true);
    setUploadStatus(msgFile ? 'uploading' : 'thinking');

    try {
      const response = await axios.post(`${API_URL}/api/chat`, formData, {
        timeout: 120000,
        onUploadProgress: (e) => {
          if (e.progress >= 1) setUploadStatus('thinking');
        }
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
    }
  };

  const statusConfig = {
    waking:  { icon: <Loader className="w-2.5 h-2.5 animate-spin" />, text: 'ESTABLISHING SECURE CONNECTION...', color: 'text-yellow-500' },
    online:  { icon: <Circle className="w-2 h-2 fill-yellow-500" />, text: 'SECURE LINK: ONLINE',        color: 'text-yellow-500' },
    offline: { icon: <WifiOff className="w-2.5 h-2.5" />,             text: 'RECONNECTING TO HUB...', color: 'text-amber-400' },
  };
  const status = statusConfig[serverStatus];

  if (!user) {
    return <Login onLogin={(u) => {
      localStorage.setItem('prc_user', JSON.stringify(u));
      setUser(u);
    }} />;
  }

  return (
    <div className="min-h-screen bg-[#09090b] text-slate-100 flex font-sans overflow-hidden h-screen">

      {/* Sidebar */}
      <aside className={`flex flex-col bg-[#050505] border-r border-slate-800/60 transition-all duration-300 ${sidebarOpen ? 'w-72' : 'w-0 overflow-hidden'}`}>
        <div className="p-4 border-b border-slate-800/60 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <Database className="w-5 h-5 text-yellow-500" />
            <span className="text-sm font-black tracking-widest text-yellow-50">PRC STUDIES</span>
          </div>
          <button onClick={handleNewChat} className="flex items-center gap-1.5 text-xs text-yellow-400 hover:text-yellow-300 border border-yellow-800/50 hover:border-yellow-600 px-2 py-1.5 rounded-lg transition-all">
            <PlusCircle className="w-3.5 h-3.5" /> New
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {sessions.length === 0 && (
            <p className="text-slate-600 text-xs text-center mt-8 px-4 leading-relaxed">No past conversations yet.<br />Start a new SCAL study above.</p>
          )}
          {sessions.map(s => (
            <div key={s.id} onClick={() => handleLoadSession(s.id)}
              className={`group flex items-start gap-3 px-3 py-3 rounded-xl cursor-pointer transition-all border ${s.id === sessionId ? 'bg-yellow-950/40 border-yellow-800/50 text-yellow-100' : 'border-transparent hover:bg-slate-900 hover:border-slate-800 text-slate-400 hover:text-slate-200'}`}>
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
        <div className="p-4 border-t border-slate-800/60 shrink-0">
          <p className="text-[10px] text-slate-700 font-mono tracking-widest uppercase text-center">Petroleum Research Center · Libya</p>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">

        {/* Header */}
        <header className="bg-[#050505] border-b border-slate-800/60 p-4 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <button onClick={() => setSidebarOpen(p => !p)} className="p-1.5 hover:bg-slate-800 rounded-lg transition-colors text-slate-400 hover:text-white">
              {sidebarOpen ? <ChevronLeft className="w-5 h-5" /> : <ChevronRight className="w-5 h-5" />}
            </button>
            <span className="text-sm font-bold tracking-widest text-yellow-50 uppercase">
              {sessions.find(s => s.id === sessionId)?.title || 'New Study'}
            </span>
          </div>
          <div className="flex items-center gap-6">
            <div className={`flex items-center gap-2 ${status.color}`}>
              {status.icon}
              <span className="text-xs font-mono tracking-widest">{status.text}</span>
            </div>
            <div className="h-4 w-px bg-slate-800" />
            <div className="flex items-center gap-3">
               <div className="text-right hidden sm:block">
                 <p className="text-[10px] text-slate-500 font-bold uppercase tracking-tighter leading-none">Authenticated Engineer</p>
                 <p className="text-xs text-white font-serif italic">{user.name}</p>
               </div>
               <button onClick={() => { localStorage.removeItem('prc_user'); setUser(null); }} className="p-2 hover:bg-yellow-950/30 text-slate-500 hover:text-yellow-400 rounded-lg transition-colors group">
                 <LogOut className="w-4 h-4" />
               </button>
            </div>
          </div>
        </header>

        {/* Wake-up banner */}
        {serverStatus === 'waking' && (
          <div className="bg-yellow-950/40 border-b border-yellow-800/30 px-4 py-2 flex items-center gap-2">
            <Loader className="w-3.5 h-3.5 text-yellow-500 animate-spin shrink-0" />
            <p className="text-xs text-yellow-400/80">Waking up the AI server — this takes about 30 seconds on first load. Please wait…</p>
          </div>
        )}

        {/* Chat Log */}
        <main className="flex-1 overflow-y-auto p-4 md:p-8 space-y-6">
          {messages.map((msg, idx) => (
            <div key={idx} className={`flex gap-4 max-w-3xl ${msg.role === 'user' ? 'ml-auto flex-row-reverse' : ''}`}>
              <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 border ${msg.role === 'user' ? 'bg-slate-800 border-slate-700' : 'bg-yellow-950 border-yellow-800/50'}`}>
                {msg.role === 'user' ? <User className="w-3.5 h-3.5 text-slate-300" /> : <Bot className="w-3.5 h-3.5 text-yellow-400" />}
              </div>
              <div className={`p-4 rounded-2xl text-[15px] leading-relaxed shadow-lg max-w-[85%] ${msg.role === 'user' ? 'bg-slate-800 text-slate-200 rounded-tr-none border border-slate-700/50' : 'bg-[#111116] text-yellow-50/90 rounded-tl-none border border-yellow-900/30'}`}>
                {msg.fileName && (
                  <div className="flex items-center gap-2 mb-3 bg-black/40 p-2 rounded-lg border border-slate-700/50 w-fit">
                    <FileText className="w-3.5 h-3.5 text-yellow-400" />
                    <span className="text-xs font-mono text-yellow-300">{msg.fileName}</span>
                  </div>
                )}
                <p className="whitespace-pre-wrap font-serif leading-[1.8]">{msg.text}</p>
                {msg.download_url && (
                  <button onClick={() => window.open(`${API_URL}${msg.download_url}`, "_blank")}
                    className="mt-5 w-full bg-yellow-600/20 hover:bg-yellow-600/40 border border-yellow-500/50 text-yellow-300 font-bold tracking-widest uppercase px-5 py-3 rounded-xl flex items-center justify-center gap-3 transition-all hover:scale-[1.02]">
                    <Download className="w-4 h-4" /> Download PRC Final Report
                  </button>
                )}
                {msg.isError && lastMessage && (
                  <button onClick={() => handleSend(lastMessage)} disabled={loading}
                    className="mt-4 w-full bg-amber-950/20 hover:bg-amber-950/40 border border-amber-600/50 text-amber-300 font-bold tracking-widest uppercase text-[10px] py-2.5 rounded-lg flex items-center justify-center gap-2 transition-all hover:scale-[1.01] disabled:opacity-50">
                    {loading ? <Loader className="w-3 h-3 animate-spin" /> : <Wifi className="w-3 h-3 text-yellow-500" />}
                    {loading ? 'RE-TRIGGERING ANALYSIS...' : 'RE-TRY (Wait 3 Minutes for Quota Reset)'}
                  </button>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex gap-4 max-w-3xl">
              <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 bg-yellow-950 border border-yellow-800/50">
                <Bot className="w-3.5 h-3.5 text-yellow-400" />
              </div>
              <div className="bg-[#111116] p-4 rounded-2xl rounded-tl-none border border-yellow-900/30 flex items-center gap-3">
                {uploadStatus === 'uploading' ? (
                  <>
                    <Loader className="w-4 h-4 text-yellow-400 animate-spin shrink-0" />
                    <span className="text-sm text-yellow-300/80 font-serif">Uploading &amp; parsing file — please wait…</span>
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

        {/* Input */}
        <footer className="p-4 bg-[#050505] border-t border-slate-800/60 shrink-0">
          <div className="max-w-3xl mx-auto flex items-center gap-3 bg-[#111116] border border-slate-800 rounded-full p-2 pl-4 focus-within:border-yellow-500/40 transition-all">
            <label className="cursor-pointer shrink-0 p-2 hover:bg-slate-800 rounded-full transition-colors relative">
              <input type="file" className="hidden" onChange={(e) => setFile(e.target.files[0])} />
              <Paperclip className={`w-5 h-5 ${file ? 'text-yellow-400' : 'text-slate-500'}`} />
              {file && <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-yellow-500 rounded-full border-2 border-[#111116]" />}
            </label>
            <input type="text" value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
              disabled={serverStatus === 'waking'}
              placeholder={serverStatus === 'waking' ? 'Connecting to AI server...' : file ? `${file.name} — add a message...` : 'Ask me anything or paste lab data...'}
              className="flex-1 bg-transparent border-none outline-none text-yellow-50 placeholder-slate-600 text-[15px] font-serif disabled:opacity-50" />
            <button onClick={handleSend} disabled={loading || serverStatus === 'waking' || (!input.trim() && !file)}
              className="bg-yellow-600 hover:bg-yellow-500 text-black p-3 rounded-full shrink-0 transition-transform hover:scale-105 disabled:opacity-30 disabled:cursor-not-allowed">
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
    <div className="min-h-screen bg-[#050505] flex items-center justify-center p-6 relative overflow-hidden">
      {/* Background Ambience */}
      <div className="absolute top-0 left-0 w-full h-full pointer-events-none overflow-hidden opacity-20">
        <div className="absolute -top-40 -left-60 w-[600px] h-[600px] bg-yellow-900/30 rounded-full blur-[140px]" />
        <div className="absolute -bottom-40 -right-60 w-[500px] h-[500px] bg-amber-900/20 rounded-full blur-[120px]" />
      </div>

      <div className="w-full max-w-md space-y-8 animate-fade-in relative z-10">
        <div className="flex flex-col items-center">
          <div className="bg-white/95 p-6 rounded-3xl shadow-2xl shadow-yellow-900/10 mb-8 border border-white/10 group hover:scale-[1.02] transition-transform duration-500">
            <img src="/prc_logo.jpg" alt="PRC Logo" className="w-48 h-auto object-contain" />
          </div>
          <h1 className="text-2xl font-black tracking-widest text-white uppercase italic text-center">Hviel | PRC AI Hub</h1>
          <p className="text-slate-500 text-sm mt-3 font-mono tracking-widest uppercase text-center animate-pulse-slow">Senior AI Petrophysical Specialist</p>
        </div>

        <div className="p-8 bg-gloss rounded-[2.5rem] border border-white/5 space-y-6 shadow-2xl backdrop-blur-3xl shadow-black/80">
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-[10px] font-bold text-slate-400 uppercase tracking-widest ml-4">Full Name & Profession</label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Eng. Ahmed Al-Lafi" className="auth-input" />
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-bold text-slate-400 uppercase tracking-widest ml-4">PRC MFA Identification</label>
              <input type="password" value={id} onChange={(e) => { setId(e.target.value); setError(''); }} 
                onKeyDown={(e) => e.key === 'Enter' && name && id && handleAuth()}
                placeholder="Enter Access Code" className="auth-input" />
            </div>
          </div>
          
          {error && <p className="text-yellow-500 text-[10px] text-center font-bold tracking-widest uppercase animate-bounce">{error}</p>}
          
          <button onClick={handleAuth} disabled={!name || !id} className="auth-button">
            Authenticate Session
          </button>
          
          <div className="pt-4 border-t border-white/5 text-center">
            <p className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">System Architect</p>
            <p className="text-xs text-yellow-400 font-serif italic mt-1 font-bold">Raouf Elkabir</p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
