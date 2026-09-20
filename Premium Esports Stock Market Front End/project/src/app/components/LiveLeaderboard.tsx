import { useEffect, useState } from 'react';
import { Trophy } from 'lucide-react';
import { useLiveLeaderboard } from '../lib/hooks';
import { toNumber } from '../lib/types';
import { colorForId } from '../lib/colors';
import { placementBadgeStyle, placementRowTint } from '../lib/placement';
import { PlayerAvatar } from './Dashboard';

// Shows a tournament's current standings, polling
// GET /tournaments/{id}/live-leaderboard every 8s (see lib/hooks.ts's
// useLiveLeaderboard). Deliberately honest about not being true real-time
// push: standings only reflect whatever the backend's last Osirion sync
// pulled (see forecast-backend/app/services/osirion_service.py), so this
// shows "updated Xs ago" from the actual last_synced_at timestamp rather
// than implying a live ticking feed.
export function LiveLeaderboard({ tournamentId, compact = false }: { tournamentId: string; compact?: boolean }) {
  const { data, loading, error } = useLiveLeaderboard(tournamentId);
  const [, forceTick] = useState(0);

  // Re-render once a second purely so the "updated Xs ago" label counts
  // up smoothly between polls, without refetching anything.
  useEffect(() => {
    const id = setInterval(() => forceTick(t => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  if (loading && !data) {
    return <LeaderboardSkeleton rows={compact ? 4 : 6} />;
  }
  if (error || !data) {
    return (
      <div className="text-center py-4">
        <p className="text-muted-foreground" style={{ fontSize: 12 }}>Standings aren't available right now.</p>
      </div>
    );
  }

  const isFinal = data.tournament_status === 'finalized';
  const entries = compact ? data.entries.slice(0, 8) : data.entries;

  return (
    <div>
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="flex items-center gap-1 px-1.5 py-0.5 rounded font-bold tracking-wide shrink-0"
            style={{
              fontSize: 9,
              background: isFinal ? 'rgba(255,255,255,0.08)' : 'rgba(255,71,87,0.15)',
              color: isFinal ? 'var(--muted-foreground)' : '#ff4757',
            }}
          >
            {!isFinal && (
              <span className="relative flex shrink-0" style={{ width: 6, height: 6 }}>
                <span
                  className="animate-ping absolute inline-flex h-full w-full rounded-full"
                  style={{ background: '#ff4757', opacity: 0.6 }}
                />
                <span className="relative inline-flex rounded-full" style={{ width: 6, height: 6, background: '#ff4757' }} />
              </span>
            )}
            {isFinal ? 'FINAL' : 'LIVE'}
          </span>
          <p className="font-semibold truncate" style={{ fontSize: 13, color: 'var(--foreground)' }}>
            {data.tournament_name}
          </p>
        </div>
        <LastUpdated lastSyncedAt={data.last_synced_at} isOsirionTracked={data.is_osirion_tracked} isLive={!isFinal} />
      </div>

      {entries.length === 0 ? (
        <div className="text-center py-4 rounded-xl" style={{ background: 'rgba(255,255,255,0.02)' }}>
          <p className="text-muted-foreground" style={{ fontSize: 12 }}>No results posted yet.</p>
        </div>
      ) : (
        <div className="space-y-1">
          {entries.map(entry => {
            const badge = placementBadgeStyle(entry.placement);
            const subline = [
              entry.eliminations != null ? `${entry.eliminations} elim${entry.eliminations === 1 ? '' : 's'}` : null,
              entry.points !== null ? `${toNumber(entry.points).toFixed(0)} pts` : null,
            ].filter(Boolean).join(' · ');
            return (
              <div
                key={entry.player_id}
                className="flex items-center gap-2 px-2 py-1.5 rounded-lg"
                style={{ background: placementRowTint(entry.placement) }}
              >
                <div
                  className="flex items-center justify-center shrink-0 rounded-lg font-mono font-bold"
                  style={{ width: 22, height: 22, fontSize: 11, ...badge }}
                >
                  {entry.placement === 1 ? <Trophy style={{ width: 12, height: 12 }} /> : entry.placement}
                </div>
                <PlayerAvatar name={entry.gamertag} color={colorForId(entry.player_id)} size={compact ? 22 : 26} />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold" style={{ fontSize: 12.5, color: 'var(--foreground)' }}>{entry.gamertag}</p>
                  {subline && !compact && (
                    <p className="truncate" style={{ fontSize: 10.5, color: 'var(--muted-foreground)' }}>{subline}</p>
                  )}
                </div>
                {compact && entry.points !== null && (
                  <span className="font-mono shrink-0" style={{ fontSize: 11.5, color: 'var(--muted-foreground)' }}>
                    {toNumber(entry.points).toFixed(0)} pts
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function LeaderboardSkeleton({ rows }: { rows: number }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between mb-2.5">
        <div className="h-3.5 rounded animate-pulse" style={{ width: 140, background: 'rgba(255,255,255,0.06)' }} />
        <div className="h-3 rounded animate-pulse" style={{ width: 60, background: 'rgba(255,255,255,0.06)' }} />
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-2 px-2 py-1.5 rounded-lg" style={{ background: 'rgba(255,255,255,0.03)' }}>
          <div className="rounded-lg animate-pulse shrink-0" style={{ width: 22, height: 22, background: 'rgba(255,255,255,0.06)' }} />
          <div className="rounded-full animate-pulse shrink-0" style={{ width: 26, height: 26, background: 'rgba(255,255,255,0.06)' }} />
          <div className="h-3 rounded animate-pulse flex-1" style={{ background: 'rgba(255,255,255,0.06)' }} />
        </div>
      ))}
    </div>
  );
}

// Anything older than this while a tournament is still supposedly "live"
// almost certainly means the background Osirion sync is stuck (rate-limited,
// the window ended without Osirion ever marking it finalized, etc.) rather
// than a genuinely fresh update -- surface that honestly instead of just
// printing a big scary minute count (the original bug report: "Updated
// 17432m ago" with no indication anything was wrong).
const STALE_SYNC_THRESHOLD_MS = 15 * 60 * 1000;

function formatAge(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function LastUpdated({
  lastSyncedAt,
  isOsirionTracked,
  isLive = false,
}: {
  lastSyncedAt: string | null;
  isOsirionTracked: boolean;
  isLive?: boolean;
}) {
  if (!isOsirionTracked) {
    return <span className="text-muted-foreground" style={{ fontSize: 10 }}>Entered by admin</span>;
  }
  if (!lastSyncedAt) {
    return <span className="text-muted-foreground" style={{ fontSize: 10 }}>Awaiting first sync…</span>;
  }
  const ageMs = Math.max(0, Date.now() - new Date(lastSyncedAt).getTime());
  const stale = isLive && ageMs > STALE_SYNC_THRESHOLD_MS;
  if (stale) {
    return (
      <span
        className="flex items-center gap-1"
        style={{ fontSize: 10, color: '#ffa502' }}
        title="This tournament hasn't synced from Osirion in a while -- it may have ended without being marked final, or the sync is stuck."
      >
        Sync stalled ({formatAge(ageMs)})
      </span>
    );
  }
  return <span className="text-muted-foreground" style={{ fontSize: 10 }}>Updated {formatAge(ageMs)}</span>;
}
