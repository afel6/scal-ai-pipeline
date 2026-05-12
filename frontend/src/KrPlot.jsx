/* eslint-disable no-unused-vars */
import React, { useMemo, useState, useEffect } from 'react';
import {
  Line, Scatter,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ComposedChart,
} from 'recharts';
import { AreaChart, Beaker, FileText, Activity } from 'lucide-react';

const COLORS = [
  '#38bdf8', // sky-blue  (water)
  '#fb923c', // orange    (oil)
  '#10b981', // emerald   (gas)
  '#f43f5e', // rose
  '#8b5cf6', // violet
  '#eab308', // yellow
];

// ── Custom tooltip ─────────────────────────────────────────────────────────────
const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#0c0c14]/95 backdrop-blur-xl border border-white/10 rounded-none px-5 py-4 shadow-2xl text-[11px] font-mono min-w-[180px]">
      <div className="text-slate-500 mb-2 border-b border-white/5 pb-1 flex justify-between">
        <span>X:</span>
        <span className="text-white font-black">
          {typeof label === 'number' ? label.toFixed(4) : label}
        </span>
      </div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color }} className="flex gap-4 items-center mb-1.5 last:mb-0">
          <span className="font-bold opacity-70 w-32 truncate">{p.name}:</span>
          <span className="font-black tracking-wider text-white ml-auto">
            {typeof p.value === 'number' ? p.value.toFixed(4) : p.value}
          </span>
        </div>
      ))}
    </div>
  );
};

