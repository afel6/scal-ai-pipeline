/* eslint-disable */
import React from 'react';
import { Database, Activity, CheckCircle2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import Mermaid from '../Mermaid';
import PetrophysicalTable from './PetrophysicalTable';
import SimulationHeatmap from '../SimulationHeatmap';
import KrCurvePlot from './KrCurvePlot';

const SectionHeader = ({ text }) => {
  return (
    <h3 className="font-bold text-lg text-yellow-500 mt-6 mb-3 flex items-center gap-2">
      <div className="w-2 h-2 rounded-full bg-yellow-500 shadow-[0_0_8px_rgba(251,191,36,0.5)]" />
      {text.replace(/###\s*/, '')}
    </h3>
  );
};

const KnowledgeCard = ({ title, content }) => {
  return (
    <div className="my-4 p-4 bg-slate-800/50 border border-slate-700 rounded-lg">
      <h4 className="text-sm font-bold text-slate-200 mb-2">{title.replace(/^\d+[\.\s]+/, '')}</h4>
      <div className="text-sm text-slate-300 leading-relaxed prc-markdown">
        <ReactMarkdown 
          remarkPlugins={[remarkGfm]}
          components={{
            table: ({node, ...props}) => (
              <div className="my-6 overflow-hidden rounded-2xl border border-yellow-500/10 bg-[#0c0c12]/60 backdrop-blur-md shadow-xl max-w-full overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs md:text-sm font-mono min-w-[400px]" {...props} />
              </div>
            ),
            th: ({node, ...props}) => (
              <th className="px-5 py-3.5 bg-yellow-950/20 border-b border-white/5 text-[10px] font-black text-yellow-500 uppercase tracking-widest" {...props} />
            ),
            td: ({node, ...props}) => (
              <td className="px-5 py-3.5 border-b border-white/[0.03] text-slate-300 transition-colors" {...props} />
            ),
            a: ({node, ...props}) => <a className="text-yellow-400 hover:text-yellow-300 underline underline-offset-2" {...props} />,
            p: ({node, ...props}) => <p className="mb-4 whitespace-pre-wrap" {...props} />
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </div>
  );
};

const CertificationSeal = () => {
  return (
    <div className="my-6 p-4 bg-green-500/10 border border-green-500/30 rounded-lg flex items-start gap-4">
      <CheckCircle2 className="w-6 h-6 text-green-500 mt-0.5 flex-shrink-0" />
      <div>
        <h4 className="text-sm font-bold text-green-400 mb-1">Data Certified</h4>
        <p className="text-xs text-green-300/80">
          The SCAL analytical suite has finalized the physical consistency audit. Results are verified.
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
  const afterPlot = [];
  {
    const segs = cleanText.split('__PRC_PLOT__');
    if (segs[0]) afterPlot.push({ type: 'text', content: segs[0] });
    for (let i = 1; i < segs.length; i++) {
      const seg = segs[i];
      const bi = seg.indexOf('{');

      if (bi === -1) continue;

      const jsonStr = _extractFirstJsonObject(seg.slice(bi));

      if (!jsonStr) continue;

      const parsed = _tryParseChartJson(jsonStr);

      if (!parsed) {
        // _tryParseChartJson already logged the error with the raw JSON
        afterPlot.push({ type: 'plot_error', raw: jsonStr.slice(0, 400) });
        const tail = seg.slice(bi + jsonStr.length).replace(/^\s*\n?/, '');
        if (tail) afterPlot.push({ type: 'text', content: tail });
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
    let currentText = [];
    lines.forEach(line => {
      const cardMatch = line.match(/^\*\*(\d+\..*?)\*\*/);
      if (cardMatch) {
        if (currentText.length > 0) {
          lineBlocks.push({ type: 'text', content: currentText.join('\n') });
          currentText = [];
        }
        if (currentCard) lineBlocks.push(currentCard);
        currentCard = { type: 'card', title: cardMatch[1], content: [] };
      } else if (currentCard && line.trim()) {
        currentCard.content.push(line);
      } else {
        if (currentCard) { lineBlocks.push(currentCard); currentCard = null; }
        currentText.push(line);
      }
    });
    if (currentText.length > 0) {
      lineBlocks.push({ type: 'text', content: currentText.join('\n') });
    }
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
    if (part.type === 'img') return <img key={i} src={part.src} alt={part.alt} className="w-full rounded-xl border border-white/10 my-8 shadow-2xl animate-fade-in" />;
    if (part.type === 'mermaid') return <Mermaid key={i} content={part.content} />;
    if (part.type === 'plot') return <KrCurvePlot key={i} plotData={part.content} />;
    if (part.type === 'simulation') return <SimulationHeatmap key={i} content={JSON.stringify(part.content)} />;
    if (part.type === 'plot_error') return (
      <div key={i} className="my-6 px-5 py-4 bg-red-950/20 border border-red-800/40 rounded-xl font-mono text-[11px] text-red-400">
        <span className="font-black uppercase tracking-widest mr-2">[PRC Plot — Render Error]</span>
        <span className="text-red-600 opacity-70">Plot data could not be rendered. Please re-run the simulation.</span>
      </div>
    );
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
    if (part.type === 'report_dl') return (
      <a
        key={i}
        href={part.url}
        download
        className="my-4 inline-flex items-center gap-2.5 px-5 py-3 bg-yellow-950/30 hover:bg-yellow-900/50 border border-yellow-700/50 hover:border-yellow-500 text-yellow-300 font-black text-[11px] uppercase tracking-widest rounded-xl transition-all active:scale-95 shadow-lg"
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
            className="my-4 inline-flex items-center gap-2.5 px-5 py-3 bg-yellow-950/30 hover:bg-yellow-900/50 border border-yellow-700/50 hover:border-yellow-500 text-yellow-300 font-black text-[11px] uppercase tracking-widest rounded-xl transition-all active:scale-95 shadow-lg"
          >
            <Database className="w-4 h-4 text-yellow-400" />
            Download Executive SCAL Report (.docx)
          </a>
        );
      }
      if (txt.toLowerCase().includes('data certified') || txt.toLowerCase().includes('analysis complete')) return <CertificationSeal key={i} />;
      if (txt.startsWith('###')) return <SectionHeader key={i} text={txt} />;
      return (
        <div key={i} className="mb-6 font-sans leading-loose text-slate-300 opacity-80 text-[16px] prc-markdown">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              table: ({node, ...props}) => (
                <div className="my-6 overflow-hidden rounded-2xl border border-yellow-500/10 bg-[#0c0c12]/60 backdrop-blur-md shadow-xl max-w-full overflow-x-auto">
                  <table className="w-full text-left border-collapse text-xs md:text-sm font-mono min-w-[400px]" {...props} />
                </div>
              ),
              th: ({node, ...props}) => (
                <th className="px-5 py-3.5 bg-yellow-950/20 border-b border-white/5 text-[10px] font-black text-yellow-500 uppercase tracking-widest" {...props} />
              ),
              td: ({node, ...props}) => (
                <td className="px-5 py-3.5 border-b border-white/[0.03] text-slate-300 transition-colors" {...props} />
              ),
              a: ({node, ...props}) => <a className="text-yellow-400 hover:text-yellow-300 underline underline-offset-2" {...props} />,
              p: ({node, ...props}) => <p className="mb-4 whitespace-pre-wrap" {...props} />
            }}
          >
            {txt}
          </ReactMarkdown>
        </div>
      );
    }
    return null;
  });
}
