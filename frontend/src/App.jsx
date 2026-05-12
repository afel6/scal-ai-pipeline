/* eslint-disable no-unused-vars */
// frontend/src/App.jsx
// Changes: admin auth via backend token (PIN removed from client) ·
//          regex intent routing for SSE vs POST · useCallback dep fix ·
//          session race guard · SSE 'done' JSON event handling

import React, {
  useState, useRef, useEffect, useCallback, startTransition, useMemo,
} from 'react';
import {
  AlertTriangle, Shield, Cookie as CookieIcon, Bug, BarChart3,
  Send, Paperclip, Bot, User, Download, FileText, Database, Circle,
  PlusCircle, Trash2, MessageSquare, X, Wifi, WifiOff, Loader, LogOut,
  Menu, BookOpen, Upload, CheckCircle, Camera, RefreshCw, Layers, ShieldCheck, Activity,
} from 'lucide-react';
import axios from 'axios';

import SidebarTabs       from './SidebarTabs';
import Mermaid           from './Mermaid';
import VisualAudit       from './VisualAudit';
import SimulationHeatmap from './SimulationHeatmap';
import KrCurvePlot from './components/KrCurvePlot';
import AdminDashboard    from './AdminDashboard';
import Login             from './components/Login';
import PetrophysicalTable from './components/PetrophysicalTable';
import { renderMessageContent } from './components/MessageRenderer';
import { FeedbackModal, PrivacyModal, TermsModal, CookieConsent, AdminLoginModal,
trackEvent } from './PrcModals';

const API_URL = import.meta.env.VITE_API_URL || '';

const WELCOME_MSG = {
  role: 'model',
  text: 'Hello, I am Hviel — your dedicated PRC Senior AI Petrophysical Specialist.\n\n'
      + 'I have been trained on the PRC petroleum engineering library and am ready to assist '
      + 'with SCAL analysis, petrophysical interpretation, and professional report generation.\n\n'
      + 'Please state your Well Name, paste lab data, or attach Word, Excel, or PDF files to begin.',
};

// Regex-based intent detection — avoids routing "what is a chart?" to the 280s POST path
const _DOC_INTENT = /\b(generate|create|export|download|make|produce)\b.{0,50}\b(report|document|excel|word|docx|xlsx|pdf|powerpoint|pptx)\b/i;
function isDocumentRequest(text, hasFiles, isRetry) {
  return isRetry || hasFiles || _DOC_INTENT.test(text);
}

