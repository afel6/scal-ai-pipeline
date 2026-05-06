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

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function PetrophysicalTable({ content }) {
  try {
    const data = JSON.parse(content);
    const headers = data.headers || Object.keys(data.rows[0] || {});
    return (
      <div className="my-6 overflow-hidden rounded-2xl border border-yellow-900/40 bg-[#0c0c10] shadow-2xl">
        <div className="bg-gradient-to-r from-yellow-950/40 to-black px-4 py-3 border-b border-yellow-900/30 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Database className="w-4 h-4 text-yellow-500" />
            <span className="text-[11px] font-black tracking-[0.2em] text-yellow-50/90 uppercase">V-Table Ingestion Preview</span>
          </div>
          <div className="text-[10px] text-slate-500 font-mono italic">
            Total Samples: {data.rows.length}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse min-w-[600px]">
            <thead>
              <tr className="bg-yellow-950/10">
                {headers.map((h, i) => (
                  <th key={i} className="px-4 py-3 text-[10px] font-bold text-yellow-600 uppercase tracking-widest border-b border-yellow-900/20">
                    {h.replace(/_/g, ' ')}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-yellow-900/10">
              {data.rows.slice(0, 10).map((row, i) => {
                const values = Array.isArray(row) ? row : headers.map(h => row[h]);
                return (
                  <tr key={i} className="hover:bg-yellow-900/5 transition-colors group">
                    {values.map((v, j) => (
                      <td key={j} className={`px-4 py-3 text-xs font-serif ${v === null || v === 'NaN' || v === 'nan' ? 'text-slate-700 italic' : 'text-slate-300'}`}>
                        {v === null || v === 'NaN' || v === 'nan' ? 'â€”' : (typeof v === 'number' ? v.toFixed(3) : v)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {data.rows.length > 10 && (
            <div className="p-3 bg-black/40 text-center border-t border-yellow-900/10">
              <p className="text-[10px] text-slate-500 font-mono italic uppercase tracking-widest">+ {data.rows.length - 10} additional samples available in full export</p>
            </div>
          )}
        </div>
      </div>
    );
  } catch (err) {
    return <div className="p-4 bg-red-950/20 border border-red-900/50 text-red-400 text-xs font-mono">Invalid Data Format: {err.message}</div>;
  }
}

// Splits a message into text, embedded charts, mermaid diagrams, and audit logs
function renderMessageContent(text) {
  if (!text) return null;
  // Match markdown images: ![alt](src) â€” supports data URIs and http URLs
  const imgRegex = /!\[([^\]]*)\]\((data:[^)]+|https?:[^)]+)\)/g;
  const parts = [];
  let lastIndex = 0;
  let match;
  while ((match = imgRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'text', content: text.slice(lastIndex, match.index) });
    }
    parts.push({ type: 'img', alt: match[1], src: match[2] });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push({ type: 'text', content: text.slice(lastIndex) });
  }

  // Chain of parsers: Mermaid -> Audit -> Data
  const mermaidParts = [];
  parts.forEach(p => {
    if (p.type === 'text') {
      const merRegex = /__MERMAID_START__([\s\S]*?)__MERMAID_END__/g;
      let lastMIndex = 0;
      let mMatch;
      while ((mMatch = merRegex.exec(p.content)) !== null) {
        if (mMatch.index > lastMIndex) mermaidParts.push({ type: 'text', content: p.content.slice(lastMIndex, mMatch.index) });
        mermaidParts.push({ type: 'mermaid', content: mMatch[1].trim() });
        lastMIndex = mMatch.index + mMatch[0].length;
      }
      if (lastMIndex < p.content.length) mermaidParts.push({ type: 'text', content: p.content.slice(lastMIndex) });
    } else mermaidParts.push(p);
  });

  const auditParts = [];
  mermaidParts.forEach(p => {
    if (p.type === 'text') {
      const auditRegex = /__AUDIT_LOG_START__([\s\S]*?)__AUDIT_LOG_END__/g;
      let lastAIndex = 0;
      let aMatch;
      while ((aMatch = auditRegex.exec(p.content)) !== null) {
        if (aMatch.index > lastAIndex) auditParts.push({ type: 'text', content: p.content.slice(lastAIndex, aMatch.index) });
        auditParts.push({ type: 'audit', content: aMatch[1].trim() });
        lastAIndex = aMatch.index + aMatch[0].length;
      }
      if (lastAIndex < p.content.length) auditParts.push({ type: 'text', content: p.content.slice(lastAIndex) });
    } else auditParts.push(p);
  });

  const finalParts = [];
  auditParts.forEach(p => {
    if (p.type === 'text') {
      const dataRegex = /__PRC_DATA_START__([\s\S]*?)__PRC_DATA_END__/g;
      let lastDIndex = 0;
      let dMatch;
      while ((dMatch = dataRegex.exec(p.content)) !== null) {
        if (dMatch.index > lastDIndex) finalParts.push({ type: 'text', content: p.content.slice(lastDIndex, dMatch.index) });
        finalParts.push({ type: 'data', content: dMatch[1].trim() });
        lastDIndex = dMatch.index + dMatch[0].length;
      }
      if (lastDIndex < p.content.length) finalParts.push({ type: 'text', content: p.content.slice(lastDIndex) });
    } else finalParts.push(p);
  });

  const simParts = [];
  finalParts.forEach(p => {
    if (p.type === 'text') {
      const simRegex = /__SIMULATION_START__([\s\S]*?)__SIMULATION_END__/g;
      let lastSIndex = 0;
      let sMatch;
      while ((sMatch = simRegex.exec(p.content)) !== null) {
        if (sMatch.index > lastSIndex) simParts.push({ type: 'text', content: p.content.slice(lastSIndex, sMatch.index) });
        simParts.push({ type: 'simulation', content: sMatch[1].trim() });
        lastSIndex = sMatch.index + sMatch[0].length;
      }
      if (lastSIndex < p.content.length) simParts.push({ type: 'text', content: p.content.slice(lastSIndex) });
    } else simParts.push(p);
  });

  // Parse __PRC_PLOT__ JSON blocks into interactive charts
  const plotParts = [];
  simParts.forEach(p => {
    if (p.type === 'text') {
      // Match either __PRC_PLOT__ token followed by JSON, or raw JSON with "curves" key
      const plotRegex = /(?:__PRC_PLOT__\s*)?({\s*"curves"[\s\S]*?}(?=\s*(?:__|$|\n\n)))/g;
      let lastPIndex = 0;
      let pMatch;
      while ((pMatch = plotRegex.exec(p.content)) !== null) {
        if (pMatch.index > lastPIndex) plotParts.push({ type: 'text', content: p.content.slice(lastPIndex, pMatch.index) });
        plotParts.push({ type: 'plot', content: pMatch[1].trim() });
        lastPIndex = pMatch.index + pMatch[0].length;
      }
      if (lastPIndex < p.content.length) plotParts.push({ type: 'text', content: p.content.slice(lastPIndex) });
    } else plotParts.push(p);
  });

  if (plotParts.length === 0) return <p className="whitespace-pre-wrap font-serif leading-[1.75]">{text}</p>;
  return plotParts.map((part, i) => {
    if (part.type === 'img') return <img key={i} src={part.src} alt={part.alt || 'PRC Chart'} className="w-full rounded-xl border border-yellow-900/30 my-3 shadow-lg" />;
    if (part.type === 'mermaid') return <Mermaid key={i} content={part.content} />;
    if (part.type === 'data') return <PetrophysicalTable key={i} content={part.content} />;
    if (part.type === 'simulation') return <SimulationHeatmap key={i} content={part.content} />;
    if (part.type === 'plot') return <KrPlot key={i} content={part.content} />;
    if (part.type === 'audit') return (
      <div key={i} className="my-4 p-4 bg-yellow-950/20 border-l-4 border-yellow-600 rounded-r-xl shadow-inner font-mono text-[13px] text-yellow-100/90">
        <div className="flex items-center gap-2 mb-2 text-yellow-500 font-black tracking-widest text-[10px] uppercase">
          <Database className="w-3 h-3" /> Engineering Audit Ledger
        </div>
        <div className="whitespace-pre-wrap leading-relaxed opacity-80">{part.content}</div>
      </div>
    );
    return part.content.trim() ? <p key={i} className="whitespace-pre-wrap font-serif leading-[1.75]">{part.content}</p> : null;
  });
}

const WELCOME_MSG = { role: 'model', text: 'Hello, I am Hviel — your dedicated PRC Senior AI Petrophysical Specialist.\n\nI have been trained on the PRC petroleum engineering library and am ready to assist with SCAL analysis, petrophysical interpretation, and professional report generation.\n\nPlease state your Well Name, paste lab data, or attach Word, Excel, or PDF files to begin.' };

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
      const { data } = await axios.get(`${API_URL}/api/sessions`);
      setSessions(data);
    } catch {}
  }, []);

  useEffect(() => {
    refreshSessions();
    // Poll every 8s instead of 5s â€” reduces server overhead by 37%
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

    // â”€â”€ Smart Route Logic â”€â”€
    // Bug fix: added 'plot','chart','graph','curve','generate' so visualization
    // requests correctly route to the Document Engine (not SSE which can't handle them)
    const triggerWords = ['document', 'report', 'excel', 'word', 'docx', 'xlsx',
      'spreadsheet', 'matrix', 'download', 'plot', 'chart', 'graph', 'curve', 'generate'];
    const isDocRequest = triggerWords.some(w => msgText.toLowerCase().includes(w));

    // â”€â”€ SSE Streaming path: plain text, no files, no document generation requests â”€â”€
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
                // First token â€” append a new bubble
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
              text: `âŒ ${data.msg}`,
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
          // We got a partial response â€” the SSE just closed cleanly
          es.close();
          setLoading(false);
          setUploadStatus('');
          refreshSessions();
        } else {
          es.close();
          setMessages(prev => [...prev, { role: 'model', text: 'âŒ Connection error. I am unable to reach the PRC Hub at this moment.', isError: true }]);
          setLoading(false);
          setUploadStatus('');
          setServerStatus('offline');
        }
      };
      return;
    }

    // â”€â”€ Blocking POST path: files or retries â”€â”€
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
        setMessages(prev => [...prev, { role: 'model', text: `âŒ ${response.data.reply}`, isError: true }]);
      }
      await refreshSessions();
    } catch (err) {
      if (err.code === 'ECONNABORTED') {
        setMessages(prev => [...prev, { role: 'model', text: 'âŒ Generation timed out. Deep AI analysis or massive document generation can take up to 4 minutes. Please try again or submit a smaller dataset.', isError: true }]);
      } else {
        setMessages(prev => [...prev, { role: 'model', text: 'âŒ Connection error. I am unable to reach the PRC Hub at this moment.', isError: true }]);
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

  // Hoisted outside render cycle via useMemo â€” avoids object recreation on every render (Vercel perf skill)
  const status = React.useMemo(() => ({
    waking:  { icon: <Loader className="w-3 h-3 animate-spin" />, text: 'Connecting...', color: 'text-yellow-500' },
    online:  { icon: <Circle className="w-2 h-2 fill-green-500" />, text: 'Online',   color: 'text-green-400' },
    offline: { icon: <WifiOff className="w-3 h-3" />, text: 'Reconnecting...', color: 'text-red-400' },
  })[serverStatus], [serverStatus]);

  if (!user) {
    return <Login onLogin={(u) => {
      localStorage.setItem('prc_user', JSON.stringify(u));
      setUser(u);
    }} />;
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
              placeholder="••••"
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

        {/* Tabs + Session list + Library â€” handled by SidebarTabs */}
        <SidebarTabs 
          sessionId={sessionId} 
          sessions={sessions} 
          handleLoadSession={handleLoadSession} 
          handleDeleteSession={handleDeleteSession} 
          tab={activeTab}
          setTab={setActiveTab}
        />

        <div className="p-4 border-t border-slate-800/60 shrink-0">
          <button onClick={() => setShowFeedback(true)} className="w-full mb-2 flex items-center justify-center gap-1.5 text-[10px] text-slate-500 hover:text-yellow-400 border border-slate-800 hover:border-yellow-800 py-1.5 rounded-lg transition-all uppercase tracking-widest font-mono"><span>Report Bug</span></button><p className="text-[10px] text-slate-700 font-mono tracking-widest uppercase text-center">Petroleum Research Center · Libya</p>
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
                <p className="text-xs text-yellow-400/80">Waking up the AI server â€” please wait ~30 secondsâ€¦</p>
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
                    {renderMessageContent(msg.text)}
                    {msg.role === 'model' && !msg.download_url && msg.text?.includes('data:image/png;base64,') && (
                      <button
                        onClick={() => handleSend({ text: 'generate document', files: [] })}
                        disabled={loading}
                        className="mt-3 w-full bg-gradient-to-r from-yellow-900/40 to-amber-900/30 hover:from-yellow-800/50 hover:to-amber-800/40 border border-yellow-600/50 text-yellow-200 font-bold tracking-widest uppercase px-4 py-3 rounded-xl flex items-center justify-center gap-2 text-xs transition-all active:scale-95 disabled:opacity-30 shadow-lg"
                      >
                        {loading ? <Loader className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
                        {loading ? 'GENERATING REPORTâ€¦' : 'EXPORT AS PRC REPORT'}
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
                        {loading ? 'GENERATINGâ€¦' : 'GENERATE CHART / DOCUMENT'}
                      </button>
                    )}
                    {msg.isError && !msg.isDocEngineError && lastMessage && (
                      <button onClick={() => handleSend(lastMessage)} disabled={loading || retryCooldown > 0}
                        className="mt-3 w-full bg-amber-950/20 hover:bg-amber-950/40 border border-amber-600/50 text-amber-300 font-bold tracking-widest uppercase text-[10px] py-2.5 rounded-lg flex items-center justify-center gap-2 transition-all active:scale-95 disabled:opacity-30">
                        {loading ? <Loader className="w-3 h-3 animate-spin" /> : <Wifi className="w-3 h-3 text-yellow-500" />}
                        {loading ? 'RETRYING...' : retryCooldown > 0 ? `RE-TRY IN ${retryCooldown}sâ€¦` : 'RE-TRY REQUEST'}
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
                        <span className="text-sm text-yellow-300/80 font-serif">Uploading fileâ€¦</span>
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
              {/* File chips */}
              {files.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-2">
                  {files.map((f, i) => (
                    <div key={i} className="flex items-center gap-1.5 bg-yellow-950/30 border border-yellow-800/40 rounded-xl px-3 py-1.5">
                      <FileText className="w-3 h-3 text-yellow-400 shrink-0" />
                      <span className="text-xs font-mono text-yellow-300 truncate max-w-[140px]">{f.name}</span>
                      <button onClick={() => setFiles(prev => prev.filter((_, idx) => idx !== i))} className="ml-1 text-slate-500 hover:text-red-400">
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <div className="flex items-center gap-2 bg-[#111116] border border-slate-800 rounded-2xl p-2 pl-4 focus-within:border-yellow-500/40 transition-all">
                <label className="cursor-pointer shrink-0 p-1.5 hover:bg-slate-800 rounded-xl transition-colors">
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
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (input.trim() || files.length > 0) handleSend(); } }}
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
          </>
        ) : activeTab === 'audit' ? (
          <VisualAudit />
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center bg-[#0c0c10] text-slate-600">
            <BookOpen className="w-12 h-12 mb-4 opacity-20" />
            <p className="text-sm font-mono tracking-widest uppercase opacity-40">Library Mode â€” Use Sidebar to Manage Data</p>
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

function Login({ onLogin }) {
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');

  const handleAuth = () => {
    if (id === '1509') {
      const fd = new FormData(); fd.append('email', email); fd.append('name', name);
      fetch((import.meta.env.VITE_API_URL || 'http://localhost:8000') + '/api/register', {method:'POST', body: fd}).catch(()=>{});
      onLogin({ name, id, email });
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
              <label className="text-[10px] font-bold text-slate-400 uppercase tracking-widest ml-2">Email Address</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && name && email && id && handleAuth()}
                placeholder="e.g. ahmed@prc.ly" className="auth-input" />
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-bold text-slate-400 uppercase tracking-widest ml-2">PRC Access Code</label>
              <input type="password" value={id} onChange={(e) => { setId(e.target.value); setError(''); }}
                onKeyDown={(e) => e.key === 'Enter' && name && id && handleAuth()}
                placeholder="Enter Access Code" className="auth-input" />
            </div>
          </div>
          {error && <p className="text-yellow-500 text-[10px] text-center font-bold tracking-widest uppercase">{error}</p>}
                    <button onClick={handleAuth} disabled={!name || !id || !email} className="auth-button">
            Authenticate Session
          </button>
          
          <div className="flex justify-center gap-4 mt-6 text-[10px] text-slate-500 font-mono tracking-widest uppercase">
            <button onClick={() => setShowPrivacy(true)} className="hover:text-yellow-500 transition-colors">Privacy Policy</button>
            <span className="opacity-30">|</span>
            <button onClick={() => setShowTerms(true)} className="hover:text-yellow-500 transition-colors">Terms of Service</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;