// ── Main component ─────────────────────────────────────────────────────────────
export default function KrPlot({ content }) {
  const data = useMemo(() => {
    try { return typeof content === 'string' ? JSON.parse(content) : content; }
    catch { return null; }
  }, [content]);

  // Build shared chartData for Line series only.
  // Scatter series use their own curve.data prop directly — this prevents
  // the Recharts bug where Scatter would read dataKey from the merged xMap
  // instead of its own data array.
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const { lineChartData, lineCurves, scatterCurves } = useMemo(() => {
    if (!data?.curves) return { lineChartData: [], lineCurves: [], scatterCurves: [] };

    const lineCurves    = data.curves.filter(c => c.showLine    !== false);
    const scatterCurves = data.curves.filter(c => c.showPoints  !== false);

    const xMap = {};
    lineCurves.forEach((curve, idx) => {
      const globalIdx = data.curves.indexOf(curve);
      curve.data.forEach(pt => {
        if (!xMap[pt.x]) xMap[pt.x] = { x: pt.x };
        xMap[pt.x][`line_${globalIdx}`] = pt.y;
      });
    });

    return {
      lineChartData: Object.values(xMap).sort((a, b) => a.x - b.x),
      lineCurves,
      scatterCurves,
    };
  }, [data]);

  if (!data?.curves) {
    return (
      <div className="p-8 bg-red-950/10 border border-red-900/30 rounded-none-[2rem] text-red-400 text-xs font-mono flex flex-col items-center gap-4">
        <Activity className="w-8 h-8 opacity-50" />
        <span className="tracking-[0.2em] font-black uppercase text-center">
          CRITICAL: PRC Plotting Engine Parse Failure
        </span>
      </div>
    );
  }

  const title  = data.title         || 'Petrophysical Analysis';
  const xLabel = data.xAxis?.label  || 'X Axis';
  const yLabel = data.yAxis?.label  || 'Y Axis';
  const y2Label= data.yAxis2?.label || '';
  const xScale = data.xAxis?.type   === 'log' ? 'log' : 'number';
  const yScale = data.yAxis?.type   === 'log' ? 'log' : 'number';
  const y2Scale= data.yAxis2?.type  === 'log' ? 'log' : 'number';

  return (
    <div className={`chart-container ${visible ? 'entered' : 'entering'} my-12 rounded-none-[2.5rem] border border-[var(--prc-border-gold)] bg-[#050508] shadow-[0_32px_64px_-16px_rgba(0,0,0,0.9)] overflow-hidden group hover:border-[var(--prc-border-focus)] transition-all duration-700`}>

      {/* Header */}
      <div className="px-10 py-8 border-b border-white/5 bg-gradient-to-b from-white/[0.03] to-transparent flex flex-col sm:flex-row items-start sm:items-end justify-between gap-6">
        <div className="max-w-2xl">
          <div className="flex items-center gap-4 mb-3">
            <div className="p-2.5 rounded-none bg-blue-500/10 text-blue-400 border border-blue-500/20 shadow-[0_0_20px_rgba(59,130,246,0.2)]">
              <AreaChart className="w-5 h-5" />
            </div>
            <span className="text-[10px] font-black tracking-[0.5em] text-blue-500/80 uppercase">
              PRC High-Fidelity Engine
            </span>
          </div>
          <h2 className="text-2xl font-black text-white tracking-tight leading-none mb-4">{title}</h2>
          <div className="flex flex-wrap items-center gap-5">
            <div className="flex items-center gap-2">
              <Beaker className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-[10px] font-mono text-slate-500 uppercase tracking-widest">
                Laboratory Calibrated
              </span>
            </div>
            <div className="w-[1px] h-3 bg-white/10 hidden sm:block" />
            <div className="flex items-center gap-2">
              <FileText className="w-3.5 h-3.5 text-blue-400" />
              <span className="text-[10px] font-mono text-slate-500 uppercase tracking-widest">
                SCAL Data: {data.curves.length} Series
              </span>
            </div>
          </div>
        </div>

        <div className="flex flex-col items-end gap-2 shrink-0">
          <div className="flex items-center gap-2.5 px-4 py-1.5 rounded-none bg-emerald-500/10 border border-emerald-500/20 shadow-[0_0_15px_rgba(16,185,129,0.1)]">
            <div className="w-2 h-2 rounded-none bg-emerald-500 animate-pulse" />
            <span className="text-[9px] text-emerald-400 font-black uppercase tracking-[0.2em]">
              Validated
            </span>
          </div>
          <span className="text-[10px] font-mono text-slate-700 uppercase tracking-tighter">
            PRC-VIS-CORE-V14
          </span>
        </div>
      </div>

      {/* Chart */}
      <div className="p-10 pb-6 relative">
        <div
          className="absolute inset-0 opacity-[0.02] pointer-events-none"
          style={{ backgroundImage: 'radial-gradient(circle, #fff 1px, transparent 1px)', backgroundSize: '32px 32px' }}
        />

        <ResponsiveContainer width="100%" height={450}>
          {/*
            ComposedChart receives lineChartData for Line components.
            Scatter components inject their own data prop independently,
            keyed by the same 'x' field that XAxis reads.
          */}
          <ComposedChart
            data={lineChartData}
            margin={{ top: 20, right: 40, bottom: 40, left: 10 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#ffffff05" vertical={false} />

            <XAxis
              dataKey="x"
              type="number"
              scale={xScale}
              domain={['auto', 'auto']}
              allowDataOverflow
              stroke="#ffffff15"
              tick={{ fontSize: 10, fill: '#64748b', fontFamily: 'monospace' }}
              label={{
                value: xLabel, position: 'insideBottom', offset: -25,
                fill: '#475569', fontSize: 11, fontWeight: 700,
                letterSpacing: '0.15em', textAnchor: 'middle',
              }}
              tickFormatter={v => v >= 1000 ? v.toExponential(1) : Number(v.toFixed(3)).toString()}
            />

            {/* Left Y axis (primary) */}
            <YAxis
              yAxisId="left"
              type="number"
              scale={yScale}
              domain={['auto', 'auto']}
              allowDataOverflow
              stroke="#ffffff15"
              tick={{ fontSize: 10, fill: '#64748b', fontFamily: 'monospace' }}
              label={{
                value: yLabel, angle: -90, position: 'insideLeft', offset: 15,
                fill: '#475569', fontSize: 11, fontWeight: 700, letterSpacing: '0.15em',
              }}
              tickFormatter={v => v >= 1000 ? v.toExponential(1) : Number(v.toFixed(3)).toString()}
            />

            {/* Right Y axis (dual-axis mode) */}
            {data.dualAxis && (
              <YAxis
                yAxisId="right"
                orientation="right"
                type="number"
                scale={y2Scale}
                domain={['auto', 'auto']}
                allowDataOverflow
                stroke="#ffffff15"
                tick={{ fontSize: 10, fill: '#64748b', fontFamily: 'monospace' }}
                label={{
                  value: y2Label, angle: 90, position: 'insideRight', offset: 15,
                  fill: '#475569', fontSize: 11, fontWeight: 700, letterSpacing: '0.15em',
                }}
                tickFormatter={v => v >= 1000 ? v.toExponential(1) : Number(v.toFixed(3)).toString()}
              />
            )}

            <Tooltip content={<CustomTooltip />} />

            {/* ── Line series (fitted models) ──────────────────────────────── */}
            {data.curves.map((curve, idx) => {
              if (curve.showLine === false) return null;
              const color    = curve.color || COLORS[idx % COLORS.length];
              const axisId   = (data.dualAxis && curve.yId === 'right') ? 'right' : 'left';
              return (
                <Line
                  key={`line-${idx}`}
                  yAxisId={axisId}
                  dataKey={`line_${idx}`}
                  name={curve.name}
                  stroke={color}
                  strokeWidth={2.5}
                  dot={false}
                  type="monotone"
                  connectNulls
                  isAnimationActive
                  animationDuration={1200}
                  activeDot={{ r: 6, strokeWidth: 0, fill: color }}
                />
              );
            })}

            {/* ── Scatter series (raw lab data) ────────────────────────────── */}
            {data.curves.map((curve, idx) => {
              if (curve.showPoints === false) return null;
              const color  = curve.color || COLORS[idx % COLORS.length];
              const axisId = (data.dualAxis && curve.yId === 'right') ? 'right' : 'left';
              return (
                <Scatter
                  key={`scatter-${idx}`}
                  yAxisId={axisId}
                  name={`${curve.name} (Lab)`}
                  /*
                   * Provide curve.data directly so each point {x, y} is
                   * positioned using XAxis dataKey="x" and our dataKey="y".
                   * This fixes the original bug where Scatter read from the
                   * shared lineChartData keyed as `curve_N`, finding nothing.
                   */
                  data={curve.data}
                  dataKey="y"
                  fill={color}
                  stroke="#0c0c14"
                  strokeWidth={1.5}
                  r={5}
                  isAnimationActive
                  animationDuration={800}
                />
              );
            })}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Legend + footer */}
      <div className="px-10 py-6 border-t border-white/5 bg-black/40 flex flex-wrap items-center justify-between gap-6">
        <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
          {data.curves.slice(0, 6).map((curve, idx) => {
            const color = curve.color || COLORS[idx % COLORS.length];
            return (
              <div key={idx} className="flex items-center gap-3">
                {curve.showLine !== false ? (
                  // Line swatch
                  <div className="w-6 h-0.5 rounded-none" style={{ backgroundColor: color }} />
                ) : (
                  // Scatter dot swatch
                  <div
                    className="w-3 h-3 rounded-none border border-[#0c0c14]"
                    style={{ backgroundColor: color, boxShadow: `0 0 8px ${color}80` }}
                  />
                )}
                <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest italic">
                  {curve.name}
                </span>
              </div>
            );
          })}
        </div>

        <div className="flex items-center gap-4 text-slate-700 border-l border-white/5 pl-6 ml-auto">
          <Activity className="w-3.5 h-3.5 text-blue-500/50" />
          <span className="text-[9px] font-mono tracking-widest uppercase">
            Verified Simulation Output
          </span>
        </div>
      </div>

      {/* Physics audit card — rendered when backend injects metadata.physics_audit */}
      {data.metadata?.physics_audit && (() => {
        const a = data.metadata.physics_audit;
        const badgeClass = a.score >= 95 ? 'pass' : a.score >= 60 ? 'warn' : 'fail';
        return (
          <div className="physics-audit-card mx-10 mb-8">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-black text-slate-500 uppercase tracking-[0.25em]">
                Physics Health Audit · {a.rules_checked} rules checked
              </span>
              <span className={`score-badge ${badgeClass}`}>{a.score}%</span>
            </div>
            <p className="text-[10px] text-slate-400 font-mono mb-2 leading-relaxed">{a.summary}</p>
            {a.violations.map((v, i) => (
              <div key={i} className="violation-row">
                [{v.severity}] {v.rule} — {v.detail}
              </div>
            ))}
          </div>
        );
      })()}
    </div>
  );
}
