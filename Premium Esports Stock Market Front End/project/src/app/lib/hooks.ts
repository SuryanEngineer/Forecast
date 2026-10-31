import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from './api';
import type {
  AnnouncedTournament,
  CalendarTournamentResponse,
  LeaderboardEntry,
  LiveLeaderboardResponse,
  MarketSnapshot,
  MarketSortKey,
  MarketSummaryResponse,
  PaginatedMarketSnapshotResponse,
  PositionResponse,
  SeasonInfo,
  SeasonSummary,
  SeasonalLeaderboard,
  UserStats,
  TournamentResponse,
} from './types';

interface FetchState<T> {
  data: T;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

function usePolledFetch<T>(path: string | null, initial: T, intervalMs?: number): FetchState<T> {
  const [data, setData] = useState<T>(initial);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const refetch = useCallback(() => setTick(t => t + 1), []);

  useEffect(() => {
    if (!path) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .get<T>(path)
      .then(res => {
        if (!cancelled) {
          setData(res);
          setError(null);
        }
      })
      .catch(e => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick]);

  useEffect(() => {
    if (!intervalMs) return;
    const id = setInterval(refetch, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, refetch]);

  return { data, loading, error, refetch };
}

const EMPTY_MARKET_PAGE: PaginatedMarketSnapshotResponse = { items: [], total: 0, page: 1, page_size: 60, total_pages: 1 };

// GET /markets is paginated server-side -- see the backend's
// app/api/v1/markets.py docstring for why (the real roster is tens of
// thousands of players, not a small curated list; fetching/rendering all
// of them at once is what made the Markets page unusable in the first
// place). Sort and search are also applied server-side, not by filtering
// whatever's already loaded, since a client-side filter over one page
// would silently miss every match on every other page.
//
// Refetches whenever page/pageSize/sort/search change (they're baked
// into the request path, which is usePolledFetch's effect dependency),
// plus every 15s on top of that so prices feel "live" without a
// WebSocket subscription per row.
export function useMarkets(page = 1, pageSize = 60, sort: MarketSortKey = 'market_cap', search = '') {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize), sort });
  const trimmedSearch = search.trim();
  if (trimmedSearch) params.set('search', trimmedSearch);
  return usePolledFetch<PaginatedMarketSnapshotResponse>(`/markets?${params.toString()}`, EMPTY_MARKET_PAGE, 15_000);
}

const EMPTY_MARKET_SUMMARY: MarketSummaryResponse = { total_market_cap: 0, total_players: 0, total_volume_24h: 0, players_trading: 0 };

// GET /markets/summary -- market-wide totals computed server-side (real
// SQL aggregates over every active player), for the overview panel. Kept
// separate from useMarkets since it needs to reflect the WHOLE market
// regardless of which page/sort/search the list view currently has
// loaded -- summing just one page's worth would be wrong once the roster
// is too large to fetch all at once (see EMPTY_MARKET_PAGE's fetch above).
export function useMarketSummary() {
  return usePolledFetch<MarketSummaryResponse>('/markets/summary', EMPTY_MARKET_SUMMARY, 30_000);
}

