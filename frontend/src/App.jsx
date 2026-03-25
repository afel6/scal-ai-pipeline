import React, { useState, useRef, useEffect } from 'react';
import { Send, Paperclip, Bot, User, Download, FileText, Database, Circle } from 'lucide-react';
import axios from 'axios';

function App() {
  const [messages, setMessages] = useState([
    { role: 'model', text: 'Welcome directly to the PRC Engineering Hub. \nWe have discontinued batch-processing forms in favor of this dedicated conversational workspace. Please tell me your Well Name, or actively upload your fragmented laboratory photos/CSV sheets to begin our SCAL analysis step-by-step.' }
  ]);
  const [input, setInput] = useState('');
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() && !file) return;

    const userMessage = { role: 'user', text: input, fileName: file ? file.name : null };
    setMessages(prev => [...prev, userMessage]);
    
    // Package Data organically for backend
    const formData = new FormData();
    formData.append('history', JSON.stringify(messages)); // We pass prior history natively
    formData.append('message', input);
    if (file) formData.append('file', file);

    setInput('');
    setFile(null);
    setLoading(true);

    try {
      const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      const response = await axios.post(`${apiUrl}/api/chat`, formData);
      
      if (response.data.status === 'success') {
        const aiMessage = { 
          role: 'model', 
          text: response.data.reply,
          download_url: response.data.is_report_ready ? response.data.download_url : null
        };
        setMessages(prev => [...prev, aiMessage]);
      } else {
        setMessages(prev => [...prev, { role: 'model', text: `ERROR: ${response.data.reply || response.data.message}` }]);
      }
    } catch (error) {
      setMessages(prev => [...prev, { role: 'model', text: `NETWORK ERROR: The Python Core is fully offline or unreachable. Terminate the black terminal and run run_pipeline.bat again.` }]);
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = (url) => {
    const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    window.open(`${apiUrl}${url}`, "_blank");
  };

  return (
    <div className="min-h-screen bg-[#09090b] text-slate-100 flex flex-col font-sans">
      
      {/* Header Block */}
      <header className="w-full bg-[#050505] border-b border-emerald-900/30 p-5 flex items-center justify-between shadow-2xl z-10 relative">
        <div className="flex items-center gap-4">
           <Database className="w-8 h-8 text-emerald-500" />
           <div>
             <h1 className="text-xl font-black tracking-widest text-emerald-50 text-shadow-sm">PRC CO-AUTHOR</h1>
             <p className="text-[10px] text-emerald-500/80 tracking-[0.3em] font-bold uppercase">Conversational SCAL Intelligence</p>
           </div>
        </div>
        <div className="flex items-center gap-3">
           <Circle className="w-2 h-2 text-emerald-500 fill-emerald-500 animate-pulse" />
           <span className="text-xs text-emerald-500/70 font-mono tracking-widest">GEMINI 2.5 PRO ACTIVE</span>
        </div>
      </header>

      {/* Infinite Chat Log */}
      <main className="flex-1 overflow-y-auto p-4 md:p-8 space-y-6 scroll-smooth bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-[#0f172a]/20 via-[#09090b] to-[#09090b]">
        {messages.map((msg, idx) => (
          <div key={idx} className={`flex gap-4 max-w-4xl mx-auto ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
            
            <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 shadow-lg border ${
              msg.role === 'user' ? 'bg-slate-800 border-slate-700' : 'bg-emerald-950 border-emerald-800/50'
            }`}>
              {msg.role === 'user' ? <User className="w-5 h-5 text-slate-300" /> : <Bot className="w-5 h-5 text-emerald-400" />}
            </div>

            <div className={`space-y-3 ${msg.role === 'user' ? 'items-end' : 'items-start'} flex flex-col`}>
              <div className={`p-5 rounded-2xl text-sm md:text-[15px] leading-relaxed shadow-2xl max-w-[85%] ${
                msg.role === 'user' 
                  ? 'bg-slate-800 text-slate-200 rounded-tr-none border border-slate-700/50' 
                  : 'bg-[#111116] text-emerald-50/90 rounded-tl-none border border-emerald-900/30'
              }`}>
                {/* Attachment Module Node */}
                {msg.fileName && (
                  <div className="flex items-center gap-2 mb-3 bg-black/40 p-2 rounded-lg border border-slate-700/50 w-fit">
                    <FileText className="w-4 h-4 text-emerald-400" />
                    <span className="text-xs font-mono text-emerald-300">{msg.fileName}</span>
                  </div>
                )}
                
                {/* Natural Response Container */}
                <p className="whitespace-pre-wrap font-serif text-[16px] leading-[1.8]">{msg.text}</p>

                {/* Sub-surface File Extract Module (If Trigger Passed) */}
                {msg.download_url && (
                  <button 
                    onClick={() => handleDownload(msg.download_url)}
                    className="mt-6 w-full bg-emerald-600/20 hover:bg-emerald-600/40 border border-emerald-500/50 text-emerald-300 font-bold tracking-widest uppercase px-6 py-4 rounded-xl flex items-center justify-center gap-3 transition-all hover:scale-[1.02] shadow-[0_0_30px_rgba(16,185,129,0.1)] mb-2"
                  >
                    <Download className="w-5 h-5"/> EXPORT PRC REPORT NOW
                  </button>
                )}
              </div>
            </div>
            
          </div>
        ))}
        {loading && (
          <div className="flex gap-4 max-w-4xl mx-auto">
             <div className="w-10 h-10 rounded-full flex items-center justify-center shrink-0 bg-emerald-950 border border-emerald-800/50">
                <Bot className="w-5 h-5 text-emerald-400" />
             </div>
             <div className="bg-[#111116] p-4 rounded-2xl rounded-tl-none border border-emerald-900/30 flex items-center gap-3">
               <span className="w-2 h-2 bg-emerald-500 rounded-full animate-bounce"></span>
               <span className="w-2 h-2 bg-emerald-500 rounded-full animate-bounce [animation-delay:0.2s]"></span>
               <span className="w-2 h-2 bg-emerald-500 rounded-full animate-bounce [animation-delay:0.4s]"></span>
             </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </main>

      {/* Neural Input Interface */}
      <footer className="p-4 md:p-6 bg-[#050505] border-t border-slate-800/50 z-10 relative">
        <div className="max-w-4xl mx-auto relative flex items-center gap-3 bg-[#111116] border border-slate-800 rounded-full p-2 pl-4 focus-within:border-emerald-500/50 focus-within:ring-1 focus-within:ring-emerald-500/20 transition-all shadow-2xl">
          
          <label className="cursor-pointer shrink-0 p-2 hover:bg-slate-800 rounded-full transition-colors relative group">
            <input type="file" className="hidden" onChange={(e) => setFile(e.target.files[0])} />
            <Paperclip className={`w-5 h-5 ${file ? 'text-emerald-400' : 'text-slate-400'}`} />
            {file && <span className="absolute -top-1 -right-1 w-3 h-3 bg-emerald-500 rounded-full border-2 border-[#111116]"></span>}
          </label>

          <input 
            type="text" 
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            placeholder={file ? `${file.name} attached. Add a message...` : "Talk to the PRC AI (Upload CSVs, core photos, or type data)..."}
            className="flex-1 bg-transparent border-none outline-none text-emerald-50 placeholder-slate-500 text-[15px] px-2 font-serif"
          />

          <button 
            onClick={handleSend}
            disabled={loading || (!input.trim() && !file)}
            className="bg-emerald-600 hover:bg-emerald-500 text-white p-3 rounded-full shrink-0 transition-transform hover:scale-105 disabled:opacity-50 disabled:hover:scale-100 disabled:cursor-not-allowed shadow-[0_0_15px_rgba(16,185,129,0.3)]"
          >
            <Send className="w-5 h-5 -ml-0.5 mt-0.5" />
          </button>
          
        </div>
        <p className="text-center text-[10px] text-emerald-500/30 mt-4 font-mono tracking-widest uppercase">Proprietary Petroleum Research Center Core Interface</p>
      </footer>
    </div>
  );
}

export default App;
