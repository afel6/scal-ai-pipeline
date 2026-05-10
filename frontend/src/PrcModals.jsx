import React, { useState, useEffect } from 'react';
import { X, Bug, Shield, FileText } from 'lucide-react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '';

// ── FEEDBACK MODAL ──
export function FeedbackModal({ userEmail, onClose }) {
  const [report, setReport] = useState('');
  const [sent, setSent] = useState(false);
  const submit = async () => {
    if (!report.trim()) return;
    const fd = new FormData();
    fd.append('user_email', userEmail || '');
    fd.append('bug_report', report);
    try { await axios.post(API_URL + '/api/feedback', fd); setSent(true); } catch {}
  };
  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#111116] border border-yellow-900/40 rounded-2xl p-6 max-w-md w-full shadow-2xl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <div className="flex items-center gap-2"><Bug className="w-5 h-5 text-yellow-400" /><h3 className="text-yellow-50 font-bold tracking-widest uppercase text-sm">Report Bug / Feedback</h3></div>
          <button onClick={onClose}><X className="w-4 h-4 text-slate-500 hover:text-white" /></button>
        </div>
        {sent ? (
          <p className="text-green-400 text-sm text-center py-8 font-mono">Thank you! Your feedback has been submitted.</p>
        ) : (
          <>
            <textarea value={report} onChange={e => setReport(e.target.value)} rows={5} placeholder="Describe the issue or suggestion..." className="w-full bg-black/50 border border-slate-700 rounded-xl p-3 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-yellow-600 resize-none" />
            <button onClick={submit} disabled={!report.trim()} className="mt-3 w-full bg-yellow-600 hover:bg-yellow-500 text-black font-bold py-2.5 rounded-xl text-xs uppercase tracking-widest disabled:opacity-30 transition-all">Submit Feedback</button>
          </>
        )}
      </div>
    </div>
  );
}

// ── PRIVACY POLICY MODAL ──
export function PrivacyModal({ onClose }) {
  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#111116] border border-yellow-900/40 rounded-2xl p-6 max-w-lg w-full shadow-2xl max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <div className="flex items-center gap-2"><Shield className="w-5 h-5 text-yellow-400" /><h3 className="text-yellow-50 font-bold tracking-widest uppercase text-sm">Privacy Policy</h3></div>
          <button onClick={onClose}><X className="w-4 h-4 text-slate-500 hover:text-white" /></button>
        </div>
        <div className="text-slate-300 text-xs space-y-3 font-serif leading-relaxed">
          <p><strong>Last Updated:</strong> May 2026</p>
          <p>PRC SCAL AI Pipeline ("Hviel") is developed and operated by SCAL AI Solutions for the Petroleum Research Center. This policy describes how we collect, use, and protect your information.</p>
          <p><strong>1. Data Collection:</strong> We collect your name, email address, and chat session data to provide personalized AI assistance and track productivity.</p>
          <p><strong>2. Data Usage:</strong> Your data is used exclusively for: (a) Providing AI petrophysical analysis, (b) Generating reports and documents, (c) Improving the system through analytics, (d) Tracking user productivity metrics.</p>
          <p><strong>3. Data Storage:</strong> All data is stored securely on encrypted servers. Chat histories are retained for operational continuity and audit purposes.</p>
          <p><strong>4. Data Sharing:</strong> We do not sell or share your personal data with third parties. Data may be shared with PRC management for productivity reporting.</p>
          <p><strong>5. Your Rights:</strong> You may request data deletion by contacting the system administrator.</p>
          <p><strong>6. Security:</strong> We implement industry-standard security measures including encrypted connections and access controls.</p>
          <p><strong>Contact:</strong> For privacy inquiries, contact your PRC system administrator.</p>
        </div>
      </div>
    </div>
  );
}

// ── TERMS OF SERVICE MODAL ──
export function TermsModal({ onClose }) {
  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#111116] border border-yellow-900/40 rounded-2xl p-6 max-w-lg w-full shadow-2xl max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <div className="flex items-center gap-2"><FileText className="w-5 h-5 text-yellow-400" /><h3 className="text-yellow-50 font-bold tracking-widest uppercase text-sm">Terms of Service</h3></div>
          <button onClick={onClose}><X className="w-4 h-4 text-slate-500 hover:text-white" /></button>
        </div>
        <div className="text-slate-300 text-xs space-y-3 font-serif leading-relaxed">
          <p><strong>Last Updated:</strong> May 2026</p>
          <p>By accessing the PRC SCAL AI Pipeline, you agree to the following terms:</p>
          <p><strong>1. Authorized Use:</strong> This system is provided exclusively for authorized PRC personnel and partners. Unauthorized access is prohibited.</p>
          <p><strong>2. AI-Generated Content:</strong> Hviel provides AI-assisted analysis. All outputs should be reviewed and validated by qualified engineers before use in critical decisions.</p>
          <p><strong>3. Data Responsibility:</strong> Users are responsible for the accuracy of uploaded data. Do not upload classified or restricted materials beyond the designated security clearance.</p>
          <p><strong>4. Intellectual Property:</strong> Reports and analyses generated through this system are the property of the Petroleum Research Center.</p>
          <p><strong>5. Availability:</strong> We strive for continuous availability but do not guarantee uninterrupted service. Scheduled maintenance may occur.</p>
          <p><strong>6. Liability:</strong> SCAL AI Solutions is not liable for decisions made based on AI-generated outputs. Professional engineering judgment must always prevail.</p>
          <p><strong>7. Account Security:</strong> Users must protect their credentials and report any suspected unauthorized access immediately.</p>
        </div>
      </div>
    </div>
  );
}

