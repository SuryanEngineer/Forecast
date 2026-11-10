// Shared helpers for the net-worth charts (My Portfolio and the investor popup).

/** Y-axis for a value chart: pads the data's range so the line never hugs the edges (flat stretches still get some context
 * above and below), then snaps to round tick values (1 / 2 / 2.5 / 5 x 10^n) so the labels read cleanly. */
export function niceAxis(values: number[]): { domain: [number, number]; ticks: number[]; step: number } {
  let lo = Math.min(...values), hi = Math.max(...values);
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { domain: [0, 1], ticks: [0, 1], step: 1 };
  const range = Math.max(hi - lo, Math.abs(hi) * 0.01, 1);   // a flat line still shows +/-0.5% around it
  const pad = range * 0.18;
  lo = Math.max(0, lo - pad); hi = hi + pad;
  const raw = (hi - lo) / 4;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = ([1, 2, 2.5, 5, 10].map(m => m * mag).find(m => m >= raw)) ?? raw;
  const first = Math.floor(lo / step) * step, last = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let v = first; v <= last + step / 2; v += step) ticks.push(Math.round(v / step) * step);
  return { domain: [ticks[0], ticks[ticks.length - 1]], ticks, step };
}

/** Compact dollar label with just enough decimals that neighbouring ticks stay distinct ($99.5K, $100K, $100.5K). */
export function axisMoney(v: number, step: number): string {
  const unit = Math.abs(v) >= 1e6 || step >= 1e6 ? 1e6 : Math.abs(v) >= 1e4 || step >= 1e3 ? 1e3 : 1;
  const suffix = unit === 1e6 ? 'M' : unit === 1e3 ? 'K' : '';
  const u = step / unit;
  let d = 0;
  while (d < 3 && Math.abs(u * 10 ** d - Math.round(u * 10 ** d)) > 1e-6) d++;
  if (unit === 1) d = u >= 1 ? 0 : 2;
  return `$${(v / unit).toFixed(d)}${suffix}`;
}
