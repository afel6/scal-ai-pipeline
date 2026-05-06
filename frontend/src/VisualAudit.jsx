import React, { useState, useRef } from 'react';
import { Camera, Upload, ShieldCheck, AlertTriangle, ArrowRight, Loader, Zap } from 'lucide-react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '';

export default function VisualAudit() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [query, setQuery] = useState('Verify this equipment setup against its manual.');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState('');
  const fileInputRef = useRef(null);

  const handleFileChange = (e) => {
    const selectedFile = e.target.files[0];
    if (selectedFile) {
      setFile(selectedFile);
      setPreview(URL.createObjectURL(selectedFile));
      setResult('');
    }
  };

  const runAudit = async () => {
    if (!file) return;
    setLoading(true);
    setResult('');
    
    const formData = new FormData();
    formData.append('file', file);
    formData.append('query', query);
    
    try {
      const { data } = await axios.post(`${API_URL}/api/vision/audit`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      if (data.status === 'success') {
        setResult(data.result);
      } else {
        setResult(`❌ Error: ${data.message}`);
      }
    } catch (err) {
      setResult('❌ Failed to communicate with the Auditor Engine.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[#0c0c10] overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-yellow-900/20 bg-black/40">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-yellow-500/10 flex items-center justify-center border border-yellow-500/20 shadow-[0_0_15px_rgba(234,179,8,0.1)]">
            <Camera className="w-5 h-5 text-yellow-500" />
          </div>
          <div>
            <h2 className="text-sm font-black text-yellow-50/90 uppercase tracking-[0.2em]">Visual Lab Auditor</h2>
            <p className="text-[10px] text-slate-500 font-mono tracking-wider">Vision-Based Quality Control</p>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6 custom-scrollbar">
        {/* Upload/Preview Section */}
        <div className="space-y-4">
          <div 
            onClick={() => fileInputRef.current.click()}
            className={`relative aspect-video rounded-3xl border-2 border-dashed transition-all flex flex-col items-center justify-center cursor-pointer group overflow-hidden
              ${preview ? 'border-yellow-600/50 bg-black' : 'border-slate-800 hover:border-yellow-500/40 bg-slate-900/20'}`}
          >
            {preview ? (
              <>
                <img src={preview} alt="Setup" className="w-full h-full object-cover opacity-60 group-hover:opacity-40 transition-opacity" />
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <div className="w-12 h-12 rounded-full bg-black/60 flex items-center justify-center border border-yellow-500/30 text-yellow-500 transform group-hover:scale-110 transition-transform">
                    <Upload className="w-5 h-5" />
                  </div>
                  <span className="text-[10px] font-bold text-yellow-500 mt-2 uppercase tracking-widest opacity-0 group-hover:opacity-100 transition-opacity">Replace Photo</span>
                </div>
              </>
            ) : (
              <div className="flex flex-col items-center gap-3">
                <div className="w-16 h-16 rounded-3xl bg-slate-800/40 flex items-center justify-center border border-slate-700/60 text-slate-500 group-hover:text-yellow-500 group-hover:border-yellow-500/30 transition-all">
                  <Camera className="w-8 h-8" />
                </div>
                <div className="text-center">
                  <p className="text-xs font-bold text-slate-400 group-hover:text-slate-200 transition-colors">Capture or Upload Equipment Photo</p>
                  <p className="text-[10px] text-slate-600 mt-1 uppercase tracking-tighter">JPEG, PNG accepted</p>
                </div>
              </div>
            )}
            <input type="file" ref={fileInputRef} onChange={handleFileChange} className="hidden" accept="image/*" />
          </div>

          <div className="space-y-2">
            <label className="text-[10px] font-black text-yellow-600 uppercase tracking-[0.2em] ml-1">Audit Instruction</label>
            <textarea 
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="What should I check for?"
              className="w-full bg-slate-900/50 border border-slate-800 rounded-2xl px-4 py-3 text-sm text-slate-300 outline-none focus:border-yellow-500/50 min-h-[80px] resize-none transition-all placeholder:text-slate-700"
            />
          </div>

          <button 
            onClick={runAudit}
            disabled={!file || loading}
            className={`w-full py-4 rounded-2xl font-black text-xs uppercase tracking-[0.3em] flex items-center justify-center gap-3 transition-all shadow-xl
              ${!file || loading 
                ? 'bg-slate-800 text-slate-600 cursor-not-allowed' 
                : 'bg-gradient-to-r from-yellow-600 to-yellow-500 text-black hover:shadow-yellow-500/20 active:scale-95'}`}
          >
            {loading ? (
              <><Loader className="w-4 h-4 animate-spin" /> Analyzing Physics...</>
            ) : (
              <><Zap className="w-4 h-4" /> Run Visual Audit</>
            )}
          </button>
        </div>

        {/* Results Section */}
        {result && (
          <div className="animate-in fade-in slide-in-from-bottom-4 duration-500 pb-8">
            <div className="p-5 rounded-3xl bg-black border border-yellow-900/30 shadow-2xl space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-yellow-900/10">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 text-green-500" />
                  <span className="text-[11px] font-black text-yellow-50/90 uppercase tracking-widest">Audit Findings</span>
                </div>
                <div className="px-2 py-1 rounded bg-yellow-500/10 border border-yellow-500/20 text-[9px] font-bold text-yellow-500 uppercase tracking-tighter">
                  Ver-1.0
                </div>
              </div>
              
              <div className="prose prose-invert prose-sm max-w-none">
                <div className="text-slate-300 text-xs leading-relaxed font-serif whitespace-pre-wrap">
                  {result}
                </div>
              </div>

              {result.includes('ERROR DETECTED') && (
                <div className="p-4 bg-red-950/20 border border-red-900/30 rounded-2xl flex items-start gap-3">
                  <AlertTriangle className="w-5 h-5 text-red-500 shrink-0" />
                  <div>
                    <h4 className="text-[11px] font-black text-red-400 uppercase tracking-wider">Critical Configuration Error</h4>
                    <p className="text-[10px] text-red-200/70 mt-1 font-mono italic">Please correct the state before initiating the SCAL sequence.</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
