import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, Search, X } from 'lucide-react';
import { api } from '../lib/api';

// Open qualifier rounds: anyone can enter, nothing is paid and no dividends come from them, so they live in their own
// collapsed section (off by default) well away from the payout tournaments. Browse any round page by page, or search a
// player's name across the finished rounds.

interface OpenRound {
  leaderboard_event_id: string;
  leaderboard_event_window_id: string;
  name: string;
  regions: string[];
  start_time: string | null;
  end_time: string | null;
  status: 'upcoming' | 'live' | 'finished';
}
interface RoundEntry { rank: number | null; points: number | null; players: string[] }
interface RoundPage { round: OpenRound; page: number; total_pages: number; entries: RoundEntry[]; updated_at?: string | null }
interface SearchHit { name: string; rank: number; points: number | null; round_name: string | null; end_time: string | null; leaderboard_event_id: string; leaderboard_event_window_id: string }
interface SearchResponse { results: SearchHit[]; rounds_indexed: number; rounds_total?: number; note: string }

const STORAGE_KEY = 'forecast:show-open-rounds';
const STATUS_STYLE: Record<OpenRound['status'], { label: string; color: string }> = {
  live: { label: 'LIVE', color: 'var(--loss)' },
  upcoming: { label: 'UPCOMING', color: '#fbbf24' },
  finished: { label: 'FINISHED', color: 'var(--muted-foreground)' },
};

