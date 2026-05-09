import React from 'react';
import { Database } from 'lucide-react';
import Mermaid from '../Mermaid';
import PetrophysicalTable from './PetrophysicalTable';
import SimulationHeatmap from '../SimulationHeatmap';
import KrPlot from '../KrPlot';

export function renderMessageContent(text) {
  if (!text) return null;

  // Match markdown images: ![alt](src) -- supports data URIs and http URLs
  const imgRegex = /!\[([^\]]*)\]\((data:[^)]+|https?:[^)]+)\)/g;
  const parts = [];
  let lastIndex = 0;
  let match;

  while ((match = imgRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'text', content: text.slice(lastIndex, match.index) });
    }
    parts.push({ type: 'img', alt: match[1], src: match[2] });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push({ type: 'text', content: text.slice(lastIndex) });
  }

  // Chain of parsers: Mermaid -> Audit -> Data
  const mermaidParts = [];
  parts.forEach(p => {
    if (p.type === 'text') {
      const merRegex = /__MERMAID_START__([\s\S]*?)__MERMAID_END__/g;
      let lastMIndex = 0;
      let mMatch;
      while ((mMatch = merRegex.exec(p.content)) !== null) {
        if (mMatch.index > lastMIndex) mermaidParts.push({ type: 'text', content: p.content.slice(lastMIndex, mMatch.index) });
        mermaidParts.push({ type: 'mermaid', content: mMatch[1].trim() });
        lastMIndex = mMatch.index + mMatch[0].length;
      }
      if (lastMIndex < p.content.length) mermaidParts.push({ type: 'text', content: p.content.slice(lastMIndex) });
    } else mermaidParts.push(p);
  });

  const auditParts = [];
  mermaidParts.forEach(p => {
    if (p.type === 'text') {
      const auditRegex = /__AUDIT_LOG_START__([\s\S]*?)__AUDIT_LOG_END__/g;
      let lastAIndex = 0;
      let aMatch;
      while ((aMatch = auditRegex.exec(p.content)) !== null) {
        if (aMatch.index > lastAIndex) auditParts.push({ type: 'text', content: p.content.slice(lastAIndex, aMatch.index) });
        auditParts.push({ type: 'audit', content: aMatch[1].trim() });
        lastAIndex = aMatch.index + aMatch[0].length;
      }
      if (lastAIndex < p.content.length) auditParts.push({ type: 'text', content: p.content.slice(lastAIndex) });
    } else auditParts.push(p);
  });

  const finalParts = [];
  auditParts.forEach(p => {
    if (p.type === 'text') {
      const dataRegex = /__PRC_DATA_START__([\s\S]*?)__PRC_DATA_END__/g;
      let lastDIndex = 0;
      let dMatch;
      while ((dMatch = dataRegex.exec(p.content)) !== null) {
        if (dMatch.index > lastDIndex) finalParts.push({ type: 'text', content: p.content.slice(lastDIndex, dMatch.index) });
        finalParts.push({ type: 'data', content: dMatch[1].trim() });
        lastDIndex = dMatch.index + dMatch[0].length;
      }
      if (lastDIndex < p.content.length) finalParts.push({ type: 'text', content: p.content.slice(lastDIndex) });
    } else finalParts.push(p);
  });

  const simParts = [];
  finalParts.forEach(p => {
    if (p.type === 'text') {
      const simRegex = /__SIMULATION_START__([\s\S]*?)__SIMULATION_END__/g;
      let lastSIndex = 0;
      let sMatch;
      while ((sMatch = simRegex.exec(p.content)) !== null) {
        if (sMatch.index > lastSIndex) simParts.push({ type: 'text', content: p.content.slice(lastSIndex, sMatch.index) });
        simParts.push({ type: 'simulation', content: sMatch[1].trim() });
        lastSIndex = sMatch.index + sMatch[0].length;
      }
      if (lastSIndex < p.content.length) simParts.push({ type: 'text', content: p.content.slice(lastSIndex) });
    } else simParts.push(p);
  });

  // Parse __PRC_PLOT__ JSON blocks into interactive charts
  const plotParts = [];
  simParts.forEach(p => {
    if (p.type === 'text') {
      const plotRegex = /(?:__PRC_PLOT__\s*)?({\s*"curves"[\s\S]*?}(?=\s*(?:__|$|\n\n)))/g;
      let lastPIndex = 0;
      let pMatch;
      while ((pMatch = plotRegex.exec(p.content)) !== null) {
        if (pMatch.index > lastPIndex) plotParts.push({ type: 'text', content: p.content.slice(lastPIndex, pMatch.index) });
        plotParts.push({ type: 'plot', content: pMatch[1].trim() });
        lastPIndex = pMatch.index + pMatch[0].length;
      }
      if (lastPIndex < p.content.length) plotParts.push({ type: 'text', content: p.content.slice(lastPIndex) });
    } else plotParts.push(p);
  });

  if (plotParts.length === 0) return <p className="whitespace-pre-wrap font-serif leading-[1.75]">{text}</p>;

  return plotParts.map((part, i) => {
    if (part.type === 'img') return <img key={i} src={part.src} alt={part.alt || 'PRC Chart'} className="w-full rounded-xl border border-yellow-900/30 my-3 shadow-lg" />;
    if (part.type === 'mermaid') return <Mermaid key={i} content={part.content} />;
    if (part.type === 'data') return <PetrophysicalTable key={i} content={part.content} />;
    if (part.type === 'simulation') return <SimulationHeatmap key={i} content={part.content} />;
    if (part.type === 'plot') return <KrPlot key={i} content={part.content} />;
    if (part.type === 'audit') return (
      <div key={i} className="my-4 p-4 bg-yellow-950/20 border-l-4 border-yellow-600 rounded-r-xl shadow-inner font-mono text-[13px] text-yellow-100/90">
        <div className="flex items-center gap-2 mb-2 text-yellow-500 font-black tracking-widest text-[10px] uppercase">
          <Database className="w-3 h-3" /> Engineering Audit Ledger
        </div>
        <div className="whitespace-pre-wrap leading-relaxed opacity-80">{part.content}</div>
      </div>
    );
    return part.content.trim() ? <p key={i} className="whitespace-pre-wrap font-serif leading-[1.75]">{part.content}</p> : null;
  });
}
