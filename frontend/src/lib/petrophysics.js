// frontend/src/lib/petrophysics.js
// Pure, framework-free logic for the Studio tab. No React, no DOM — unit-tested
// in petrophysics.test.js. The Corey math mirrors the backend canonical
// implementation in petrophysical_curves.py so the live preview matches the
// server-fitted curves exactly.

/**
 * Normalized water saturation (effective saturation).
 *   Se = (Sw - Swi) / (1 - Swi - Sor), clamped to [0, 1].
 * Mirrors backend _Se(): a zero (or inverted) mobile range returns 0.5.
 */
export function seFromSw(Sw, Swi, Sor) {
  const mobile = 1 - Swi - Sor;
  if (mobile <= 0) return 0.5;
  const se = (Sw - Swi) / mobile;
  if (se < 0) return 0;
  if (se > 1) return 1;
  return se;
}

/**
 * Generate Brooks-Corey relative-permeability curves over the mobile
 * saturation range [Swi, 1 - Sor].
 *   krw = krwMax · Se^nw
 *   kro = kroMax · (1 - Se)^no
 *
 * @returns {{ krw: {x:number,y:number}[], kro: {x:number,y:number}[] }}
 *          x = water saturation Sw, y = relative permeability.
 */
export function coreyCurves({ Swi, Sor, nw, no, krwMax, kroMax, samples = 51 }) {
  const n = Math.max(2, samples | 0);
  const swMin = Swi;
  const swMax = 1 - Sor;
  const krw = [];
  const kro = [];
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    const Sw = swMin + t * (swMax - swMin);
    const Se = seFromSw(Sw, Swi, Sor);
    krw.push({ x: Sw, y: krwMax * Se ** nw });
    kro.push({ x: Sw, y: kroMax * (1 - Se) ** no });
  }
  return { krw, kro };
}

/**
 * Convert an array of {x,y} data points into an SVG path "d" string, scaling
 * each point from data domains into pixel space with an inverted y-axis
 * (SVG y grows downward). Domains default to the unit square [0,1].
 */
export function pointsToSvgPath(
  points,
  { width, height, padding = 0, xDomain = [0, 1], yDomain = [0, 1] } = {},
) {
  if (!points || points.length === 0) return '';
  const [xMin, xMax] = xDomain;
  const [yMin, yMax] = yDomain;
  const innerW = width - 2 * padding;
  const innerH = height - 2 * padding;
  const sx = (v) => padding + ((v - xMin) / (xMax - xMin)) * innerW;
  const sy = (v) => padding + (1 - (v - yMin) / (yMax - yMin)) * innerH;
  return points
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${sx(p.x).toFixed(2)} ${sy(p.y).toFixed(2)}`)
    .join(' ');
}

/**
 * Merge two file lists, deduplicating by file name (existing wins). Shared by
 * the file-input onChange and the drag-and-drop drop handler so both paths
 * behave identically.
 */
export function mergeFilesDedup(existing, incoming) {
  const seen = new Set(existing.map((f) => f.name));
  return [...existing, ...incoming.filter((f) => !seen.has(f.name))];
}
