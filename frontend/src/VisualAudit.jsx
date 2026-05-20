// frontend/src/VisualAudit.jsx
// PRC-HUB-VER-15-PROD-READY | 2026-05-10
// Changes: Fixed syntax errors in conditional rendering · Hardened for tool output

/* eslint-disable no-unused-vars */
import React, { useState, useRef, useEffect } from 'react';
import { Camera, Upload, ShieldCheck, AlertTriangle, ArrowRight, Loader, Zap, CheckCircle, Crosshair, Search, PlusCircle } from 'lucide-react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '';

const ScannerLine = () => (
  <div className="absolute inset-0 pointer-events-none z-10 overflow-hidden rounded-[2rem]">
    <div className="absolute top-0 left-0 w-full h-[2px] bg-gradient-to-r from-transparent via-yellow-500 to-transparent shadow-[0_0_15px_rgba(234,179,8,0.8)] animate-scanner-down" />
    <div className="absolute inset-0 bg-gradient-to-b from-yellow-500/5 to-transparent opacity-20 animate-pulse-slow" />
  </div>
);

export default function VisualAudit({ content }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [query, setQuery] = useState('Verify this equipment setup against its manual.');
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState(content || '');
  const [scanProgress, setScanProgress] = useState(0);
  const fileInputRef = useRef(null);

  const isResultMode = !!content;

  const handleFileChange = (e) => {
    const selectedFile = e.target.files[0];
    if (selectedFile) {
      setFile(selectedFile);
      setPreview(URL.createObjectURL(selectedFile));
      setResult('');
      setScanProgress(0);
    }
  };

  const runAudit = async () => {
    if (!file) return;
    setLoading(true);
    setScanning(true);
    setResult('');
    setScanProgress(0);
    
    const progressInterval = setInterval(() => {
      setScanProgress(prev => Math.min(prev + 5, 95));
    }, 150);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('query', query);
    
    try {
      const { data } = await axios.post(`${API_URL}/api/vision/audit`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      
      await new Promise(resolve => setTimeout(resolve, 2000));
      
      clearInterval(progressInterval);
      setScanProgress(100);
      setScanning(false);

      if (data.status === 'success') {
        setResult(data.result);
      } else {
        setResult(`❌ Error: ${data.message}`);
      }
    } catch (err) {
      setScanning(false);
      setResult('❌ Failed to communicate with the Auditor Engine.');
    } finally {
      setLoading(false);
      clearInterval(progressInterval);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[#050505] overflow-hidden">
      {/* Header */}
      <div className="p-4 md:p-6 border-b border-yellow-900/20 bg-black/60 backdrop-blur-md">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-yellow-500/10 flex items-center justify-center border border-yellow-500/20 shadow-[0_0_20px_rgba(234,179,8,0.15)] relative group">
              <Camera className="w-6 h-6 text-yellow-500 group-hover:scale-110 transition-transform" />
              <div className="absolute -top-1 -right-1 w-3 h-3 bg-green-500 border-2 border-black rounded-full animate-pulse" />
            </div>
            <div>
              <h2 className="text-sm md:text-base font-black text-white uppercase tracking-[0.25em] italic">Visual Lab Auditor</h2>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-[9px] text-yellow-600 font-mono font-bold uppercase tracking-widest">Vision-AI Module</span>
                <span className="w-1.5 h-1.5 bg-slate-700 rounded-full" />
                <p className="text-[9px] text-slate-500 font-mono tracking-wider uppercase">V-Engine 2.4 Active</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 md:p-8 space-y-8 custom-scrollbar">
        {!isResultMode && (
          <div className="max-w-4xl mx-auto space-y-6">
            <div 
              onClick={() => !loading && fileInputRef.current.click()}
              className={`relative aspect-video md:aspect-[21/9] rounded-[2rem] border-2 border-dashed transition-all flex flex-col items-center justify-center cursor-pointer group overflow-hidden
                ${preview ? 'border-yellow-600/30 bg-black shadow-2xl' : 'border-slate-800 hover:border-yellow-500/40 bg-slate-900/10'}
                ${scanning ? 'border-yellow-500 scale-[0.99]' : ''}`}
            >
              {preview ? (
                <>
                  <img src={preview} alt="Setup" className={`w-full h-full object-cover transition-all duration-700 ${scanning ? 'opacity-40 scale-105 saturate-0' : 'opacity-70 group-hover:opacity-50'}`} />
                  {scanning && <ScannerLine />}
                  {!scanning && (
                    <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/20 opacity-0 group-hover:opacity-100 transition-opacity">
                      <div className="w-14 h-14 rounded-2xl bg-yellow-500 flex items-center justify-center text-black shadow-2xl shadow-yellow-500/40 scale-90 group-hover:scale-100 transition-transform duration-500">
                        <Upload className="w-6 h-6" />
                      </div>
                      <span className="text-[11px] font-black text-yellow-500 mt-4 uppercase tracking-[0.2em] bg-black/60 px-4 py-2 rounded-xl border border-yellow-500/20">Replace Capture</span>
                    </div>
                  )}
                </>
              ) : (
                <div className="flex flex-col items-center gap-6 p-10 text-center">
                  <Camera className="w-10 h-10 text-slate-500 group-hover:text-yellow-500 transition-colors" />
                  <div>
                    <p className="text-sm font-black text-slate-300 uppercase tracking-widest">Upload Lab Equipment Visuals</p>
                    <p className="text-[10px] text-slate-600 mt-2 uppercase tracking-widest font-mono">Reference against ISO-882 Standards</p>
                  </div>
                </div>
              )}
              <input type="file" ref={fileInputRef} onChange={handleFileChange} className="hidden" accept="image/*" />
            </div>

            <div className="grid md:grid-cols-4 gap-6">
              <div className="md:col-span-3 space-y-3">
                <textarea 
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="e.g. Verify pressure gauge calibration status..."
                  className="w-full bg-[#111116] border border-slate-800 rounded-[1.5rem] px-6 py-4 text-sm text-slate-300 outline-none focus:border-yellow-500/50 min-h-[100px] resize-none"
                />
              </div>
              <button 
                onClick={runAudit}
                disabled={!file || loading}
                className={`w-full rounded-[1.5rem] font-black text-[10px] uppercase tracking-[0.3em] flex flex-col items-center justify-center gap-2
                  ${!file || loading ? 'bg-slate-900 text-slate-600' : 'bg-yellow-600 text-black hover:bg-yellow-500 shadow-2xl'}`}
              >
                {loading ? <Loader className="w-6 h-6 animate-spin" /> : <Zap className="w-6 h-6" />}
                <span>{loading ? 'Analyzing' : 'Run Audit'}</span>
              </button>
            </div>
          </div>
        )}

        {(result || scanning) && (
          <div className="max-w-4xl mx-auto space-y-6">
            <div className="relative p-8 rounded-[2rem] bg-[#0c0c10] border border-yellow-900/20 shadow-2xl">
              <div className="flex items-center justify-between pb-4 border-b border-yellow-900/10 mb-6">
                <div className="flex items-center gap-3">
                  <ShieldCheck className="w-5 h-5 text-green-500" />
                  <span className="text-[11px] font-black text-white uppercase tracking-[0.2em]">Engineering Audit Results</span>
                </div>
              </div>
              
              <div className="text-slate-300 text-[13px] leading-loose font-mono whitespace-pre-wrap">
                {scanning ? 'Analyzing visual data...' : result}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
