/* eslint-disable */
import React from 'react';
import { Database, Activity, CheckCircle2 } from 'lucide-react';
import Mermaid from '../Mermaid';
import PetrophysicalTable from './PetrophysicalTable';
import SimulationHeatmap from '../SimulationHeatmap';
import KrCurvePlot from './KrCurvePlot';

const SectionHeader = ({ text }) => {
  const lowerText = text.toLowerCase();
  const isComplete = lowerText.includes('complete') || lowerText.includes('done') || lowerText.includes('phase 3') || lowerText.includes('certified');
  const isPhase = lowerText.includes('phase');
  
  return (
    <div className={`flex items-center gap-5 my-12 group animate-fade-in ${isPhase ? 'mt-16 mb-10' : 'my-10'}`}>
      <div className={`flex-none w-14 h-14 rounded-none flex items-center justify-center transition-all duration-700 shadow-[0_0_30px_rgba(0,0,0,0.5)] border-2 ${
        isComplete ? 'bg-green-500/20 text-green-400 border-green-500/50 shadow-green-500/10' : 
        isPhase ? 'bg-blue-600/20 text-blue-400 border-blue-500/50 shadow-blue-500/10' :
        'bg-yellow-500/20 text-yellow-400 border-yellow-500/50 shadow-yellow-500/10'
      } group-hover:scale-110 group-hover:rotate-3 relative overflow-hidden`}>
        <div className="absolute inset-0 bg-gradient-to-br from-white/10 to-transparent opacity-50" />
        {isComplete ? <CheckCircle2 className="w-7 h-7 animate-pulse-slow" /> : <Activity className="w-7 h-7" />}
      </div>
      <div className="flex-1">
        <div className="flex items-center gap-5">
          <h3 className={`font-black uppercase tracking-[0.4em] text-white whitespace-nowrap drop-shadow-md ${isPhase ? 'text-xl text-blue-400' : 'text-base text-slate-100'}`}>
            {text.replace(/###\s*/, '').replace(/\.$/, '')}
          </h3>
          <div className={`h-[2px] w-full bg-gradient-to-r ${isPhase ? 'from-blue-500/50' : 'from-slate-200/20'} via-transparent to-transparent`} />
        </div>
        <p className="text-[12px] font-mono text-slate-400 uppercase tracking-[0.3em] mt-2 flex items-center gap-3">
          <span className={`w-2.5 h-2.5 rounded-none animate-pulse ${isComplete ? 'bg-green-500' : isPhase ? 'bg-blue-500' : 'bg-yellow-500'}`} />
          {isComplete ? 'PRC SYSTEM CERTIFICATION ACTIVE' : isPhase ? 'STRUCTURAL PIPELINE MILESTONE' : 'ENGINEERING OBSERVATION'}
        </p>
      </div>
    </div>
  );
};

const KnowledgeCard = ({ title, content }) => {
  return (
    <div className="my-8 relative group animate-fade-in">
      <div className="absolute -inset-0.5 bg-gradient-to-r from-blue-500/20 to-purple-500/20 rounded-none blur opacity-30 group-hover:opacity-100 transition duration-1000"></div>
      <div className="relative bg-[#0d1117]/80 backdrop-blur-xl border border-white/10 rounded-none overflow-hidden shadow-2xl">
        <div className="bg-gradient-to-r from-blue-900/40 to-transparent p-4 border-b border-white/5">
          <h4 className="text-sm font-black text-blue-100 uppercase tracking-widest flex items-center gap-3">
            <div className="w-1.5 h-6 bg-blue-500 rounded-none" />
            {title.replace(/^\d+[\.\s]+/, '')}
          </h4>
        </div>
        <div className="p-6 text-slate-300 leading-relaxed font-sans text-[15px] opacity-90">
          {content}
        </div>
      </div>
    </div>
  );
};

const CertificationSeal = () => {
  return (
    <div className="my-12 p-8 bg-gradient-to-br from-green-500/10 to-emerald-900/10 border-2 border-green-500/30 rounded-none relative overflow-hidden group animate-bounce-in">
      <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
        <CheckCircle2 className="w-32 h-32 text-green-500 -rotate-12" />
      </div>
      <div className="relative z-10 flex flex-col items-center text-center">
        <div className="w-20 h-20 bg-green-500/20 rounded-none flex items-center justify-center border-4 border-green-500/40 mb-6 shadow-[0_0_40px_rgba(34,197,94,0.3)]">
          <CheckCircle2 className="w-10 h-10 text-green-400" />
        </div>
        <h2 className="text-2xl font-black text-white uppercase tracking-[0.5em] mb-3">DATA CERTIFIED</h2>
        <div className="h-1 w-24 bg-green-500 mb-4" />
        <p className="text-green-100/60 font-mono text-[11px] uppercase tracking-widest max-w-md leading-relaxed">
          The SCAL analytical suite has finalized the physical consistency audit. 
          Results are verified for reservoir simulation deployment.
        </p>
      </div>
    </div>
  );
};

// Brace-counting JSON extractor — immune to whitespace, unicode, and multi-line JSON.
// Returns the first complete root-level {...} object starting at position 0 of `str`,
// or null if the object is not yet complete (streaming still in progress).
function _extractFirstJsonObject(str) {
  let depth = 0, inStr = false, esc = false;
  for (let i = 0; i < str.length; i++) {
    const c = str[i];
    if (esc)                        { esc = false; continue; }
    if (c === '\\' && inStr)        { esc = true;  continue; }
    if (c === '"')                  { inStr = !inStr; continue; }
    if (inStr)                      continue;
    if (c === '{')                  depth++;
    else if (c === '}' && --depth === 0) return str.slice(0, i + 1);
  }
  return null; // JSON not yet complete — caller should suppress raw output
}

// Attempt to sanitize and parse JSON that Gemini may have generated with minor formatting errors.
// Returns parsed object on success, null on failure.
function _tryParseChartJson(raw) {
  // Attempt 1 — straight parse
  try { return JSON.parse(raw); } catch (_) {}

  // Attempt 2 — strip carriage returns (\r) which Windows / Gemini occasionally injects
  const stripped = raw.replace(/\r/g, '');
  try { return JSON.parse(stripped); } catch (_) {}

  // Attempt 3 — remove trailing commas before ] or } (common Gemini JSON quirk)
  const noTrailing = stripped.replace(/,(\s*[}\]])/g, '$1');
  try { return JSON.parse(noTrailing); } catch (_) {}

  // Attempt 4 — replace unescaped control characters inside strings
  const sanitized = noTrailing.replace(/[\x00-\x1F\x7F]/g, c => {
    const map = { '\n': '\\n', '\r': '\\r', '\t': '\\t' };
    return map[c] || '';
  });
  try { return JSON.parse(sanitized); } catch (e) {
    console.error('[PRC Plot] JSON parse failed after sanitization:', e.message, '\nRaw:', raw.slice(0, 200));
    return null;
  }
}

