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

export function renderMessageContent(text) {
  if (!text) return null;

  let cleanText = text.replace(/__INTERNAL_DATA_START__[\s\S]*?__INTERNAL_DATA_END__/g, '').trim();
  if (!cleanText && text.includes('__INTERNAL_DATA_START__')) return null;

  const blocks = [];
  const lines = cleanText.split('\n');
  let currentCard = null;

  lines.forEach(line => {
    const cardMatch = line.match(/^\*\*(\d+\..*?)\*\*/);
    if (cardMatch) {
      if (currentCard) blocks.push(currentCard);
      currentCard = { type: 'card', title: cardMatch[1], content: [] };
    } else if (currentCard && line.trim()) {
      currentCard.content.push(line);
    } else {
      if (currentCard) {
        blocks.push(currentCard);
        currentCard = null;
      }
      blocks.push({ type: 'text', content: line });
    }
  });
  if (currentCard) blocks.push(currentCard);

  const imgRegex = /!\[([^\]]*)\]\((data:[^)]+|https?:[^)]+)\)/g;
  const parts = [];
  
  blocks.forEach(b => {
    if (b.type === 'card') {
      parts.push({ type: 'knowledge_card', title: b.title, content: b.content.join('\n') });
      return;
    }
    
    let lastIndex = 0;
    let match;
    const txt = b.content;

    while ((match = imgRegex.exec(txt)) !== null) {
      if (match.index > lastIndex) parts.push({ type: 'text', content: txt.slice(lastIndex, match.index) });
      parts.push({ type: 'img', alt: match[1], src: match[2] });
      lastIndex = match.index + match[0].length;
    }
    if (lastIndex < txt.length) parts.push({ type: 'text', content: txt.slice(lastIndex) });
  });

  const mermaidParts = [];
  parts.forEach(p => {
    if (p.type === 'text') {
      const merRegex = /__MERMAID_START__([\s\S]*?)__MERMAID_END__/g;
      let lastMIndex = 0, mMatch;
      while ((mMatch = merRegex.exec(p.content)) !== null) {
        if (mMatch.index > lastMIndex) mermaidParts.push({ type: 'text', content: p.content.slice(lastMIndex, mMatch.index) });
        mermaidParts.push({ type: 'mermaid', content: mMatch[1].trim() });
        lastMIndex = mMatch.index + mMatch[0].length;
      }
      if (lastMIndex < p.content.length) mermaidParts.push({ type: 'text', content: p.content.slice(lastMIndex) });
    } else mermaidParts.push(p);
  });

  const plotParts = [];
  mermaidParts.forEach(p => {
    if (p.type === 'text') {
      const plotRegex = /__PRC_PLOT__\n?(\{[\s\S]*?\})(?=\s*(?:__|$|\n\n))/g;
      let lastPIndex = 0, pMatch;
      while ((pMatch = plotRegex.exec(p.content)) !== null) {
        if (pMatch.index > lastPIndex) plotParts.push({ type: 'text', content: p.content.slice(lastPIndex, pMatch.index) });
        plotParts.push({ type: 'plot', content: pMatch[1].trim() });
        lastPIndex = pMatch.index + pMatch[0].length;
      }
      if (lastPIndex < p.content.length) plotParts.push({ type: 'text', content: p.content.slice(lastPIndex) });
    } else plotParts.push(p);
  });

  const dashboardParts = [];
  plotParts.forEach(p => {
    if (p.type === 'text') {
      const dashRegex = /__PRC_DASHBOARD__([\s\S]*?)__PRC_DASHBOARD__/g;
      let lastDIndex = 0, dMatch;
      while ((dMatch = dashRegex.exec(p.content)) !== null) {
        if (dMatch.index > lastDIndex) dashboardParts.push({ type: 'text', content: p.content.slice(lastDIndex, dMatch.index) });
        dashboardParts.push({ type: 'dashboard', content: dMatch[1].trim() });
        lastDIndex = dMatch.index + dMatch[0].length;
      }
      if (lastDIndex < p.content.length) dashboardParts.push({ type: 'text', content: p.content.slice(lastDIndex) });
    } else dashboardParts.push(p);
  });

  return dashboardParts.map((part, i) => {
    if (part.type === 'img') return <img key={i} src={part.src} alt={part.alt} className="w-full rounded-2xl border border-white/10 my-8 shadow-2xl animate-fade-in" />;
    if (part.type === 'mermaid') return <Mermaid key={i} content={part.content} />;
    if (part.type === 'plot') return <KrCurvePlot key={i} plotData={part.content} />;
    if (part.type === 'dashboard') return (
      <div key={i} className="my-10 rounded-[2rem] border border-white/10 bg-[#050508] overflow-hidden shadow-2xl animate-fade-in h-[500px]">
        <iframe 
          srcDoc={`
            <html>
              <head>
                <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
                <style>
                  body { background: #050508; color: white; margin: 0; padding: 20px; font-family: sans-serif; overflow: hidden; }
                  canvas { max-height: 450px !important; }
                </style>
              </head>
              <body>${part.content}</body>
            </html>
          `}
          className="w-full h-full border-0"
          title="PRC Dynamic Dashboard"
        />
      </div>
    );
    if (part.type === 'knowledge_card') return <KnowledgeCard key={i} title={part.title} content={part.content} />;
    
    if (part.type === 'text') {
      const text = part.content.trim();
      if (!text) return null;
      
      if (text.toLowerCase().includes('data certified') || text.toLowerCase().includes('analysis complete')) {
        return <CertificationSeal key={i} />;
      }
      
      if (text.startsWith('###')) {
        return <SectionHeader key={i} text={text} />;
      }
      
      return <p key={i} className="mb-6 whitespace-pre-wrap font-serif leading-loose text-slate-300 opacity-80 text-[16px]">{text}</p>;
    }
    return null;
  });
}
