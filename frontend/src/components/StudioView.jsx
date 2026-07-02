// frontend/src/components/StudioView.jsx
// Industrial Glass-Brutalist "Petrophysical Studio" — an additive tab.
// Split-pane: [Ingestion + Telemetry + SVG plotter] · [Corey params] · [Co-Pilot].
//
// Chat is driven by the SAME state + handleSend passed from App — no SSE,
// session, or Axios logic is duplicated here. Telemetry / Corey-exponent state
// is local (pure UI, no backend coupling). All curve math comes from the
// unit-tested ../lib/petrophysics module.

import React, { useMemo, useRef, useEffect, useState } from 'react';
import { Upload, FileText, Send, Loader, Activity, Beaker, Database, X } from 'lucide-react';
import { coreyCurves, pointsToSvgPath, mergeFilesDedup } from '../lib/petrophysics';
import { renderMessageContent } from './MessageRenderer';

const SKY = 'var(--color-data-sky)';
const GOLD = 'var(--color-brand-gold)';

// SVG plot geometry — padded inner box so axes/labels have room.
const W = 520;
const H = 360;
const PAD = 44;
const INNER_W = W - 2 * PAD;
const INNER_H = H - 2 * PAD;
const TICKS = [0, 0.25, 0.5, 0.75, 1];
const fx = (f) => PAD + f * INNER_W;        // domain fraction → x px
const fy = (f) => PAD + (1 - f) * INNER_H;  // domain fraction → y px (inverted)

const TELE_CARDS = [
  { key: 'porosity',     label: 'Porosity',     unit: 'φ frac',  max: 0.4,    step: 0.001 },
  { key: 'permeability', label: 'Permeability', unit: 'mD',      max: 1000,   step: 1 },
  { key: 'swi',          label: 'Swi',          unit: 'frac',    max: 1,      step: 0.01 },
  { key: 'sor',          label: 'Sor',          unit: 'frac',    max: 1,      step: 0.01 },
];

