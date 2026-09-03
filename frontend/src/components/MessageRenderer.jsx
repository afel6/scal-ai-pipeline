/* eslint-disable */
import React, { lazy, Suspense } from 'react';
import { Database, Activity, CheckCircle2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
// Lazy — mermaid pulls cytoscape+katex (~800kB); only load it when a message
// actually contains a diagram.
const Mermaid = lazy(() => import('../Mermaid'));
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
              <div className="my-4 overflow-hidden rounded-xl border border-yellow-500/15 bg-[#0a0a0f]/80 backdrop-blur-md shadow-2xl max-w-full overflow-x-auto custom-scrollbar">
                <table className="w-full table-fixed text-left border-collapse text-xs font-mono" {...props} />
              </div>
            ),
            th: ({node, ...props}) => (
              <th className="px-4 py-2.5 bg-yellow-950/30 border-b border-white/5 text-[10px] font-bold text-yellow-500 uppercase tracking-wider whitespace-normal break-words align-bottom" {...props} />
            ),
            td: ({node, ...props}) => (
              <td className="px-4 py-2.5 border-b border-white/[0.03] text-slate-300 transition-colors whitespace-normal break-words align-top" {...props} />
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

// Dynamic adapter function to convert Plotly-style JSON (with "data" and "layout") into custom "curves" format.
function _adaptPlotData(parsed) {
  if (!parsed) return null;
  if (parsed.curves) {
    return parsed; // Already conforms to custom curves format
  }
  
  if (parsed.data && Array.isArray(parsed.data)) {
    const defaultColors = [
      '#38bdf8', // sky-400
      '#fb923c', // orange-400
      '#34d399', // emerald-400
      '#a78bfa', // purple-400
      '#facc15', // yellow-400
      '#f43f5e', // rose-500
      '#22d3ee', // cyan-400
    ];

    const title = parsed.layout?.title?.text || parsed.layout?.title || 'SCAL Analysis Curves';
    
    // x and y axis labels
    const xLabel = parsed.layout?.xaxis?.title?.text || parsed.layout?.xaxis?.title || 'x';
    const yLabel = parsed.layout?.yaxis?.title?.text || parsed.layout?.yaxis?.title || 'y';
    
    // Check if scales are log
    const xLog = parsed.layout?.xaxis?.type === 'log';
    const yLog = parsed.layout?.yaxis?.type === 'log';
    
    // Let's see if we have dual axis
    const dualAxis = !!parsed.layout?.yaxis2 || parsed.data.some(trace => trace.yaxis === 'y2');
    const yLabel2 = parsed.layout?.yaxis2?.title?.text || parsed.layout?.yaxis2?.title || 'y2';
    const yLog2 = parsed.layout?.yaxis2?.type === 'log';

    // Map Plotly traces into curves format
    const curves = parsed.data.map((trace, index) => {
      const showLine = trace.mode ? trace.mode.includes('lines') : true;
      const showPoints = trace.mode ? trace.mode.includes('markers') : (trace.type === 'scatter');
      const yId = (trace.yaxis === 'y2') ? 'right' : 'left';

      // Zip x and y arrays into an array of objects { x, y }
      const dataPoints = [];
      const xs = trace.x || [];
      const ys = trace.y || [];
      const len = Math.min(xs.length, ys.length);
      for (let i = 0; i < len; i++) {
        const xVal = parseFloat(xs[i]);
        const yVal = parseFloat(ys[i]);
        if (!isNaN(xVal) && !isNaN(yVal)) {
          dataPoints.push({ x: xVal, y: yVal });
        }
      }

      return {
        name: trace.name || `Curve ${index + 1}`,
        color: trace.line?.color || trace.marker?.color || defaultColors[index % defaultColors.length],
        showLine: showLine,
        showPoints: showPoints,
        dashed: trace.line?.dash === 'dash' || trace.line?.dash === 'dot',
        yId: yId,
        data: dataPoints
      };
    });

    return {
      title,
      xAxis: { label: xLabel },
      yAxis: { label: yLabel },
      xAxisLog: xLog,
      yAxisLog: yLog,
      dualAxis: dualAxis,
      yAxis2: dualAxis ? { label: yLabel2 } : undefined,
      yAxisRightLog: dualAxis ? yLog2 : undefined,
      curves
    };
  }

  return null;
}

export function renderMessageContent(text) {
  if (!text) return null;

  // Strip \r (Windows CRLF / Gemini streaming artefact) before any processing
  let cleanText = text
    .replace(/\r/g, '')
    .replace(/__INTERNAL_DATA_START__[\s\S]*?__INTERNAL_DATA_END__/g, '')
    .trim();

  // Enforce spacing before markdown headings (##, ###) if they lack a preceding double newline.
  cleanText = cleanText.replace(/([^\n])\s*(#{2,}\s)/g, '$1\n\n$2');
  // Enforce padding before the first row of a markdown table.
  cleanText = cleanText.replace(/(^|\n)([^|\n]+)\s*(\|)/g, '$1$2\n\n$3');
  // Enforce newlines between concatenated table rows.
  cleanText = cleanText.replace(/\|\s+(?=\|)/g, '|\n');

  // Clean up markdown code block fences enclosing __PRC_PLOT__
  cleanText = cleanText.replace(/```+__PRC_PLOT__/g, '__PRC_PLOT__');

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

      if (bi === -1) {
        // No JSON start found, clean up backticks from the segment
        let tail = seg.replace(/^\s*```*\s*/, '');
        if (tail) afterPlot.push({ type: 'text', content: tail });
        continue;
      }

      const jsonStr = _extractFirstJsonObject(seg.slice(bi));

      if (!jsonStr) {
        let tail = seg.replace(/^\s*```*\s*/, '');
        if (tail) afterPlot.push({ type: 'text', content: tail });
        continue;
      }

      const parsed = _tryParseChartJson(jsonStr);

      if (!parsed) {
        // _tryParseChartJson already logged the error with the raw JSON
        afterPlot.push({ type: 'plot_error', raw: jsonStr.slice(0, 400) });
        let tail = seg.slice(bi + jsonStr.length);
        tail = tail.replace(/^\s*```*\s*/, '');
        if (tail) afterPlot.push({ type: 'text', content: tail });
        continue;
      }

      // Adapt the Plotly-style JSON to standard curves format
      const adapted = _adaptPlotData(parsed);

      if (!adapted || !adapted.curves) {
        // Not a curve plot, skip plot node completely
        let tail = seg.slice(bi + jsonStr.length);
        tail = tail.replace(/^\s*```*\s*/, '');
        if (tail) afterPlot.push({ type: 'text', content: tail });
        continue;
      }

      afterPlot.push({ type: 'plot', content: adapted });
      let tail = seg.slice(bi + jsonStr.length);
      // Clean up markdown code block fences
      tail = tail.replace(/^\s*```*\s*/, '');
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
    if (part.type === 'mermaid') return (
      <Suspense key={i} fallback={<div className="text-xs opacity-60 p-4">Rendering diagram…</div>}>
        <Mermaid content={part.content} />
      </Suspense>
    );
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
        <div key={i} className="mb-6 font-sans leading-relaxed text-slate-200 text-[15px] prc-markdown">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              table: ({node, ...props}) => (
                <div className="my-4 overflow-hidden rounded-xl border border-yellow-500/15 bg-[#0a0a0f]/80 backdrop-blur-md shadow-2xl max-w-full overflow-x-auto custom-scrollbar">
                  <table className="w-full text-left border-collapse text-xs font-mono min-w-max" {...props} />
                </div>
              ),
              th: ({node, ...props}) => (
                <th className="px-4 py-2.5 bg-yellow-950/30 border-b border-white/5 text-[10px] font-bold text-yellow-500 uppercase tracking-wider whitespace-nowrap" {...props} />
              ),
              td: ({node, ...props}) => (
                <td className="px-4 py-2.5 border-b border-white/[0.03] text-slate-300 transition-colors whitespace-nowrap" {...props} />
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
