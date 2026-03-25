import React, { useState, useRef } from 'react';
import { UploadCloud, Activity, CheckCircle, AlertTriangle, Layers, Combine } from 'lucide-react';
import axios from 'axios';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

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
      <header className="mb-10 text-center mt-6">
        <h1 className="text-5xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 via-indigo-400 to-emerald-400 mb-3 flex items-center justify-center gap-4 drop-shadow-lg">
          <Combine className="w-12 h-12 text-blue-400" />
          Expert SCAL AI Platform
        </h1>
        <p className="text-slate-400 max-w-2xl mx-auto text-lg mt-4">Upload standard Core Analysis PDFs and our <span className="text-blue-300 font-semibold">Physics-Informed Neural Network (PINN)</span> will automatically predict full multi-phase fluid displacement curves perfectly rivaling Sendra software.</p>
      </header>

      <main className="w-full max-w-5xl flex flex-col gap-6">
        <div 
          className={`border-2 border-dashed border-slate-700 bg-slate-900/60 rounded-3xl p-16 text-center cursor-pointer transition-all hover:bg-slate-800/80 hover:border-blue-500 shadow-2xl backdrop-blur-sm`}
          onClick={() => fileInputRef.current?.click()}
        >
          <input 
            type="file" 
            ref={fileInputRef} 
            className="hidden" 
            accept=".pdf,.doc,.docx"
            onChange={(e) => handleUpload(e.target.files[0])}
          />
          <UploadCloud className="w-20 h-20 mx-auto text-blue-500 mb-6 animate-pulse" />
          <p className="text-2xl font-bold mb-2">Engage Core Extractor (Click & Drop)</p>
          <p className="text-slate-400">Our computer vision system parses thousands of tables instantly.</p>
        </div>

        {loading && (
          <div className="bg-blue-900/20 border border-blue-500/30 rounded-2xl p-10 flex flex-col items-center justify-center animate-pulse mt-4">
             <Layers className="w-16 h-16 text-blue-400 mb-4 animate-spin" />
             <p className="text-xl font-medium text-blue-300">Simulating Fluid Displacement via Deep Neural Network...</p>
          </div>
        )}

        {error && (
          <div className="bg-red-900/20 border border-red-500/30 rounded-2xl p-6 flex items-start gap-4 shadow-lg mt-4">
             <AlertTriangle className="w-10 h-10 text-red-500 shrink-0" />
             <div>
               <h3 className="text-xl font-bold text-red-400">Analysis Halted</h3>
               <p className="text-red-300/80 mt-2">{error}</p>
             </div>
          </div>
        )}

        {result && (
          <div className="bg-slate-900 border border-emerald-500/30 rounded-3xl p-8 shadow-[0_0_80px_rgba(16,185,129,0.1)] mt-4">
            <div className="flex items-center gap-4 mb-6 border-b border-slate-800 pb-5">
              <CheckCircle className="w-10 h-10 text-emerald-400" />
              <h2 className="text-3xl font-extrabold text-emerald-400">AI Simulation Complete</h2>
            </div>
            
            <div className="grid grid-cols-4 gap-4 mb-8">
              <div className="bg-slate-950 p-6 rounded-2xl border border-slate-800 shadow-inner">
                <p className="text-slate-500 text-xs font-bold uppercase tracking-wider mb-2">Porosity (Φ)</p>
                <p className="text-4xl font-black text-white">{result.data.Porosity}</p>
              </div>
              <div className="bg-slate-950 p-6 rounded-2xl border border-slate-800 shadow-inner">
                <p className="text-slate-500 text-xs font-bold uppercase tracking-wider mb-2">Permeability (k)</p>
                <p className="text-4xl font-black text-white flex items-baseline gap-1">
                  {result.data.Permeability} <span className="text-lg text-slate-600 font-medium">mD</span>
                </p>
              </div>
              <div className="bg-slate-950 p-6 rounded-2xl border border-slate-800 shadow-inner">
                <p className="text-slate-500 text-xs font-bold uppercase tracking-wider mb-2">Connate Water</p>
                <p className="text-4xl font-black text-blue-400">{result.data.Swi}</p>
              </div>
              <div className="bg-slate-950 p-6 rounded-2xl border border-slate-800 shadow-inner">
                <p className="text-slate-500 text-xs font-bold uppercase tracking-wider mb-2">Residual Oil</p>
                <p className="text-4xl font-black text-emerald-400">{result.data.Sor}</p>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              
              <div className="lg:col-span-2 bg-slate-950 border border-slate-800 rounded-2xl p-6">
                <h3 className="text-lg font-bold text-slate-300 mb-6 flex items-center gap-2">
                  <Activity className="w-5 h-5 text-indigo-400" />
                  Physics-Informed Prediction: Relative Permeability
                </h3>
                <div className="w-full h-80">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={result.ai_insights.Curve_Data} margin={{ top: 5, right: 30, left: 20, bottom: 25 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                      <XAxis 
                        dataKey="Sw" 
                        stroke="#64748b" 
                        label={{ value: 'Water Saturation (Sw)', position: 'bottom', offset: 0, fill: '#94a3b8' }} 
                        tick={{fill: '#475569'}}
                      />
                      <YAxis 
                         stroke="#64748b" 
                         label={{ value: 'Relative Permeability', angle: -90, position: 'insideLeft', offset: -10, fill: '#94a3b8' }} 
                         tick={{fill: '#475569'}}
                      />
                      <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', borderRadius: '8px', color: '#fff' }} itemStyle={{color: '#e2e8f0'}} />
                      <Legend verticalAlign="top" height={36} iconType="circle" />
                      <Line type="monotone" dataKey="krw" name="Krw (Water)" stroke="#3b82f6" strokeWidth={4} dot={{r: 3, fill: '#3b82f6', strokeWidth: 0}} activeDot={{ r: 8 }} />
                      <Line type="monotone" dataKey="kro" name="Kro (Oil)" stroke="#10b981" strokeWidth={4}  dot={{r: 3, fill: '#10b981', strokeWidth: 0}} activeDot={{ r: 8 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="bg-gradient-to-br from-indigo-900/30 to-purple-900/20 border border-indigo-500/30 rounded-2xl p-6 flex flex-col justify-center">
                <h3 className="text-indigo-300 font-bold mb-6 uppercase tracking-wider text-sm flex items-center gap-2"><Layers className="w-4 h-4"/> Neural Network Insights</h3>
                
                <div className="space-y-6">
                  <div>
                    <p className="text-slate-400 text-sm mb-1">AI Oil Corey Exponent (No)</p>
                    <p className="text-3xl font-mono text-white">{result.ai_insights.Corey_Exponents.no}</p>
                  </div>
                  <div>
                    <p className="text-slate-400 text-sm mb-1">AI Water Corey Exponent (Nw)</p>
                    <p className="text-3xl font-mono text-white">{result.ai_insights.Corey_Exponents.nw}</p>
                  </div>
                  <div className="pt-6 border-t border-indigo-500/20 mt-4">
                    <p className="text-slate-400 text-sm mb-1">Intersection Saturation Node</p>
                    <p className="text-4xl font-black text-indigo-400">~{((1 - result.data.Sor + result.data.Swi) / 2).toFixed(2)}</p>
                  </div>
                </div>
              </div>

            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
