import React from 'react';
import { Database } from 'lucide-react';

export default function PetrophysicalTable({ content }) {
  try {
    const data = JSON.parse(content);
    const rows = Array.isArray(data.rows) ? data.rows : [];
    const headers = data.headers || (rows.length > 0 ? Object.keys(rows[0] || {}) : []);

    if (rows.length === 0 && !data.headers) throw new Error("No data found");

    return (
      <div className="my-8 overflow-hidden rounded-3xl border border-yellow-500/20 bg-[#0c0c12]/80 backdrop-blur-xl shadow-[0_24px_60px_-15px_rgba(0,0,0,0.8),inset_0_1px_1px_rgba(255,255,255,0.05)] animate-fade-in">
        <div className="bg-gradient-to-r from-yellow-950/30 to-transparent px-6 py-4 border-b border-white/5 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-lg bg-yellow-500/10 border border-yellow-500/20 text-yellow-400">
              <Database className="w-4 h-4" />
            </div>
            <span className="text-[11px] font-black tracking-[0.2em] text-yellow-400 uppercase">V-Table Ingestion Preview</span>
          </div>
          <div className="text-[10px] text-slate-400 font-mono bg-white/5 border border-white/5 px-2.5 py-1 rounded-full">
            TOTAL SAMPLES: <span className="text-yellow-400 font-bold">{data.rows.length}</span>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse min-w-[600px]">
            <thead>
              <tr className="bg-white/[0.02]">
                {headers.map((h, i) => (
                  <th key={i} className="px-6 py-4 text-[10px] font-black text-yellow-500 uppercase tracking-widest border-b border-white/5 whitespace-nowrap">
                    {h.replace(/_/g, ' ')}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {data.rows.slice(0, 10).map((row, i) => {
                const values = Array.isArray(row) ? row : headers.map(h => row[h]);
                return (
                  <tr key={i} className="hover:bg-yellow-500/[0.03] transition-colors group">
                    {values.map((v, j) => (
                      <td key={j} className={`px-6 py-4 text-xs font-mono transition-colors group-hover:text-white whitespace-nowrap ${v === null || v === 'NaN' || v === 'nan' ? 'text-slate-600 italic' : 'text-slate-300'}`}>
                        {v === null || v === 'NaN' || v === 'nan' ? '--' : (typeof v === 'number' ? v.toFixed(3) : v)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {data.rows.length > 10 && (
            <div className="px-6 py-4 bg-black/20 text-center border-t border-white/5">
              <p className="text-[10px] text-slate-400 font-mono italic uppercase tracking-widest">+ {data.rows.length - 10} additional samples available in full export</p>
            </div>
          )}
        </div>
      </div>
    );
  } catch (err) {
    return <div className="p-4 bg-red-950/20 border border-red-900/50 text-red-400 text-xs font-mono">Invalid Data Format: {err.message}</div>;
  }
}
