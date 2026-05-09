import React from 'react';
import { Database } from 'lucide-react';

export default function PetrophysicalTable({ content }) {
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
                        {v === null || v === 'NaN' || v === 'nan' ? '--' : (typeof v === 'number' ? v.toFixed(3) : v)}
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
