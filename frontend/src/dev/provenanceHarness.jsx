// Dev-only harness (C1 item 1.1) — real-browser render of the corrected and
// clean Archie payloads through the real KrCurvePlot. Safe to delete.
import React from 'react';
import { createRoot } from 'react-dom/client';
import KrCurvePlot from '../components/KrCurvePlot';
import '../index.css';

const corrected = {
  title: 'Resistivity Index  -  RI vs Sw (harness: CORRECTED fit)',
  xAxis: { label: 'Water Saturation Sw (fraction)' },
  yAxis: { label: 'Resistivity Index RI (dimensionless)' },
  xAxisLog: true,
  yAxisLog: true,
  curves: [
    { name: 'RI Lab (harness)', showLine: false, showPoints: true, color: '#f59e0b',
      data: [{ x: 0.9, y: 1.135 }, { x: 0.7, y: 1.534 }, { x: 0.5, y: 2.297 }, { x: 0.3, y: 4.241 }] },
    { name: 'RI Archie (n unresolved — outside physical range, not fitted)',
      showLine: true, showPoints: false, color: '#fbbf24',
      data: [{ x: 0.9, y: 1.171 }, { x: 0.7, y: 1.708 }, { x: 0.5, y: 2.828 }, { x: 0.3, y: 6.086 }] },
  ],
  metadata: {
    archie: { n: null, fitted: false,
      note: 'Free fit out of bounds (b=1.000, n=1.200); re-solving within [0.5, 1.5] / [1.5, 2.5].' },
    physics_audit: { score: 40, grade: 'F' },
  },
};

const clean = {
  ...corrected,
  title: 'Resistivity Index  -  RI vs Sw (harness: CLEAN fit)',
  curves: [corrected.curves[0], { ...corrected.curves[1], name: 'RI Archie  n=2.000' }],
  metadata: { archie: { n: 2.0, fitted: true }, physics_audit: { score: 100, grade: 'A' } },
};

createRoot(document.getElementById('root')).render(
  <div style={{ padding: 24 }}>
    <KrCurvePlot plotData={corrected} />
    <KrCurvePlot plotData={clean} />
  </div>,
);
