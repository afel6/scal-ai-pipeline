import React, { useState, useRef, useEffect, useCallback, startTransition } from 'react';

import { AlertTriangle, Shield, Cookie as CookieIcon, Bug, BarChart3 } from 'lucide-react';

import { Send, Paperclip, Bot, User, Download, FileText, Database, Circle, PlusCircle, Trash2, MessageSquare, X, Wifi, WifiOff, Loader, LogOut, Menu, BookOpen, Upload, CheckCircle, Camera, RefreshCw, Layers } from 'lucide-react';

import axios from 'axios';

import SidebarTabs from './SidebarTabs';
import Mermaid from './Mermaid';
import VisualAudit from './VisualAudit';
import { FeedbackModal, PrivacyModal, TermsModal, CookieConsent, trackEvent } from './PrcModals';
import SimulationHeatmap from './SimulationHeatmap';
import KrPlot from './KrPlot';
import AdminDashboard from './AdminDashboard';

// New Modular Components
import Login from './components/Login';
import PetrophysicalTable from './components/PetrophysicalTable';
import { renderMessageContent } from './components/MessageRenderer';



const API_URL = import.meta.env.VITE_API_URL || '';



// PetrophysicalTable extracted to components/PetrophysicalTable.jsx



// Splits a message into text, embedded charts, mermaid diagrams, and audit logs

// renderMessageContent extracted to components/MessageRenderer.jsx