export default function StudioView({
  messages, input, setInput, handleSend, loading, files, setFiles, serverStatus,
}) {
  const [tele, setTele]   = useState({ porosity: 0.22, permeability: 150, swi: 0.15, sor: 0.20 });
  const [corey, setCorey] = useState({ nw: 2.5, no: 3.0, krwMax: 0.6, kroMax: 0.9 });
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);
  const chatEndRef = useRef(null);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  // Real-time Corey curves — redrawn whenever any endpoint or exponent changes.
  const { krw, kro } = useMemo(
    () => coreyCurves({
      Swi: tele.swi, Sor: tele.sor,
      nw: corey.nw, no: corey.no,
      krwMax: corey.krwMax, kroMax: corey.kroMax,
      samples: 60,
    }),
    [tele.swi, tele.sor, corey.nw, corey.no, corey.krwMax, corey.kroMax],
  );
  const krwPath = useMemo(() => pointsToSvgPath(krw, { width: W, height: H, padding: PAD }), [krw]);
  const kroPath = useMemo(() => pointsToSvgPath(kro, { width: W, height: H, padding: PAD }), [kro]);

  const acceptDrop = (fileList) => {
    const incoming = Array.from(fileList || []);
    if (incoming.length) setFiles((prev) => mergeFilesDedup(prev, incoming));
  };

  const setTeleVal   = (k, v) => setTele((p) => ({ ...p, [k]: Number.isFinite(+v) ? +v : 0 }));
  const setCoreyVal  = (k, v) => setCorey((p) => ({ ...p, [k]: +v }));

  const sendDisabled = loading || serverStatus === 'waking' || (!input.trim() && files.length === 0);

  return (
    <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[minmax(0,1.2fr)_280px_minmax(380px,460px)] gap-3 p-3 overflow-hidden bg-mesh">

      {/* ══ CENTER · Petrophysical Dashboard ══════════════════════════════ */}
      <section className="glass-brutal rounded-none flex flex-col min-h-0 overflow-y-auto custom-scrollbar p-4 gap-4">
        <h2 className="text-[11px] font-mono uppercase tracking-[0.3em] text-[color:var(--color-brand-gold)] flex items-center gap-2">
          <Database className="w-3.5 h-3.5" /> Petrophysical Dashboard
        </h2>

        {/* ── Ingestion Zone ── */}
        <div
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={(e) => { e.preventDefault(); setDragOver(false); }}
          onDrop={(e) => { e.preventDefault(); setDragOver(false); acceptDrop(e.dataTransfer.files); }}
          className={`glass-brutal rounded-none cursor-pointer px-5 py-7 flex flex-col items-center justify-center gap-2 text-center transition-all ${dragOver ? 'glass-brutal-active' : ''}`}
          data-testid="ingestion-zone"
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".txt,.pdf,.csv,.xlsx,.xls,.doc,.docx,image/jpeg,image/png,image/gif,image/webp"
            className="hidden"
            onChange={(e) => { acceptDrop(e.target.files); e.target.value = ''; }}
          />
          <Upload className={`w-6 h-6 ${dragOver ? 'text-[color:var(--color-brand-amber)]' : 'text-slate-500'}`} />
          <span className="text-[11px] font-mono uppercase tracking-widest text-slate-400">
            {dragOver ? 'Release to ingest core data' : 'Drag SCAL files here or click to browse'}
          </span>
          <span className="text-[9px] font-mono text-slate-600 uppercase">XLSX · CSV · PDF · DOCX · IMG</span>
        </div>

        {files.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {files.map((f, i) => (
              <div key={i} className="flex items-center gap-2 glass-brutal rounded-none px-2.5 py-1.5">
                <FileText className="w-3 h-3 text-[color:var(--color-data-sky)] shrink-0" />
                <span className="text-[10px] font-mono text-slate-300 truncate max-w-[140px]">{f.name}</span>
                <button
                  onClick={(e) => { e.stopPropagation(); setFiles((prev) => prev.filter((_, idx) => idx !== i)); }}
                  className="text-slate-600 hover:text-red-400"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* ── Telemetry Cards ── */}
        <div className="grid grid-cols-2 gap-3">
          {TELE_CARDS.map((c) => {
            const val = tele[c.key];
            const pct = Math.max(0, Math.min(100, (val / c.max) * 100));
            return (
              <div key={c.key} className="glass-brutal rounded-none p-3 flex flex-col gap-2" data-testid={`tele-${c.key}`}>
                <div className="flex items-center justify-between">
                  <span className="text-[9px] font-mono uppercase tracking-[0.2em] text-slate-500">{c.label}</span>
                  <span className="text-[8px] font-mono text-slate-600 uppercase">{c.unit}</span>
                </div>
                <input
                  type="number"
                  value={val}
                  min={0}
                  max={c.max}
                  step={c.step}
                  onChange={(e) => setTeleVal(c.key, e.target.value)}
                  className="w-full bg-[color:var(--color-bg-base)] border border-[color:var(--color-border-brutal)] rounded-none px-2 py-1.5 text-sm font-mono text-white outline-none focus:border-[color:var(--color-data-sky)]"
                />
                <div className="h-1 w-full bg-[color:var(--color-bg-base)] overflow-hidden">
                  <div className="h-full transition-all duration-300" style={{ width: `${pct}%`, background: SKY }} />
                </div>
              </div>
            );
          })}
        </div>

        {/* ── Real-Time SVG Corey Plotter ── */}
        <div className="glass-brutal rounded-none p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-mono uppercase tracking-[0.25em] text-[color:var(--color-brand-gold)] flex items-center gap-2">
              <Beaker className="w-3.5 h-3.5" /> Relative Permeability — Corey
            </span>
            <span className="text-[9px] font-mono text-slate-600">krw / kro vs Sw</span>
          </div>
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" data-testid="corey-svg" role="img" aria-label="Corey relative permeability curves">
            {/* grid + ticks */}
            {TICKS.map((t) => (
              <g key={`gx-${t}`}>
                <line x1={fx(t)} y1={fy(0)} x2={fx(t)} y2={fy(1)} stroke="#ffffff0d" strokeWidth="1" />
                <text x={fx(t)} y={fy(0) + 16} fill="#64748b" fontSize="9" fontFamily="monospace" textAnchor="middle">{t.toFixed(2)}</text>
              </g>
            ))}
            {TICKS.map((t) => (
              <g key={`gy-${t}`}>
                <line x1={fx(0)} y1={fy(t)} x2={fx(1)} y2={fy(t)} stroke="#ffffff0d" strokeWidth="1" />
                <text x={fx(0) - 8} y={fy(t) + 3} fill="#64748b" fontSize="9" fontFamily="monospace" textAnchor="end">{t.toFixed(2)}</text>
              </g>
            ))}
            {/* axes */}
            <line x1={fx(0)} y1={fy(0)} x2={fx(1)} y2={fy(0)} stroke="#ffffff25" strokeWidth="1.5" />
            <line x1={fx(0)} y1={fy(0)} x2={fx(0)} y2={fy(1)} stroke="#ffffff25" strokeWidth="1.5" />
            {/* curves */}
            <path d={kroPath} fill="none" stroke="var(--color-brand-amber)" strokeWidth="2.5" />
            <path d={krwPath} fill="none" stroke="var(--color-data-sky)" strokeWidth="2.5" />
            {/* axis labels */}
            <text x={fx(0.5)} y={H - 6} fill="#475569" fontSize="10" fontFamily="monospace" textAnchor="middle" letterSpacing="2">Sw — WATER SATURATION</text>
            <text x={12} y={fy(0.5)} fill="#475569" fontSize="10" fontFamily="monospace" textAnchor="middle" transform={`rotate(-90 12 ${fy(0.5)})`} letterSpacing="2">Kr</text>
          </svg>
          <div className="flex items-center gap-5 mt-2 px-2">
            <span className="flex items-center gap-2 text-[10px] font-mono text-slate-400"><span className="w-4 h-0.5" style={{ background: SKY }} /> krw (water)</span>
            <span className="flex items-center gap-2 text-[10px] font-mono text-slate-400"><span className="w-4 h-0.5" style={{ background: 'var(--color-brand-amber)' }} /> kro (oil)</span>
          </div>
        </div>
      </section>

      {/* ══ Simulation Parameters Sidebar ════════════════════════════════ */}
      <aside className="glass-brutal rounded-none flex flex-col min-h-0 overflow-y-auto custom-scrollbar p-4 gap-5">
        <h2 className="text-[11px] font-mono uppercase tracking-[0.3em] text-[color:var(--color-brand-gold)] flex items-center gap-2">
          <Activity className="w-3.5 h-3.5" /> Corey Exponents
        </h2>

        {[
          { key: 'nw', label: 'nw — water exponent' },
          { key: 'no', label: 'no — oil exponent' },
        ].map(({ key, label }) => (
          <div key={key} className="flex flex-col gap-2" data-testid={`slider-${key}`}>
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono uppercase tracking-widest text-slate-400">{label}</span>
              <span className="text-xs font-mono font-bold text-[color:var(--color-data-sky)] tabular-nums">{corey[key].toFixed(1)}</span>
            </div>
            <input
              type="range" min="1" max="6" step="0.1"
              value={corey[key]}
              onChange={(e) => setCoreyVal(key, e.target.value)}
              className="w-full accent-[color:var(--color-brand-amber)]"
            />
          </div>
        ))}

        <div className="h-px bg-[color:var(--color-border-brutal)]" />

        {[
          { key: 'krwMax', label: 'krw,max' },
          { key: 'kroMax', label: 'kro,max' },
        ].map(({ key, label }) => (
          <div key={key} className="flex flex-col gap-2">
            <span className="text-[10px] font-mono uppercase tracking-widest text-slate-400">{label}</span>
            <input
              type="number" min="0" max="1" step="0.05"
              value={corey[key]}
              onChange={(e) => setCoreyVal(key, e.target.value)}
              className="w-full bg-[color:var(--color-bg-base)] border border-[color:var(--color-border-brutal)] rounded-none px-2 py-1.5 text-sm font-mono text-white outline-none focus:border-[color:var(--color-data-sky)]"
            />
          </div>
        ))}

        <p className="mt-auto text-[9px] font-mono text-slate-600 uppercase tracking-widest leading-relaxed">
          Curves redraw live · mirrors backend Brooks-Corey kernel
        </p>
      </aside>

      {/* ══ RIGHT · Sovereign Co-Pilot (terminal chat) ═══════════════════ */}
      <section className="glass-brutal rounded-none flex flex-col min-h-0 relative overflow-hidden bg-[color:var(--color-bg-surface)]">
        <div className="px-4 py-3.5 border-b border-[color:var(--color-border-brutal)] flex items-center justify-between shrink-0 bg-black/20">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[color:var(--color-brand-gold)] animate-pulse" />
            <span className="text-[11px] font-sans font-bold uppercase tracking-[0.2em] text-white">Hviel Co-Pilot</span>
          </div>
          <span className="text-[9px] font-mono text-slate-500 uppercase bg-black/60 px-1.5 py-0.5 border border-slate-800">ONLINE</span>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar p-4 space-y-4 relative z-0">
          {messages.map((m, i) => (
            <div key={i} className={`flex flex-col w-full ${m.role === 'user' ? 'items-end' : 'items-start'}`}>
              <div 
                className={`px-3.5 py-2.5 text-xs font-sans leading-relaxed rounded-2xl max-w-[90%] shadow-lg border ${
                  m.role === 'user' 
                    ? 'bg-slate-800/70 border-slate-700/30 text-slate-200 rounded-tr-none' 
                    : 'bg-slate-900/70 border-slate-800/40 text-slate-100 rounded-tl-none'
                }`}
              >
                {renderMessageContent(m.text)}
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex items-center gap-2 text-xs font-sans text-slate-500 italic animate-pulse">
              <Loader className="w-3.5 h-3.5 animate-spin" />
              <span>Thinking...</span>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        <div className="p-3 border-t border-[color:var(--color-border-brutal)] shrink-0 bg-black/20 relative z-20">
          <div className="flex items-end gap-2 bg-[#050508] border border-[color:var(--color-border-brutal)] p-2 rounded-xl focus-within:border-[color:var(--color-brand-amber)] transition-all">
            <textarea
              rows={1}
              value={input}
              disabled={serverStatus === 'waking'}
              onChange={(e) => {
                setInput(e.target.value);
                e.target.style.height = 'auto';
                e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  if (!sendDisabled) handleSend();
                }
              }}
              placeholder={serverStatus === 'waking' ? 'Establishing link…' : 'Query Hviel…'}
              className="flex-1 bg-transparent outline-none resize-none text-xs font-sans text-slate-100 placeholder-slate-700 max-h-32 py-1 leading-relaxed"
            />
            <button
              onClick={() => { if (!sendDisabled) handleSend(); }}
              disabled={sendDisabled}
              className="shrink-0 p-2 rounded-lg bg-[color:var(--color-brand-amber)] hover:bg-amber-500 text-black disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? <Loader className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
