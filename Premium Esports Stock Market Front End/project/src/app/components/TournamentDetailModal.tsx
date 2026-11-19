import { MobileClose } from './MobileClose';
import { useEffect, useMemo, useState } from 'react';
import { Calendar, Trophy, X } from 'lucide-react';
import { motion } from 'motion/react';
import { api } from '../lib/api';
import { useMarketsByIds } from '../lib/hooks';
import { toNumber, type TournamentResponse } from '../lib/types';
import { titledName } from '../lib/tournamentName';
import { VerifiedBadge } from './HelpModal';
import { TeamLeaderboard } from './TeamLeaderboard';
import { usd } from '../lib/format';

interface Props {
  tournament: TournamentResponse;
  onClose: () => void;
  onOpenPlayer: (id: string) => void;
  /** When set (opened from a player's profile), the standings open on that player's team, highlighted. */
  focusPlayerId?: string;
}

// This modal IS the "dedicated page" for one tournament's full leaderboard
// (see Tournaments.tsx's compact previews, which link here) -- so it can
// afford a much bigger page size than an inline card would.

interface TournamentEntrant {
  player_id: string;
  gamertag: string;
  is_verified?: boolean;
}

interface PayoutPreviewData {
  mode: 'placement' | 'per_win';
  pool: number | null;
  field_players?: number | null;
  field_known?: boolean;
  win_share?: number;
  team_size?: number;
  per_win?: number;
  rows: { placement?: number; fraction?: number; wins?: number; pool_each: number }[];
}

