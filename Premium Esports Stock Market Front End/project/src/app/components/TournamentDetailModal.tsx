import { useEffect, useState } from 'react';
import { Calendar, Trophy, X } from 'lucide-react';
import { motion } from 'motion/react';
import { api } from '../lib/api';
import { useMarkets } from '../lib/hooks';
import { toNumber, type TournamentResponse } from '../lib/types';
import { colorForId } from '../lib/colors';
import { PlayerAvatar } from './Dashboard';

interface Props {
  tournament: TournamentResponse;
  onClose: () => void;
  onOpenPlayer: (id: string) => void;
}

interface PlacementResult {
  id: string;
  tournament_id: string;
  player_id: string;
  placement: number;
  points: string | number | null;
  prize_won: string | number | null;
  eliminations: number | null;
}

interface DividendPayout {
  id: string;
  tournament_id: string;
  player_id: string;
  total_pool_amount: string | number;
  per_share_amount: string | number | null;
  shares_outstanding_snapshot: number;
}

function placementBadgeStyle(placement: number) {
  if (placement === 1) return { background: 'rgba(251,191,36,0.2)', color: '#fbbf24' };
  if (placement === 2) return { background: 'rgba(156,163,175,0.15)', color: '#9ca3af' };
  if (placement === 3) return { background: 'rgba(205,127,50,0.15)', color: '#cd7f32' };
  return { background: 'rgba(255,255,255,0.06)', color: 'var(--muted-foreground)' };
}

/** Full "details" view for a single tournament: every placement entered,
 * and the per-share dividend that placement actually paid out (cross-
 * referencing GET /tournaments/{id}/results with GET
 * /dividends/player/{player_id} for each player who placed -- the real
 * backend has no single endpoint that returns both together, and
 * PlacementResultResponse itself has no gamertag/dividend fields, unlike
 * ForecastDemo's equivalent local API response).
 *
 * NOTE on scope: ForecastDemo groups placements into solos/duos teams
 * (via `tournament.format` / `tournament.lobby_size`, fields that only
 * exist in its own simulator). The real backend doesn't track a
 * tournament's format or team pairings at all -- an admin (or the
 * Osirion live sync) just enters whatever placement each player actually
 * earned in the real event -- so this shows a flat list by placement
 * instead of grouped teams. Works for both finalized tournaments (shows
 * results) and ones still upcoming (shows a placeholder only). */