// ── COOKIE CONSENT BANNER ──
export function CookieConsent() {
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (!localStorage.getItem('prc_cookie_consent')) setShow(true);
  }, []);
  if (!show) return null;
  return (
    <div className="fixed bottom-0 left-0 right-0 bg-[#111116] border-t border-yellow-900/40 p-4 z-50 flex flex-col sm:flex-row items-center justify-between gap-3">
      <p className="text-xs text-slate-400 font-serif">This application uses cookies and local storage to maintain your session and preferences. By continuing, you consent to our use of cookies.</p>
      <div className="flex gap-2 shrink-0">
        <button onClick={() => { localStorage.setItem('prc_cookie_consent', 'true'); setShow(false); }} className="bg-yellow-600 hover:bg-yellow-500 text-black font-bold px-4 py-2 rounded-lg text-xs uppercase tracking-widest transition-all">Accept</button>
        <button onClick={() => setShow(false)} className="border border-slate-700 text-slate-400 hover:text-white px-4 py-2 rounded-lg text-xs uppercase tracking-widest transition-all">Dismiss</button>
      </div>
    </div>
  );
}

// ── ADMIN LOGIN MODAL ──
export function AdminLoginModal({ isOpen, onLogin, onClose }) {
  const [pin, setPin] = useState('');
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async () => {
    setLoading(true);
    setError(false);
    const success = await onLogin(pin);
    if (!success) {
      setError(true);
      setPin('');
    }
    setLoading(false);
  };

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-[100] flex items-center justify-center p-4">
      <div className="bg-[#0a0a0c] border border-amber-900/40 rounded-3xl p-8 max-w-sm w-full shadow-[0_0_50px_-12px_rgba(245,158,11,0.2)]">
        <div className="flex flex-col items-center mb-8">
          <div className="w-16 h-16 bg-amber-500/10 rounded-2xl flex items-center justify-center border border-amber-500/20 mb-4">
            <Shield className="w-8 h-8 text-amber-500" />
          </div>
          <h2 className="text-xl font-black text-white tracking-tight">Admin Vault</h2>
          <p className="text-[10px] text-slate-500 font-mono tracking-[0.2em] uppercase mt-1">Authorized Access Only</p>
        </div>

        <div className="space-y-6">
          <div className="space-y-2">
            <input
              type="password"
              value={pin}
              onChange={e => { setPin(e.target.value); setError(false); }}
              onKeyDown={e => e.key === 'Enter' && pin && handleSubmit()}
              placeholder="Enter Admin PIN"
              autoFocus
              className={`w-full bg-black/40 border ${error ? 'border-red-500/50' : 'border-white/[0.06]'} rounded-xl px-4 py-3.5 text-center text-lg font-mono tracking-[0.5em] text-white outline-none focus:border-amber-500/50 transition-all`}
            />
            {error && <p className="text-[10px] text-red-400 font-bold uppercase tracking-widest text-center">Invalid Credentials</p>}
          </div>

          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="flex-1 bg-white/[0.03] hover:bg-white/[0.08] text-slate-400 font-bold py-3.5 rounded-xl text-[10px] uppercase tracking-[0.2em] transition-all"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={!pin || loading}
              className="flex-[2] bg-amber-500 hover:bg-amber-400 text-black font-black py-3.5 rounded-xl text-[10px] uppercase tracking-[0.2em] transition-all disabled:opacity-30 disabled:grayscale"
            >
              {loading ? 'Verifying...' : 'Unlock Vault'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── ANALYTICS TRACKER ──
export function trackEvent(userEmail, eventType, eventData = '') {
  const fd = new FormData();
  fd.append('user_email', userEmail || '');
  fd.append('event_type', eventType);
  fd.append('event_data', eventData);
  axios.post(API_URL + '/api/analytics/event', fd).catch(() => {});
}
