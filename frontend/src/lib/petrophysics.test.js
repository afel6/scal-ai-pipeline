// frontend/src/lib/petrophysics.test.js
// TDD RED-first specs for the Studio tab's pure logic:
//   1. seFromSw       — normalized water saturation (mirrors backend _Se)
//   2. coreyCurves    — Brooks-Corey krw/kro point generator
//   3. pointsToSvgPath — data points → SVG path "d" string
//   4. mergeFilesDedup — drag-drop / file-input dedupe by name
//
// Canonical math mirrored from petrophysical_curves.py:
//   Se   = (Sw - Swi) / (1 - Swi - Sor), clamped [0,1]
//   krw  = krwMax · Se^nw
//   kro  = kroMax · (1 - Se)^no

import { describe, it, expect } from 'vitest';
import {
  seFromSw,
  coreyCurves,
  pointsToSvgPath,
  mergeFilesDedup,
} from './petrophysics';

describe('seFromSw — normalized water saturation', () => {
  it('is 0 at the connate-water endpoint (Sw = Swi)', () => {
    expect(seFromSw(0.2, 0.2, 0.2)).toBe(0);
  });

  it('is 1 at the residual-oil endpoint (Sw = 1 - Sor)', () => {
    expect(seFromSw(0.8, 0.2, 0.2)).toBe(1);
  });

  it('is 0.5 at the mid-point of the mobile range', () => {
    // Swi=0.2, Sor=0.2 → mobile=0.6; Sw=0.5 → (0.3)/0.6 = 0.5
    expect(seFromSw(0.5, 0.2, 0.2)).toBeCloseTo(0.5, 10);
  });

  it('clamps below Swi to 0 and above 1-Sor to 1', () => {
    expect(seFromSw(0.05, 0.2, 0.2)).toBe(0);
    expect(seFromSw(0.95, 0.2, 0.2)).toBe(1);
  });

  it('guards a zero mobile range (Swi + Sor >= 1) by returning 0.5', () => {
    expect(seFromSw(0.5, 0.6, 0.5)).toBe(0.5);
  });
});

describe('coreyCurves — Brooks-Corey krw/kro generator', () => {
  const params = { Swi: 0.15, Sor: 0.2, nw: 2, no: 3, krwMax: 0.6, kroMax: 0.9, samples: 51 };

  it('returns krw and kro arrays of the requested sample length', () => {
    const { krw, kro } = coreyCurves(params);
    expect(krw).toHaveLength(51);
    expect(kro).toHaveLength(51);
  });

  it('spans Sw from Swi to (1 - Sor) on the x-axis', () => {
    const { krw } = coreyCurves(params);
    expect(krw[0].x).toBeCloseTo(0.15, 10);
    expect(krw[50].x).toBeCloseTo(0.8, 10);
  });

  it('enforces physical endpoints: krw(Swi)=0, krw(1-Sor)=krwMax', () => {
    const { krw } = coreyCurves(params);
    expect(krw[0].y).toBeCloseTo(0, 10);
    expect(krw[50].y).toBeCloseTo(0.6, 10);
  });

  it('enforces physical endpoints: kro(Swi)=kroMax, kro(1-Sor)=0', () => {
    const { kro } = coreyCurves(params);
    expect(kro[0].y).toBeCloseTo(0.9, 10);
    expect(kro[50].y).toBeCloseTo(0, 10);
  });

  it('applies the Corey exponents at the mid-point (Se=0.5)', () => {
    const { krw, kro } = coreyCurves(params);
    // Se=0.5: krw = 0.6 · 0.5^2 = 0.15 ; kro = 0.9 · 0.5^3 = 0.1125
    expect(krw[25].y).toBeCloseTo(0.15, 6);
    expect(kro[25].y).toBeCloseTo(0.1125, 6);
  });

  it('produces a monotonically increasing krw and decreasing kro', () => {
    const { krw, kro } = coreyCurves(params);
    for (let i = 1; i < krw.length; i++) {
      expect(krw[i].y).toBeGreaterThanOrEqual(krw[i - 1].y);
      expect(kro[i].y).toBeLessThanOrEqual(kro[i - 1].y);
    }
  });
});

describe('pointsToSvgPath — data points → SVG "d" string', () => {
  it('maps domain corners to pixel space with an inverted y-axis', () => {
    const d = pointsToSvgPath([{ x: 0, y: 0 }, { x: 1, y: 1 }], { width: 100, height: 100 });
    // (0,0) → bottom-left (0,100); (1,1) → top-right (100,0)
    expect(d).toBe('M 0.00 100.00 L 100.00 0.00');
  });

  it('starts the path with a Move command', () => {
    const d = pointsToSvgPath([{ x: 0.5, y: 0.5 }], { width: 200, height: 80 });
    expect(d.startsWith('M ')).toBe(true);
  });

  it('returns an empty string for no points', () => {
    expect(pointsToSvgPath([], { width: 100, height: 100 })).toBe('');
  });
});

describe('mergeFilesDedup — dedupe uploads by file name', () => {
  it('appends new files and drops duplicates by name', () => {
    const existing = [new File([], 'a.xlsx')];
    const incoming = [new File([], 'a.xlsx'), new File([], 'b.csv')];
    const merged = mergeFilesDedup(existing, incoming);
    expect(merged.map(f => f.name)).toEqual(['a.xlsx', 'b.csv']);
  });

  it('preserves existing order then appends', () => {
    const existing = [new File([], 'x.pdf'), new File([], 'y.pdf')];
    const incoming = [new File([], 'z.pdf')];
    expect(mergeFilesDedup(existing, incoming).map(f => f.name)).toEqual(['x.pdf', 'y.pdf', 'z.pdf']);
  });

  it('returns the existing set unchanged when nothing new arrives', () => {
    const existing = [new File([], 'only.docx')];
    expect(mergeFilesDedup(existing, []).map(f => f.name)).toEqual(['only.docx']);
  });
});