function when(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function RoundModal({ round, onClose, startPage = 0 }: { round: OpenRound; onClose: () => void; startPage?: number }) {
  const [page, setPage] = useState(startPage);
  const [data, setData] = useState<RoundPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true); setError(null);
    const qs = new URLSearchParams({
      leaderboard_event_id: round.leaderboard_event_id,
      leaderboard_event_window_id: round.leaderboard_event_window_id,
      page: String(page),
    });
    api.get<RoundPage>(`/tournaments/open-rounds/entries?${qs.toString()}`)
      .then(d => { if (alive) setData(d); })
      .catch(e => { if (alive) setError(e instanceof Error ? e.message : 'Could not load this page'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [round.leaderboard_event_id, round.leaderboard_event_window_id, page]);

  const total = data?.total_pages ?? 1;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.6)' }} onClick={onClose}>
      <div className="w-full rounded-2xl overflow-hidden flex flex-col" style={{ maxWidth: 640, maxHeight: '88vh', background: 'var(--card)', border: '1px solid var(--border)' }} onClick={e => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 px-5 py-4" style={{ borderBottom: '1px solid var(--border)' }}>
          <div className="min-w-0">
            <p className="text-foreground font-bold truncate" style={{ fontSize: 16 }}>{round.name}</p>
            <p className="text-muted-foreground" style={{ fontSize: 12 }}>
              Open round · no payout · {STATUS_STYLE[round.status].label.toLowerCase()}{round.end_time ? ` · ends ${when(round.end_time)}` : ''}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-muted-foreground hover:text-foreground"><X className="w-5 h-5" /></button>
        </div>
        <div className="overflow-y-auto flex-1">
          {loading && !data && <p className="text-muted-foreground text-center py-10" style={{ fontSize: 14 }}>Loading…</p>}
          {error && <p className="text-center py-10" style={{ fontSize: 13.5, color: 'var(--loss)' }}>{error}</p>}
          {data && data.entries.length === 0 && !error && <p className="text-muted-foreground text-center py-10" style={{ fontSize: 14 }}>No standings on this page yet.</p>}
          {data && data.entries.map((e, i) => (
            <div key={`${e.rank}-${i}`} className="flex items-center gap-3 px-5 py-2" style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border)' }}>
              <span className="font-mono font-bold text-muted-foreground shrink-0 text-right" style={{ fontSize: 13, width: 54 }}>#{e.rank ?? '–'}</span>
              <span className="flex-1 min-w-0 text-foreground truncate" style={{ fontSize: 13.5 }}>{e.players.join(' · ')}</span>
              <span className="font-mono text-muted-foreground shrink-0" style={{ fontSize: 12.5 }}>{e.points ?? '–'} pts</span>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-between px-5 py-3" style={{ borderTop: '1px solid var(--border)' }}>
          <button disabled={page <= 0 || loading} onClick={() => setPage(p => Math.max(0, p - 1))} className="px-3 py-1.5 rounded-lg border border-border text-foreground disabled:opacity-40" style={{ fontSize: 13 }}>Previous</button>
          <span className="text-muted-foreground" style={{ fontSize: 12.5 }}>Page {page + 1} of {total.toLocaleString()}</span>
          <button disabled={page + 1 >= total || loading} onClick={() => setPage(p => p + 1)} className="px-3 py-1.5 rounded-lg border border-border text-foreground disabled:opacity-40" style={{ fontSize: 13 }}>Next</button>
        </div>
      </div>
    </div>
  );
}

export function OpenRoundsSection() {
  const [show, setShow] = useState<boolean>(() => {
    try { return localStorage.getItem(STORAGE_KEY) === '1'; } catch { return false; }
  });
  const [rounds, setRounds] = useState<OpenRound[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | OpenRound['status']>('all');
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [openRound, setOpenRound] = useState<{ round: OpenRound; page: number } | null>(null);

  function toggle() {
    setShow(s => {
      const next = !s;
      try { localStorage.setItem(STORAGE_KEY, next ? '1' : '0'); } catch { /* storage unavailable */ }
      return next;
    });
  }

  useEffect(() => {
    if (!show || rounds !== null) return;
    api.get<OpenRound[]>('/tournaments/open-rounds').then(setRounds).catch(e => { setError(e instanceof Error ? e.message : 'Could not load open rounds'); setRounds([]); });
  }, [show, rounds]);

  // Player search across finished rounds (debounced).
  useEffect(() => {
    const q = query.trim();
    if (!show || q.length < 2) { setHits(null); return; }
    setSearching(true);
    const id = setTimeout(() => {
      api.get<SearchResponse>(`/tournaments/open-rounds/search?q=${encodeURIComponent(q)}`)
        .then(setHits).catch(() => setHits({ results: [], rounds_indexed: 0, note: 'Search is unavailable right now.' }))
        .finally(() => setSearching(false));
    }, 350);
    return () => clearTimeout(id);
  }, [query, show]);

  const visible = useMemo(() => (rounds ?? []).filter(r => filter === 'all' || r.status === filter), [rounds, filter]);
  const roundFor = (h: SearchHit) => (rounds ?? []).find(r => r.leaderboard_event_id === h.leaderboard_event_id && r.leaderboard_event_window_id === h.leaderboard_event_window_id);

  return (
    <div className="rounded-2xl border border-border" style={{ background: 'rgba(255,255,255,0.02)' }}>
      <button onClick={toggle} className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left" aria-expanded={show}>
        <span>
          <span className="text-foreground font-bold" style={{ fontSize: 14 }}>Open qualifier rounds</span>
          <span className="text-muted-foreground ml-2" style={{ fontSize: 12 }}>No payout · anyone can enter · {show ? 'shown' : 'hidden'}</span>
        </span>
        {show ? <ChevronUp className="w-4 h-4 text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground" />}
      </button>

      {show && (
        <div className="px-4 pb-4 space-y-3" style={{ borderTop: '1px solid var(--border)' }}>
          <p className="text-muted-foreground pt-3" style={{ fontSize: 12.5, lineHeight: 1.5 }}>
            These are the open rounds that lead into the tournaments above. They pay no dividends and are only here for reference: browse a round’s
            full standings page by page, or look a player up.
          </p>

          <div className="relative">
            <Search className="w-4 h-4 text-muted-foreground absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search a player across finished open rounds"
              aria-label="Search players in open rounds"
              className="w-full pl-9 pr-3 py-2 rounded-xl border border-border text-foreground outline-none focus:border-primary/50"
              style={{ background: 'var(--card)', fontSize: 13.5 }}
            />
          </div>

          {hits ? (
            <div className="space-y-1.5">
              {searching && <p className="text-muted-foreground" style={{ fontSize: 12.5 }}>Searching…</p>}
              {hits.results.length === 0 && !searching && <p className="text-muted-foreground" style={{ fontSize: 13 }}>No match in the finished rounds indexed so far ({hits.rounds_indexed} round{hits.rounds_indexed === 1 ? '' : 's'}).</p>}
              {hits.results.map((h, i) => {
                const r = roundFor(h);
                return (
                  <button
                    key={`${h.name}-${h.rank}-${i}`} disabled={!r} onClick={() => r && setOpenRound({ round: r, page: 0 })}
                    className="w-full flex items-center gap-3 px-3 py-2 rounded-lg border border-border text-left disabled:cursor-default"
                    style={{ background: 'var(--card)' }}
                  >
                    <span className="font-mono font-bold text-muted-foreground shrink-0" style={{ fontSize: 13, width: 56 }}>#{h.rank}</span>
                    <span className="flex-1 min-w-0">
                      <span className="block text-foreground font-semibold truncate" style={{ fontSize: 13.5 }}>{h.name}</span>
                      <span className="block text-muted-foreground truncate" style={{ fontSize: 11.5 }}>{h.round_name}</span>
                    </span>
                    <span className="font-mono text-muted-foreground shrink-0" style={{ fontSize: 12 }}>{h.points ?? '–'} pts</span>
                  </button>
                );
              })}
              <p className="text-muted-foreground" style={{ fontSize: 11.5 }}>{hits.note}</p>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap gap-1.5">
                {(['all', 'live', 'upcoming', 'finished'] as const).map(f => (
                  <button
                    key={f} onClick={() => setFilter(f)}
                    className="px-3 py-1 rounded-full border"
                    style={{ fontSize: 12, borderColor: filter === f ? 'var(--primary)' : 'var(--border)', color: filter === f ? 'var(--foreground)' : 'var(--muted-foreground)', background: filter === f ? 'rgba(255,255,255,0.06)' : 'transparent' }}
                  >
                    {f === 'all' ? 'All' : f[0].toUpperCase() + f.slice(1)}
                  </button>
                ))}
              </div>
              {rounds === null && <p className="text-muted-foreground" style={{ fontSize: 13 }}>Loading open rounds…</p>}
              {error && <p style={{ fontSize: 13, color: 'var(--loss)' }}>{error}</p>}
              {rounds !== null && visible.length === 0 && !error && <p className="text-muted-foreground" style={{ fontSize: 13 }}>No open rounds to show.</p>}
              {visible.map(r => {
                const st = STATUS_STYLE[r.status];
                return (
                  <button
                    key={`${r.leaderboard_event_id}/${r.leaderboard_event_window_id}`} onClick={() => setOpenRound({ round: r, page: 0 })}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border border-border text-left transition-colors hover:border-primary/40"
                    style={{ background: 'var(--card)' }}
                  >
                    <span className="font-mono font-bold shrink-0 rounded-md text-center" style={{ fontSize: 10, width: 74, padding: '3px 0', color: st.color, border: `1px solid ${st.color}` }}>{st.label}</span>
                    <span className="flex-1 min-w-0">
                      <span className="block text-foreground font-semibold truncate" style={{ fontSize: 13.5 }}>{r.name}</span>
                      <span className="block text-muted-foreground truncate" style={{ fontSize: 11.5 }}>{when(r.start_time)}{r.regions.length ? ` · ${r.regions.join(', ')}` : ''} · no payout</span>
                    </span>
                  </button>
                );
              })}
            </>
          )}
        </div>
      )}

      {openRound && <RoundModal round={openRound.round} startPage={openRound.page} onClose={() => setOpenRound(null)} />}
    </div>
  );
}
