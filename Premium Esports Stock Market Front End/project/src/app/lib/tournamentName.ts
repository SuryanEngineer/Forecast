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

export type LobbyLabel = 'Open lobby' | 'Set lobby';

/** Whether an event is an open lobby (anyone can enter) or a set lobby (a fixed field). The tracker's own record wins; without
 * it, the name ("open") and the tier (finals / qualifiers we track are all set lobbies) decide. null when it can't be told. */
export function lobbyLabel(name: string, type?: string | null, lobby?: string | null): LobbyLabel | null {
  if (lobby === 'open') return 'Open lobby';
  if (lobby === 'set') return 'Set lobby';
  if (/\bopen\b/i.test(name)) return 'Open lobby';
  if (type === 'fncs_finals' || type === 'fncs_qualifier' || type === 'global_championship' || type === 'major' || type === 'performance_eval') return 'Set lobby';
  return null;
}

/** Display name plus its lobby type: "NAC FNCS Solo Reload Finals · Set lobby", "FNCS Solo Reload Open Round 1 · Open lobby". */
export function titledName(name: string, region?: string | null, type?: string | null, lobby?: string | null, _stage?: string | null): string {
  const base = tournamentDisplayName(name, region);
  const label = lobbyLabel(name, type, lobby);
  return label ? `${base} · ${label}` : base;
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