function timeAgo(ts) {
  const diff = Date.now() / 1000 - ts;
  if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function App() {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('prc_user')); }
    catch { return null; }
  });

  const [messages,       setMessages]       = useState([WELCOME_MSG]);
  const [input,          setInput]          = useState('');
  const [files,          setFiles]          = useState([]);
  const [loading,        setLoading]        = useState(false);
  const [uploadStatus,   setUploadStatus]   = useState('');
  const [sessionId, setSessionId] = useState(() => {
    const val = localStorage.getItem('prc_session_id');
    return (val && val !== 'null' && val !== 'undefined') ? val : null;
  });
  const [lastMessage,    setLastMessage]    = useState(null);
  const [retryCooldown,  setRetryCooldown]  = useState(0);
  const [sessions,       setSessions]       = useState([]);
  const [sidebarOpen,    setSidebarOpen]    = useState(false);
  const [showFeedback,   setShowFeedback]   = useState(false);
  const [showPrivacy,    setShowPrivacy]    = useState(false);
  const [showTerms,      setShowTerms]      = useState(false);
  const [serverStatus,   setServerStatus]   = useState('waking');
  const [activeTab,      setActiveTab]      = useState('chats');
  const [showAdmin,      setShowAdmin]      = useState(false);
  const [showAdminGate,  setShowAdminGate]  = useState(false);
  const [adminPin,       setAdminPin]       = useState('');
  const [adminToken,     setAdminToken]     = useState(() => localStorage.getItem('prc_admin_token') || '');
  const [adminPinError,  setAdminPinError]  = useState(false);
  const [adminPinLoading,setAdminPinLoading]= useState(false);
  const [reportLoading,  setReportLoading]  = useState(false);

  const messagesEndRef    = useRef(null);
  const inputRef          = useRef(null);
  const initialLoadGuard  = useRef(false);  // prevents session race condition

  // ── auto-scroll ────────────────────────────────────────────────────────────
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // ── persist session id ─────────────────────────────────────────────────────
  useEffect(() => {
    if (sessionId !== null) {
      localStorage.setItem('prc_session_id', sessionId);
    }
  }, [sessionId]);

  // ── persist admin token ────────────────────────────────────────────────────
  useEffect(() => {
    if (adminToken) {
      localStorage.setItem('prc_admin_token', adminToken);
    } else {
      localStorage.removeItem('prc_admin_token');
    }
  }, [adminToken]);

  // ── session loader (stable ref — no stale-closure risk) ───────────────────
  const handleLoadSession = useCallback(async (sid) => {
    if (!sid) return;
    try {
      const { data } = await axios.get(`${API_URL}/api/session/${sid}`);
      if (data.status === 'ok') {
        startTransition(() => {
          setSessionId(sid);
          setMessages([
            WELCOME_MSG,
            ...data.messages.map(m => ({
              role:         m.role,
              text:         m.text,
              download_url: m.download_url,
              fileName:     m.fileName,
              doc_type:     m.text?.includes('EXCEL') ? 'excel'
                          : m.text?.includes('PPTX')  ? 'pptx'
                          : m.text?.includes('PDF')   ? 'pdf'
                          : 'docx',
            })),
          ]);
          setLastMessage(null);
        });
        localStorage.setItem('prc_session_id', sid);
      }
    } catch { /* silently ignore network errors on load */ }
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, []); // stable — no deps that change

  // ── server wake + initial session load ────────────────────────────────────
  useEffect(() => {
    const wake = async () => {
      try {
        await axios.get(`${API_URL}/`, { timeout: 180_000 });
        setServerStatus('online');
      } catch {
        setServerStatus('offline');
      }
    };
    wake();
    if (window.innerWidth >= 768) setSidebarOpen(true);
    const saved = localStorage.getItem('prc_session_id');
    if (saved) handleLoadSession(saved);
  }, [handleLoadSession]);

  // ── session list polling ───────────────────────────────────────────────────
  const refreshSessions = useCallback(async () => {
    try {
      const emailParam = user?.email ? `?email=${encodeURIComponent(user.email)}` : '';
      const { data }   = await axios.get(`${API_URL}/api/sessions${emailParam}`);
      setSessions(data);
    } catch { /* ignore */ }
  }, [user]);

  useEffect(() => {
    refreshSessions();
    const interval = setInterval(refreshSessions, 8_000);
    return () => clearInterval(interval);
  }, [refreshSessions]);

  // Auto-load most-recent session once, after sessions list populates
  useEffect(() => {
    if (initialLoadGuard.current) return;
    if (!user?.email || !sessions.length) return;
    const saved = localStorage.getItem('prc_session_id');
    if (saved) return; // already loaded
    initialLoadGuard.current = true;
    handleLoadSession(sessions[0].id);
  }, [user, sessions, handleLoadSession]);

  // ── new chat ───────────────────────────────────────────────────────────────
  const handleNewChat = useCallback(() => {
    setSessionId('');
    localStorage.setItem('prc_session_id', '');
    setMessages([WELCOME_MSG]);
    setLastMessage(null);
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, []);

  // ── delete session ─────────────────────────────────────────────────────────
  const handleDeleteSession = useCallback(async (e, sid) => {
    e.stopPropagation();
    await axios.delete(`${API_URL}/api/session/${sid}?email=${encodeURIComponent(user?.email || '')}`);
    await refreshSessions();
    if (sid === sessionId) {
      setSessionId('');
      localStorage.removeItem('prc_session_id');
      setMessages([WELCOME_MSG]);
    }
  }, [sessionId, refreshSessions, user]);

  // ── rename session ────────────────────────────────────────────────────────
  const handleRenameSession = useCallback(async (sid, newTitle) => {
    if (!sid || !newTitle) return;
    const form = new URLSearchParams({ title: newTitle });
    await axios.post(`${API_URL}/api/session/${sid}/title`, form);
    await refreshSessions();
  }, [refreshSessions]);

  // ── admin PIN → backend auth ───────────────────────────────────────────────
  const handleAdminAuth = useCallback(async (pin) => {
    try {
      const form = new URLSearchParams({ pin });
      const { data } = await axios.post(`${API_URL}/api/admin/auth`, form);
      if (data.token) {
        setAdminToken(data.token);
        setShowAdminGate(false);
        setShowAdmin(true);
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }, []);

  // ── executive report download ──────────────────────────────────────────────
  const handleDownloadReport = useCallback(async () => {
    if (!sessionId || reportLoading) return;
    setReportLoading(true);
    try {
      const wellName = sessions.find(s => s.id === sessionId)?.title || 'UNKNOWN WELL';
      const form     = new URLSearchParams({ session_id: sessionId, well_name: wellName });
      const { data } = await axios.post(`${API_URL}/api/report/generate`, form);
      if (data.download_url) {
        const a    = document.createElement('a');
        a.href     = `${API_URL}${data.download_url}`;
        a.download = data.download_url.split('/').pop();
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      }
    } catch (err) {
      console.error('[Report]', err);
    } finally {
      setReportLoading(false);
    }
  }, [sessionId, sessions, reportLoading]);

  // ── retry cooldown ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (retryCooldown <= 0) return;
    const t = setTimeout(() => setRetryCooldown(c => c - 1), 1_000);
    return () => clearTimeout(t);
  }, [retryCooldown]);

  // ── send ───────────────────────────────────────────────────────────────────
  const handleSend = useCallback(async (retryObj = null) => {
    const msgText  = retryObj ? retryObj.text  : input;
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

    // ── SSE path: plain text, no files, not a doc-generation request ─────────
    if (!isDocumentRequest(msgText, msgFiles.length > 0, !!retryObj)) {
      setUploadStatus('thinking');

      const params = new URLSearchParams({
        message:       msgText,
        session_id:    sessionId || '',
        engineer_name: user?.name  || 'PRC Engineer',
        user_email:    user?.email || '',
      });

      const es = new EventSource(`${API_URL}/api/chat/stream?${params}`);
      let streamedText  = '';
      let streamMsgIdx  = null;

      es.onmessage = (e) => {
        // Handle the well-formed [DONE] sentinel the old server sends
        // (new server sends JSON {"type":"done"} — both handled below)
        if (e.data === '[DONE]') {
          es.close();
          setLoading(false);
          setUploadStatus('');
          refreshSessions();
          return;
        }
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
            setMessages(prev => [...prev, {
              role: 'model', text: ` ${data.msg}`, isError: true,
              isDocEngineError: data.msg?.includes('generate document'),
            }]);
            setLoading(false);
            setUploadStatus('');
            setServerStatus('offline');
          }
        } catch { /* non-JSON frame — ignore */ }
      };

      es.onerror = (err) => {
        if (streamedText) {
          es.close();
          setLoading(false);
          setUploadStatus('');
          refreshSessions();
        } else {
          es.close();
          const detail = (err && err.message) ? `: ${err.message}` : '';
          setMessages(prev => [...prev, {
            role: 'model',
            text: `[!] Connection error. Unable to reach the PRC Hub${detail}. Please check your internet or try refreshing.`,
            isError: true,
          }]);
          setLoading(false);
          setUploadStatus('');
          setServerStatus('offline');
        }
      };

      return;
    }

    // ── POST path: files, retries, or explicit document generation ────────────
    const formData = new FormData();
    formData.append('message',       msgText);
    formData.append('session_id',    sessionId || '');
    formData.append('engineer_name', user?.name  || 'PRC Engineer');
    formData.append('user_email',    user?.email || '');
    msgFiles.forEach(f => formData.append('files', f));

    setUploadStatus(msgFiles.length > 0 ? 'uploading' : 'thinking');

    try {
      const response = await axios.post(`${API_URL}/api/chat`, formData, {
        timeout: 280_000,
        onUploadProgress: (e) => { if (e.progress >= 1) setUploadStatus('thinking'); },
      });

      if (response.data.session_id) setSessionId(response.data.session_id);
      setServerStatus('online');

      if (response.data.status === 'success') {
        setMessages(prev => [...prev, {
          role:         'model',
          text:         response.data.reply,
          download_url: response.data.is_report_ready ? response.data.download_url : null,
          doc_type:     response.data.doc_type || 'docx',
        }]);
      } else {
        setMessages(prev => [...prev, {
          role: 'model', text: ` ${response.data.reply}`, isError: true,
        }]);
      }
      await refreshSessions();
    } catch (err) {
      const detail = err.response ? `HTTP ${err.response.status}` : err.message;
      const msg = err.code === 'ECONNABORTED'
        ? ' Generation timed out. Deep analysis can take up to 4 minutes. Please try again or submit a smaller dataset.'
        : ` Connection error during upload: ${detail}. Unable to reach the PRC Hub at this moment.`;
      setMessages(prev => [...prev, { role: 'model', text: msg, isError: true }]);
      setServerStatus('offline');
    } finally {
      setLoading(false);
      setUploadStatus('');
      if (retryObj) setRetryCooldown(15);
    }
  }, [input, files, sessionId, user, refreshSessions]);

  const statusConfig = useMemo(() => ({
    online: { icon: <ShieldCheck className="w-3 h-3" />, text: 'Encrypted', color: 'text-emerald-500' },
    offline: { icon: <Activity className="w-3 h-3 animate-pulse" />, text: 'Offline', color: 'text-red-500' },
    busy: { icon: <Loader className="w-3 h-3 animate-spin" />, text: 'Processing', color: 'text-yellow-500' },
  })[serverStatus] || { icon: <Loader className="w-3 h-3 animate-spin" />, text: 'Connecting...', color: 'text-yellow-500' }, [serverStatus]);

  // ── guards ────────────────────────────────────────────────────────────────
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
    return <AdminDashboard 
        adminToken={adminToken}
        onBack={() => setShowAdmin(false)} 
        onLogout={() => { setAdminToken(''); setShowAdmin(false); }}
      />;
  }

  // ── render ─────────────────────────────────────────────────────────────────
  return (
    <div className="flex h-screen w-screen bg-[#09090b] text-slate-100 overflow-hidden relative font-sans">

      <AdminLoginModal
        isOpen={showAdminGate}
        onLogin={handleAdminAuth}
        onClose={() => setShowAdminGate(false)}
      />

      {/* ── Mobile backdrop ────────────────────────────────────────────────── */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-20 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* ── Sidebar ────────────────────────────────────────────────────────── */}
      <aside className={`
        sidebar-glass
        fixed md:relative top-0 left-0 h-full z-30 flex flex-col
        transition-transform duration-300 ease-in-out w-72
        ${sidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0 md:w-0 md:overflow-hidden md:border-0'}
      `}>
        <div className="p-4 border-b border-slate-800/60 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <Database className="w-5 h-5 text-yellow-500 shrink-0" />
            <span className="text-sm font-black tracking-widest text-yellow-50">PRC STUDIES</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleNewChat}
              className="flex items-center gap-1 text-xs text-yellow-400 hover:text-yellow-300 border border-yellow-800/50 hover:border-yellow-600 px-2 py-1.5 rounded-none transition-all"
            >
              <PlusCircle className="w-3.5 h-3.5" /> New
            </button>
            <button
              onClick={() => setSidebarOpen(false)}
              className="md:hidden p-1 text-slate-500 hover:text-white"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        <SidebarTabs
          sessionId={sessionId}
          sessions={sessions}
          handleLoadSession={handleLoadSession}
          handleDeleteSession={handleDeleteSession}
          handleRenameSession={handleRenameSession}
          tab={activeTab}
          setTab={setActiveTab}
        />

        <div className="p-4 border-t border-slate-800/60 shrink-0">
          <button
            onClick={() => setShowFeedback(true)}
            className="w-full mb-2 flex items-center justify-center gap-1.5 text-[10px] text-slate-500 hover:text-yellow-400 border border-slate-800 hover:border-yellow-800 py-1.5 rounded-none transition-all uppercase tracking-widest font-mono"
          >
            <span>Report Bug</span>
          </button>
          <p className="text-[10px] text-slate-700 font-mono tracking-widest uppercase text-center">
            Petroleum Research Center Libya
          </p>
        </div>
      </aside>

      {/* ── Main ───────────────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 h-full">

        {/* Header */}
        <header className="bg-[#050505] border-b border-slate-800/60 px-3 md:px-4 py-3 flex items-center justify-between shrink-0 gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <button
              onClick={() => setSidebarOpen(p => !p)}
              className="p-2 hover:bg-slate-800 rounded-none transition-colors text-slate-400 hover:text-white shrink-0"
            >
              <Menu className="w-5 h-5" />
            </button>
            <span className="text-sm font-bold tracking-[0.2em] text-yellow-500 uppercase truncate hidden sm:block">
              PRC PETROPHYSICS ENGINE
            </span>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            <div className={`flex items-center gap-1.5 ${status.color}`}>
              {status.icon}
              <span className="text-xs font-mono tracking-wide hidden sm:block">{status.text}</span>
            </div>
            <div className="h-4 w-px bg-slate-800 hidden sm:block" />
            <div className="flex items-center gap-2">
              <div className="text-right hidden sm:block">
                <p className="text-[10px] text-slate-500 font-bold uppercase tracking-tighter leading-none">Engineer</p>
                <p className="text-xs text-white font-sans italic truncate max-w-[120px]">{user.name}</p>
              </div>
              <button
                onClick={handleDownloadReport}
                disabled={reportLoading || !sessionId}
                className="flex items-center gap-1.5 px-2.5 py-1.5 bg-yellow-950/20 hover:bg-yellow-900/40 border border-yellow-800/40 hover:border-yellow-600/60 text-yellow-500 hover:text-yellow-300 rounded-none transition-all text-[10px] font-black uppercase tracking-widest disabled:opacity-30 disabled:cursor-not-allowed"
                title="Download Executive SCAL Report (.docx)"
              >
                {reportLoading
                  ? <Loader className="w-3.5 h-3.5 animate-spin" />
                  : <FileText className="w-3.5 h-3.5" />}
                <span className="hidden sm:block">Report</span>
              </button>
              <button
                onClick={() => {
                  if (adminToken) {
                    setShowAdmin(true);
                  } else {
                    setShowAdminGate(true);
                    setAdminPin('');
                    setAdminPinError(false);
                  }
                }}
                className="p-2 hover:bg-yellow-950/30 text-slate-500 hover:text-amber-400 rounded-none transition-colors"
                title="Admin Dashboard"
              >
                <BarChart3 className="w-4 h-4" />
              </button>
              <button
                onClick={() => {
                  localStorage.removeItem('prc_user');
                  localStorage.removeItem('prc_session_id');
                  setUser(null);
                }}
                className="p-2 hover:bg-yellow-950/30 text-slate-500 hover:text-yellow-400 rounded-none transition-colors"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          </div>
        </header>

        {/* ── Chat tab ───────────────────────────────────────────────────────── */}
        {activeTab === 'chats' ? (
          <>
            {serverStatus === 'waking' && (
              <div className="bg-yellow-950/40 border-b border-yellow-800/30 px-4 py-2 flex items-center gap-2 shrink-0">
                <Loader className="w-3.5 h-3.5 text-yellow-500 animate-spin shrink-0" />
                <p className="text-xs text-yellow-400/80">
                  Waking up the AI server — please wait ~30 seconds
                </p>
              </div>
            )}

            <main className="flex-1 overflow-y-auto px-3 py-4 md:px-6 md:py-6 space-y-4">
              {messages.map((msg, idx) => (
                <div
                  key={idx}
                  className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''} max-w-2xl ${msg.role === 'user' ? 'ml-auto' : 'mr-auto'} w-full msg-bubble`}
                  style={{ animationDelay: `${Math.min(idx, 5) * 0.1}s` }}
                >
                  {/* Avatar */}
                  <div className={`w-8 h-8 rounded-none flex items-center justify-center shrink-0 border
                    ${msg.role === 'user'
                      ? 'bg-slate-800 border-slate-700'
                      : 'bg-yellow-950 border-yellow-800/50'}`}
                  >
                    {msg.role === 'user'
                      ? <User className="w-3.5 h-3.5 text-slate-300" />
                      : <Bot  className="w-3.5 h-3.5 text-yellow-400" />}
                  </div>

                  {/* Bubble */}
                  <div className={`px-4 py-3 rounded-none text-sm md:text-[15px] leading-relaxed shadow-lg max-w-[85%]
                    ${msg.role === 'user'
                      ? 'bg-slate-800 text-slate-200 rounded-none-none border border-slate-700/50'
                      : 'bg-[#111116] text-yellow-50/90 rounded-none-none border border-yellow-900/30'}`}
                  >
                    {msg.fileName && (
                      <div className="flex items-center gap-2 mb-2 bg-black/40 p-2 rounded-none border border-slate-700/50 w-fit">
                        <FileText className="w-3.5 h-3.5 text-yellow-400 shrink-0" />
                        <span className="text-xs font-mono text-yellow-300 truncate max-w-[160px]">
                          {msg.fileName}
                        </span>
                      </div>
                    )}

                    {renderMessageContent(msg.text)}

                    {/* Export button when plots are present but no download URL yet */}
                    {msg.role === 'model' && !msg.download_url && msg.text?.includes('data:image/png;base64,') && (
                      <button
                        onClick={() => handleSend({ text: 'generate document', files: [] })}
                        disabled={loading}
                        className="mt-3 w-full bg-gradient-to-r from-yellow-900/40 to-amber-900/30 hover:from-yellow-800/50 hover:to-amber-800/40 border border-yellow-600/50 text-yellow-200 font-bold tracking-widest uppercase px-4 py-3 rounded-none flex items-center justify-center gap-2 text-xs transition-all active:scale-95 disabled:opacity-30 shadow-lg"
                      >
                        {loading ? <Loader className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
                        {loading ? 'GENERATING REPORT' : 'EXPORT AS PRC REPORT'}
                      </button>
                    )}

                    {/* Download button */}
                    {msg.download_url && (
                      <button
                        onClick={() => window.open(`${API_URL}${msg.download_url}`, '_self')}
                        className="mt-4 w-full bg-yellow-600/20 hover:bg-yellow-600/40 border border-yellow-500/50 text-yellow-300 font-bold tracking-widest uppercase px-4 py-3 rounded-none flex items-center justify-center gap-2 text-xs transition-all active:scale-95"
                      >
                        <Download className="w-4 h-4" />
                        Download {
                          msg.doc_type === 'pptx'  ? 'PowerPoint Presentation' :
                          msg.doc_type === 'pdf'   ? 'PDF Evaluation' :
                          msg.doc_type === 'excel' ? 'Excel Spreadsheet' :
                                                     'Word Document'
                        }
                      </button>
                    )}

                    {/* Doc engine error — offer retry */}
                    {msg.isDocEngineError && (
                      <button
                        onClick={() => handleSend({ text: 'generate document', files: [] })}
                        disabled={loading}
                        className="mt-3 w-full bg-yellow-600/20 hover:bg-yellow-600/35 border border-yellow-500/50 text-yellow-300 font-bold tracking-widest uppercase text-[10px] py-2.5 rounded-none flex items-center justify-center gap-2 transition-all active:scale-95 disabled:opacity-30"
                      >
                        {loading ? <Loader className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}
                        {loading ? 'GENERATING' : 'GENERATE CHART / DOCUMENT'}
                      </button>
                    )}

                    {/* Generic error — retry original request */}
                    {msg.isError && !msg.isDocEngineError && lastMessage && (
                      <button
                        onClick={() => handleSend(lastMessage)}
                        disabled={loading || retryCooldown > 0}
                        className="mt-3 w-full bg-amber-950/20 hover:bg-amber-950/40 border border-amber-600/50 text-amber-300 font-bold tracking-widest uppercase text-[10px] py-2.5 rounded-none flex items-center justify-center gap-2 transition-all active:scale-95 disabled:opacity-30"
                      >
                        {loading
                          ? <Loader className="w-3 h-3 animate-spin" />
                          : <Wifi className="w-3 h-3 text-yellow-500" />}
                        {loading           ? 'RETRYING...'
                          : retryCooldown > 0 ? `RE-TRY IN ${retryCooldown}s`
                          :                     'RE-TRY REQUEST'}
                      </button>
                    )}
                  </div>
                </div>
              ))}

              {/* Typing indicator */}
              {loading && (
                <div className="flex gap-3 max-w-2xl w-full">
                  <div className="w-8 h-8 rounded-none flex items-center justify-center shrink-0 bg-yellow-950 border border-yellow-800/50">
                    <Bot className="w-3.5 h-3.5 text-yellow-400" />
                  </div>
                  <div className="bg-[#111116] px-4 py-3 rounded-none rounded-none-none border border-yellow-900/30 flex items-center gap-2">
                    {uploadStatus === 'uploading' ? (
                      <>
                        <Loader className="w-4 h-4 text-yellow-400 animate-spin shrink-0" />
                        <span className="text-sm text-yellow-300/80 font-mono tracking-wide">Uploading file</span>
                      </>
                    ) : (
                      <>
                        <span className="w-2 h-2 bg-yellow-500 rounded-none animate-bounce" />
                        <span className="w-2 h-2 bg-yellow-500 rounded-none animate-bounce [animation-delay:0.15s]" />
                        <span className="w-2 h-2 bg-yellow-500 rounded-none animate-bounce [animation-delay:0.3s]" />
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

              {files.length > 0 && (
                <div className="mb-3 flex flex-wrap gap-2 animate-in fade-in slide-in-from-bottom-2">
                  {files.map((f, i) => (
                    <div key={i} className="flex items-center gap-2 bg-yellow-950/20 border border-yellow-500/20 rounded-none px-3 py-2 shadow-inner">
                      <FileText className="w-3.5 h-3.5 text-yellow-500 shrink-0" />
                      <span className="text-[10px] font-black text-yellow-200 uppercase tracking-wider truncate max-w-[140px]">
                        {f.name}
                      </span>
                      <button
                        onClick={() => setFiles(prev => prev.filter((_, idx) => idx !== i))}
                        className="ml-1 text-slate-500 hover:text-red-500 transition-colors"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <div className="relative group">
                <div className="absolute -inset-1 bg-gradient-to-r from-yellow-500/20 to-amber-500/20 rounded-none-[22px] blur opacity-0 group-focus-within:opacity-100 transition-opacity duration-500" />
                <div className="relative flex items-center gap-3 bg-[#0a0a0c] border border-slate-800 rounded-none p-2 pl-4 group-focus-within:border-yellow-500/50 transition-all shadow-2xl">
                  <label className="cursor-pointer shrink-0 p-2 hover:bg-yellow-500/10 rounded-none transition-all hover:scale-110 active:scale-95 group">
                    <input
                      type="file"
                      multiple
                      accept=".txt,.pdf,.csv,.xlsx,.xls,.doc,.docx,image/jpeg,image/png,image/gif,image/webp"
                      className="hidden"
                      onChange={(e) => {
                        const incoming = Array.from(e.target.files);
                        setFiles(prev => {
                          const existing = new Set(prev.map(f => f.name));
                          return [...prev, ...incoming.filter(f => !existing.has(f.name))];
                        });
                        e.target.value = '';
                      }}
                    />
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
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        if (input.trim() || files.length > 0) handleSend();
                      }
                    }}
                    rows={1}
                    disabled={serverStatus === 'waking'}
                    placeholder={serverStatus === 'waking' ? 'Establishing secure link...' : 'Query Hviel Intel...'}
                    className="flex-1 bg-transparent border-none outline-none text-slate-100 placeholder-slate-700 text-sm md:text-[15px] font-medium disabled:opacity-50 resize-none overflow-y-auto py-3 min-h-[48px] leading-relaxed block"
                  />

                  <button
                    onClick={() => handleSend()}
                    disabled={loading || serverStatus === 'waking' || (!input.trim() && files.length === 0)}
                    className={`bg-gradient-to-br from-yellow-500 to-amber-600 hover:from-yellow-400 hover:to-amber-500 text-black p-3 rounded-none shrink-0 transition-all active:scale-90 disabled:opacity-30 disabled:cursor-not-allowed shadow-[0_0_20px_rgba(234,179,8,0.3)] hover:shadow-[0_0_25px_rgba(234,179,8,0.5)] ${loading ? 'btn-streaming' : ''}`}
                  >
                    {loading ? <Loader className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
                  </button>
                </div>
              </div>

              <div className="mt-2 text-center">
                <p className="text-[8px] text-slate-700 font-mono uppercase tracking-[0.3em]">
                  Sovereign AI Node — Encrypted PRC Stream
                </p>
              </div>
            </footer>
          </>
        ) : activeTab === 'audit' ? (
          <VisualAudit />
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center bg-[#0c0c10] text-slate-600">
            <BookOpen className="w-12 h-12 mb-4 opacity-20" />
            <p className="text-sm font-mono tracking-widest uppercase opacity-40">
              Library Mode — Use Sidebar to Manage Data
            </p>
          </div>
        )}
      </div>

      {showFeedback && <FeedbackModal userEmail={user?.email} onClose={() => setShowFeedback(false)} />}
      {showPrivacy  && <PrivacyModal  onClose={() => setShowPrivacy(false)} />}
      {showTerms    && <TermsModal    onClose={() => setShowTerms(false)} />}
      <CookieConsent />
    </div>
  );
}
