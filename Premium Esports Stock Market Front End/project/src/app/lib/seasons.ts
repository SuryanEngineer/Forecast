import type { SeasonSummary } from './types';

/** "Chapter 7: Season 4 (Override)" -> "C7 S4"; "Mini-Season (Treasure Hunters)" -> "Mini-Season". For chart labels. */
export function shortSeasonName(name: string): string {
  const m = name.match(/Chapter\s+(\d+)\s*[:\-]?\s*Season\s+(\d+)/i);
  if (m) return `C${m[1]} S${m[2]}`;
  return name.replace(/\s*\(.*\)\s*$/, '').trim();
}

/** "12 days left" / "5h left" / "End date TBD" / "ending now". */
export function seasonCountdown(s: Pick<SeasonSummary, 'ends_at'>): string {
  if (!s.ends_at) return 'End date TBD';
  const ms = new Date(s.ends_at).getTime() - Date.now();
  if (ms <= 0) return 'ending now';
  const d = Math.floor(ms / 86_400_000);
  if (d >= 1) return `${d} day${d === 1 ? '' : 's'} left`;
  return `${Math.max(1, Math.floor(ms / 3_600_000))}h left`;
}

export interface SeasonMarker { t: number; label: string; full: string }

/** Season starts that fall inside [from, to] (ms). Nothing before the chart's own data is ever drawn, so past seasons
 * simply don't appear and future ones show up automatically as time passes. */
export function seasonMarkersBetween(seasons: SeasonSummary[], from: number, to: number): SeasonMarker[] {
  return seasons
    .map(s => ({ t: new Date(s.starts_at).getTime(), label: shortSeasonName(s.name), full: s.name }))
    .filter(m => Number.isFinite(m.t) && m.t > from && m.t <= to)
    .sort((a, b) => a.t - b.t);
}
