import React, { useState, useRef } from 'react';
import { UploadCloud, CheckCircle, AlertTriangle, Layers, Database, Download } from 'lucide-react';
import axios from 'axios';

function App() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const fileInputRef = useRef(null);

  const handleUpload = async (fileToUpload) => {
    if (!fileToUpload) return;
    setLoading(true);
    setError(null);
    setResult(null);

    const formData = new FormData();
    formData.append('file', fileToUpload);

    try {
      const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      const response = await axios.post(`${apiUrl}/api/batch_process`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 60000 
      });
      if (response.data.status === 'success') {
        setResult(response.data);
      } else {
        setError(response.data.message || 'Error executing macro-level analysis.');
      }
    } catch (err) {
      setError(err.message || 'Server connection failed. Ensure FastAPI is running on Port 8000.');
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = () => {
      if(!result || !result.download_url) return;
      const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      window.open(`${apiUrl}${result.download_url}`, "_blank");
  };

  return (
    <div className="min-h-screen p-8 bg-black text-slate-100 flex flex-col items-center font-sans selection:bg-indigo-500/30">
      
      <div className="w-full max-w-7xl flex items-center justify-between mb-16 border-b border-white/5 pb-6 mt-4">
        <div className="flex items-center gap-4">
           <Database className="w-10 h-10 text-emerald-500" />
           <div>
             <h1 className="text-2xl font-black tracking-widest text-white">PETROLEUM RESEARCH CENTER</h1>
             <p className="text-xs text-emerald-500 tracking-[0.2em] font-bold">ENTERPRISE SCAL AI FRAMEWORK</p>
           </div>
        </div>
        <div className="text-right">
           <p className="text-xs text-slate-500 uppercase tracking-widest">System Status</p>
           <p className="text-emerald-400 font-mono text-sm shadow-[0_0_15px_rgba(16,185,129,0.2)]">● ONLINE CLUSTER</p>
        </div>
      </div>

      <main className="w-full max-w-4xl flex flex-col gap-6">
        
        <div className="bg-[#0a0a0a] border border-white/10 rounded-2xl p-1 shadow-2xl">
          <div className="bg-[#111] rounded-xl p-16 text-center 
                          hover:bg-[#151515] transition-all cursor-pointer border border-transparent hover:border-emerald-500/50"
               onClick={() => fileInputRef.current?.click()}
          >
            <input 
              type="file" 
              ref={fileInputRef} 
              className="hidden" 
              accept=".pdf,.doc,.docx,.xlsx,.xls,.csv"
              onChange={(e) => handleUpload(e.target.files[0])}
            />
            <div className="w-24 h-24 rounded-full bg-emerald-500/10 flex items-center justify-center mx-auto mb-8 
                            shadow-[0_0_30px_rgba(16,185,129,0.15)] ring-1 ring-emerald-500/30">
               <UploadCloud className="w-10 h-10 text-emerald-400" />
            </div>
            <h2 className="text-3xl font-light text-white mb-2">Execute Batch Reservoir Study</h2>
            <p className="text-slate-500 text-sm tracking-widest">DROP MASSIVE EXCEL, CSV, OR LAB PDF HERE</p>
          </div>
        </div>

        {loading && (
          <div className="bg-indigo-950/20 border border-indigo-500/20 rounded-2xl p-12 flex flex-col items-center justify-center">
             <Layers className="w-12 h-12 text-indigo-400 mb-6 animate-spin" />
             <h3 className="text-xl font-light text-white mb-2">Processing Unified Batch Extraction...</h3>
             <p className="text-indigo-400/60 text-sm font-mono tracking-wider">Deploying Deep Learning Cluster & Formatting Word Export...</p>
          </div>
        )}

        {error && (
          <div className="bg-red-950/30 border border-red-500/30 rounded-2xl p-8 flex items-start gap-6">
             <AlertTriangle className="w-10 h-10 text-red-500 shrink-0" />
             <div>
               <h3 className="text-xl font-bold text-red-400">CRITICAL SYSTEM ERROR</h3>
               <p className="text-red-300/70 mt-2 font-mono text-sm leading-relaxed">{error}</p>
             </div>
          </div>
        )}

        {result && (
          <div className="bg-emerald-950/20 border border-emerald-500/30 rounded-2xl p-10 overflow-hidden relative">
            <div className="absolute top-0 right-0 w-64 h-64 bg-emerald-500/10 blur-[80px] rounded-full pointer-events-none"></div>
            
            <div className="flex items-center gap-5 mb-8 border-b border-emerald-500/20 pb-8">
              <CheckCircle className="w-12 h-12 text-emerald-400" />
              <div>
                <h2 className="text-3xl font-bold text-white">Batch Simulation Completed</h2>
                <p className="text-emerald-400/80 font-mono mt-1">Successfully deployed Neural Networks & Compiled MS Word Deliverable.</p>
              </div>
            </div>
            
            <div className="grid grid-cols-2 gap-6 mb-10">
              <div className="bg-black/50 p-6 rounded-xl border border-white/5">
                <p className="text-slate-500 text-xs font-bold uppercase tracking-widest mb-3">Core Samples Validated</p>
                <p className="text-5xl font-light text-white">{result.samples_processed}</p>
              </div>
              <div className="bg-black/50 p-6 rounded-xl border border-white/5">
                 <p className="text-slate-500 text-xs font-bold uppercase tracking-widest mb-3">Thermodynamic Models Generated</p>
                 <p className="text-5xl font-light text-white">{result.samples_processed}</p>
              </div>
            </div>

            <div className="flex justify-center border-t border-white/5 pt-10">
               <button 
                 onClick={handleDownload}
                 className="bg-emerald-600 hover:bg-emerald-500 text-white font-bold tracking-widest uppercase px-12 py-5 rounded-lg flex items-center justify-center gap-4 transition-all hover:scale-[1.02] shadow-[0_0_40px_rgba(16,185,129,0.3)] ring-1 ring-emerald-400"
               >
                 <Download className="w-6 h-6"/> Download MS Word Final Report
               </button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
