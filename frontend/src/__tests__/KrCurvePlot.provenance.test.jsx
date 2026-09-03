/**
 * C1 item 1.1 — the frontend sink of the corrected-fit metadata shape.
 *
 * Pre-C1 changed `metadata.archie` for corrected (clamped, unfitted) Archie
 * fits from a bare number to `{ n: null, fitted: false, note: … }`. This
 * renders the REAL KrCurvePlot component with the REAL payload the backend
 * formatter now emits and pins the requirement: a corrected fit must show a
 * visible unfitted state — never the string "null", never a silent blank where
 * a number was, never a crash. A clean fit must still show its number.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import KrCurvePlot from '../components/KrCurvePlot';

// Byte-shape of the app.py sandbox_fit_archie formatter output (corrected fit).
const CORRECTED_RI_PAYLOAD = {
  title: 'Resistivity Index  -  RI vs Sw (C1-fe)',
  xAxis: { label: 'Water Saturation Sw (fraction)' },
  yAxis: { label: 'Resistivity Index RI (dimensionless)' },
  xAxisLog: true,
  yAxisLog: true,
  curves: [
    {
      name: 'RI Lab (C1-fe)', showLine: false, showPoints: true, color: '#f59e0b',
      data: [{ x: 0.9, y: 1.135 }, { x: 0.6, y: 1.846 }, { x: 0.3, y: 4.241 }],
    },
    {
      name: 'RI Archie (n unresolved — outside physical range, not fitted)',
      showLine: true, showPoints: false, color: '#fbbf24',
      data: [{ x: 0.9, y: 1.171 }, { x: 0.6, y: 2.152 }, { x: 0.3, y: 6.086 }],
    },
  ],
  metadata: {
    archie: {
      n: null,
      fitted: false,
      note: 'Free fit out of bounds (b=1.000, n=1.200); re-solving within [0.5, 1.5] / [1.5, 2.5].',
    },
    physics_audit: { score: 40, grade: 'F' },
  },
};

const CLEAN_RI_PAYLOAD = {
  ...CORRECTED_RI_PAYLOAD,
  curves: [
    CORRECTED_RI_PAYLOAD.curves[0],
    { ...CORRECTED_RI_PAYLOAD.curves[1], name: 'RI Archie  n=2.000' },
  ],
  metadata: {
    archie: { n: 2.0, fitted: true },
    physics_audit: { score: 100, grade: 'A' },
  },
};

describe('KrCurvePlot corrected-fit provenance rendering', () => {
  it('shows a visible unfitted state for a corrected fit (no "null", no blank, no crash)', () => {
    const { container } = render(<KrCurvePlot plotData={CORRECTED_RI_PAYLOAD} />);
    // Never the string "null" where a number was.
    expect(container.textContent).not.toMatch(/\bnull\b/);
    // The Archie Parameters panel must not silently vanish (the blank-where-a-
    // number-was failure): it renders, and declares the unfitted state itself —
    // the footer-legend curve label alone is not enough.
    const panelHeading = screen.getByText('Archie Parameters');
    expect(panelHeading).toBeInTheDocument();
    const panel = panelHeading.closest('div');
    expect(panel.textContent).toMatch(/not fitted|unfitted|unresolved/i);
    // And no numeric n is presented as a parameter value anywhere.
    expect(container.textContent).not.toMatch(/n \(saturation exp\.\)\s*\d/);
  });

  it('still shows the fitted n for a clean fit', () => {
    render(<KrCurvePlot plotData={CLEAN_RI_PAYLOAD} />);
    expect(screen.getByText('n (saturation exp.)')).toBeInTheDocument();
    expect(screen.getByText('2.0000')).toBeInTheDocument();
  });
});
