/* eslint-disable no-unused-vars */
import React, { useState } from 'react';

export default function Login({ onLogin, setShowPrivacy, setShowTerms }) {
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');

  const handleAuth = async () => {
    if (!id || !name || !email) return;
    setError('');
    
    try {
      const fd = new FormData();
      fd.append('pin', id);
      const resp = await fetch((import.meta.env.VITE_API_URL || '') + '/api/auth', {
        method: 'POST',
        body: fd
      });
      
      if (resp.ok) {
        // Track login event
        const regFd = new FormData();
        regFd.append('email', email);
        regFd.append('name', name);
        fetch((import.meta.env.VITE_API_URL || '') + '/api/register', {method:'POST', body: regFd}).catch(()=>{});
        
        onLogin({ name, id, email });
      } else {
        setError('Invalid MFA Credentials. Access Denied.');
        setId('');
      }
    } catch (err) {
      setError('Connection to PRC Hub failed. Please check network.');
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
          <div className="bg-white/95 p-5 rounded-2xl shadow-2xl shadow-yellow-900/20 mb-6 border border-white/10 hover:scale-[1.04] transition-all duration-500">
            <img src="/prc_logo.jpg" alt="PRC Logo" className="w-40 h-auto object-contain rounded-lg" />
          </div>
          <h1 className="text-xl font-black tracking-widest text-white uppercase italic text-center">Hviel | PRC AI Hub</h1>
          <p className="text-slate-500 text-xs mt-2 font-mono tracking-widest uppercase text-center animate-pulse-slow">Senior AI Petrophysical Specialist</p>
        </div>

        {/* Form */}
        <div className="p-6 bg-gloss rounded-3xl border border-white/5 space-y-5 shadow-2xl backdrop-blur-3xl shadow-black/80">
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-[10px] font-bold text-slate-400 uppercase tracking-widest ml-2">Full Name & Profession</label>
              <input 
                type="text" 
                value={name} 
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && name && id && handleAuth()}
                placeholder="e.g. Eng. Ahmed Al-Lafi" 
                className="auth-input" 
              />
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-bold text-slate-400 uppercase tracking-widest ml-2">Email Address</label>
              <input 
                type="email" 
                value={email} 
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && name && email && id && handleAuth()}
                placeholder="e.g. ahmed@prc.ly" 
                className="auth-input" 
              />
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-bold text-slate-400 uppercase tracking-widest ml-2">PRC Access Code</label>
              <input 
                type="password" 
                value={id} 
                onChange={(e) => { setId(e.target.value); setError(''); }}
                onKeyDown={(e) => e.key === 'Enter' && name && id && handleAuth()}
                placeholder="Enter Access Code" 
                className="auth-input" 
              />
            </div>
          </div>
          
          {error && <p className="text-yellow-500 text-[10px] text-center font-bold tracking-widest uppercase">{error}</p>}

          <button 
            onClick={handleAuth} 
            disabled={!name || !id || !email} 
            className="auth-button"
          >
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