/** For an event that has not been played: what it pays and how, so you know what to expect before buying. */
function PayoutPreview({ tournamentId }: { tournamentId: string }) {
  const [data, setData] = useState<PayoutPreviewData | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    api.get<PayoutPreviewData>(`/tournaments/${tournamentId}/payout-preview`).then(d => { if (alive) setData(d); }).catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [tournamentId]);

  if (failed) return null;
  if (!data) return <p className="text-muted-foreground" style={{ fontSize: 12.5 }}>Loading payouts…</p>;
  if (data.pool === null || data.rows.length === 0) {
    return (
      <div className="rounded-2xl border border-border p-4" style={{ background: 'var(--muted)' }}>
        <p className="text-foreground font-semibold" style={{ fontSize: 13.5 }}>Dividend payouts</p>
        <p className="text-muted-foreground mt-1" style={{ fontSize: 12.5, lineHeight: 1.5 }}>This event's dividend pool hasn't been set yet.</p>
      </div>
    );
  }
  const perWin = data.mode === 'per_win';
  const cols = perWin ? '1fr 1fr' : '1fr 70px 1fr';
  return (
    <div className="rounded-2xl border border-border overflow-hidden" style={{ background: 'var(--muted)' }}>
      <div className="px-4 pt-3.5 pb-2.5">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <p className="text-foreground font-semibold" style={{ fontSize: 14 }}>What this event will pay</p>
          <p className="font-mono font-bold" style={{ fontSize: 15, color: 'var(--gain)' }}>{usd(data.pool)} dividend pool</p>
        </div>
        <p className="text-muted-foreground mt-1.5" style={{ fontSize: 12, lineHeight: 1.55 }}>
          {perWin
            ? `This event pays per game won, not by final placement. Each win is worth ${Math.round((data.win_share ?? 0.25) * 100)}% of the pool, shared across the winning team, so a ${data.team_size}-player team's win pays each player ${usd(data.per_win ?? 0)}.`
            : "Each player's placement earns a share of the pool, shown per player below (everyone on a team gets their own). That amount is split among everyone who owned the player's shares when the event started, in proportion to how many they held."}
        </p>
      </div>
      <div className="px-2 pb-2 overflow-y-auto" style={{ maxHeight: 300 }}>
        <div className="rounded-xl overflow-hidden" style={{ background: 'var(--card)' }}>
          <div className="grid items-center px-3 py-2 text-muted-foreground" style={{ gridTemplateColumns: cols, fontSize: 10.5, letterSpacing: '0.06em', fontWeight: 600 }}>
            <span>{perWin ? 'GAMES WON' : 'PLACEMENT'}</span>
            {!perWin && <span className="text-right">% OF POOL</span>}
            <span className="text-right">POOL PER PLAYER</span>
          </div>
          {data.rows.map((r, i) => (
            <div key={i} className="grid items-center px-3 py-2" style={{ gridTemplateColumns: cols, borderTop: '1px solid var(--border)', fontSize: 12.5 }}>
              <span className="text-foreground font-semibold">
                {perWin ? `${r.wins} win${r.wins === 1 ? '' : 's'}` : r.placement === data.field_players && (r.placement ?? 0) > 12 ? `#${r.placement} (last)` : `#${r.placement}`}
              </span>
              {!perWin && <span className="text-right font-mono text-muted-foreground">{((r.fraction ?? 0) * 100).toFixed((r.fraction ?? 0) >= 0.01 ? 1 : 2)}%</span>}
              <span className="text-right font-mono font-bold" style={{ color: 'var(--gain)' }}>{usd(r.pool_each)}</span>
            </div>
          ))}
        </div>
      </div>
      {!perWin && data.field_players && (
        <p className="text-muted-foreground px-4 pb-3" style={{ fontSize: 11 }}>
          Placements below the top 12 shrink gradually to last place. Based on a field of about {data.field_players} players{data.field_known ? '' : " (the real number isn't known yet)"}.
        </p>
      )}
    </div>
  );
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
export function TournamentDetailModal({ tournament, onClose, onOpenPlayer, focusPlayerId }: Props) {
  const [entrants, setEntrants] = useState<TournamentEntrant[] | null>(null);

  // For a tournament still in progress, this modal IS the "click through to
  // see the full leaderboard" dedicated view the compact preview cards link
  // to -- so it polls the same live-leaderboard endpoint they do, just at a
  // full page size with real pagination instead of a capped preview.
  // phase, not raw status -- status stays 'results_pending' for a
  // tournament's whole life until it finalizes (see Tournaments.tsx's
  // CalendarRow comment), so it doesn't by itself mean "poll for live
  // standings right now". Once the window has actually ended (phase
  // becomes 'finalizing'), fall through to the same results section a
  // finalized tournament uses -- whatever's been recorded so far, without
  // polling something that's no longer moving.
  const isLive = tournament.phase === 'live';

  // Before any placement results exist, show who's already qualified (see
  // GET /tournaments/{id}/entrants -- populated from a sibling
  // heat/qualifier round's leaderboard once that heat concluded, see
  // osirion_service.py's _seed_entrants_from_heat_windows) instead of a
  // flat "no results yet" placeholder.
  useEffect(() => {
    if (tournament.phase === 'completed') return;
    let cancelled = false;
    api
      .get<TournamentEntrant[]>(`/tournaments/${tournament.id}/entrants`)
      .then(r => { if (!cancelled) setEntrants(r); })
      .catch(() => { if (!cancelled) setEntrants([]); });
    return () => { cancelled = true; };
  }, [tournament.id, tournament.phase]);

  // Looks up specific players by id (this tournament's entrants and/or
  // placed competitors), not a ranked page of the market -- see
  // useMarketsByIds' docstring in lib/hooks.ts for why the old "fetch
  // the whole roster and .find()" approach no longer works now that the
  // real roster is 89k+ players.
  const lookupIds = useMemo(() => (entrants ?? []).map(e => e.player_id), [entrants]);
  const { data: marketById } = useMarketsByIds(lookupIds);
  const prizePool = toNumber(tournament.prize_pool);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 modal-overlay"
      style={{ background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(6px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <motion.div
        className="w-full overflow-y-auto rounded-2xl border border-border modal-panel modal-scroll"
        style={{ background: 'var(--card)', maxWidth: 1080, maxHeight: '92vh', scrollbarWidth: 'thin', scrollbarColor: 'rgba(255,255,255,0.08) transparent' }}
        initial={{ opacity: 0, scale: 0.96, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        <MobileClose onClose={onClose} />
        <div className="px-4 sm:px-6 pt-5 pb-4" style={{ background: 'linear-gradient(135deg, rgba(0,200,255,0.08), rgba(155,111,255,0.06))' }}>
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
                {tournament.phase === 'completed'
                  ? 'Final'
                  : tournament.phase === 'live'
                  ? 'In Progress'
                  : tournament.phase === 'finalizing'
                  ? 'Finalizing'
                  : 'Upcoming'}
              </span>
            </div>
            <button onClick={onClose} className="p-2 rounded-xl hover:bg-white/10 transition-colors shrink-0">
              <X className="w-5 h-5 text-muted-foreground" />
            </button>
          </div>
          <h2 className="text-foreground font-bold" style={{ fontSize: 20, lineHeight: 1.3 }}>{titledName(tournament.name, tournament.region, tournament.tournament_type, tournament.live_progress?.lobby, tournament.live_progress?.stage)}</h2>
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
          {tournament.phase === 'upcoming' && <div className="mb-4"><PayoutPreview tournamentId={tournament.id} /></div>}
          {tournament.phase === 'upcoming' && entrants && entrants.length > 0 ? (
            <div className="space-y-2">
              <p className="text-muted-foreground uppercase" style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.08em' }}>
                Qualified entrants ({entrants.length})
              </p>
              <p className="text-muted-foreground" style={{ fontSize: 12, lineHeight: 1.5 }}>
                These players have already qualified for this event. Results and dividend payouts appear here once it's played.
              </p>
              <div className="grid grid-cols-2 gap-2">
                {entrants.map(e => {
                  const market = marketById.get(e.player_id);
                  const gamertag = market ? (market.real_name || market.gamertag) : e.gamertag;
                  return (
                    <button
                      key={e.player_id}
                      onClick={() => onOpenPlayer(e.player_id)}
                      className="flex items-center gap-2.5 p-2.5 rounded-xl text-left hover:bg-white/[0.03] transition-colors"
                      style={{ background: 'var(--muted)' }}
                    >
                      <p className="text-foreground font-semibold truncate" style={{ fontSize: 12.5 }}>{gamertag}<VerifiedBadge show={(market?.is_verified ?? e.is_verified)} /></p>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : tournament.phase === 'upcoming' ? (
            <div className="rounded-2xl border border-border p-6 text-center" style={{ background: 'var(--muted)' }}>
              <p style={{ fontSize: 24 }}>⏳</p>
              <p className="text-muted-foreground mt-2" style={{ fontSize: 13, lineHeight: 1.6 }}>
                This one hasn't happened yet. Results and the final leaderboard appear here once it's underway.
              </p>
            </div>
          ) : (
            <TeamLeaderboard tournamentId={tournament.id} onOpenPlayer={onOpenPlayer} focusPlayerId={focusPlayerId} live={isLive} />
          )}
        </div>
      </motion.div>
    </div>
  );
}
