/* eslint-disable no-unused-vars */
// frontend/src/components/KrCurvePlot.jsx
// Industrial-grade SCAL curve renderer.
// Supports Kr, MICP Pc/PSD, RI (log-log), FF (log-log), J-Function, Pc-centrifuge, Overburden.

import React, { useMemo, useState } from 'react';
import {
  ComposedChart, Line, Scatter,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer,
} from 'recharts';
import { Activity, Beaker, CheckCircle, AlertTriangle, XCircle, Eye, EyeOff } from 'lucide-react';

// ── CONSTANTS ──────────────────────────────────────────────────────────────────
const WETTABILITY_CONFIG = {
  'strongly-water-wet': { label: 'Strongly Water-Wet', color: '#38bdf8', bg: 'bg-sky-950/40',   border: 'border-sky-700/40' },
  'water-wet':          { label: 'Water-Wet',          color: '#0ea5e9', bg: 'bg-sky-950/30',   border: 'border-sky-800/30' },
  'mixed-wet':          { label: 'Mixed-Wet',          color: '#a3e635', bg: 'bg-lime-950/30',  border: 'border-lime-700/30' },
  'oil-wet':            { label: 'Oil-Wet',            color: '#fb923c', bg: 'bg-orange-950/30',border: 'border-orange-700/30' },
  'strongly-oil-wet':   { label: 'Strongly Oil-Wet',  color: '#ef4444', bg: 'bg-red-950/30',   border: 'border-red-700/30' },
  'indeterminate':      { label: 'Indeterminate',      color: '#94a3b8', bg: 'bg-slate-900/30', border: 'border-slate-700/30' },
};

// ── LOG TICK FORMATTER ──────────────────────────────────────────────────────────
const logTickFmt = v => {
  if (v === 0) return '0';
  const abs = Math.abs(v);
  if (abs >= 1000) return v.toExponential(0);
  if (abs >= 100)  return Number(v.toFixed(0)).toString();
  if (abs >= 10)   return Number(v.toFixed(1)).toString();
  if (abs >= 1)    return Number(v.toFixed(2)).toString();
  return Number(v.toFixed(3)).toString();
};
const linTickFmt = v => v >= 1000 ? v.toExponential(1) : Number(v.toFixed(3)).toString();

// ── TOOLTIP ────────────────────────────────────────────────────────────────────
const KrTooltip = ({ active, payload, label, xLabel }) => {
  if (!active || !payload?.length) return null;

  const seen = new Set();
  const unique = payload.filter(p => {
    if (!p.name || seen.has(p.name)) return false;
    seen.add(p.name);
    return true;
  });

  return (
    <div className="bg-[#080810]/98 backdrop-blur-2xl border border-white/10 rounded-2xl
                    px-5 py-4 shadow-2xl shadow-black/60 text-[11px] font-mono min-w-[220px]">
      <div className="flex justify-between items-center mb-3 pb-2 border-b border-white/8">
        <span className="text-slate-500 uppercase tracking-widest text-[9px]">{xLabel || 'x'}</span>
        <span className="text-white font-black text-sm tracking-wider">
          {typeof label === 'number' ? label.toFixed(4) : label}
        </span>
      </div>

      {unique.map((entry, i) => {
        const isLab = entry.name?.includes('Lab') || entry.name?.includes('(Core');
        return (
          <div key={i} className="flex items-center justify-between gap-6 mb-2 last:mb-0">
            <div className="flex items-center gap-2">
              {isLab ? (
                <div className="w-2.5 h-2.5 rounded-full border border-[#080810]"
                     style={{ backgroundColor: entry.color }} />
              ) : (
                <div className="w-4 h-1 rounded-full" style={{ backgroundColor: entry.color }} />
              )}
              <span className="text-slate-400 truncate max-w-[120px]">{entry.name}</span>
            </div>
            <span className="font-black text-white tabular-nums">
              {typeof entry.value === 'number' ? entry.value.toFixed(4) : '—'}
            </span>
          </div>
        );
      })}
    </div>
  );
};