export function renderMessageContent(text) {
  if (!text) return null;

  // Strip \r (Windows CRLF / Gemini streaming artefact) before any processing
  let cleanText = text
    .replace(/\r/g, '')
    .replace(/__INTERNAL_DATA_START__[\s\S]*?__INTERNAL_DATA_END__/g, '')
    .trim();

  // ── __REPORT_DL__ download button injection ──────────────────────────────────
  if (cleanText.includes('__REPORT_DL__')) {
    const reportDlRe = /__REPORT_DL__(\/api\/download\/[^\s_]+)__END_REPORT_DL__/g;
    cleanText = cleanText.replace(reportDlRe, (_, url) => {
      // Remove the marker and let the download button appear via the rendered JSX segment approach below.
      // Store the URL as a data attr placeholder that we render after the pass-1 loop.
      return `\x00REPORT_DL:${url}\x00`;
    });
  }
  if (!cleanText && text.includes('__INTERNAL_DATA_START__')) return null;

  // ── PASS 1: __PRC_PLOT__ extraction ─────────────────────────────────────────
  // MUST run on full text before any line-splitting, otherwise a marker on one
  // line and its JSON on the next line end up in different segments and never match.
  if (cleanText.includes('__PRC_PLOT__')) {
    console.log('[PRC Plot] marker detected, text length =', cleanText.length);
  }

  const afterPlot = [];
  {
    const segs = cleanText.split('__PRC_PLOT__');
    if (segs[0]) afterPlot.push({ type: 'text', content: segs[0] });
    for (let i = 1; i < segs.length; i++) {
      const seg = segs[i];
      const bi = seg.indexOf('{');

      if (bi === -1) {
        console.log('[PRC Plot] seg', i, '— no { found (streaming in progress)');
        continue;
      }

      const jsonStr = _extractFirstJsonObject(seg.slice(bi));

      if (!jsonStr) {
        console.log('[PRC Plot] seg', i, '— brace-counter: null (JSON incomplete)');
        continue;
      }

      console.log('[PRC Plot] seg', i, '— extracted', jsonStr.length, 'chars |', jsonStr.slice(0, 80));

      const parsed = _tryParseChartJson(jsonStr);

      if (!parsed) {
        // _tryParseChartJson already logged the error with the raw JSON
        afterPlot.push({ type: 'plot_error', raw: jsonStr.slice(0, 400) });
        continue;
      }

      afterPlot.push({ type: 'plot', content: jsonStr });
      const tail = seg.slice(bi + jsonStr.length).replace(/^\s*\n?/, '');
      if (tail) afterPlot.push({ type: 'text', content: tail });
    }
  }

  // ── PASS 2: __MERMAID_START__ / __MERMAID_END__ ──────────────────────────────
  const afterMermaid = [];
  afterPlot.forEach(p => {
    if (p.type !== 'text') { afterMermaid.push(p); return; }
    const merRegex = /__MERMAID_START__([\s\S]*?)__MERMAID_END__/g;
    let last = 0, m;
    while ((m = merRegex.exec(p.content)) !== null) {
      if (m.index > last) afterMermaid.push({ type: 'text', content: p.content.slice(last, m.index) });
      afterMermaid.push({ type: 'mermaid', content: m[1].trim() });
      last = m.index + m[0].length;
    }
    if (last < p.content.length) afterMermaid.push({ type: 'text', content: p.content.slice(last) });
  });

  // ── PASS 3: __PRC_DASHBOARD__ ─────────────────────────────────────────────────
  const afterDash = [];
  afterMermaid.forEach(p => {
    if (p.type !== 'text') { afterDash.push(p); return; }
    const dashRegex = /__PRC_DASHBOARD__([\s\S]*?)__PRC_DASHBOARD__/g;
    let last = 0, m;
    while ((m = dashRegex.exec(p.content)) !== null) {
      if (m.index > last) afterDash.push({ type: 'text', content: p.content.slice(last, m.index) });
      afterDash.push({ type: 'dashboard', content: m[1].trim() });
      last = m.index + m[0].length;
    }
    if (last < p.content.length) afterDash.push({ type: 'text', content: p.content.slice(last) });
  });

  // ── PASS 3.5: __SIMULATION_START__ ──────────────────────────────────────────
  const afterSim = [];
  afterDash.forEach(p => {
    if (p.type !== 'text') { afterSim.push(p); return; }
    const simRegex = /__SIMULATION_START__([\s\S]*?)__SIMULATION_END__/g;
    let last = 0, m;
    while ((m = simRegex.exec(p.content)) !== null) {
      if (m.index > last) afterSim.push({ type: 'text', content: p.content.slice(last, m.index) });
      
      const jsonStr = m[1].trim();
      const parsed = _tryParseChartJson(jsonStr);
      if (!parsed) {
        afterSim.push({ type: 'plot_error', raw: jsonStr.slice(0, 400) });
      } else {
        afterSim.push({ type: 'simulation', content: parsed });
      }
      
      last = m.index + m[0].length;
    }
    if (last < p.content.length) afterSim.push({ type: 'text', content: p.content.slice(last) });
  });

  // ── PASS 4: Line splitting → card and image detection ────────────────────────
  const imgRegex = /!\[([^\]]*)\]\((data:[^)]+|https?:[^)]+)\)/g;
  const finalParts = [];
  afterSim.forEach(p => {
    if (p.type !== 'text') { finalParts.push(p); return; }

    const lines = p.content.split('\n');
    let currentCard = null;
    const lineBlocks = [];
    lines.forEach(line => {
      const cardMatch = line.match(/^\*\*(\d+\..*?)\*\*/);
      if (cardMatch) {
        if (currentCard) lineBlocks.push(currentCard);
        currentCard = { type: 'card', title: cardMatch[1], content: [] };
      } else if (currentCard && line.trim()) {
        currentCard.content.push(line);
      } else {
        if (currentCard) { lineBlocks.push(currentCard); currentCard = null; }
        lineBlocks.push({ type: 'text', content: line });
      }
    });
    if (currentCard) lineBlocks.push(currentCard);

    lineBlocks.forEach(b => {
      if (b.type === 'card') {
        finalParts.push({ type: 'knowledge_card', title: b.title, content: b.content.join('\n') });
        return;
      }
      let last = 0, m;
      const txt = b.content;
      imgRegex.lastIndex = 0;
      while ((m = imgRegex.exec(txt)) !== null) {
        if (m.index > last) finalParts.push({ type: 'text', content: txt.slice(last, m.index) });
        finalParts.push({ type: 'img', alt: m[1], src: m[2] });
        last = m.index + m[0].length;
      }
      if (last < txt.length) finalParts.push({ type: 'text', content: txt.slice(last) });
    });
  });

  // ── RENDER ───────────────────────────────────────────────────────────────────
  return finalParts.map((part, i) => {
    if (part.type === 'img') return <img key={i} src={part.src} alt={part.alt} className="w-full rounded-none border border-white/10 my-8 shadow-2xl animate-fade-in" />;
    if (part.type === 'mermaid') return <Mermaid key={i} content={part.content} />;
    if (part.type === 'plot') return <KrCurvePlot key={i} plotData={part.content} />;
    if (part.type === 'simulation') return <SimulationHeatmap key={i} content={JSON.stringify(part.content)} />;
    if (part.type === 'plot_error') return (
      <div key={i} className="my-6 px-5 py-4 bg-red-950/20 border border-red-800/40 rounded-none font-mono text-[11px] text-red-400">
        <span className="font-black uppercase tracking-widest mr-2">[PRC Plot — Invalid JSON]</span>
        <span className="text-red-600 opacity-70">Check browser console for details.</span>
        <pre className="mt-2 text-red-700/60 whitespace-pre-wrap break-all text-[10px]">{part.raw}</pre>
      </div>
    );
    if (part.type === 'dashboard') return (
      <div key={i} className="my-10 rounded-none-[2rem] border border-white/10 bg-[#050508] overflow-hidden shadow-2xl animate-fade-in h-[500px]">
        <iframe
          srcDoc={`<html><head><script src="https://cdn.jsdelivr.net/npm/chart.js"></script><style>body{background:#050508;color:white;margin:0;padding:20px;font-family:sans-serif;overflow:hidden}canvas{max-height:450px!important}</style></head><body>${part.content}</body></html>`}
          className="w-full h-full border-0"
          title="PRC Dynamic Dashboard"
        />
      </div>
    );
    if (part.type === 'knowledge_card') return <KnowledgeCard key={i} title={part.title} content={part.content} />;
    if (part.type === 'report_dl') return (
      <a
        key={i}
        href={part.url}
        download
        className="my-4 inline-flex items-center gap-2.5 px-5 py-3 bg-yellow-950/30 hover:bg-yellow-900/50 border border-yellow-700/50 hover:border-yellow-500 text-yellow-300 font-black text-[11px] uppercase tracking-widest rounded-none transition-all active:scale-95 shadow-lg"
      >
        <Database className="w-4 h-4 text-yellow-400" />
        Download Executive SCAL Report (.docx)
      </a>
    );
    if (part.type === 'text') {
      const txt = part.content.trim();
      if (!txt) return null;
      // Render __REPORT_DL__ placeholder as a download button
      if (txt.startsWith('\x00REPORT_DL:') && txt.endsWith('\x00')) {
        const url = txt.slice(11, -1);
        return (
          <a
            key={i}
            href={url}
            download
            className="my-4 inline-flex items-center gap-2.5 px-5 py-3 bg-yellow-950/30 hover:bg-yellow-900/50 border border-yellow-700/50 hover:border-yellow-500 text-yellow-300 font-black text-[11px] uppercase tracking-widest rounded-none transition-all active:scale-95 shadow-lg"
          >
            <Database className="w-4 h-4 text-yellow-400" />
            Download Executive SCAL Report (.docx)
          </a>
        );
      }
      if (txt.toLowerCase().includes('data certified') || txt.toLowerCase().includes('analysis complete')) return <CertificationSeal key={i} />;
      if (txt.startsWith('###')) return <SectionHeader key={i} text={txt} />;
      return <p key={i} className="mb-6 whitespace-pre-wrap font-sans leading-loose text-slate-300 opacity-80 text-[16px]">{txt}</p>;
    }
    return null;
  });
}
