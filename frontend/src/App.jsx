import React, { useState, useRef } from 'react';
import { UploadCloud, Activity, Database, CheckCircle, AlertTriangle } from 'lucide-react';
import axios from 'axios';

function App() {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const fileInputRef = useRef(null);

  const handleUpload = async (fileToUpload) => {
    if (!fileToUpload) return;
    setFile(fileToUpload);
    setLoading(true);
    setError(null);
    setResult(null);

    const formData = new FormData();
    formData.append('file', fileToUpload);

    try {
      const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      const response = await axios.post(`${apiUrl}/api/analyze`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });

      if (response.data.status === 'success') {
        setResult(response.data);
      } else {
        setError(response.data.message || 'Error processing report');
      }
    } catch (err) {
      setError(err.message || 'Server connection failed. Is FastAPI running?');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen p-8 bg-slate-950 text-slate-100 flex flex-col items-center">
      <header className="mb-10 text-center">
        <h1 className="text-4xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-emerald-400 mb-3 flex items-center justify-center gap-3">
          <Activity className="w-10 h-10 text-blue-400" />
          SCAL AI Pipeline
        </h1>
        <p className="text-slate-400 max-w-lg mx-auto">Upload a Core Analysis Report (PDF) to automatically extract petrophysical parameters and predict endpoints via Deep Learning.</p>
      </header>

      <main className="w-full max-w-3xl flex flex-col gap-6">
        <div 
          className={`border-2 border-dashed border-slate-700 bg-slate-900/50 rounded-2xl p-12 text-center cursor-pointer transition-all hover:bg-slate-800/50 hover:border-blue-500`}
          onClick={() => fileInputRef.current?.click()}
        >
          <input 
            type="file" 
            ref={fileInputRef} 
            className="hidden" 
            accept=".pdf"
            onChange={(e) => handleUpload(e.target.files[0])}
          />
          <UploadCloud className="w-16 h-16 mx-auto text-blue-500 mb-4 animate-pulse" />
          <p className="text-xl font-semibold mb-2">Click or Drag to Upload SCAL PDF</p>
          <p className="text-slate-400 text-sm">Supports standard lab reports</p>
        </div>

        {loading && (
          <div className="bg-blue-900/20 border border-blue-500/30 rounded-xl p-6 flex flex-col items-center justify-center animate-pulse">
             <Database className="w-12 h-12 text-blue-400 mb-4 animate-spin" />
             <p className="text-lg font-medium text-blue-300">Extracting and Running Deep Learning Inference...</p>
          </div>
        )}

        {error && (
          <div className="bg-red-900/20 border border-red-500/30 rounded-xl p-6 flex items-start gap-4">
             <AlertTriangle className="w-8 h-8 text-red-500 shrink-0" />
             <div>
               <h3 className="text-lg font-bold text-red-400">Analysis Failed</h3>
               <p className="text-red-300/80 mt-1">{error}</p>
             </div>
          </div>
        )}

        {result && (
          <div className="bg-slate-900 border border-emerald-500/30 rounded-xl p-8 shadow-2xl">
            <div className="flex items-center gap-3 mb-6 border-b border-slate-800 pb-4">
              <CheckCircle className="w-8 h-8 text-emerald-400" />
              <h2 className="text-2xl font-bold text-emerald-400">Analysis Complete</h2>
            </div>
            
            <div className="grid grid-cols-2 gap-6 mb-8">
              <div className="bg-slate-950 p-5 rounded-xl border border-slate-800">
                <p className="text-slate-400 text-sm mb-1">Porosity (Φ)</p>
                <p className="text-3xl font-mono text-white">{result.data.Porosity}</p>
              </div>
              <div className="bg-slate-950 p-5 rounded-xl border border-slate-800">
                <p className="text-slate-400 text-sm mb-1">Permeability (k)</p>
                <p className="text-3xl font-mono text-white flex items-end gap-2">
                  {result.data.Permeability} <span className="text-lg text-slate-500">mD</span>
                </p>
              </div>
              <div className="bg-slate-950 p-5 rounded-xl border border-slate-800">
                <p className="text-slate-400 text-sm mb-1">Irreducible Water (Swi)</p>
                <p className="text-3xl font-mono text-white">{result.data.Swi}</p>
              </div>
              <div className="bg-slate-950 p-5 rounded-xl border border-slate-800">
                <p className="text-slate-400 text-sm mb-1">Residual Oil (Sor)</p>
                <p className="text-3xl font-mono text-white">{result.data.Sor}</p>
              </div>
            </div>

            <div className="bg-gradient-to-br from-blue-900/40 to-emerald-900/20 border border-blue-500/30 rounded-xl p-6">
              <h3 className="text-slate-300 font-medium mb-2 flex items-center gap-2">
                <Activity className="w-5 h-5 text-blue-400" />
                AI Prediction (Multi-Layer Perceptron)
              </h3>
              <div className="flex justify-between items-end">
                <p className="text-slate-400 text-sm">Predicted Relative Permeability (krw @ Sor)</p>
                <p className="text-4xl font-extrabold text-blue-400 font-mono">{result.predictions.krw_at_sor}</p>
              </div>
            </div>
            
            <p className="text-center text-slate-500 text-sm mt-6">
              Full report saved as: <span className="font-mono text-slate-400">{result.report_generated}</span>
            </p>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
