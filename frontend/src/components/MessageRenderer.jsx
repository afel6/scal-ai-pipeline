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
      <div className={`flex-none w-14 h-14 rounded-2xl flex items-center justify-center transition-all duration-700 shadow-[0_0_30px_rgba(0,0,0,0.5)] border-2 ${
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
          <span className={`w-2.5 h-2.5 rounded-full animate-pulse ${isComplete ? 'bg-green-500' : isPhase ? 'bg-blue-500' : 'bg-yellow-500'}`} />
          {isComplete ? 'PRC SYSTEM CERTIFICATION ACTIVE' : isPhase ? 'STRUCTURAL PIPELINE MILESTONE' : 'ENGINEERING OBSERVATION'}
        </p>
      </div>
    </div>
  );
};

const KnowledgeCard = ({ title, content }) => {
  return (
    <div className="my-8 relative group animate-fade-in">
      <div className="absolute -inset-0.5 bg-gradient-to-r from-blue-500/20 to-purple-500/20 rounded-2xl blur opacity-30 group-hover:opacity-100 transition duration-1000"></div>
      <div className="relative bg-[#0d1117]/80 backdrop-blur-xl border border-white/10 rounded-2xl overflow-hidden shadow-2xl">
        <div className="bg-gradient-to-r from-blue-900/40 to-transparent p-4 border-b border-white/5">
          <h4 className="text-sm font-black text-blue-100 uppercase tracking-widest flex items-center gap-3">
            <div className="w-1.5 h-6 bg-blue-500 rounded-full" />
            {title.replace(/^\d+[\.\s]+/, '')}
          </h4>
        </div>
        <div className="p-6 text-slate-300 leading-relaxed font-serif text-[15px] opacity-90">
          {content}
        </div>
      </div>
    </div>
  );
};

const CertificationSeal = () => {
  return (
    <div className="my-12 p-8 bg-gradient-to-br from-green-500/10 to-emerald-900/10 border-2 border-green-500/30 rounded-3xl relative overflow-hidden group animate-bounce-in">
      <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
        <CheckCircle2 className="w-32 h-32 text-green-500 -rotate-12" />
      </div>
      <div className="relative z-10 flex flex-col items-center text-center">
        <div className="w-20 h-20 bg-green-500/20 rounded-full flex items-center justify-center border-4 border-green-500/40 mb-6 shadow-[0_0_40px_rgba(34,197,94,0.3)]">
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

export function renderMessageContent(text) {
  if (!text) return null;

  let cleanText = text.replace(/__INTERNAL_DATA_START__[\s\S]*?__INTERNAL_DATA_END__/g, '').trim();
  if (!cleanText && text.includes('__INTERNAL_DATA_START__')) return null;

  // ── PASS 1: __PRC_PLOT__ extraction ─────────────────────────────────────────
  // MUST run on full text before any line-splitting, otherwise a marker on one
  // line and its JSON on the next line end up in different segments and never match.
  const afterPlot = [];
  {
    const segs = cleanText.split('__PRC_PLOT__');
    if (segs[0]) afterPlot.push({ type: 'text', content: segs[0] });
    for (let i = 1; i < segs.length; i++) {
      const seg = segs[i];
      const bi = seg.indexOf('{');
      if (bi === -1) continue; // marker with no JSON yet — suppress during streaming
      const jsonStr = _extractFirstJsonObject(seg.slice(bi));
      if (!jsonStr) continue; // incomplete JSON — suppress raw output during streaming
      try {
        JSON.parse(jsonStr);
        afterPlot.push({ type: 'plot', content: jsonStr });
        const tail = seg.slice(bi + jsonStr.length).replace(/^\s*\n?/, '');
        if (tail) afterPlot.push({ type: 'text', content: tail });
      } catch {
        afterPlot.push({ type: 'text', content: '__PRC_PLOT__' + seg }); // malformed — surface for debug
      }
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

  // ── PASS 4: Line splitting → card and image detection ────────────────────────
  const imgRegex = /!\[([^\]]*)\]\((data:[^)]+|https?:[^)]+)\)/g;
  const finalParts = [];
  afterDash.forEach(p => {
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
    if (part.type === 'img') return <img key={i} src={part.src} alt={part.alt} className="w-full rounded-2xl border border-white/10 my-8 shadow-2xl animate-fade-in" />;
    if (part.type === 'mermaid') return <Mermaid key={i} content={part.content} />;
    if (part.type === 'plot') return <KrCurvePlot key={i} plotData={part.content} />;
    if (part.type === 'dashboard') return (
      <div key={i} className="my-10 rounded-[2rem] border border-white/10 bg-[#050508] overflow-hidden shadow-2xl animate-fade-in h-[500px]">
        <iframe
          srcDoc={`<html><head><script src="https://cdn.jsdelivr.net/npm/chart.js"></script><style>body{background:#050508;color:white;margin:0;padding:20px;font-family:sans-serif;overflow:hidden}canvas{max-height:450px!important}</style></head><body>${part.content}</body></html>`}
          className="w-full h-full border-0"
          title="PRC Dynamic Dashboard"
        />
      </div>
    );
    if (part.type === 'knowledge_card') return <KnowledgeCard key={i} title={part.title} content={part.content} />;
    if (part.type === 'text') {
      const txt = part.content.trim();
      if (!txt) return null;
      if (txt.toLowerCase().includes('data certified') || txt.toLowerCase().includes('analysis complete')) return <CertificationSeal key={i} />;
      if (txt.startsWith('###')) return <SectionHeader key={i} text={txt} />;
      return <p key={i} className="mb-6 whitespace-pre-wrap font-serif leading-loose text-slate-300 opacity-80 text-[16px]">{txt}</p>;
    }
    return null;
  });
}
