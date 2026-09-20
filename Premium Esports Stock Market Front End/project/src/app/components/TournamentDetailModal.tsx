import { useEffect, useState } from 'react';
import { Calendar, ChevronLeft, ChevronRight, Trophy, X } from 'lucide-react';
import { motion } from 'motion/react';
import { api } from '../lib/api';
import { useLiveLeaderboard, useMarkets } from '../lib/hooks';
import {
  toNumber,
  type PaginatedPlacementResultResponse,
  type PlacementResultResponse,
  type TournamentResponse,
} from '../lib/types';
import { colorForId } from '../lib/colors';
import { placementBadgeStyle } from '../lib/placement';
import { PlayerAvatar } from './Dashboard';

interface Props {
  tournament: TournamentResponse;
  onClose: () => void;
  onOpenPlayer: (id: string) => void;
}

// This modal IS the "dedicated page" for one tournament's full leaderboard
// (see Tournaments.tsx's compact previews, which link here) -- so it can
// afford a much bigger page size than an inline card would.
const DETAIL_PAGE_SIZE = 100;

type PlacementResult = PlacementResultResponse;

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
              <p className="text-foreground font-semibold truncate" style={{ fontSize: 13.5 }}>{entry.gamertag}</p>
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

interface DividendPayout {
  id: string;
  tournament_id: string;
  player_id: string;
  total_pool_amount: string | number;
  per_share_amount: string | number | null;
  shares_outstanding_snapshot: number;
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
  const { data: markets } = useMarkets();
  const [results, setResults] = useState<PlacementResult[] | null>(null);
  const [resultsTotal, setResultsTotal] = useState(0);
  const [resultsTotalPages, setResultsTotalPages] = useState(1);
  const [resultsPage, setResultsPage] = useState(1);
  const [payoutsByPlayer, setPayoutsByPlayer] = useState<Record<string, DividendPayout>>({});
  const [loading, setLoading] = useState(false);
  const [entrants, setEntrants] = useState<TournamentEntrant[] | null>(null);

