import React, { useState, useRef, useEffect } from 'react';
import { Send, Paperclip, Bot, User, Download, FileText, Database, Circle, PlusCircle, Trash2 } from 'lucide-react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const WELCOME = { role: 'model', text: 'Welcome to the PRC Engineering Hub.\n\nI am your dedicated SCAL AI Co-Author. Tell me your Well Name, paste lab data directly, or attach Excel files and core photographs to begin our analysis.' };

function App() {
  const [messages, setMessages] = useState([WELCOME]);
  const [input, setInput] = useState('');
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  // Session ID persisted in localStorage so the AI remembers across refreshes
  const [sessionId, setSessionId] = useState(() => localStorage.getItem('prc_session_id') || '');
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Persist session_id whenever it changes
  useEffect(() => {
    if (sessionId) localStorage.setItem('prc_session_id', sessionId);
  }, [sessionId]);

  const handleNewChat = async () => {
    if (sessionId) {
      try { await axios.delete(`${API_URL}/api/session/${sessionId}`); } catch {}
    }
    const newId = '';
    setSessionId(newId);
    localStorage.removeItem('prc_session_id');
    setMessages([WELCOME]);
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

      // Persist the session ID the server assigned
      if (response.data.session_id) setSessionId(response.data.session_id);

      if (response.data.status === 'success') {
        const aiMessage = {
          role: 'model',
          text: response.data.reply,
          download_url: response.data.is_report_ready ? response.data.download_url : null
        };
        setMessages(prev => [...prev, aiMessage]);
      } else {
        setMessages(prev => [...prev, { role: 'model', text: `❌ ${response.data.reply}` }]);
      }
    } catch (error) {
      setMessages(prev => [...prev, { role: 'model', text: 'NETWORK ERROR: Python backend is offline. Run run_pipeline.bat to restart it.' }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#09090b] text-slate-100 flex flex-col font-sans">

      {/* Header */}
      <header className="w-full bg-[#050505] border-b border-emerald-900/30 p-4 flex items-center justify-between shadow-2xl z-10">
        <div className="flex items-center gap-4">
          <Database className="w-7 h-7 text-emerald-500" />
          <div>
            <h1 className="text-lg font-black tracking-widest text-emerald-50">PRC CO-AUTHOR</h1>
            <p className="text-[10px] text-emerald-500/70 tracking-[0.3em] uppercase">Conversational SCAL Intelligence</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Circle className="w-2 h-2 text-emerald-500 fill-emerald-500 animate-pulse" />
            <span className="text-xs text-emerald-500/60 font-mono tracking-widest">GEMINI FLASH ONLINE</span>
          </div>
          <button
            onClick={handleNewChat}
            className="flex items-center gap-2 text-xs text-slate-400 hover:text-white border border-slate-700 hover:border-slate-500 px-3 py-2 rounded-lg transition-all"
          >
            <PlusCircle className="w-3.5 h-3.5" /> New Chat
          </button>
        </div>
      </header>

      {/* Chat Log */}
      <main className="flex-1 overflow-y-auto p-4 md:p-8 space-y-6">
        {messages.map((msg, idx) => (
          <div key={idx} className={`flex gap-4 max-w-4xl mx-auto ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
            <div className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 border ${
              msg.role === 'user' ? 'bg-slate-800 border-slate-700' : 'bg-emerald-950 border-emerald-800/50'
            }`}>
              {msg.role === 'user' ? <User className="w-4 h-4 text-slate-300" /> : <Bot className="w-4 h-4 text-emerald-400" />}
            </div>
            <div className={`space-y-3 flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'} max-w-[85%]`}>
              <div className={`p-5 rounded-2xl text-[15px] leading-relaxed shadow-2xl ${
                msg.role === 'user'
                  ? 'bg-slate-800 text-slate-200 rounded-tr-none border border-slate-700/50'
                  : 'bg-[#111116] text-emerald-50/90 rounded-tl-none border border-emerald-900/30'
              }`}>
                {msg.fileName && (
                  <div className="flex items-center gap-2 mb-3 bg-black/40 p-2 rounded-lg border border-slate-700/50 w-fit">
                    <FileText className="w-4 h-4 text-emerald-400" />
                    <span className="text-xs font-mono text-emerald-300">{msg.fileName}</span>
                  </div>
                )}
                <p className="whitespace-pre-wrap font-serif leading-[1.8]">{msg.text}</p>
                {msg.download_url && (
                  <button
                    onClick={() => window.open(`${API_URL}${msg.download_url}`, "_blank")}
                    className="mt-5 w-full bg-emerald-600/20 hover:bg-emerald-600/40 border border-emerald-500/50 text-emerald-300 font-bold tracking-widest uppercase px-6 py-4 rounded-xl flex items-center justify-center gap-3 transition-all hover:scale-[1.02]"
                  >
                    <Download className="w-5 h-5" /> Download PRC Final Report
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex gap-4 max-w-4xl mx-auto">
            <div className="w-9 h-9 rounded-full flex items-center justify-center shrink-0 bg-emerald-950 border border-emerald-800/50">
              <Bot className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="bg-[#111116] p-5 rounded-2xl rounded-tl-none border border-emerald-900/30 flex items-center gap-2">
              <span className="w-2 h-2 bg-emerald-500 rounded-full animate-bounce"></span>
              <span className="w-2 h-2 bg-emerald-500 rounded-full animate-bounce [animation-delay:0.2s]"></span>
              <span className="w-2 h-2 bg-emerald-500 rounded-full animate-bounce [animation-delay:0.4s]"></span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </main>

      {/* Input Bar */}
      <footer className="p-4 md:p-6 bg-[#050505] border-t border-slate-800/50 z-10">
        <div className="max-w-4xl mx-auto relative flex items-center gap-3 bg-[#111116] border border-slate-800 rounded-full p-2 pl-4 focus-within:border-emerald-500/50 transition-all shadow-2xl">
          <label className="cursor-pointer shrink-0 p-2 hover:bg-slate-800 rounded-full transition-colors relative">
            <input type="file" className="hidden" onChange={(e) => setFile(e.target.files[0])} />
            <Paperclip className={`w-5 h-5 ${file ? 'text-emerald-400' : 'text-slate-400'}`} />
            {file && <span className="absolute -top-1 -right-1 w-3 h-3 bg-emerald-500 rounded-full border-2 border-[#111116]"></span>}
          </label>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
            placeholder={file ? `${file.name} attached — add context...` : "Ask me anything or paste lab data..."}
            className="flex-1 bg-transparent border-none outline-none text-emerald-50 placeholder-slate-500 text-[15px] font-serif"
          />
          <button
            onClick={handleSend}
            disabled={loading || (!input.trim() && !file)}
            className="bg-emerald-600 hover:bg-emerald-500 text-white p-3 rounded-full shrink-0 transition-transform hover:scale-105 disabled:opacity-40 disabled:cursor-not-allowed shadow-[0_0_15px_rgba(16,185,129,0.3)]"
          >
            <Send className="w-5 h-5" />
          </button>
        </div>
        <p className="text-center text-[9px] text-slate-600 mt-3 font-mono tracking-widest uppercase">Petroleum Research Center · Libya · Confidential</p>
      </footer>
    </div>
  );
}

export default App;