// Looks up a specific, bounded set of players by id -- for callers that
// need particular players (a user's own portfolio holdings, a
// tournament's entrants/placed competitors), NOT a ranked page of the
// market. Before GET /markets was paginated, every caller just fetched
// the whole roster and did `.find()`/`.get()` on it; now that the real
// roster is 89k+ players, that same lookup has to go by id instead,
// since the player someone holds/placed might not be anywhere near the
// top of whatever page/sort the ranked listing would return. Uses the
// existing GET /markets/{player_id} single-player endpoint, one request
// per id, in parallel -- fine at the scale these callers actually need
// (a person's own holdings, one tournament's field), unlike the full
// roster this replaces.
export function useMarketsByIds(ids: string[]): { data: Map<string, MarketSnapshot>; loading: boolean } {
  const uniqueIds = useMemo(() => [...new Set(ids)].sort(), [ids.join(',')]); // eslint-disable-line react-hooks/exhaustive-deps
  const [data, setData] = useState<Map<string, MarketSnapshot>>(new Map());
  const [loading, setLoading] = useState(false);
  const key = uniqueIds.join(',');

  useEffect(() => {
    if (uniqueIds.length === 0) {
      setData(new Map());
      return;
    }
    let cancelled = false;
    setLoading(true);
    const fetchAll = () => {
      Promise.allSettled(uniqueIds.map(id => api.get<MarketSnapshot>(`/markets/${id}`))).then(results => {
        if (cancelled) return;
        const next = new Map<string, MarketSnapshot>();
        results.forEach((r, i) => {
          if (r.status === 'fulfilled') next.set(uniqueIds[i], r.value);
        });
        setData(next);
        setLoading(false);
      });
    };
    fetchAll();
    const interval = setInterval(fetchAll, 15_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { data, loading };
}

export function useMyPositions() {
  return usePolledFetch<PositionResponse[]>('/players/positions/me', [], 15_000);
}

export function useTournamentsList() {
  return usePolledFetch<TournamentResponse[]>('/tournaments', []);
}

// The upcoming-tournaments calendar (GET /tournaments/calendar) -- 45s
// polling matches the backend's OSIRION_SYNC_INTERVAL_SECONDS, i.e. this
// refreshes at the same cadence new tournaments get auto-tracked and
// standings get pulled, so the calendar's status/payout figures update on
// their own with no admin action needed.
export function useTournamentCalendar(includeCompleted = false) {
  return usePolledFetch<CalendarTournamentResponse[]>(
    includeCompleted ? '/tournaments/calendar?include_completed=true' : '/tournaments/calendar', [], 45_000);
}

export interface DayChange { net_worth: number; net_worth_then: number; change: number; change_pct: number; hours: number }

/** Real 24h change in the user's net worth (trades / deposits netted out, dividends counted) -- computed server-side. */
export function useDayChange() {
  return usePolledFetch<DayChange | null>('/wallet/day-change', null, 30_000);
}

export function useAnnouncedTournaments() {
  return usePolledFetch<AnnouncedTournament[]>('/tournaments/announced', [], 5 * 60_000);
}

export function useLeaderboard() {
  return usePolledFetch<LeaderboardEntry[]>('/leaderboard', [], 30_000);
}

const EMPTY_SEASONAL: SeasonalLeaderboard = { season: null, entries: [], me: null };

// Seasonal Points leaderboard for the active season (resets every season) -- GET /leaderboard/seasonal.
export function useSeasonalLeaderboard() {
  return usePolledFetch<SeasonalLeaderboard>('/leaderboard/seasonal?limit=100', EMPTY_SEASONAL, 30_000);
}

const EMPTY_SEASON_INFO: SeasonInfo = { season: null, ranks: [], points_per_percent: 100 };

export function useSeasonInfo() {
  return usePolledFetch<SeasonInfo>('/seasons/current', EMPTY_SEASON_INFO, 60_000);
}

// Every Fortnite season on the calendar (past, current, upcoming) -- GET /seasons. Used for the chart markers.
export function useSeasonList() {
  return usePolledFetch<SeasonSummary[]>('/seasons', [], 10 * 60_000);
}

// Lifetime stats for the logged-in user -- GET /stats/me.
export function useMyStats() {
  return usePolledFetch<UserStats | null>('/stats/me', null, 60_000);
}

// Polls the live standings for one tournament every 8s -- see
// GET /tournaments/{id}/live-leaderboard in forecast-backend. `null`
// tournamentId means "don't fetch yet" (e.g. no live tournament found).
// `pageSize` defaults small (10) since every caller today is a compact
// preview widget -- pass a bigger one (and/or a page number) from a full
// paginated view instead of ever relying on the backend's own default.
export function useLiveLeaderboard(tournamentId: string | null, page = 1, pageSize = 10) {
  const path = tournamentId ? `/tournaments/${tournamentId}/live-leaderboard?page=${page}&page_size=${pageSize}` : null;
  return usePolledFetch<LiveLeaderboardResponse | null>(path, null, 8_000);
}

// Picks the single tournament most worth showing a "live" widget for,
// out of whatever GET /tournaments already returned: prefer one that has
// started but isn't finalized yet (i.e. actually in progress or awaiting
// results), else fall back to the most recently finalized one so there's
// still something to show right after a tournament wraps up.
export function usePickLiveTournament(tournaments: TournamentResponse[]): TournamentResponse | null {
  return useMemo(() => {
    if (tournaments.length === 0) return null;
    const now = Date.now();

    const inProgress = tournaments.filter(t => {
      if (t.status === 'finalized') return false;
      const started = !t.start_time || new Date(t.start_time).getTime() <= now;
      return started;
    });
    if (inProgress.length > 0) {
      // Most recently started of the in-progress ones.
      return inProgress.reduce((latest, t) =>
        !latest.start_time || (t.start_time && new Date(t.start_time) > new Date(latest.start_time)) ? t : latest
      );
    }

    const finalized = tournaments.filter(t => t.status === 'finalized');
    if (finalized.length > 0) {
      return finalized.reduce((latest, t) => (new Date(t.created_at) > new Date(latest.created_at) ? t : latest));
    }

    return null;
  }, [tournaments]);
}
