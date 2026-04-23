import React, { useMemo } from 'react';
import {
  LineChart, Line, ScatterChart, Scatter,
  XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, ComposedChart
} from 'recharts';

const COLORS = {
  krw_raw: '#38bdf8',   // sky blue - raw water data
  kro_raw: '#fb923c',   // orange - raw oil data
  krw_fit: '#0ea5e9',   // blue - fitted water
  kro_fit: '#f97316',   // deep orange - fitted oil
};

const CustomTooltip = ({ active, payload }) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-[#0c0c14] border border-yellow-900/50 rounded-xl px-4 py-3 shadow-2xl text-xs font-mono">
        {payload.map((p, i) => (
          <div key={i} style={{ color: p.color }} className="flex gap-3 items-center">
            <span className="font-bold">{p.name}:</span>
            <span>{typeof p.value === 'number' ? p.value.toFixed(4) : p.value}</span>
          </div>
        ))}
      </div>
    );
  }
  return null;
};

export default function KrPlot({ content }) {
  const data = useMemo(() => {
    try {
      return typeof content === 'string' ? JSON.parse(content) : content;
    } catch { return null; }
  }, [content]);

  if (!data || !data.curves) return (
    <div className="p-4 bg-red-950/20 border border-red-900/40 rounded-xl text-red-400 text-xs font-mono">
      Invalid plot data.
    </div>
  );

  // Build unified dataset for ComposedChart (line + scatter in one)
  // Separate scatter (raw) and line (fitted) curves
  const scatterCurves = data.curves.filter(c => c.type === 'scatter');
  const lineCurves = data.curves.filter(c => c.type === 'line');

  // Build line data keyed by x
  const lineMap = {};
  lineCurves.forEach(curve => {
    const key = curve.label.toLowerCase().includes('krw') ? 'krw_fit' : 'kro_fit';
    curve.x.forEach((x, i) => {
      const xVal = parseFloat(x.toFixed(3));
      if (!lineMap[xVal]) lineMap[xVal] = { Sw: xVal };
      lineMap[xVal][key] = curve.y[i];
    });
  });
  const lineData = Object.values(lineMap).sort((a, b) => a.Sw - b.Sw);

  // Build scatter data
  const scatterData = {
    krw_raw: [],
    kro_raw: [],
  };
  scatterCurves.forEach(curve => {
    const key = curve.label.toLowerCase().includes('krw') ? 'krw_raw' : 'kro_raw';
    curve.x.forEach((x, i) => {
      scatterData[key].push({ Sw: parseFloat(x.toFixed(4)), Kr: parseFloat(curve.y[i].toFixed(4)) });
    });
  });

  const title = data.title || 'Relative Permeability Curves';
  const xLabel = data.x_label || 'Water Saturation (Sw)';
  const yLabel = data.y_label || 'Relative Permeability (Kr)';

  return (
    <div className="my-6 rounded-2xl border border-yellow-900/40 bg-[#07070d] shadow-2xl overflow-hidden">
      {/* Header */}
      <div className="bg-gradient-to-r from-yellow-950/50 to-black px-5 py-4 border-b border-yellow-900/30 flex items-center justify-between">
        <div>
          <p className="text-[10px] font-black tracking-[0.2em] text-yellow-500 uppercase">PRC Petrophysics Engine</p>
          <p className="text-sm font-bold text-white mt-0.5">{title}</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          <span className="text-[10px] text-green-400 font-mono uppercase tracking-widest">Live Render</span>
        </div>
      </div>

      {/* Chart */}
      <div className="p-5 pt-6">
        {/* Line chart for fitted curves */}
        <ResponsiveContainer width="100%" height={340}>
          <ComposedChart margin={{ top: 10, right: 30, bottom: 40, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
            <XAxis
              dataKey="Sw"
              type="number"
              domain={[0.1, 0.9]}
              tickCount={9}
              tickFormatter={v => v.toFixed(2)}
              stroke="#475569"
              tick={{ fontSize: 10, fill: '#64748b', fontFamily: 'monospace' }}
              label={{ value: xLabel, position: 'insideBottom', offset: -25, fill: '#64748b', fontSize: 11 }}
            />
            <YAxis
              type="number"
              domain={[0, 1]}
              tickCount={6}
              tickFormatter={v => v.toFixed(2)}
              stroke="#475569"
              tick={{ fontSize: 10, fill: '#64748b', fontFamily: 'monospace' }}
              label={{ value: yLabel, angle: -90, position: 'insideLeft', offset: 5, fill: '#64748b', fontSize: 11 }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              wrapperStyle={{ fontSize: '11px', fontFamily: 'monospace', paddingTop: '16px' }}
              formatter={(value) => <span style={{ color: '#94a3b8' }}>{value}</span>}
            />

            {/* Fitted lines */}
            <Line
              data={lineData}
              dataKey="krw_fit"
              name="Krw Fitted (Brooks-Corey)"
              stroke={COLORS.krw_fit}
              strokeWidth={2.5}
              dot={false}
              type="monotone"
            />
            <Line
              data={lineData}
              dataKey="kro_fit"
              name="Kro Fitted (Brooks-Corey)"
              stroke={COLORS.kro_fit}
              strokeWidth={2.5}
              dot={false}
              type="monotone"
            />

            {/* Raw scatter points */}
            <Scatter
              data={scatterData.krw_raw}
              dataKey="Kr"
              name="Krw Lab Data"
              fill={COLORS.krw_raw}
              opacity={0.85}
              r={5}
            />
            <Scatter
              data={scatterData.kro_raw}
              dataKey="Kr"
              name="Kro Lab Data"
              fill={COLORS.kro_raw}
              opacity={0.85}
              r={5}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Footer stats */}
      <div className="border-t border-yellow-900/20 px-5 py-3 flex items-center gap-6 flex-wrap">
        <div className="flex items-center gap-2">
          <div className="w-6 h-0.5 bg-sky-400" />
          <span className="text-[10px] text-slate-500 font-mono">Krw Fitted</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-6 h-0.5 bg-orange-400" />
          <span className="text-[10px] text-slate-500 font-mono">Kro Fitted</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-sky-300 opacity-80" />
          <span className="text-[10px] text-slate-500 font-mono">Krw Raw Lab</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-orange-300 opacity-80" />
          <span className="text-[10px] text-slate-500 font-mono">Kro Raw Lab</span>
        </div>
        <div className="ml-auto text-[10px] text-slate-600 font-mono italic">
          Brooks-Corey History Match · Simulated Annealing Engine
        </div>
      </div>
    </div>
  );
}
