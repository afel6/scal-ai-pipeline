import React, { useEffect, useRef } from 'react';
import mermaid from 'mermaid';

// Configure mermaid once
mermaid.initialize({
  startOnLoad: true,
  theme: 'base',
  themeVariables: {
    primaryColor: '#fbbf24',
    primaryTextColor: '#fff',
    primaryBorderColor: '#92400e',
    lineColor: '#fbbf24',
    secondaryColor: '#2d358e',
    tertiaryColor: '#09090b',
    mainBkg: '#0d0d0d',
    nodeBorder: '#fbbf24',
    clusterBkg: '#0d0d0d',
    titleColor: '#fbbf24',
    fontSize: '14px',
    fontFamily: "'Outfit', sans-serif"
  },
  flowchart: { curve: 'basis', htmlLabels: true },
  sequence: { showSequenceNumbers: true },
  securityLevel: 'loose'
});

const Mermaid = ({ content }) => {
  const chartRef = useRef(null);

  useEffect(() => {
    if (chartRef.current && content) {
      // Clear previous content
      chartRef.current.innerHTML = '';
      
      const uniqueId = `mermaid-${Math.random().toString(36).substr(2, 9)}`;
      
      try {
        mermaid.render(uniqueId, content).then(({ svg }) => {
          if (chartRef.current) {
            chartRef.current.innerHTML = svg;
          }
        });
      } catch (err) {
        console.error('Mermaid rendering failed:', err);
        chartRef.current.innerHTML = '<div class="p-4 text-rose-500 text-xs font-mono bg-rose-500/10 rounded-none">Diagram rendering error</div>';
      }
    }
  }, [content]);

  return (
    <div className="my-6 w-full flex justify-center bg-[#070707] rounded-none border border-white/5 p-6 shadow-2xl overflow-hidden animate-fade-in group relative">
       <div className="absolute top-3 right-4 opacity-0 group-hover:opacity-60 transition-opacity text-[10px] font-bold text-prc-gold uppercase tracking-widest">
        Engineering Workflow
      </div>
      <div ref={chartRef} className="mermaid w-full max-w-full overflow-x-auto" />
    </div>
  );
};

export default Mermaid;