export function TournamentDetailModal({ tournament, onClose, onOpenPlayer }: Props) {
  const { data: markets } = useMarkets();
  const [results, setResults] = useState<PlacementResult[] | null>(null);
  const [payoutsByPlayer, setPayoutsByPlayer] = useState<Record<string, DividendPayout>>({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (tournament.status !== 'finalized') return;
    let cancelled = false;
    setLoading(true);
    api
      .get<PlacementResult[]>(`/tournaments/${tournament.id}/results`)
      .then(async r => {
        if (cancelled) return;
        setResults(r);
        // One request per placed player to find this tournament's payout
        // for them -- there's no bulk "dividends for this tournament"
        // endpoint, so this is capped by however many players actually
        // placed (bounded, not the whole roster).
        const uniquePlayerIds = [...new Set(r.map(row => row.player_id))];
        const settled = await Promise.allSettled(
          uniquePlayerIds.map(pid => api.get<DividendPayout[]>(`/dividends/player/${pid}`))
        );
        if (cancelled) return;
        const map: Record<string, DividendPayout> = {};
        settled.forEach((res, i) => {
          if (res.status !== 'fulfilled') return;
          const match = res.value.find(p => p.tournament_id === tournament.id);
          if (match) map[uniquePlayerIds[i]] = match;
        });
        setPayoutsByPlayer(map);
      })
      .catch(() => { if (!cancelled) setResults([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [tournament.id, tournament.status]);

  const marketById = new Map(markets.map(m => [m.id, m]));
  const prizePool = toNumber(tournament.prize_pool);
  const sorted = results ? [...results].sort((a, b) => a.placement - b.placement) : [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(6px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <motion.div
        className="w-full overflow-y-auto rounded-2xl border border-border"
        style={{ background: 'var(--card)', maxWidth: 640, maxHeight: '85vh', scrollbarWidth: 'thin', scrollbarColor: 'rgba(255,255,255,0.08) transparent' }}
        initial={{ opacity: 0, scale: 0.96, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        <div className="px-6 pt-5 pb-4" style={{ background: 'linear-gradient(135deg, rgba(0,200,255,0.08), rgba(155,111,255,0.06))' }}>
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              <span className="px-2.5 py-0.5 rounded-full font-bold uppercase" style={{ fontSize: 10, background: 'rgba(155,111,255,0.15)', color: 'var(--accent)' }}>
                {tournament.tournament_type.replace('_', ' ')}
              </span>
              <span
                className="px-2.5 py-0.5 rounded-full font-bold uppercase"
                style={{
                  fontSize: 10,
                  background: tournament.status === 'finalized' ? 'rgba(16,217,160,0.15)' : 'rgba(0,200,255,0.15)',
                  color: tournament.status === 'finalized' ? 'var(--gain)' : 'var(--primary)',
                }}
              >
                {tournament.status === 'finalized' ? 'Final' : tournament.status === 'results_pending' ? 'In Progress' : 'Upcoming'}
              </span>
            </div>
            <button onClick={onClose} className="p-2 rounded-xl hover:bg-white/10 transition-colors shrink-0">
              <X className="w-5 h-5 text-muted-foreground" />
            </button>
          </div>
          <h2 className="text-foreground font-bold" style={{ fontSize: 20, lineHeight: 1.3 }}>{tournament.name}</h2>
          <div className="flex items-center gap-4 mt-2 flex-wrap text-muted-foreground" style={{ fontSize: 12.5 }}>
            {tournament.region && <span>{tournament.region}</span>}
            {tournament.start_time && (
              <span className="flex items-center gap-1.5">
                <Calendar className="w-3.5 h-3.5" />
                {new Date(tournament.start_time).toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
              </span>
            )}
            {prizePool > 0 && (
              <span className="flex items-center gap-1.5" style={{ color: 'var(--gain)' }}>
                <Trophy className="w-3.5 h-3.5" /> ${prizePool.toLocaleString()} pool
              </span>
            )}
          </div>
        </div>

        <div className="px-5 pb-5 pt-4">
          {tournament.status === 'scheduled' ? (
            <div className="rounded-2xl border border-border p-6 text-center" style={{ background: 'var(--muted)' }}>
              <p style={{ fontSize: 24 }}>⏳</p>
              <p className="text-muted-foreground mt-2" style={{ fontSize: 13, lineHeight: 1.6 }}>
                This one hasn't happened yet. Check back once it's underway or an admin has entered results.
              </p>
            </div>
          ) : loading ? (
            <p className="text-muted-foreground text-center py-8" style={{ fontSize: 13 }}>Loading results…</p>
          ) : sorted.length === 0 ? (
            <p className="text-muted-foreground text-center py-8" style={{ fontSize: 13 }}>No results recorded for this tournament yet.</p>
          ) : (
            <div className="space-y-2">
              <p className="text-muted-foreground uppercase" style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.08em' }}>
                Placements &amp; dividend payouts
              </p>
              {sorted.map(r => {
                const market = marketById.get(r.player_id);
                const gamertag = market ? (market.real_name || market.gamertag) : 'Unknown player';
                const payout = payoutsByPlayer[r.player_id];
                const perShare = payout?.per_share_amount != null ? toNumber(payout.per_share_amount) : null;
                const poolAmount = payout ? toNumber(payout.total_pool_amount) : r.prize_won !== null ? toNumber(r.prize_won) : null;
                return (
                  <button
                    key={r.id}
                    onClick={() => onOpenPlayer(r.player_id)}
                    className="w-full flex items-center gap-3 p-3 rounded-2xl text-left hover:bg-white/[0.03] transition-colors"
                    style={{ background: 'var(--muted)' }}
                  >
                    <div
                      className="w-8 h-8 rounded-xl flex items-center justify-center font-mono font-bold shrink-0"
                      style={{ fontSize: 12, ...placementBadgeStyle(r.placement) }}
                    >
                      #{r.placement}
                    </div>
                    <PlayerAvatar name={gamertag} color={colorForId(r.player_id)} size={36} />
                    <div className="flex-1 min-w-0">
                      <p className="text-foreground font-semibold truncate" style={{ fontSize: 13.5 }}>{gamertag}</p>
                      <p className="text-muted-foreground" style={{ fontSize: 11 }}>
                        {r.eliminations !== null ? `${r.eliminations} elims` : ''}
                        {r.points !== null ? `${r.eliminations !== null ? ' · ' : ''}${toNumber(r.points)} pts` : ''}
                      </p>
                    </div>
                    {poolAmount !== null && poolAmount > 0 && (
                      <div className="text-right shrink-0">
                        <p className="font-mono font-bold" style={{ fontSize: 13, color: 'var(--gain)' }}>${poolAmount.toLocaleString()}</p>
                        <p className="text-muted-foreground" style={{ fontSize: 10 }}>
                          {perShare !== null ? `$${perShare.toFixed(2)}/share` : 'paid to shareholders'}
                        </p>
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </motion.div>
    </div>
  );
}
