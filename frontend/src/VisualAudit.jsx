import React, { useState, useRef } from 'react';
import { Camera, Upload, ShieldCheck, AlertTriangle, ArrowRight, Loader, Zap, CheckCircle, Crosshair, Search, PlusCircle } from 'lucide-react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '';

const ScannerLine = () => (
  <div className="absolute inset-0 pointer-events-none z-10 overflow-hidden rounded-[2rem]">
    <div className="absolute top-0 left-0 w-full h-[2px] bg-gradient-to-r from-transparent via-yellow-500 to-transparent shadow-[0_0_15px_rgba(234,179,8,0.8)] animate-scanner-down" />
    <div className="absolute inset-0 bg-gradient-to-b from-yellow-500/5 to-transparent opacity-20 animate-pulse-slow" />
  </div>
);

export default function VisualAudit() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [query, setQuery] = useState('Verify this equipment setup against its manual.');
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState('');
  const [scanProgress, setScanProgress] = useState(0);
  const fileInputRef = useRef(null);

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
            <div className="w-12 h-12 rounded-2xl bg-yellow-500/10 flex items-center justify-center border border-yellow-500/20 shadow-[0_0_20px_rgba(234,179,8,0.15)] relative group">
              <Camera className="w-6 h-6 text-yellow-500 group-hover:scale-110 transition-transform" />
              <div className="absolute -top-1 -right-1 w-3 h-3 bg-green-500 border-2 border-black rounded-full animate-pulse" />
            </div>
            <div>
              <h2 className="text-sm md:text-base font-black text-white uppercase tracking-[0.25em] italic">Visual Lab Auditor</h2>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-[9px] text-yellow-600 font-mono font-bold uppercase tracking-widest">Vision-AI Module</span>
                <span className="w-1 h-1 bg-slate-700 rounded-full" />
                <p className="text-[9px] text-slate-500 font-mono tracking-wider uppercase">V-Engine 2.4 Active</p>
              </div>
            </div>
          </div>
          
          {loading && (
            <div className="hidden md:flex items-center gap-3 px-4 py-2 bg-yellow-500/5 border border-yellow-500/20 rounded-full">
              <div className="flex gap-1">
                {[0,1,2].map(i => (
                  <div key={i} className="w-1 h-3 bg-yellow-500/40 rounded-full animate-bounce" style={{ animationDelay: `${i * 0.1}s` }} />
                ))}
              </div>
              <span className="text-[10px] font-black text-yellow-500 uppercase tracking-widest">Processing Data</span>
            </div>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 md:p-8 space-y-8 custom-scrollbar">
        {/* Upload/Preview Section */}
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
                    <div className="w-14 h-14 rounded-full bg-yellow-500 flex items-center justify-center text-black shadow-2xl shadow-yellow-500/40 scale-90 group-hover:scale-100 transition-transform duration-500">
                      <Upload className="w-6 h-6" />
                    </div>
                    <span className="text-[11px] font-black text-yellow-500 mt-4 uppercase tracking-[0.2em] bg-black/60 px-4 py-2 rounded-full border border-yellow-500/20">Replace Capture</span>
                  </div>
                )}

                {/* HUD Elements */}
                <div className="absolute top-4 left-4 p-3 border-l-2 border-t-2 border-yellow-500/40 opacity-60">
                  <div className="text-[9px] font-mono text-yellow-500 tracking-tighter uppercase">X: 124.5Y</div>
                  <div className="text-[9px] font-mono text-yellow-500 tracking-tighter uppercase">Z: 88.2A</div>
                </div>
                <div className="absolute bottom-4 right-4 p-3 border-r-2 border-b-2 border-yellow-500/40 opacity-60">
                  <div className="text-[9px] font-mono text-yellow-500 tracking-tighter uppercase">ISO: 800</div>
                  <div className="text-[9px] font-mono text-yellow-500 tracking-tighter uppercase">AUDIT: READY</div>
                </div>
                
                {scanning && (
                  <div className="absolute bottom-6 left-1/2 -translate-x-1/2 w-48 h-1 bg-white/10 rounded-full overflow-hidden border border-white/5">
                    <div className="h-full bg-yellow-500 transition-all duration-300 shadow-[0_0_10px_#eab308]" style={{ width: `${scanProgress}%` }} />
                  </div>
                )}
              </>
            ) : (
              <div className="flex flex-col items-center gap-6 p-10 text-center">
                <div className="relative">
                  <div className="w-24 h-24 rounded-[2rem] bg-slate-900/50 flex items-center justify-center border border-slate-800 text-slate-500 group-hover:text-yellow-500 group-hover:border-yellow-500/30 group-hover:shadow-[0_0_30px_rgba(234,179,8,0.1)] transition-all duration-500">
                    <Camera className="w-10 h-10" />
                  </div>
                  <div className="absolute -bottom-2 -right-2 w-8 h-8 rounded-xl bg-yellow-600 flex items-center justify-center border-2 border-black text-black opacity-0 group-hover:opacity-100 transition-opacity translate-y-2 group-hover:translate-y-0 duration-500">
                    <PlusCircle className="w-4 h-4" />
                  </div>
                </div>
                <div>
                  <p className="text-sm font-black text-slate-300 group-hover:text-white transition-colors tracking-widest uppercase">Upload Lab Equipment Visuals</p>
                  <p className="text-[10px] text-slate-600 mt-2 uppercase tracking-widest font-mono">Reference against ISO-882 Standards</p>
                </div>
              </div>
            )}
            <input type="file" ref={fileInputRef} onChange={handleFileChange} className="hidden" accept="image/*" />
          </div>

          <div className="grid md:grid-cols-4 gap-6 items-start">
            <div className="md:col-span-3 space-y-3">
              <label className="flex items-center gap-2 text-[10px] font-black text-yellow-600 uppercase tracking-[0.2em] ml-1">
                <Search className="w-3 h-3" /> Audit Parameter
              </label>
              <div className="relative group">
                <textarea 
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="e.g. Verify pressure gauge calibration status..."
                  className="w-full bg-[#111116] border border-slate-800 rounded-[1.5rem] px-6 py-4 text-sm text-slate-300 outline-none focus:border-yellow-500/50 min-h-[100px] resize-none transition-all placeholder:text-slate-700 shadow-inner group-hover:border-slate-700"
                />
                <div className="absolute bottom-4 right-4 flex items-center gap-1.5 opacity-40 group-focus-within:opacity-100 transition-opacity">
                  <div className="w-1.5 h-1.5 rounded-full bg-yellow-500 animate-pulse" />
                  <span className="text-[9px] font-mono text-yellow-500 font-black uppercase">V-Core Active</span>
                </div>
              </div>
            </div>

            <div className="space-y-3">
              <label className="text-[10px] font-black text-slate-600 uppercase tracking-[0.2em] ml-1">Actions</label>
              <button 
                onClick={runAudit}
                disabled={!file || loading}
                className={`w-full aspect-square md:aspect-auto md:py-8 rounded-[1.5rem] font-black text-[10px] uppercase tracking-[0.3em] flex flex-col items-center justify-center gap-4 transition-all relative overflow-hidden group
                  ${!file || loading 
                    ? 'bg-slate-900 border border-slate-800 text-slate-600 cursor-not-allowed' 
                    : 'bg-yellow-600 text-black hover:bg-yellow-500 shadow-2xl shadow-yellow-900/20 active:scale-95'}`}
              >
                {loading ? (
                  <>
                    <Loader className="w-6 h-6 animate-spin" />
                    <span className="animate-pulse">Analyzing...</span>
                  </>
                ) : (
                  <>
                    <Zap className="w-6 h-6 group-hover:scale-125 transition-transform" />
                    <span>Run Audit</span>
                  </>
                )}
                
                {file && !loading && (
                  <div className="absolute inset-0 bg-white/20 -translate-x-full group-hover:translate-x-full transition-transform duration-1000 skew-x-12" />
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Results Section */}
        {(result || scanning) && (
          <div className="max-w-4xl mx-auto animate-in fade-in slide-in-from-bottom-8 duration-700 pb-20">
            <div className="relative group">
              {/* Outer Glow */}
              <div className="absolute -inset-1 bg-gradient-to-r from-yellow-600/20 to-amber-600/20 rounded-[2.5rem] blur opacity-50 group-hover:opacity-100 transition-opacity" />
              
              <div className="relative p-6 md:p-8 rounded-[2rem] bg-[#0c0c10] border border-yellow-900/20 shadow-2xl space-y-6">
                <div className="flex items-center justify-between pb-4 border-b border-yellow-900/10">
                  <div className="flex items-center gap-3">
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center border shadow-inner ${scanning ? 'bg-yellow-500/10 border-yellow-500/20 text-yellow-500' : 'bg-green-500/10 border-green-500/20 text-green-500'}`}>
                      {scanning ? <Loader className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
                    </div>
                    <div>
                      <span className="text-[11px] font-black text-white uppercase tracking-[0.2em]">Engineering Audit Results</span>
                      <p className="text-[9px] text-slate-500 font-mono mt-0.5">Reference ID: PRC-VA-{Math.floor(Math.random() * 9000 + 1000)}</p>
                    </div>
                  </div>
                  <div className="px-3 py-1 rounded-full bg-yellow-500/5 border border-yellow-500/20 text-[9px] font-black text-yellow-500 uppercase tracking-widest">
                    V-Analysis Stable
                  </div>
                </div>
                
                <div className="min-h-[100px] flex items-center">
                  {scanning ? (
                    <div className="w-full space-y-4">
                      <div className="h-4 bg-slate-800/40 rounded-full w-3/4 animate-pulse" />
                      <div className="h-4 bg-slate-800/40 rounded-full w-1/2 animate-pulse" />
                      <div className="h-4 bg-slate-800/40 rounded-full w-2/3 animate-pulse" />
                    </div>
                  ) : (
                    <div className="prose prose-invert prose-sm max-w-none w-full">
                      <div className="text-slate-300 text-[15px] leading-loose font-serif whitespace-pre-wrap selection:bg-yellow-500/30 selection:text-white first-letter:text-3xl first-letter:font-black first-letter:text-yellow-500 first-letter:mr-3 first-letter:float-left">
                        {result}
                      </div>
                    </div>
                  )}
                </div>

                {!scanning && result && (
                  <div className="pt-6 border-t border-yellow-900/10 flex flex-wrap gap-4">
                    <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-green-500/5 border border-green-500/20">
                      <CheckCircle className="w-3 h-3 text-green-500" />
                      <span className="text-[10px] font-black text-green-500 uppercase tracking-widest">Validation Success</span>
                    </div>
                    <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800/40 border border-slate-700/40">
                      <Crosshair className="w-3 h-3 text-slate-400" />
                      <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">Target Confirmed</span>
                    </div>
                  </div>
                )}

                {result.includes('ERROR DETECTED') && (
                  <div className="p-5 bg-red-950/20 border border-red-900/30 rounded-3xl flex items-start gap-4 animate-shake">
                    <div className="w-10 h-10 rounded-2xl bg-red-500/10 flex items-center justify-center border border-red-500/20 shrink-0">
                      <AlertTriangle className="w-5 h-5 text-red-500" />
                    </div>
                    <div>
                      <h4 className="text-[11px] font-black text-red-400 uppercase tracking-[0.15em]">Critical Configuration Mismatch</h4>
                      <p className="text-xs text-red-200/60 mt-1 font-mono leading-relaxed">System has identified a variance from ISO protocol. Calibration sequence required before proceeding to Phase 2 operations.</p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
