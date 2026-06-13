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
  const [simProgress,    setSimProgress]    = useState(null); // { val, text }
  const [cognitiveMode,  setCognitiveMode]  = useState('');

  const [docRetrying,    setDocRetrying]    = useState(false);

  const messagesEndRef    = useRef(null);
  const inputRef          = useRef(null);
  const initialLoadGuard  = useRef(false);  // prevents session race condition
  const docRetryTimerRef  = useRef(null);

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

  // ── session loader — includes email for RLS (/api/session/:sid?email=) ────
  const handleLoadSession = useCallback(async (sid) => {
    if (!sid) return;
    const emailParam = user?.email ? `?email=${encodeURIComponent(user.email)}` : '';
    try {
      const { data } = await axios.get(`${API_URL}/api/session/${sid}${emailParam}`);
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
  }, [user?.email]); // recreates only when email changes — provides RLS param

  // ── server wake — mount only, no session logic here ──────────────────────
  useEffect(() => {
    const wake = async () => {
      try {
        // Poll the PUBLIC /health endpoint (not the auth-gated /api/diag).
        // wake() runs once on mount, before any login token/email exists, so
        // /api/diag returned 401 here and the badge always showed "Offline".
        await axios.get(`${API_URL}/health`, { timeout: 180_000 });
        setServerStatus('online');
      } catch {
        setServerStatus('offline');
      }
    };
    wake();
    if (window.innerWidth >= 768) setSidebarOpen(true);
  }, []); // intentionally empty — runs once on mount

  // ── restore saved session once user is authenticated ─────────────────────
  useEffect(() => {
    if (!user?.email) return; // wait for auth before hitting RLS-protected endpoint
    const saved = localStorage.getItem('prc_session_id');
    if (saved && saved !== 'null' && saved !== 'undefined') handleLoadSession(saved);
  }, [user?.email, handleLoadSession]); // fires on login and when handleLoadSession stabilises

  // ── session list polling ───────────────────────────────────────────────────
  const refreshSessions = useCallback(async () => {
    try {
      const emailParam = user?.email ? `?email=${encodeURIComponent(user.email)}` : '';
      const { data }   = await axios.get(`${API_URL}/api/sessions${emailParam}`);
      setSessions(data);
    } catch { /* ignore */ }
  }, [user]);

  // Immediate fetch on login (refreshSessions recreates when user changes),
  // then keep polling every 8 s.
  useEffect(() => {
    if (!user?.email) return; // don't poll unauthenticated — backend returns []
    refreshSessions();
    const interval = setInterval(refreshSessions, 8_000);
    return () => clearInterval(interval);
  }, [user?.email, refreshSessions]);

  // Auto-load most-recent session once, after sessions list populates
  useEffect(() => {
    if (localStorage.getItem('prc_session_id') === '') {
      initialLoadGuard.current = true;
      return;
    }
    if (initialLoadGuard.current) return;
    if (!user?.email || !sessions.length) return;
    
    // Set guard to true immediately to ensure this auto-load NEVER triggers again
    initialLoadGuard.current = true;
    
    const saved = localStorage.getItem('prc_session_id');
    // If a saved session preference exists (even an empty string for New Chat), respect it!
    if (saved !== null && saved !== 'null' && saved !== 'undefined') {
      return;
    }
    
    handleLoadSession(sessions[0].id);
  }, [user, sessions, handleLoadSession]);

  // ── new chat ───────────────────────────────────────────────────────────────
  const handleNewChat = useCallback(async () => {
    if (user?.email) {
      try {
        const form = new URLSearchParams({ email: user.email });
        await axios.post(`${API_URL}/api/clear-user-files`, form);
      } catch (err) {
        console.error('Failed to clear user files:', err);
      }
    }
    setSessionId('');
    localStorage.setItem('prc_session_id', '');
    setMessages([WELCOME_MSG]);
    setLastMessage(null);
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, [user]);


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
    const form = new URLSearchParams({ title: newTitle, email: user?.email || '' });
    await axios.post(`${API_URL}/api/session/${sid}/title`, form);
    await refreshSessions();
  }, [refreshSessions, user]);

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
          setSimProgress(null);
          refreshSessions();
          return;
        }
        try {
          const data = JSON.parse(e.data);
          if (data.type === 'session') {
            setSessionId(data.session_id);
            localStorage.setItem('prc_session_id', data.session_id);
          } else if (data.type === 'mode') {
            setCognitiveMode(data.text);
          } else if (data.type === 'progress') {
            const match = data.text.match(/PROGRESS:\s*(\d+)\/(\d+)/);
            if (match) {
              const current = parseInt(match[1]);
              const total = parseInt(match[2]);
              setSimProgress({ val: (current / total) * 100, text: data.text });
            } else {
              setSimProgress({ val: null, text: data.text });
            }
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
            setSimProgress(null);
            setCognitiveMode('');
            refreshSessions();
          } else if (data.type === 'error') {
            es.close();
            const isDocErr = data.msg?.toLowerCase().includes('document') || data.msg?.toLowerCase().includes('generat');
            const userMsg  = isDocErr
              ? ' Document generation paused. Please retry or request a different format.'
              : ' Analysis paused. An error occurred during processing. Please retry your query.';
            setMessages(prev => [...prev, {
              role: 'model', text: userMsg, isError: true,
              isDocEngineError: isDocErr,
            }]);
            setLoading(false);
            setUploadStatus('');
            setSimProgress(null);
            setCognitiveMode('');
            setServerStatus('offline');
          }
        } catch { /* non-JSON frame — ignore */ }
      };

      es.onerror = (err) => {
        // If we've already received text or progress, treat the drop as a likely end-of-stream.
        // SSE can terminate slightly abruptly after the last packet, which we should ignore.
        if (streamedText || (simProgress && simProgress.val > 0)) {
          es.close();
          setLoading(false);
          setUploadStatus('');
          setSimProgress(null);
          refreshSessions();
          return;
        }

        // If the browser is automatically trying to reconnect, don't show an error yet.
        if (es.readyState === EventSource.CONNECTING) {
          setServerStatus('offline'); // Show status indicator but don't inject message
          return;
        }

        // Terminal error or persistent failure
        es.close();
        setMessages(prev => [...prev, {
          role: 'model',
          text: `[!] Cannot connect to the PRC Hub backend. Port 8001 may not be running — start the backend server and retry.`,
          isError: true,
        }]);
        setLoading(false);
        setUploadStatus('');
        setSimProgress(null);
        setCognitiveMode('');
        setServerStatus('offline');
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
    // After 6s on a doc generation request, switch to the high-demand retrying indicator.
    // The backend retries Gemini up to 5 times (total ~62s) before failing.
    docRetryTimerRef.current = setTimeout(() => setDocRetrying(true), 6000);

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
          role: 'model',
          text: ` ${response.data.reply}`,
          isError: true,
          isDocEngineError: !!response.data.is_doc_error,
        }]);
      }
      await refreshSessions();
    } catch (err) {
      const isNoBackend = !err.response || err.response.status === 502 || err.response.status === 504;
      const msg = err.code === 'ECONNABORTED'
        ? ' Generation timed out. Deep analysis can take up to 4 minutes. Please try again or submit a smaller dataset.'
        : err.response?.status === 503
        ? ' Gemini is currently unavailable after 5 attempts. Please try again in a few minutes or contact PRC support.'
        : err.response?.status === 401
        ? ' Session authentication failed. Please log out and log back in.'
        : isNoBackend
        ? ' Cannot connect to the PRC Hub backend (port 8001 is not responding). Please start the backend server and retry.'
        : ' Unable to reach the PRC Hub. Please check your connection and retry.';
      setMessages(prev => [...prev, {
        role: 'model', text: msg, isError: true,
        isDocEngineError: err.response?.status === 503,
      }]);
      setServerStatus('offline');
    } finally {
      clearTimeout(docRetryTimerRef.current);
      setDocRetrying(false);
      setLoading(false);
      setUploadStatus('');
      if (retryObj) setRetryCooldown(15);
    }
  }, [input, files, sessionId, user, refreshSessions, simProgress]);

  const status = useMemo(() => ({
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
    <div className="flex h-screen w-screen bg-mesh text-slate-100 overflow-hidden relative font-sans">

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
              className="flex items-center gap-1 text-xs text-yellow-400 hover:text-yellow-300 border border-yellow-800/50 hover:border-yellow-600 px-2 py-1.5 rounded-xl transition-all"
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
            className="w-full mb-2 flex items-center justify-center gap-1.5 text-[10px] text-slate-500 hover:text-yellow-400 border border-slate-800 hover:border-yellow-800 py-1.5 rounded-xl transition-all uppercase tracking-widest font-mono"
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
        <header className="bg-gloss border-b border-white/5 px-3 md:px-4 py-3 flex items-center justify-between shrink-0 gap-2 z-10 !border-x-0 !border-t-0 !rounded-none">
          <div className="flex items-center gap-2 min-w-0">
            <button
              onClick={() => setSidebarOpen(p => !p)}
              className="p-2 hover:bg-slate-800 rounded-xl transition-colors text-slate-400 hover:text-white shrink-0"
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
                className="flex items-center gap-1.5 px-2.5 py-1.5 bg-yellow-950/20 hover:bg-yellow-900/40 border border-yellow-800/40 hover:border-yellow-600/60 text-yellow-500 hover:text-yellow-300 rounded-xl transition-all text-[10px] font-black uppercase tracking-widest disabled:opacity-30 disabled:cursor-not-allowed"
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
                className="p-2 hover:bg-yellow-950/30 text-slate-500 hover:text-amber-400 rounded-xl transition-colors"
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
                className="p-2 hover:bg-yellow-950/30 text-slate-500 hover:text-yellow-400 rounded-xl transition-colors"
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

            <main className="flex-1 min-w-0 overflow-y-auto overflow-x-hidden px-3 py-4 md:px-6 md:py-6 space-y-4">
              {messages.map((msg, idx) => (
                <div
                  key={idx}
                  className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''} max-w-5xl ${msg.role === 'user' ? 'ml-auto' : 'mr-auto'} w-full msg-bubble min-w-0`}
                  style={{ animationDelay: `${Math.min(idx, 5) * 0.1}s` }}
                >
                  {/* Avatar */}
                  <div className={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 border
                    ${msg.role === 'user'
                      ? 'bg-slate-800 border-slate-700'
                      : 'bg-yellow-950 border-yellow-800/50'}`}
                  >
                    {msg.role === 'user'
                      ? <User className="w-3.5 h-3.5 text-slate-300" />
                      : <Bot  className="w-3.5 h-3.5 text-yellow-400" />}
                  </div>

                  {/* Bubble */}
                  <div className={`px-4 py-3.5 text-sm md:text-[15px] leading-relaxed shadow-xl w-full max-w-[85%] min-w-0 break-words transition-all
                    ${msg.role === 'user'
                      ? 'bg-slate-800/85 backdrop-blur-sm text-slate-200 rounded-2xl rounded-tr-none border border-slate-700/40 shadow-black/40'
                      : 'bg-[#0e0e12]/95 backdrop-blur-sm text-yellow-50/95 rounded-2xl rounded-tl-none border border-yellow-900/20 shadow-black/60 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)]'}`}
                  >
                    {msg.fileName && (
                      <div className="flex items-center gap-2 mb-2 bg-black/40 p-2 rounded-xl border border-slate-700/50 w-fit">
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
                        className="mt-3 w-full bg-gradient-to-r from-yellow-900/40 to-amber-900/30 hover:from-yellow-800/50 hover:to-amber-800/40 border border-yellow-600/50 text-yellow-200 font-bold tracking-widest uppercase px-4 py-3 rounded-xl flex items-center justify-center gap-2 text-xs transition-all active:scale-95 disabled:opacity-30 shadow-lg"
                      >
                        {loading ? <Loader className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
                        {loading ? 'GENERATING REPORT' : 'EXPORT AS PRC REPORT'}
                      </button>
                    )}

                    {/* Download button */}
                    {msg.download_url && (
                      <button
                        onClick={() => window.open(`${API_URL}${msg.download_url}`, '_self')}
                        className="mt-4 w-full bg-yellow-600/20 hover:bg-yellow-600/40 border border-yellow-500/50 text-yellow-300 font-bold tracking-widest uppercase px-4 py-3 rounded-xl flex items-center justify-center gap-2 text-xs transition-all active:scale-95"
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
                        className="mt-3 w-full bg-yellow-600/20 hover:bg-yellow-600/35 border border-yellow-500/50 text-yellow-300 font-bold tracking-widest uppercase text-[10px] py-2.5 rounded-xl flex items-center justify-center gap-2 transition-all active:scale-95 disabled:opacity-30"
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
                        className="mt-3 w-full bg-amber-950/20 hover:bg-amber-950/40 border border-amber-600/50 text-amber-300 font-bold tracking-widest uppercase text-[10px] py-2.5 rounded-xl flex items-center justify-center gap-2 transition-all active:scale-95 disabled:opacity-30"
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
                <div className="flex gap-3 max-w-5xl w-full">
                  <div className="w-8 h-8 rounded-xl flex items-center justify-center shrink-0 bg-yellow-950 border border-yellow-800/50">
                    <Bot className="w-3.5 h-3.5 text-yellow-400" />
                  </div>
                  <div className="bg-[#111116] px-4 py-3 rounded-xl border border-yellow-900/30 flex flex-col gap-2 min-w-[200px]">
                    {simProgress ? (
                      <>
                        <div className="flex justify-between items-center gap-4">
                          <div className="flex items-center gap-2">
                            <Activity className="w-3.5 h-3.5 text-yellow-500 animate-pulse" />
                            <span className="text-[10px] text-yellow-500 font-black uppercase tracking-widest">
                              {cognitiveMode || 'Simulation in Progress'}
                            </span>
                          </div>
                          <span className="text-[10px] text-slate-500 font-mono">
                            {simProgress.val !== null ? `${Math.round(simProgress.val)}%` : '...'}
                          </span>
                        </div>
                        <div className="w-full h-1 bg-slate-800 rounded-xl overflow-hidden">
                          <div 
                            className="h-full bg-yellow-500 transition-all duration-300 ease-out shadow-[0_0_8px_rgba(234,179,8,0.5)]"
                            style={{ width: `${simProgress.val ?? 0}%` }}
                          />
                        </div>
                        <span className="text-[9px] text-slate-400 font-mono truncate italic opacity-70">
                          {simProgress.text}
                        </span>
                      </>
                    ) : uploadStatus === 'uploading' ? (
                      <div className="flex items-center gap-2 py-1">
                        <Upload className="w-4 h-4 text-yellow-500 animate-bounce shrink-0" />
                        <span className="text-[11px] text-yellow-300 font-mono tracking-widest uppercase font-bold">Transferring Data Packets</span>
                      </div>
                    ) : docRetrying ? (
                      <div className="flex flex-col gap-2 py-1">
                        <div className="flex items-center gap-2">
                          <Loader className="w-3.5 h-3.5 text-amber-400 animate-spin shrink-0" />
                          <span className="text-[10px] text-amber-300 font-mono tracking-widest uppercase font-bold">Gemini Under High Demand — Retrying Automatically...</span>
                        </div>
                        <span className="text-[9px] text-slate-400 font-mono italic">Up to 5 attempts. Please do not close this tab.</span>
                      </div>
                    ) : (
                      <div className="flex flex-col gap-3 py-1">
                        {cognitiveMode && (
                          <div className="flex items-center gap-2 bg-yellow-500/10 px-2 py-1 border border-yellow-500/20 w-fit">
                            <Layers className="w-3 h-3 text-yellow-500 animate-pulse" />
                            <span className="text-[9px] text-yellow-400 font-black uppercase tracking-[0.2em]">{cognitiveMode}</span>
                          </div>
                        )}
                        <div className="flex items-center gap-2">
                          <div className="flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 bg-yellow-500 rounded-xl animate-bounce" />
                            <span className="w-1.5 h-1.5 bg-yellow-500 rounded-xl animate-bounce [animation-delay:0.2s]" />
                            <span className="w-1.5 h-1.5 bg-yellow-500 rounded-xl animate-bounce [animation-delay:0.4s]" />
                          </div>
                          {!cognitiveMode && <span className="text-[10px] text-slate-500 font-mono uppercase tracking-widest ml-2 italic">Thinking...</span>}
                        </div>
                      </div>
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
                    <div key={i} className="flex items-center gap-2 bg-yellow-950/20 border border-yellow-500/20 rounded-full px-3 py-2 shadow-inner">
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
                <div className="absolute -inset-1 bg-gradient-to-r from-yellow-500/20 to-amber-500/20 rounded-[2.1rem] blur opacity-0 group-focus-within:opacity-100 transition-all duration-700" />
                <div className="relative flex items-center gap-3 bg-[#07070a]/90 backdrop-blur-md border border-slate-800 rounded-[2rem] p-2 pl-4 group-focus-within:border-yellow-500/50 transition-all shadow-2xl">
                  <label className="cursor-pointer shrink-0 p-2 hover:bg-yellow-500/10 rounded-full transition-all hover:scale-110 active:scale-95 group">
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
                    className={`bg-gradient-to-br from-yellow-500 to-amber-600 hover:from-yellow-400 hover:to-amber-500 text-black p-3.5 rounded-full shrink-0 transition-all active:scale-90 disabled:opacity-30 disabled:cursor-not-allowed shadow-[0_0_20px_rgba(234,179,8,0.3)] hover:shadow-[0_0_25px_rgba(234,179,8,0.5)] ${loading ? 'btn-streaming' : ''}`}
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
          <div className="flex-1 flex flex-col items-center justify-center bg-mesh text-slate-500 p-8 text-center relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-br from-yellow-500/5 to-transparent pointer-events-none" />
            <div className="p-10 rounded-[2.5rem] bg-gloss border border-white/5 max-w-md space-y-6 shadow-2xl relative z-10 hover:scale-[1.01] transition-all duration-500">
              <div className="w-16 h-16 rounded-[1.25rem] bg-yellow-500/10 border border-yellow-500/20 flex items-center justify-center text-yellow-500 mx-auto shadow-[0_0_30px_rgba(234,179,8,0.15)] animate-pulse-slow">
                <BookOpen className="w-8 h-8" />
              </div>
              <div className="space-y-2">
                <h3 className="text-sm font-black text-white uppercase tracking-[0.25em] italic">Knowledge Reference Portal</h3>
                <p className="text-[11px] text-slate-400 font-mono uppercase tracking-widest leading-relaxed">
                  Use the Sidebar Library Tab to ingest, manage, and audit proprietary geological database shards.
                </p>
              </div>
              <div className="w-full h-px bg-slate-800/80" />
              <div className="flex items-center justify-center gap-6 text-[9px] text-slate-600 font-mono uppercase tracking-widest">
                <span>PDF Ingestion</span>
                <span>•</span>
                <span>DOCX Extraction</span>
                <span>•</span>
                <span>Structured DB</span>
              </div>
            </div>
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
