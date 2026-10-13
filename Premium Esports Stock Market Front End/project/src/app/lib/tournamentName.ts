// Display name for a tournament: a leading "[NAC]" / "[EU]" tag is rewritten as a plain "NAC " / "EU " prefix, and
// NAC / EU events that carry no tag at all get one from their region, so both regions read the same way.
// LAN / global events (region ONSITE etc.) are left as they are.
export function tournamentDisplayName(name: string, region?: string | null): string {
  const tagged = name.match(/^\s*\[(NAC|EU)\]\s*/i);
  const rest = tagged ? name.slice(tagged[0].length) : name;
  const r = (region ?? '').toUpperCase();
  const tag = tagged ? tagged[1].toUpperCase() : r === 'NAC' || r === 'EU' ? r : null;
  if (!tag) return rest;
  return new RegExp(`^${tag}\\b`, 'i').test(rest) ? rest : `${tag} ${rest}`;
}