const WELCOME_MSG = { role: 'model', text: 'Hello, I am Hviel  --  your dedicated PRC Senior AI Petrophysical Specialist.\n\nI have been trained on the PRC petroleum engineering library and am ready to assist with SCAL analysis, petrophysical interpretation, and professional report generation.\n\nPlease state your Well Name, paste lab data, or attach Word, Excel, or PDF files to begin.' };



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

  const [sidebarOpen, setSidebarOpen] = useState(false);

  const [showFeedback, setShowFeedback] = useState(false);

  const [showPrivacy, setShowPrivacy] = useState(false);

  const [showTerms, setShowTerms] = useState(false); // default closed on mobile

  const [serverStatus, setServerStatus] = useState('waking');

  const [activeTab, setActiveTab] = useState('chats');

  const [showAdmin, setShowAdmin] = useState(false);

  const [showAdminGate, setShowAdminGate] = useState(false);

  const [adminPin, setAdminPin] = useState('');

  const [adminPinError, setAdminPinError] = useState(false);

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
      const emailParam = user?.email ? `?email=${user.email}` : '';
      const { data } = await axios.get(`${API_URL}/api/sessions${emailParam}`);
  useEffect(() => {
    if (user?.email && !sessionId && sessions.length > 0) {
      handleLoadSession(sessions[0].id);
    }
  }, [user, sessionId, sessions]);

      setSessions(data);
    } catch {}
  }, [user]);



  useEffect(() => {

    refreshSessions();

    // Poll every 8s instead of 5s -- reduces server overhead by 37%

    const interval = setInterval(refreshSessions, 8000);

    return () => clearInterval(interval);

  }, [refreshSessions]);



  const handleNewChat = async () => {

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

        startTransition(() => {

          setSessionId(sid);

          setMessages([WELCOME_MSG, ...data.messages.map(m => ({

            role: m.role,

            text: m.text,

            download_url: m.download_url, // Synchronized with backend's new 'download_url' key

            doc_type: m.text?.includes('EXCEL') ? 'excel' : m.text?.includes('PPTX') ? 'pptx' : m.text?.includes('PDF') ? 'pdf' : 'docx'

          }))]);

          setLastMessage(null);

        });

        localStorage.setItem('prc_session_id', sid);

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

    if (!retryObj) {

      const fileNames = msgFiles.map(f => f.name).join(', ');

      setMessages(prev => [...prev, { role: 'user', text: msgText, fileName: fileNames || null }]);

      setLastMessage({ text: msgText, files: msgFiles });

      setInput('');

      setFiles([]);

      if (inputRef.current) inputRef.current.style.height = 'auto';

    }



    setLoading(true);



    // "" Smart Route Logic ""

    // Bug fix: added 'plot','chart','graph','curve','generate' so visualization

    // requests correctly route to the Document Engine (not SSE which can't handle them)

    const triggerWords = ['document', 'report', 'excel', 'word', 'docx', 'xlsx',

      'spreadsheet', 'matrix', 'download', 'plot', 'chart', 'graph', 'curve', 'generate'];

    const isDocRequest = triggerWords.some(w => msgText.toLowerCase().includes(w));



    // "" SSE Streaming path: plain text, no files, no document generation requests ""

    if (msgFiles.length === 0 && !retryObj && !isDocRequest) {

      setUploadStatus('thinking');

      const params = new URLSearchParams({

        message: msgText,

        session_id: sessionId,

        engineer_name: user?.name || 'PRC Engineer',

        user_email: user?.email || '',

      });

      const es = new EventSource(`${API_URL}/api/chat/stream?${params}`);

      let streamedText = '';

      let streamMsgIdx = null;



      es.onmessage = (e) => {

        try {

          const data = JSON.parse(e.data);

          if (data.type === 'session') {

            setSessionId(data.session_id);

            localStorage.setItem('prc_session_id', data.session_id);

          } else if (data.type === 'token') {

            streamedText += data.text.replace(/\\n/g, '\n');

            setMessages(prev => {

              const next = [...prev];

              if (streamMsgIdx === null) {

                // First token -- append a new bubble

                streamMsgIdx = next.length;

                next.push({ role: 'model', text: streamedText });

              } else {

                next[streamMsgIdx] = { role: 'model', text: streamedText };

              }

              return next;

            });

            setServerStatus('online');

          } else if (data.type === 'done') {

            es.close();

            setLoading(false);

            setUploadStatus('');

            refreshSessions();

          } else if (data.type === 'error') {

            es.close();

            // Tag doc-engine errors so we can show the clickable button

            const isDocEngineError = data.msg?.includes('generate document') || data.msg?.includes('Document Engine');

            setMessages(prev => [...prev, {

              role: 'model',

              text: ` ${data.msg}`,

              isError: true,

              isDocEngineError,

            }]);

            setLoading(false);

            setUploadStatus('');

            setServerStatus('offline');

          }

        } catch {}

      };



      es.onerror = () => {

        if (streamedText) {

          // We got a partial response -- the SSE just closed cleanly

          es.close();

          setLoading(false);

          setUploadStatus('');

          refreshSessions();

        } else {

          es.close();

          setMessages(prev => [...prev, { role: 'model', text: '[!] Connection error. I am unable to reach the PRC Hub at this moment.', isError: true }]);

          setLoading(false);

          setUploadStatus('');

          setServerStatus('offline');

        }

      };

      return;

    }



    // "" Blocking POST path: files or retries ""

    const formData = new FormData();

    formData.append('message', msgText);

    formData.append('session_id', sessionId);

    formData.append('engineer_name', user?.name || 'PRC Engineer');

    formData.append('user_email', user?.email || '');

    msgFiles.forEach(f => formData.append('files', f));

    setUploadStatus(msgFiles.length > 0 ? 'uploading' : 'thinking');

    try {

      const response = await axios.post(`${API_URL}/api/chat`, formData, {

        timeout: 280000,

        onUploadProgress: (e) => { if (e.progress >= 1) setUploadStatus('thinking'); }

      });

      if (response.data.session_id) setSessionId(response.data.session_id);

      setServerStatus('online');

      if (response.data.status === 'success') {

        setMessages(prev => [...prev, {

          role: 'model',

          text: response.data.reply,

          download_url: response.data.is_report_ready ? response.data.download_url : null,

          doc_type: response.data.doc_type || 'docx'

        }]);

      } else {

        setMessages(prev => [...prev, { role: 'model', text: ` ${response.data.reply}`, isError: true }]);

      }

      await refreshSessions();

    } catch (err) {

      if (err.code === 'ECONNABORTED') {

        setMessages(prev => [...prev, { role: 'model', text: ' Generation timed out. Deep AI analysis or massive document generation can take up to 4 minutes. Please try again or submit a smaller dataset.', isError: true }]);

      } else {

        setMessages(prev => [...prev, { role: 'model', text: ' Connection error. I am unable to reach the PRC Hub at this moment.', isError: true }]);

      }

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



  // Hoisted outside render cycle via useMemo -- avoids object recreation on every render (Vercel perf skill)

  const status = React.useMemo(() => ({

    waking:  { icon: <Loader className="w-3 h-3 animate-spin" />, text: 'Connecting...', color: 'text-yellow-500' },

    online:  { icon: <Circle className="w-2 h-2 fill-green-500" />, text: 'Online',   color: 'text-green-400' },

    offline: { icon: <WifiOff className="w-3 h-3" />, text: 'Reconnecting...', color: 'text-red-400' },

  })[serverStatus], [serverStatus]);



  if (!user) {
    return (
      <Login 
        onLogin={(u) => {
          localStorage.setItem('prc_user', JSON.stringify(u));
          setUser(u);
        }} 
        setShowPrivacy={setShowPrivacy} 
        setShowTerms={setShowTerms} 
      />
    );
  }



  if (showAdmin) {

    return <AdminDashboard onBack={() => setShowAdmin(false)} />;

  }



  return (

    <div className="flex h-screen w-screen bg-[#09090b] text-slate-100 overflow-hidden relative font-sans">

      

      {/* Admin PIN Gate Modal */}

      {showAdminGate && (

        <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center backdrop-blur-sm" onClick={() => setShowAdminGate(false)}>

          <div className="bg-[#0c0c10] border border-amber-900/30 rounded-2xl p-8 w-80 shadow-2xl" onClick={e => e.stopPropagation()}>

            <div className="flex items-center gap-3 mb-5">

              <div className="p-2 rounded-xl bg-amber-950/30 border border-amber-900/20">

                <Shield className="w-5 h-5 text-amber-400" />

              </div>

              <div>

                <h3 className="text-sm font-black text-white tracking-tight">Admin Access</h3>

                <p className="text-[10px] text-slate-600 font-mono uppercase tracking-widest">Enter PIN to continue</p>

              </div>

            </div>

            <input

              type="password"

              maxLength={4}

              value={adminPin}

              onChange={e => { setAdminPin(e.target.value); setAdminPinError(false); }}

              onKeyDown={e => {

                if (e.key === 'Enter') {

                  if (adminPin === '0608') { setShowAdminGate(false); setShowAdmin(true); }

                  else { setAdminPinError(true); }

                }

              }}

              placeholder="****"

              autoFocus

              className={`auth-input text-center text-2xl tracking-[0.5em] mb-3 ${adminPinError ? 'border-red-500/60 shake' : ''}`}

            />

            {adminPinError && <p className="text-xs text-red-400 text-center mb-3">Incorrect PIN</p>}

            <button

              onClick={() => {

                if (adminPin === '0608') { setShowAdminGate(false); setShowAdmin(true); }

                else { setAdminPinError(true); }

              }}

              className="auth-button text-sm"

            >Authenticate</button>

          </div>

        </div>

      )}



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



        {/* Tabs + Session list + Library -- handled by SidebarTabs */}

        <SidebarTabs 

          sessionId={sessionId} 

          sessions={sessions} 

          handleLoadSession={handleLoadSession} 

          handleDeleteSession={handleDeleteSession} 

          tab={activeTab}

          setTab={setActiveTab}

        />



        <div className="p-4 border-t border-slate-800/60 shrink-0">

          <button onClick={() => setShowFeedback(true)} className="w-full mb-2 flex items-center justify-center gap-1.5 text-[10px] text-slate-500 hover:text-yellow-400 border border-slate-800 hover:border-yellow-800 py-1.5 rounded-lg transition-all uppercase tracking-widest font-mono"><span>Report Bug</span></button><p className="text-[10px] text-slate-700 font-mono tracking-widest uppercase text-center">Petroleum Research Center  Libya</p>

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

                onClick={() => { setShowAdminGate(true); setAdminPin(''); setAdminPinError(false); }}

                className="p-2 hover:bg-yellow-950/30 text-slate-500 hover:text-amber-400 rounded-lg transition-colors"

                title="Admin Dashboard"

              >

                <BarChart3 className="w-4 h-4" />

              </button>

              <button

                onClick={() => { localStorage.removeItem('prc_user'); setUser(null); }}

                className="p-2 hover:bg-yellow-950/30 text-slate-500 hover:text-yellow-400 rounded-lg transition-colors"

              >

                <LogOut className="w-4 h-4" />

              </button>

            </div>

          </div>

        </header>



        {/* Main Content Area */}

        {activeTab === 'chats' ? (

          <>

            {/* Wake banner */}

            {serverStatus === 'waking' && (

              <div className="bg-yellow-950/40 border-b border-yellow-800/30 px-4 py-2 flex items-center gap-2 shrink-0">

                <Loader className="w-3.5 h-3.5 text-yellow-500 animate-spin shrink-0" />

                <p className="text-xs text-yellow-400/80">Waking up the AI server -- please wait ~30 seconds</p>

              </div>

            )}



            {/* Chat log */}

            <main className="flex-1 overflow-y-auto px-3 py-4 md:px-6 md:py-6 space-y-4">

              {messages.map((msg, idx) => (

                <div key={idx} 
                  className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''} max-w-2xl ${msg.role === 'user' ? 'ml-auto' : 'mr-auto'} w-full msg-bubble`}
                  style={{ animationDelay: `${Math.min(idx, 5) * 0.1}s` }}>

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

                    {renderMessageContent(msg.text)}

                    {msg.role === 'model' && !msg.download_url && msg.text?.includes('data:image/png;base64,') && (

                      <button

                        onClick={() => handleSend({ text: 'generate document', files: [] })}

                        disabled={loading}

                        className="mt-3 w-full bg-gradient-to-r from-yellow-900/40 to-amber-900/30 hover:from-yellow-800/50 hover:to-amber-800/40 border border-yellow-600/50 text-yellow-200 font-bold tracking-widest uppercase px-4 py-3 rounded-xl flex items-center justify-center gap-2 text-xs transition-all active:scale-95 disabled:opacity-30 shadow-lg"

                      >

                        {loading ? <Loader className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}

                        {loading ? 'GENERATING REPORT' : 'EXPORT AS PRC REPORT'}

                      </button>

                    )}

                    {msg.download_url && (

                      <button onClick={() => {

                        const dlUrl = `${API_URL}${msg.download_url}`;

                        window.open(dlUrl, "_self");

                      }}

                        className="mt-4 w-full bg-yellow-600/20 hover:bg-yellow-600/40 border border-yellow-500/50 text-yellow-300 font-bold tracking-widest uppercase px-4 py-3 rounded-xl flex items-center justify-center gap-2 text-xs transition-all active:scale-95">

                        <Download className="w-4 h-4" /> Download {msg.doc_type === 'pptx' ? 'PowerPoint Presentation' : msg.doc_type === 'pdf' ? 'PDF Evaluation' : msg.doc_type === 'excel' ? 'Excel Spreadsheet' : 'Word Document'}

                      </button>

                    )}

                    {msg.isDocEngineError && (

                      <button

                        onClick={() => handleSend({ text: 'generate document', files: [] })}

                        disabled={loading}

                        className="mt-3 w-full bg-yellow-600/20 hover:bg-yellow-600/35 border border-yellow-500/50 text-yellow-300 font-bold tracking-widest uppercase text-[10px] py-2.5 rounded-lg flex items-center justify-center gap-2 transition-all active:scale-95 disabled:opacity-30"

                      >

                        {loading ? <Loader className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}

                        {loading ? 'GENERATING' : 'GENERATE CHART / DOCUMENT'}

                      </button>

                    )}

                    {msg.isError && !msg.isDocEngineError && lastMessage && (

                      <button onClick={() => handleSend(lastMessage)} disabled={loading || retryCooldown > 0}

                        className="mt-3 w-full bg-amber-950/20 hover:bg-amber-950/40 border border-amber-600/50 text-amber-300 font-bold tracking-widest uppercase text-[10px] py-2.5 rounded-lg flex items-center justify-center gap-2 transition-all active:scale-95 disabled:opacity-30">

                        {loading ? <Loader className="w-3 h-3 animate-spin" /> : <Wifi className="w-3 h-3 text-yellow-500" />}

                        {loading ? 'RETRYING...' : retryCooldown > 0 ? `RE-TRY IN ${retryCooldown}s` : 'RE-TRY REQUEST'}

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

                        <span className="text-sm text-yellow-300/80 font-serif">Uploading file</span>

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
            <footer className="p-4 bg-black/40 backdrop-blur-xl border-t border-slate-800/60 shrink-0 relative overflow-hidden">
              <div className="absolute inset-0 bg-gradient-to-t from-yellow-500/5 to-transparent pointer-events-none" />
              
              {/* File chips */}
              {files.length > 0 && (
                <div className="mb-3 flex flex-wrap gap-2 animate-in fade-in slide-in-from-bottom-2">
                  {files.map((f, i) => (
                    <div key={i} className="flex items-center gap-2 bg-yellow-950/20 border border-yellow-500/20 rounded-xl px-3 py-2 shadow-inner">
                      <FileText className="w-3.5 h-3.5 text-yellow-500 shrink-0" />
                      <span className="text-[10px] font-black text-yellow-200 uppercase tracking-wider truncate max-w-[140px]">{f.name}</span>
                      <button onClick={() => setFiles(prev => prev.filter((_, idx) => idx !== i))} className="ml-1 text-slate-500 hover:text-red-500 transition-colors">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <div className="relative group">
                {/* Glow effect on focus */}
                <div className="absolute -inset-1 bg-gradient-to-r from-yellow-500/20 to-amber-500/20 rounded-[22px] blur opacity-0 group-focus-within:opacity-100 transition-opacity duration-500" />
                
                <div className="relative flex items-center gap-3 bg-[#0a0a0c] border border-slate-800 rounded-2xl p-2 pl-4 group-focus-within:border-yellow-500/50 transition-all shadow-2xl">
                  <label className="cursor-pointer shrink-0 p-2 hover:bg-yellow-500/10 rounded-xl transition-all hover:scale-110 active:scale-95 group">
                    <input type="file" multiple accept=".txt,.pdf,.csv,.xlsx,.xls,.doc,.docx,image/jpeg,image/png,image/gif,image/webp" className="hidden"
                      onChange={(e) => {
                        const newFiles = Array.from(e.target.files);
                        setFiles(prev => {
                          const existingNames = prev.map(f => f.name);
                          const deduped = newFiles.filter(f => !existingNames.includes(f.name));
                          return [...prev, ...deduped];
                        });
                        e.target.value = '';
                      }} />
                    <Paperclip className={`w-5 h-5 transition-colors ${files.length > 0 ? 'text-yellow-500' : 'text-slate-500 group-hover:text-yellow-500/70'}`} />
                  </label>

                  <textarea
                    ref={inputRef}
                    value={input}
                    onChange={(e) => {
                      setInput(e.target.value);
                      e.target.style.height = 'auto';
                      e.target.style.height = `${Math.min(e.target.scrollHeight, 250)}px`;
                    }}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (input.trim() || files.length > 0) handleSend(); } }}
                    rows={1}
                    disabled={serverStatus === 'waking'}
                    placeholder={serverStatus === 'waking' ? 'Establishing secure link...' : 'Query Hviel Intel...'}
                    className="flex-1 bg-transparent border-none outline-none text-slate-100 placeholder-slate-700 text-sm md:text-[15px] font-medium disabled:opacity-50 resize-none overflow-y-auto py-3 min-h-[48px] leading-relaxed block"
                  />

                  <button
                    onClick={() => handleSend()}
                    disabled={loading || serverStatus === 'waking' || (!input.trim() && files.length === 0)}
                    className="bg-gradient-to-br from-yellow-500 to-amber-600 hover:from-yellow-400 hover:to-amber-500 text-black p-3 rounded-xl shrink-0 transition-all active:scale-90 disabled:opacity-30 disabled:cursor-not-allowed shadow-[0_0_20px_rgba(234,179,8,0.3)] hover:shadow-[0_0_25px_rgba(234,179,8,0.5)]"
                  >
                    {loading ? <Loader className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
                  </button>
                </div>
              </div>
              
              <div className="mt-2 text-center">
                <p className="text-[8px] text-slate-700 font-mono uppercase tracking-[0.3em]">Sovereign AI Node -- Encrypted PRC Stream</p>
              </div>
            </footer>

          </>

        ) : activeTab === 'audit' ? (

          <VisualAudit />

        ) : (

          <div className="flex-1 flex flex-col items-center justify-center bg-[#0c0c10] text-slate-600">

            <BookOpen className="w-12 h-12 mb-4 opacity-20" />

            <p className="text-sm font-mono tracking-widest uppercase opacity-40">Library Mode -- Use Sidebar to Manage Data</p>

          </div>

        )}

      </div>

      {showFeedback && <FeedbackModal userEmail={user?.email} onClose={() => setShowFeedback(false)} />}

      {showPrivacy && <PrivacyModal onClose={() => setShowPrivacy(false)} />}

      {showTerms && <TermsModal onClose={() => setShowTerms(false)} />}

      <CookieConsent />
    </div>
  );
}

export default App;
















