import { useEffect, useState } from 'react';
import { useLiveLeaderboard } from '../lib/hooks';
import { toNumber } from '../lib/types';

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
    return <p className="text-muted-foreground" style={{ fontSize: 12 }}>Loading standings…</p>;
  }
  if (error || !data) {
    return <p className="text-muted-foreground" style={{ fontSize: 12 }}>Standings aren't available right now.</p>;
  }

  const isFinal = data.tournament_status === 'finalized';
  const entries = compact ? data.entries.slice(0, 8) : data.entries;

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span
            className="px-1.5 py-0.5 rounded font-bold tracking-wide"
            style={{
              fontSize: 9,
              background: isFinal ? 'rgba(255,255,255,0.08)' : 'rgba(255,71,87,0.15)',
              color: isFinal ? 'var(--muted-foreground)' : '#ff4757',
            }}
          >
            {isFinal ? 'FINAL' : '● LIVE'}
          </span>
          <p className="font-semibold truncate" style={{ fontSize: 13, color: 'var(--foreground)', maxWidth: 220 }}>
            {data.tournament_name}
          </p>
        </div>
        <LastUpdated lastSyncedAt={data.last_synced_at} isOsirionTracked={data.is_osirion_tracked} />
      </div>

      {entries.length === 0 ? (
        <p className="text-muted-foreground" style={{ fontSize: 12 }}>No results posted yet.</p>
      ) : (
        <div className="space-y-1">
          {entries.map(entry => (
            <div key={entry.player_id} className="flex items-center justify-between px-2 py-1.5 rounded-lg" style={{ background: 'rgba(255,255,255,0.03)' }}>
              <div className="flex items-center gap-2 min-w-0">
                <span
                  className="font-mono font-bold shrink-0 text-center"
                  style={{ fontSize: 12, width: 20, color: entry.placement <= 3 ? 'var(--accent)' : 'var(--muted-foreground)' }}
                >
                  #{entry.placement}
                </span>
                <span className="truncate" style={{ fontSize: 13, color: 'var(--foreground)' }}>{entry.gamertag}</span>
              </div>
              {entry.points !== null && (
                <span className="font-mono shrink-0" style={{ fontSize: 12, color: 'var(--muted-foreground)' }}>
                  {toNumber(entry.points).toFixed(0)} pts
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function LastUpdated({ lastSyncedAt, isOsirionTracked }: { lastSyncedAt: string | null; isOsirionTracked: boolean }) {
  if (!isOsirionTracked) {
    return <span className="text-muted-foreground" style={{ fontSize: 10 }}>Entered by admin</span>;
  }
  if (!lastSyncedAt) {
    return <span className="text-muted-foreground" style={{ fontSize: 10 }}>Awaiting first sync…</span>;
  }
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(lastSyncedAt).getTime()) / 1000));
  const label = seconds < 60 ? `${seconds}s ago` : `${Math.floor(seconds / 60)}m ago`;
  return <span className="text-muted-foreground" style={{ fontSize: 10 }}>Updated {label}</span>;
}
