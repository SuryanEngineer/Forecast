// Display name for a tournament: a leading "[NAC]" / "[EU]" tag is rewritten as a plain "NAC " / "EU " prefix, and
// NAC / EU events that carry no tag at all get one from their region, so both regions read the same way.
// LAN / global events (region ONSITE etc.) are left as they are.
//
// The trailing date the tracker adds to stored names ("... — Nov 15, 2026") is removed: it is the event's UTC date, which can
// be a different calendar day from the local date and time shown next to every listing, and it only repeats that information.
const TRAILING_DATE = /\s*[—–-]\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\s*$/i;

export function stripTrailingDate(name: string): string {
  return name.replace(TRAILING_DATE, '').trim();
}

export type StageLabel = 'Open round' | 'Qualifier' | 'Finals';

/** Which stage of its event a tournament is. The tracker's own record wins (open lobby, final vs round); otherwise the tier
 * and the words in the name decide. null when it can't be told. */
export function stageLabel(name: string, type?: string | null, lobby?: string | null, stage?: string | null): StageLabel | null {
  const n = name.toLowerCase();
  if (lobby === 'open' || /\bopen\b/.test(n)) return 'Open round';
  if (stage === 'final' || type === 'fncs_finals' || type === 'global_championship' || type === 'major' || /\bfinals?\b/.test(n)) return 'Finals';
  if (stage === 'round' || type === 'fncs_qualifier' || /qualifier|heats?\b|last chance|session|round/.test(n)) return 'Qualifier';
  return null;
}

/** Display name plus its stage when the name doesn't already say it: "NAC Reload Cash Cup · Open round". */
export function titledName(name: string, region?: string | null, type?: string | null, lobby?: string | null, stage?: string | null): string {
  const base = tournamentDisplayName(name, region);
  const label = stageLabel(name, type, lobby, stage);
  if (!label) return base;
  const n = base.toLowerCase();
  const says = label === 'Open round' ? /\bopen\b/.test(n) : label === 'Finals' ? /\bfinals?\b/.test(n) : /qualifier|heats?\b/.test(n);
  return says ? base : `${base} · ${label}`;
}

export function tournamentDisplayName(name: string, region?: string | null): string {
  const clean = stripTrailingDate(name);
  const tagged = clean.match(/^\s*\[(NAC|EU)\]\s*/i);
  const rest = tagged ? clean.slice(tagged[0].length) : clean;
  const r = (region ?? '').toUpperCase();
  const tag = tagged ? tagged[1].toUpperCase() : r === 'NAC' || r === 'EU' ? r : null;
  if (!tag) return rest;
  return new RegExp(`^${tag}\\b`, 'i').test(rest) ? rest : `${tag} ${rest}`;
}
