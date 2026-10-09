import { useEffect, useMemo, useState } from 'react';
import { Calendar, ChevronLeft, ChevronRight, Trophy, X } from 'lucide-react';
import { motion } from 'motion/react';
import { api } from '../lib/api';
import { useLiveLeaderboard, useMarketsByIds } from '../lib/hooks';
import { toNumber, type TournamentResponse } from '../lib/types';
import { colorForId } from '../lib/colors';
import { placementBadgeStyle } from '../lib/placement';
import { PlayerAvatar } from './Dashboard';
import { VerifiedBadge } from './HelpModal';
import { TeamLeaderboard } from './TeamLeaderboard';

interface Props {
  tournament: TournamentResponse;
  onClose: () => void;
  onOpenPlayer: (id: string) => void;
}

// This modal IS the "dedicated page" for one tournament's full leaderboard
// (see Tournaments.tsx's compact previews, which link here) -- so it can
// afford a much bigger page size than an inline card would.
const DETAIL_PAGE_SIZE = 100;

function PageControls({
  page,
  totalPages,
  total,
  onPage,
}: {
  page: number;
  totalPages: number;
  total: number;
  onPage: (p: number) => void;
}) {
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-between pt-1">
      <p className="text-muted-foreground" style={{ fontSize: 11 }}>
        {total.toLocaleString()} total &middot; page {page} of {totalPages}
      </p>
      <div className="flex items-center gap-1.5">
        <button
          onClick={() => onPage(page - 1)}
          disabled={page <= 1}
          className="p-1.5 rounded-lg transition-colors hover:bg-white/[0.06] disabled:opacity-30"
          style={{ background: 'var(--muted)' }}
        >
          <ChevronLeft className="w-4 h-4 text-muted-foreground" />
        </button>
        <button
          onClick={() => onPage(page + 1)}
          disabled={page >= totalPages}
          className="p-1.5 rounded-lg transition-colors hover:bg-white/[0.06] disabled:opacity-30"
          style={{ background: 'var(--muted)' }}
        >
          <ChevronRight className="w-4 h-4 text-muted-foreground" />
        </button>
      </div>
    </div>
  );
}

// The dedicated full-leaderboard view for a tournament still in progress --
// this is what a compact preview card (Tournaments.tsx's "Happening Now")
// links to. Separate from the finalized-results branch below since a live
// LiveLeaderboardEntry has no team_id/prize_won/percentile yet (those only
// exist once PlacementResult rows are written at finalization).
function LiveStandingsSection({
  data,
  loading,
  page,
  onPage,
  onOpenPlayer,
}: {
  data: ReturnType<typeof useLiveLeaderboard>['data'];
  loading: boolean;
  page: number;
  onPage: (p: number) => void;
  onOpenPlayer: (id: string) => void;
}) {
  if (loading && !data) {
    return <p className="text-muted-foreground text-center py-8" style={{ fontSize: 13 }}>Loading live standings…</p>;
  }
  if (!data || data.entries.length === 0) {
    return <p className="text-muted-foreground text-center py-8" style={{ fontSize: 13 }}>No standings posted yet -- check back once the tournament is underway.</p>;
  }
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-muted-foreground uppercase" style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.08em' }}>
          Live standings ({data.total_entries.toLocaleString()})
        </p>
      </div>
      <div className="space-y-1.5">
        {data.entries.map(entry => (
          <button
            key={entry.player_id}
            onClick={() => onOpenPlayer(entry.player_id)}
            className="w-full flex items-center gap-3 p-3 rounded-2xl text-left hover:bg-white/[0.03] transition-colors"
            style={{ background: 'var(--muted)' }}
          >
            <div
              className="w-8 h-8 rounded-xl flex items-center justify-center font-mono font-bold shrink-0"
              style={{ fontSize: 12, ...placementBadgeStyle(entry.placement) }}
            >
              #{entry.placement}
            </div>
            <PlayerAvatar name={entry.gamertag} color={colorForId(entry.player_id)} size={36} />
            <div className="flex-1 min-w-0">
              <p className="text-foreground font-semibold truncate" style={{ fontSize: 13.5 }}>{entry.gamertag}<VerifiedBadge show={entry.is_verified} /></p>
              <p className="text-muted-foreground" style={{ fontSize: 11 }}>
                {entry.eliminations !== null ? `${entry.eliminations} elims` : ''}
                {entry.points !== null ? `${entry.eliminations !== null ? ' · ' : ''}${toNumber(entry.points)} pts` : ''}
              </p>
            </div>
          </button>
        ))}
      </div>
      <PageControls page={page} totalPages={data.total_pages} total={data.total_entries} onPage={onPage} />
    </div>
  );
}

interface TournamentEntrant {
  player_id: string;
  gamertag: string;
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
  const [entrants, setEntrants] = useState<TournamentEntrant[] | null>(null);

  // For a tournament still in progress, this modal IS the "click through to
  // see the full leaderboard" dedicated view the compact preview cards link
  // to -- so it polls the same live-leaderboard endpoint they do, just at a
  // full page size with real pagination instead of a capped preview.
  const [livePage, setLivePage] = useState(1);
  // phase, not raw status -- status stays 'results_pending' for a
  // tournament's whole life until it finalizes (see Tournaments.tsx's
  // CalendarRow comment), so it doesn't by itself mean "poll for live
  // standings right now". Once the window has actually ended (phase
  // becomes 'finalizing'), fall through to the same results section a
  // finalized tournament uses -- whatever's been recorded so far, without
  // polling something that's no longer moving.
  const isLive = tournament.phase === 'live';
  const { data: liveData, loading: liveLoading } = useLiveLeaderboard(
    isLive ? tournament.id : null,
    livePage,
    DETAIL_PAGE_SIZE
  );

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
                      <PlayerAvatar name={gamertag} color={colorForId(e.player_id)} size={28} />
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
                This one hasn't happened yet. Check back once it's underway or an admin has entered results.
              </p>
            </div>
          ) : isLive ? (
            <LiveStandingsSection
              data={liveData}
              loading={liveLoading}
              page={livePage}
              onPage={setLivePage}
              onOpenPlayer={onOpenPlayer}
            />
          ) : (
            <TeamLeaderboard tournamentId={tournament.id} onOpenPlayer={onOpenPlayer} />
          )}
        </div>
      </motion.div>
    </div>
  );
}
