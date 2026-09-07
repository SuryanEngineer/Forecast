import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from './api';
import type { LeaderboardEntry, LiveLeaderboardResponse, MarketSnapshot, PositionResponse, TournamentResponse } from './types';

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

// Markets list refreshes periodically so prices feel "live" without a
// WebSocket subscription per row -- 15s is frequent enough to feel
// responsive without hammering the API from every open tab.
export function useMarkets() {
  return usePolledFetch<MarketSnapshot[]>('/markets', [], 15_000);
}

export function useMyPositions() {
  return usePolledFetch<PositionResponse[]>('/players/positions/me', [], 15_000);
}

export function useTournamentsList() {
  return usePolledFetch<TournamentResponse[]>('/tournaments', []);
}

export function useLeaderboard() {
  return usePolledFetch<LeaderboardEntry[]>('/leaderboard', [], 30_000);
}

// Polls the live standings for one tournament every 8s -- see
// GET /tournaments/{id}/live-leaderboard in forecast-backend. `null`
// tournamentId means "don't fetch yet" (e.g. no live tournament found).
export function useLiveLeaderboard(tournamentId: string | null) {
  const path = tournamentId ? `/tournaments/${tournamentId}/live-leaderboard` : null;
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