  // For a tournament still in progress, this modal IS the "click through to
  // see the full leaderboard" dedicated view the compact preview cards link
  // to -- so it polls the same live-leaderboard endpoint they do, just at a
  // full page size with real pagination instead of a capped preview.
  const [livePage, setLivePage] = useState(1);
  const isLive = tournament.status === 'results_pending';
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
    if (tournament.status === 'finalized') return;
    let cancelled = false;
    api
      .get<TournamentEntrant[]>(`/tournaments/${tournament.id}/entrants`)
      .then(r => { if (!cancelled) setEntrants(r); })
      .catch(() => { if (!cancelled) setEntrants([]); });
    return () => { cancelled = true; };
  }, [tournament.id, tournament.status]);

  useEffect(() => {
    if (tournament.status !== 'finalized') return;
    let cancelled = false;
    setLoading(true);
    api
      .get<PaginatedPlacementResultResponse>(
        `/tournaments/${tournament.id}/results?page=${resultsPage}&page_size=${DETAIL_PAGE_SIZE}`
      )
      .then(async page => {
        if (cancelled) return;
        setResults(page.items);
        setResultsTotal(page.total);
        setResultsTotalPages(page.total_pages);
        // One request per placed player (on this page only) to find this
        // tournament's payout for them -- there's no bulk "dividends for
        // this tournament" endpoint, so this is capped by however many
        // players placed on the current page, not the whole field.
        const uniquePlayerIds = [...new Set(page.items.map(row => row.player_id))];
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
  }, [tournament.id, tournament.status, resultsPage]);

  const marketById = new Map(markets.map(m => [m.id, m]));
  const prizePool = toNumber(tournament.prize_pool);
  const sorted = results ? [...results].sort((a, b) => a.placement - b.placement) : [];

  // Osirion's leaderboard is per-TEAM (duos/squads share one placement --
  // see forecast-backend's osirion_service.py module docstring), and each
  // PlacementResult now carries that same team_id (see PlacementResult's
  // backend docstring for why it was added). Group same-team rows into
  // one card here so a duo/squad placement reads as one entry instead of
  // two unrelated-looking rows that just happen to share a rank. A null
  // team_id (manually/CSV-entered results predate this field, or a solo
  // format) falls back to its own row id, so it never merges with anyone.
  const groups: { placement: number; rows: PlacementResult[] }[] = [];
  const groupIndexByKey = new Map<string, number>();
  for (const r of sorted) {
    const key = r.team_id ? `${r.placement}:${r.team_id}` : r.id;
    const existingIndex = groupIndexByKey.get(key);
    if (existingIndex !== undefined) {
      groups[existingIndex].rows.push(r);
    } else {
      groupIndexByKey.set(key, groups.length);
      groups.push({ placement: r.placement, rows: [r] });
    }
  }

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
          {tournament.status === 'scheduled' && entrants && entrants.length > 0 ? (
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
                      <p className="text-foreground font-semibold truncate" style={{ fontSize: 12.5 }}>{gamertag}</p>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : tournament.status === 'scheduled' ? (
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
          ) : loading ? (
            <p className="text-muted-foreground text-center py-8" style={{ fontSize: 13 }}>Loading results…</p>
          ) : sorted.length === 0 ? (
            <p className="text-muted-foreground text-center py-8" style={{ fontSize: 13 }}>No results recorded for this tournament yet.</p>
          ) : (
            <div className="space-y-2">
              <p className="text-muted-foreground uppercase" style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.08em' }}>
                Placements &amp; dividend payouts
              </p>
              {groups.map(group => {
                const isTeam = group.rows.length > 1;
                const rowContent = (r: PlacementResult) => {
                  const market = marketById.get(r.player_id);
                  const gamertag = market ? (market.real_name || market.gamertag) : 'Unknown player';
                  const payout = payoutsByPlayer[r.player_id];
                  const perShare = payout?.per_share_amount != null ? toNumber(payout.per_share_amount) : null;
                  const poolAmount = payout ? toNumber(payout.total_pool_amount) : r.prize_won !== null ? toNumber(r.prize_won) : null;
                  // A payout with zero shares outstanding means this player
                  // was auto-added to fill a leaderboard gap (an Osirion
                  // competitor nobody's IPO'd yet) -- there's no one to pay
                  // a dividend to, so show that plainly instead of a
                  // misleading dollar amount (see osirion_service.py's
                  // _match_player for where these get created).
                  const noSharesAvailable = payout != null && payout.shares_outstanding_snapshot === 0;
                  return (
                    <button
                      key={r.id}
                      onClick={() => onOpenPlayer(r.player_id)}
                      className={`w-full flex items-center gap-3 text-left hover:bg-white/[0.03] transition-colors ${isTeam ? 'py-1.5' : 'p-3 rounded-2xl'}`}
                      style={isTeam ? undefined : { background: 'var(--muted)' }}
                    >
                      {!isTeam && (
                        <div
                          className="w-8 h-8 rounded-xl flex items-center justify-center font-mono font-bold shrink-0"
                          style={{ fontSize: 12, ...placementBadgeStyle(r.placement) }}
                        >
                          #{r.placement}
                        </div>
                      )}
                      <PlayerAvatar name={gamertag} color={colorForId(r.player_id)} size={isTeam ? 30 : 36} />
                      <div className="flex-1 min-w-0">
                        <p className="text-foreground font-semibold truncate" style={{ fontSize: isTeam ? 12.5 : 13.5 }}>{gamertag}</p>
                        <p className="text-muted-foreground" style={{ fontSize: 11 }}>
                          {r.eliminations !== null ? `${r.eliminations} elims` : ''}
                          {r.points !== null ? `${r.eliminations !== null ? ' · ' : ''}${toNumber(r.points)} pts` : ''}
                        </p>
                      </div>
                      {noSharesAvailable ? (
                        <div className="text-right shrink-0">
                          <p className="text-muted-foreground italic" style={{ fontSize: 11 }}>No available shares</p>
                        </div>
                      ) : poolAmount !== null && poolAmount > 0 && (
                        <div className="text-right shrink-0">
                          <p className="font-mono font-bold" style={{ fontSize: 13, color: 'var(--gain)' }}>${poolAmount.toLocaleString()}</p>
                          <p className="text-muted-foreground" style={{ fontSize: 10 }}>
                            {perShare !== null ? `$${perShare.toFixed(2)}/share` : 'paid to shareholders'}
                          </p>
                        </div>
                      )}
                    </button>
                  );
                };

                if (!isTeam) return rowContent(group.rows[0]);

                // A duo/squad that placed together -- one card, one
                // placement badge, teammates stacked underneath (each
                // still individually clickable/payable, since dividends
                // are per-player-holding, not per-team).
                return (
                  <div key={`${group.placement}-${group.rows[0].team_id}`} className="rounded-2xl p-3" style={{ background: 'var(--muted)' }}>
                    <div className="flex items-center gap-2 mb-1.5">
                      <div
                        className="w-8 h-8 rounded-xl flex items-center justify-center font-mono font-bold shrink-0"
                        style={{ fontSize: 12, ...placementBadgeStyle(group.placement) }}
                      >
                        #{group.placement}
                      </div>
                      <p className="text-muted-foreground uppercase" style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.06em' }}>
                        {group.rows.length === 2 ? 'Duo' : 'Squad'}
                      </p>
                    </div>
                    <div className="space-y-0.5" style={{ paddingLeft: 40 }}>
                      {group.rows.map(rowContent)}
                    </div>
                  </div>
                );
              })}
              <PageControls page={resultsPage} totalPages={resultsTotalPages} total={resultsTotal} onPage={setResultsPage} />
            </div>
          )}
        </div>
      </motion.div>
    </div>
  );
}