// ── VALIDATION BADGE ───────────────────────────────────────────────────────────
const ValidationBadge = ({ validation }) => {
  const [open, setOpen] = useState(false);
  if (!validation) return null;

  const { is_valid, warnings = [], errors = [] } = validation;
  const total = warnings.length + errors.length;

  const Icon  = errors.length > 0 ? XCircle : warnings.length > 0 ? AlertTriangle : CheckCircle;
  const color = errors.length > 0 ? 'text-red-400' : warnings.length > 0 ? 'text-yellow-400' : 'text-emerald-400';
  const bg    = errors.length > 0 ? 'bg-red-950/40 border-red-700/40'
              : warnings.length > 0 ? 'bg-yellow-950/40 border-yellow-700/40'
              : 'bg-emerald-950/40 border-emerald-700/40';

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className={`flex items-center gap-2 px-3.5 py-1.5 rounded-full border text-[10px] font-black
                    uppercase tracking-widest transition-all ${bg} ${color} shadow-lg shadow-black/20`}
      >
        <Icon className="w-3.5 h-3.5" />
        {is_valid ? 'Physics OK' : 'Physics Issues'}
        {total > 0 && <span className="ml-1 opacity-70">({total})</span>}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 z-50 w-80 bg-[#0c0c14]/98
                        border border-white/10 rounded-2xl p-4 shadow-2xl shadow-black/80
                        backdrop-blur-2xl text-[11px] font-mono">
          {errors.map((e, i) => (
            <div key={i} className="flex gap-2 mb-2 text-red-300">
              <XCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>{e}</span>
            </div>
          ))}
          {warnings.map((w, i) => (
            <div key={i} className="flex gap-2 mb-2 text-yellow-300">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>{w}</span>
            </div>
          ))}
          {total === 0 && (
            <div className="flex gap-2 text-emerald-300">
              <CheckCircle className="w-3.5 h-3.5 shrink-0" />
              <span>All physics checks passed.</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ── PARAMETER PANEL ────────────────────────────────────────────────────────────
const ParamPanel = ({ fit_params, endpoints, archie, jfunction }) => {
  // Archie params (RI / FF)
  if (archie) {
    const rows = [
      archie.n != null && ['n (saturation exp.)', archie.n?.toFixed(4)],
      archie.m != null && ['m (cementation exp.)', archie.m?.toFixed(4)],
      archie.a != null && ['a (tortuosity factor)', archie.a?.toFixed(4)],
    ].filter(Boolean);
    if (!rows.length) return null;
    return (
      <div className="mt-6">
        <div className="bg-[#0a0a0f] border border-white/5 rounded-2xl p-4 max-w-xs">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-[0.3em] mb-3">Archie Parameters</p>
          <table className="w-full text-[11px] font-mono">
            <tbody>
              {rows.map(([label, val], i) => (
                <tr key={i} className={i % 2 === 0 ? 'bg-white/[0.02]' : ''}>
                  <td className="py-1.5 px-2 text-slate-500">{label}</td>
                  <td className="py-1.5 px-2 text-white font-black text-right tabular-nums">{val}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  // J-function params
  if (jfunction) {
    const rows = [
      ['k (mD)', jfunction.k_md?.toFixed(2)],
      ['φ (fraction)', jfunction.phi?.toFixed(4)],
      ['σcosθ (mN/m)', jfunction.ift_cos_theta?.toFixed(2)],
    ];
    return (
      <div className="mt-6">
        <div className="bg-[#0a0a0f] border border-white/5 rounded-2xl p-4 max-w-xs">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-[0.3em] mb-3">J-Function Parameters</p>
          <table className="w-full text-[11px] font-mono">
            <tbody>
              {rows.map(([label, val], i) => (
                <tr key={i} className={i % 2 === 0 ? 'bg-white/[0.02]' : ''}>
                  <td className="py-1.5 px-2 text-slate-500">{label}</td>
                  <td className="py-1.5 px-2 text-white font-black text-right tabular-nums">{val}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  if (!fit_params?.model) return null;

  const isBC  = fit_params.model === 'Brooks-Corey' || fit_params.model === 'Brooks_Corey';
  const isLET = fit_params.model === 'LET';

  const rows = isBC ? [
    ['nw (water)', fit_params.nw?.toFixed(4)],
    ['no (oil)',   fit_params.no?.toFixed(4)],
    ['R² Krw',     fit_params['R²_Krw']?.toFixed(4)],
    ['R² Kro',     fit_params['R²_Kro']?.toFixed(4)],
  ] : isLET ? [
    ['Lw / Ew / Tw', `${fit_params.Lw} / ${fit_params.Ew} / ${fit_params.Tw}`],
    ['Lo / Eo / To', `${fit_params.Lo} / ${fit_params.Eo} / ${fit_params.To}`],
    ['R² Krw',        fit_params['R²_Krw']?.toFixed(4)],
    ['R² Kro',        fit_params['R²_Kro']?.toFixed(4)],
  ] : [];

  const epRows = endpoints ? [
    ['Swi', endpoints.Swi?.toFixed(4)],
    ['Sor', endpoints.Sor?.toFixed(4)],
    ['Krw_max', endpoints.Krw_max?.toFixed(4)],
    ['Kro_max', endpoints.Kro_max?.toFixed(4)],
  ] : [];

  return (
    <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-4">
      <div className="bg-[#0a0a0f] border border-white/5 rounded-2xl p-4">
        <p className="text-[9px] font-black text-slate-500 uppercase tracking-[0.3em] mb-3">
          {fit_params.model} Parameters
        </p>
        <table className="w-full text-[11px] font-mono">
          <tbody>
            {rows.map(([label, val], i) => (
              <tr key={i} className={i % 2 === 0 ? 'bg-white/[0.02]' : ''}>
                <td className="py-1.5 px-2 text-slate-500">{label}</td>
                <td className="py-1.5 px-2 text-white font-black text-right tabular-nums">{val}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {epRows.length > 0 && (
        <div className="bg-[#0a0a0f] border border-white/5 rounded-2xl p-4">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-[0.3em] mb-3">
            Endpoint Configuration
          </p>
          <table className="w-full text-[11px] font-mono">
            <tbody>
              {epRows.map(([label, val], i) => (
                <tr key={i} className={i % 2 === 0 ? 'bg-white/[0.02]' : ''}>
                  <td className="py-1.5 px-2 text-slate-500">{label}</td>
                  <td className="py-1.5 px-2 text-white font-black text-right tabular-nums">{val}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

// ── MAIN COMPONENT ─────────────────────────────────────────────────────────────
export default function KrCurvePlot({ plotData }) {
  const [hiddenCurves, setHiddenCurves] = useState(new Set());

  const data = useMemo(() => {
    try { return typeof plotData === 'string' ? JSON.parse(plotData) : plotData; }
    catch { return null; }
  }, [plotData]);

  const { lineChartData, lineSeries } = useMemo(() => {
    if (!data?.curves) return { lineChartData: [], lineSeries: [] };
    const lines = data.curves.filter(c => c.showLine !== false);
    const xMap = {};
    lines.forEach((curve) => {
      const gIdx = data.curves.indexOf(curve);
      curve.data.forEach(pt => {
        const key = pt.x.toFixed(6);
        if (!xMap[key]) xMap[key] = { x: pt.x };
        xMap[key][`line_${gIdx}`] = pt.y;
      });
    });
    return {
      lineChartData: Object.values(xMap).sort((a, b) => a.x - b.x),
      lineSeries:    lines,
    };
  }, [data]);

  if (!data?.curves) {
    return (
      <div className="p-10 bg-red-950/10 border border-red-900/30 rounded-2xl text-red-400 text-xs font-mono flex flex-col items-center gap-4">
        <Activity className="w-10 h-10 opacity-40" />
        <span className="uppercase tracking-widest font-black text-center">PRC Curve Engine — Parse Failure</span>
      </div>
    );
  }

  const meta        = data.metadata || {};
  const validation  = meta.validation  || {};
  const fit_params  = meta.fit_params  || {};
  const endpoints   = meta.endpoints   || {};
  const archie      = meta.archie      || null;
  const jfunction   = meta.jfunction   || null;
  const crossover   = validation.crossover || {};
  const wettConfig  = WETTABILITY_CONFIG[validation.wettability] || WETTABILITY_CONFIG['indeterminate'];

  // Log-scale flags
  const xLog      = !!data.xAxisLog;
  const yLog      = !!data.yAxisLog;
  const yRightLog = !!data.yAxisRightLog;

  const xTickFmt = xLog ? logTickFmt : linTickFmt;
  const yTickFmt = yLog ? logTickFmt : linTickFmt;
  const yRTickFmt = yRightLog ? logTickFmt : linTickFmt;

  const xLabel = data.xAxis?.label || 'x';

  const toggleCurve = name => {
    setHiddenCurves(prev => {
      const next = new Set(prev);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });
  };

  return (
    <div className="my-10 rounded-[2.5rem] border border-white/5 bg-[#04040a] shadow-[0_40px_80px_-20px_rgba(0,0,0,0.95)] overflow-hidden">
      <div className="px-8 pt-8 pb-6 border-b border-white/5 bg-gradient-to-b from-white/[0.025] to-transparent">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <div className="p-2 rounded-xl bg-sky-500/10 border border-sky-500/20">
                <Beaker className="w-4 h-4 text-sky-400" />
              </div>
              <span className="text-[9px] font-black tracking-[0.5em] text-sky-500/70 uppercase">PRC SCAL — Curve Engine v14</span>
            </div>
            <h2 className="text-xl font-black text-white tracking-tight">{data.title}</h2>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {validation.wettability && (
              <div className={`flex items-center gap-2 px-3.5 py-1.5 rounded-full border text-[10px] font-black uppercase tracking-widest ${wettConfig.bg} ${wettConfig.border} shadow-lg shadow-black/10`} style={{ color: wettConfig.color }}>
                <div className="w-2 h-2 rounded-full animate-pulse" style={{ backgroundColor: wettConfig.color }} />
                {wettConfig.label}
              </div>
            )}
            <ValidationBadge validation={validation} />
          </div>
        </div>
        {crossover.Sw != null && (
          <div className="mt-4 inline-flex items-center gap-3 px-4 py-2 bg-white/[0.03] border border-white/8 rounded-full text-[11px] font-mono">
            <div className="w-px h-4 bg-yellow-400/60" />
            <span className="text-slate-400">Crossover:</span>
            <span className="text-yellow-300 font-black">Sw = {crossover.Sw?.toFixed(4)}</span>
            <span className="text-slate-500">│</span>
            <span className="text-slate-400">Kr = {crossover.Kr?.toFixed(4)}</span>
          </div>
        )}
        {(xLog || yLog) && (
          <div className="mt-3 flex items-center gap-2 text-[9px] font-mono text-slate-600 uppercase tracking-widest">
            <span className="px-2.5 py-1 rounded-md bg-white/5 border border-white/5">LOG-LOG AXES</span>
            {xLog && <span>X: log</span>}
            {yLog && <span>Y: log</span>}
          </div>
        )}
      </div>

      <div className="px-6 py-8 relative">
        <div className="absolute inset-0 opacity-[0.018] pointer-events-none" style={{ backgroundImage: 'radial-gradient(circle, #fff 1px, transparent 1px)', backgroundSize: '28px 28px' }} />
        <ResponsiveContainer width="100%" height={420}>
          <ComposedChart data={lineChartData} margin={{ top: 10, right: 60, bottom: 48, left: 10 }}>
            <CartesianGrid strokeDasharray="2 4" stroke="#ffffff06" vertical={false} />
            <XAxis
              dataKey="x"
              type="number"
              scale={xLog ? 'log' : 'linear'}
              domain={xLog ? ['auto', 'auto'] : [0, 'auto']}
              allowDataOverflow={xLog}
              stroke="#ffffff10"
              tick={{ fontSize: 10, fill: '#475569', fontFamily: 'monospace' }}
              tickFormatter={xTickFmt}
              label={{ value: xLabel, position: 'insideBottom', offset: -32, fill: '#64748b', fontSize: 11, fontWeight: 700, fontFamily: 'monospace', letterSpacing: '0.1em' }}
            />
            <YAxis
              yAxisId="left"
              scale={yLog ? 'log' : 'linear'}
              domain={yLog ? ['auto', 'auto'] : [0, 'auto']}
              allowDataOverflow={yLog}
              stroke="#38bdf830"
              tick={{ fontSize: 10, fill: '#38bdf8', fontFamily: 'monospace' }}
              tickFormatter={yTickFmt}
              label={{ value: data.yAxis?.label || 'y', angle: -90, position: 'insideLeft', offset: 14, fill: '#38bdf8', fontSize: 10, fontWeight: 700, fontFamily: 'monospace' }}
            />
            {data.dualAxis && (
              <YAxis
                yAxisId="right"
                orientation="right"
                scale={yRightLog ? 'log' : 'linear'}
                domain={yRightLog ? ['auto', 'auto'] : [0, 'auto']}
                allowDataOverflow={yRightLog}
                stroke="#fb923c30"
                tick={{ fontSize: 10, fill: '#fb923c', fontFamily: 'monospace' }}
                tickFormatter={yRTickFmt}
                label={{ value: data.yAxis2?.label || 'y2', angle: 90, position: 'insideRight', offset: 14, fill: '#fb923c', fontSize: 10, fontWeight: 700, fontFamily: 'monospace' }}
              />
            )}
            <Tooltip content={<KrTooltip xLabel={xLabel} />} />
            {crossover.Sw != null && (
              <ReferenceLine x={crossover.Sw} yAxisId="left" stroke="#facc15" strokeWidth={1.5} strokeDasharray="5 4" />
            )}
            {data.curves.map((curve, idx) => {
              if (curve.showLine === false) return null;
              const axisId  = data.dualAxis && curve.yId === 'right' ? 'right' : 'left';
              const opacity = hiddenCurves.has(curve.name) ? 0 : 1;
              return (
                <Line
                  key={`line-${idx}`}
                  yAxisId={axisId}
                  dataKey={`line_${idx}`}
                  name={curve.name}
                  stroke={curve.color}
                  strokeWidth={2.5}
                  strokeOpacity={opacity}
                  strokeDasharray={curve.dashed ? '8 5' : undefined}
                  dot={false}
                  type="monotone"
                  connectNulls
                />
              );
            })}
            {data.curves.map((curve, idx) => {
              if (curve.showPoints === false) return null;
              const axisId  = data.dualAxis && curve.yId === 'right' ? 'right' : 'left';
              const opacity = hiddenCurves.has(curve.name) ? 0 : 1;
              return (
                <Scatter
                  key={`scatter-${idx}`}
                  yAxisId={axisId}
                  name={curve.name}
                  data={curve.data}
                  dataKey="y"
                  fill={curve.color}
                  fillOpacity={opacity}
                  stroke="#04040a"
                  strokeWidth={1.5}
                  r={5}
                />
              );
            })}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* ── INTERACTIVE LEGEND ─────────────────────────────────────────────────── */}
      <div className="px-8 py-5 border-t border-white/5 bg-black/30 flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
          {data.curves.map((curve, idx) => {
            const hidden = hiddenCurves.has(curve.name);
            return (
              <button
                key={idx}
                onClick={() => toggleCurve(curve.name)}
                title={hidden ? 'Show curve' : 'Hide curve'}
                className={`flex items-center gap-2.5 rounded-xl px-2.5 py-1.5 transition-all
                            ${hidden ? 'opacity-30 hover:opacity-60' : 'opacity-100 hover:opacity-80'}
                            border border-transparent hover:border-white/10`}
              >
                {curve.showLine !== false ? (
                  <svg width="20" height="4">
                    <line x1="0" y1="2" x2="20" y2="2"
                          stroke={curve.color} strokeWidth="2.5" strokeLinecap="round"
                          strokeDasharray={curve.dashed ? '5 3' : undefined}
                          strokeOpacity={hidden ? 0.3 : 1} />
                  </svg>
                ) : (
                  <div className="w-3 h-3 rounded-full border-2 border-[#04040a]"
                       style={{ backgroundColor: curve.color, opacity: hidden ? 0.3 : 1 }} />
                )}
                <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">
                  {curve.name}
                </span>
                {hidden
                  ? <EyeOff className="w-2.5 h-2.5 text-slate-600" />
                  : <Eye    className="w-2.5 h-2.5 text-slate-700" />
                }
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2 text-slate-700 text-[9px] font-mono tracking-widest uppercase">
          <Activity className="w-3 h-3 text-sky-700/50" />
          <span>PRC-SCAL-ENGINE-V14</span>
        </div>
      </div>

      <div className="px-8 pb-8">
        <ParamPanel fit_params={fit_params} endpoints={endpoints} archie={archie} jfunction={jfunction} />
      </div>
    </div>
  );
}
