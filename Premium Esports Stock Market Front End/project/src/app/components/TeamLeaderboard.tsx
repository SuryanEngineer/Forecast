import { useEffect, useState } from 'react';
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Coins } from 'lucide-react';
import { api } from '../lib/api';
import {
  toNumber,
  type PaginatedTeamResultResponse,
  type TeamGamesResponse,
  type TeamResultResponse,
} from '../lib/types';
import { colorForId } from '../lib/colors';
import { placementBadgeStyle } from '../lib/placement';
import { PlayerAvatar } from './Dashboard';
import { VerifiedBadge } from './HelpModal';

const PAGE_SIZE = 50;

function money(n: number): string {
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

// "TIME_ALIVE_STAT" -> "Time alive"
function prettyStatName(key: string): string {
  const s = key.replace(/_STAT(_INDEX)?$/i, '').replace(/_/g, ' ').toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg px-2.5 py-1.5 text-center" style={{ background: 'rgba(255,255,255,0.05)' }}>
      <p className="font-mono font-bold text-foreground" style={{ fontSize: 13 }}>{value}</p>
      <p className="text-muted-foreground uppercase" style={{ fontSize: 9, letterSpacing: '0.06em' }}>{label}</p>
    </div>
  );
}

// Game-by-game breakdown for one team -- fetched lazily the first time a team card is expanded.
function TeamGames({ tournamentId, playerId }: { tournamentId: string; playerId: string }) {
  const [data, setData] = useState<TeamGamesResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [openGame, setOpenGame] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<TeamGamesResponse>(`/tournaments/${tournamentId}/players/${playerId}/games`)
      .then(r => { if (!cancelled) setData(r); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [tournamentId, playerId]);

  if (failed) {
    return <p className="text-muted-foreground py-2" style={{ fontSize: 12 }}>Couldn't load this team's games.</p>;
  }
  if (!data) {
    return <p className="text-muted-foreground py-2" style={{ fontSize: 12 }}>Loading games…</p>;
  }
  if (data.games.length === 0) {
    return (
      <p className="text-muted-foreground py-2" style={{ fontSize: 12 }}>
        Game-by-game data isn't available for this team.
      </p>
    );
  }

  return (
    <div className="space-y-2.5 pt-1">
      <div className="grid grid-cols-5 gap-1.5">
        <Chip label="Games" value={String(data.games_played)} />
        <Chip label="Wins" value={String(data.wins)} />
        <Chip label="Avg place" value={data.avg_placement !== null ? toNumber(data.avg_placement).toFixed(1) : '–'} />
        <Chip label="Best" value={data.best_placement !== null ? `#${data.best_placement}` : '–'} />
        <Chip label="Elims" value={data.total_eliminations !== null ? String(data.total_eliminations) : '–'} />
      </div>

      <div className="rounded-xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.03)' }}>
        <div className="grid items-center px-3 py-1.5 text-muted-foreground uppercase" style={{ gridTemplateColumns: '48px 1fr 1fr 1fr 20px', fontSize: 10, letterSpacing: '0.06em', fontWeight: 600 }}>
          <span>Game</span><span>Placed</span><span>Elims</span><span>Points</span><span />
        </div>
        {data.games.map(g => {
          const extra = Object.entries(g.stats).filter(
            ([k]) => !/PLACEMENT|ELIMS|Eliminations/i.test(k) && ['number', 'string'].includes(typeof g.stats[k])
          );
          const isOpen = openGame === g.game;
          return (
            <div key={g.game} className="border-t" style={{ borderColor: 'rgba(255,255,255,0.05)' }}>
              <button
                onClick={() => extra.length > 0 && setOpenGame(isOpen ? null : g.game)}
                className="w-full grid items-center px-3 py-2 text-left"
                style={{ gridTemplateColumns: '48px 1fr 1fr 1fr 20px', cursor: extra.length > 0 ? 'pointer' : 'default' }}
              >
                <span className="font-mono text-muted-foreground" style={{ fontSize: 12 }}>#{g.game}</span>
                <span
                  className="font-mono font-bold"
                  style={{ fontSize: 13, color: g.placement === 1 ? '#fbbf24' : 'var(--foreground)' }}
                >
                  {g.placement !== null ? `${g.placement}${g.placement === 1 ? ' 🏆' : ''}` : '–'}
                </span>
                <span className="font-mono text-foreground" style={{ fontSize: 13 }}>{g.eliminations ?? '–'}</span>
                <span className="font-mono text-foreground" style={{ fontSize: 13 }}>{g.points !== null ? toNumber(g.points) : '–'}</span>
                {extra.length > 0 ? (
                  isOpen ? <ChevronUp className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />
                ) : <span />}
              </button>
              {isOpen && extra.length > 0 && (
                <div className="px-3 pb-2.5 grid grid-cols-2 gap-x-4 gap-y-1">
                  {extra.map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between">
                      <span className="text-muted-foreground" style={{ fontSize: 11 }}>{prettyStatName(k)}</span>
                      <span className="font-mono text-foreground" style={{ fontSize: 11.5 }}>{String(v)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TeamCard({
  team,
  tournamentId,
  onOpenPlayer,
}: {
  team: TeamResultResponse;
  tournamentId: string;
  onOpenPlayer: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const pool = team.team_pool_amount !== null ? toNumber(team.team_pool_amount) : null;
  const mine = team.my_payout !== null ? toNumber(team.my_payout) : null;
  const hasStake = mine !== null || (team.my_shares_at_start ?? 0) > 0;
  const label = team.members.length === 1 ? null : team.members.length === 2 ? 'Duo' : 'Squad';

  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{
        background: 'var(--muted)',
        // Teams the viewer owns a piece of stand out with an accent border + glow.
        border: hasStake ? '1.5px solid rgba(251,191,36,0.65)' : '1px solid transparent',
        boxShadow: hasStake ? '0 0 0 1px rgba(251,191,36,0.15), 0 0 18px rgba(251,191,36,0.10)' : undefined,
      }}
    >
      <div className="flex items-start gap-3 p-3">
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center font-mono font-bold shrink-0"
          style={{ fontSize: 12, ...placementBadgeStyle(team.placement) }}
        >
          #{team.placement}
        </div>

        <div className="flex-1 min-w-0 space-y-1">
          {label && (
            <p className="text-muted-foreground uppercase" style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.06em' }}>{label}</p>
          )}
          {team.members.map(m => (
            <button
              key={m.player_id}
              onClick={() => onOpenPlayer(m.player_id)}
              className="flex items-center gap-2 text-left w-full hover:opacity-80 transition-opacity"
            >
              <PlayerAvatar name={m.gamertag} color={colorForId(m.player_id)} size={26} />
              <span className="text-foreground font-semibold truncate" style={{ fontSize: 13.5 }}>
                {m.gamertag}
                <VerifiedBadge show={m.is_verified} />
              </span>
              {(m.my_shares_at_start ?? 0) > 0 && (
                <span className="shrink-0 rounded-full px-1.5 py-0.5 font-bold" style={{ fontSize: 9.5, background: 'rgba(251,191,36,0.18)', color: '#fbbf24' }}>
                  YOU OWN
                </span>
              )}
            </button>
          ))}
          {/* Team-wide numbers, shown ONCE (they're cumulative for the whole team). */}
          <p className="text-muted-foreground" style={{ fontSize: 11.5 }}>
            {team.eliminations !== null ? `${team.eliminations} elims` : ''}
            {team.points !== null ? `${team.eliminations !== null ? ' · ' : ''}${toNumber(team.points)} pts` : ''}
          </p>
        </div>

        <div className="text-right shrink-0 space-y-1">
          {pool !== null && pool > 0 ? (
            <div>
              <p className="font-mono font-bold" style={{ fontSize: 14, color: 'var(--gain)' }}>{money(pool)}</p>
              <p className="text-muted-foreground" style={{ fontSize: 10 }}>team dividend pool</p>
            </div>
          ) : (
            <p className="text-muted-foreground italic" style={{ fontSize: 11 }}>No payout</p>
          )}
          {mine !== null && mine > 0 ? (
            <div className="rounded-lg px-2 py-1 text-right" style={{ background: 'rgba(251,191,36,0.16)', border: '1px solid rgba(251,191,36,0.5)' }}>
              <p className="font-mono font-bold flex items-center justify-end gap-1" style={{ fontSize: 13, color: '#fbbf24' }}>
                <Coins className="w-3.5 h-3.5" /> +{money(mine)}
              </p>
              <p style={{ fontSize: 9.5, color: '#fbbf24' }}>your payout</p>
            </div>
          ) : (team.my_shares_at_start ?? 0) > 0 ? (
            <div className="rounded-lg px-2 py-1 text-right" style={{ background: 'rgba(251,191,36,0.10)', border: '1px dashed rgba(251,191,36,0.45)' }}>
              <p style={{ fontSize: 11, color: '#fbbf24', fontWeight: 600 }}>{team.my_shares_at_start} shares held at start</p>
              <p style={{ fontSize: 9.5, color: '#fbbf24' }}>payout pending</p>
            </div>
          ) : null}
        </div>
      </div>

      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-center gap-1 py-1.5 transition-colors hover:bg-white/[0.04]"
        style={{ borderTop: '1px solid rgba(255,255,255,0.05)', fontSize: 11.5, color: 'var(--primary)', fontWeight: 600 }}
      >
        {open ? 'Hide games' : 'Game-by-game breakdown'}
        {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
      </button>
      {open && (
        <div className="px-3 pb-3">
          <TeamGames tournamentId={tournamentId} playerId={team.members[0].player_id} />
        </div>
      )}
    </div>
  );
}

/** Finalized/finalizing tournament leaderboard grouped by TEAM, with team dividend pools, the viewer's own
 * payout highlighted, and an expandable game-by-game history per team. */
export function TeamLeaderboard({
  tournamentId,
  onOpenPlayer,
}: {
  tournamentId: string;
  onOpenPlayer: (id: string) => void;
}) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<PaginatedTeamResultResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .get<PaginatedTeamResultResponse>(`/tournaments/${tournamentId}/teams?page=${page}&page_size=${PAGE_SIZE}`)
      .then(r => { if (!cancelled) setData(r); })
      .catch(() => { if (!cancelled) setData(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [tournamentId, page]);

  if (loading && !data) {
    return <p className="text-muted-foreground text-center py-8" style={{ fontSize: 13 }}>Loading results…</p>;
  }
  if (!data || data.items.length === 0) {
    return <p className="text-muted-foreground text-center py-8" style={{ fontSize: 13 }}>No results recorded for this tournament yet.</p>;
  }

  const myTotal = data.my_total_payout !== null ? toNumber(data.my_total_payout) : 0;

  return (
    <div className="space-y-2">
      <p className="text-muted-foreground uppercase" style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.08em' }}>
        Teams &amp; dividend payouts ({data.total.toLocaleString()})
      </p>
      {myTotal > 0 && (
        <div className="rounded-xl p-3 flex items-center gap-2" style={{ background: 'rgba(251,191,36,0.12)', border: '1px solid rgba(251,191,36,0.5)' }}>
          <Coins className="w-4 h-4" style={{ color: '#fbbf24' }} />
          <p style={{ fontSize: 12.5, color: '#fbbf24', fontWeight: 600 }}>
            You earned {money(myTotal)} from this tournament{data.total_pages > 1 ? ' (on this page)' : ''}.
          </p>
        </div>
      )}
      <p className="text-muted-foreground" style={{ fontSize: 11.5, lineHeight: 1.5 }}>
        Dividends are paid on the shares you held when the tournament started
        {data.record_date ? ` (${new Date(data.record_date).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })})` : ''}
        {' '}— shares bought afterwards don't count, and shares sold afterwards still do. Teams you own a piece of are outlined in gold.
      </p>

      {data.items.map(team => (
        <TeamCard key={`${team.placement}-${team.team_id ?? team.members[0].player_id}`} team={team} tournamentId={tournamentId} onOpenPlayer={onOpenPlayer} />
      ))}

      {data.total_pages > 1 && (
        <div className="flex items-center justify-between pt-1">
          <p className="text-muted-foreground" style={{ fontSize: 11 }}>
            {data.total.toLocaleString()} teams &middot; page {page} of {data.total_pages}
          </p>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setPage(p => p - 1)}
              disabled={page <= 1}
              className="p-1.5 rounded-lg transition-colors hover:bg-white/[0.06] disabled:opacity-30"
              style={{ background: 'var(--muted)' }}
            >
              <ChevronLeft className="w-4 h-4 text-muted-foreground" />
            </button>
            <button
              onClick={() => setPage(p => p + 1)}
              disabled={page >= data.total_pages}
              className="p-1.5 rounded-lg transition-colors hover:bg-white/[0.06] disabled:opacity-30"
              style={{ background: 'var(--muted)' }}
            >
              <ChevronRight className="w-4 h-4 text-muted-foreground" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
