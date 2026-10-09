import { useEffect, useState } from 'react';
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Coins } from 'lucide-react';
import { api } from '../lib/api';
import {
  toNumber,
  type PaginatedTeamResultResponse,
  type TeamGamesResponse,
  type TournamentGamesResponse,
  type TeamResultResponse,
} from '../lib/types';
import { colorForId } from '../lib/colors';
import { placementBadgeStyle } from '../lib/placement';
import { PlayerAvatar } from './Dashboard';
import { VerifiedBadge } from './HelpModal';

const PAGE_SIZE = 50;
const COLS = '44px 1fr 1fr 1fr 1fr 1fr';

function money(n: number): string {
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function statNum(stats: Record<string, unknown>, key: string): number | null {
  const v = stats[key];
  return typeof v === 'number' ? v : null;
}

function mmss(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const r = Math.round(seconds % 60);
  return `${m}:${String(r).padStart(2, '0')}`;
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
        <div className="grid items-center px-3 py-1.5 text-muted-foreground uppercase" style={{ gridTemplateColumns: COLS, fontSize: 10, letterSpacing: '0.06em', fontWeight: 600 }}>
          <span>Game</span><span>Placed</span><span>Elims</span><span>Alive</span><span>Dealt</span><span>Taken</span>
        </div>
        {data.games.map(g => {
          const alive = statNum(g.stats, 'TIME_ALIVE_STAT');
          const dealt = statNum(g.stats, 'DamageDealt');
          const taken = statNum(g.stats, 'DamageReceived');
          return (
            <div
              key={g.game}
              className="grid items-center px-3 py-2 border-t"
              style={{ gridTemplateColumns: COLS, borderColor: 'rgba(255,255,255,0.05)' }}
            >
              <span className="font-mono text-muted-foreground" style={{ fontSize: 12 }}>#{g.game}</span>
              <span
                className="font-mono font-bold"
                style={{ fontSize: 13, color: g.placement === 1 ? '#fbbf24' : 'var(--foreground)' }}
              >
                {g.placement !== null ? `${g.placement}${g.placement === 1 ? ' 🏆' : ''}` : '–'}
              </span>
              <span className="font-mono text-foreground" style={{ fontSize: 13 }}>{g.eliminations ?? '–'}</span>
              <span className="font-mono text-foreground" style={{ fontSize: 13 }}>{alive !== null ? mmss(alive) : '–'}</span>
              <span className="font-mono text-foreground" style={{ fontSize: 13 }}>{dealt !== null ? dealt.toLocaleString() : '–'}</span>
              <span className="font-mono text-foreground" style={{ fontSize: 13 }}>{taken !== null ? taken.toLocaleString() : '–'}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const GOLD = '#fbbf24';

function TeamCard({
  team,
  tournamentId,
  estimate,
  onOpenPlayer,
}: {
  team: TeamResultResponse;
  tournamentId: string;
  estimate: boolean;
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
      <div className="flex items-stretch gap-4 p-3.5">
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center font-mono font-bold shrink-0"
          style={{ fontSize: 13, ...placementBadgeStyle(team.placement) }}
        >
          #{team.placement}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5">
            {label && (
              <span className="text-muted-foreground uppercase" style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.06em' }}>{label}</span>
            )}
            {/* Team-wide numbers, shown ONCE (they're cumulative for the whole team). */}
            <span className="text-muted-foreground" style={{ fontSize: 12 }}>
              {team.eliminations !== null ? `${team.eliminations} elims` : ''}
              {team.points !== null ? `${team.eliminations !== null ? ' · ' : ''}${toNumber(team.points)} pts` : ''}
            </span>
          </div>

          {/* One row per player: name, what their placement paid out in total, and the per-share dividend. */}
          <div className="space-y-1">
            {team.members.map(m => {
              const mPool = m.pool_amount !== null ? toNumber(m.pool_amount) : null;
              const perShare = m.per_share_amount !== null ? toNumber(m.per_share_amount) : null;
              const myPay = m.my_payout !== null ? toNumber(m.my_payout) : null;
              return (
                <div key={m.player_id} className="flex items-center gap-3">
                  <button
                    onClick={() => onOpenPlayer(m.player_id)}
                    className="flex items-center gap-2 text-left min-w-0 flex-1 hover:opacity-80 transition-opacity"
                  >
                    <PlayerAvatar name={m.gamertag} color={colorForId(m.player_id)} size={28} />
                    <span className="text-foreground font-semibold truncate" style={{ fontSize: 14 }}>
                      {m.gamertag}
                      <VerifiedBadge show={m.is_verified} />
                    </span>
                    {(m.my_shares_at_start ?? 0) > 0 && (
                      <span className="shrink-0 rounded-full px-1.5 py-0.5 font-bold" style={{ fontSize: 9.5, background: 'rgba(251,191,36,0.18)', color: GOLD }}>
                        YOU OWN {m.my_shares_at_start}
                      </span>
                    )}
                  </button>
                  <div className="text-right shrink-0" style={{ minWidth: 96 }}>
                    <p className="font-mono font-bold" style={{ fontSize: 13, color: mPool && mPool > 0 ? 'var(--gain)' : 'var(--muted-foreground)' }}>
                      {mPool !== null && mPool > 0 ? money(mPool) : '$0'}
                    </p>
                    <p className="text-muted-foreground" style={{ fontSize: 9.5 }}>{estimate ? 'est. total payout' : 'total payout'}</p>
                  </div>
                  <div className="text-right shrink-0" style={{ minWidth: 84 }}>
                    <p className="font-mono font-semibold text-foreground" style={{ fontSize: 13 }}>
                      {perShare !== null ? `$${perShare.toLocaleString(undefined, { maximumFractionDigits: 4 })}` : '–'}
                    </p>
                    <p className="text-muted-foreground" style={{ fontSize: 9.5 }}>per share</p>
                  </div>
                  <div className="text-right shrink-0" style={{ minWidth: 96 }}>
                    {myPay !== null && myPay > 0 ? (
                      <div className="rounded-lg px-2 py-1" style={{ background: 'rgba(251,191,36,0.16)', border: '1px solid rgba(251,191,36,0.5)' }}>
                        <p className="font-mono font-bold flex items-center justify-end gap-1" style={{ fontSize: 13, color: GOLD }}>
                          <Coins className="w-3.5 h-3.5" /> +{money(myPay)}
                        </p>
                        <p style={{ fontSize: 9, color: GOLD }}>your payout</p>
                      </div>
                    ) : (m.my_shares_at_start ?? 0) > 0 && !estimate ? (
                      <div className="rounded-lg px-2 py-1" style={{ background: 'rgba(251,191,36,0.10)', border: '1px dashed rgba(251,191,36,0.45)' }}>
                        <p style={{ fontSize: 11, color: GOLD, fontWeight: 600 }}>payout pending</p>
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {team.members.length > 1 && (
          <div className="text-right shrink-0 self-center pl-3" style={{ borderLeft: '1px solid rgba(255,255,255,0.07)', minWidth: 104 }}>
            <p className="font-mono font-bold" style={{ fontSize: 15, color: 'var(--gain)' }}>{pool !== null ? money(pool) : '$0'}</p>
            <p className="text-muted-foreground" style={{ fontSize: 10 }}>team total</p>
            {mine !== null && mine > 0 && (
              <p className="font-mono font-bold mt-1" style={{ fontSize: 12, color: GOLD }}>you +{money(mine)}</p>
            )}
          </div>
        )}
      </div>

      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-center gap-1 py-1.5 transition-colors hover:bg-white/[0.04]"
        style={{ borderTop: '1px solid rgba(255,255,255,0.05)', fontSize: 11.5, color: 'var(--primary)', fontWeight: 600 }}
      >
        {open ? 'Hide this team’s games' : 'This team’s games'}
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

function Pager({ page, totalPages, total, noun, onPage }: { page: number; totalPages: number; total: number; noun: string; onPage: (p: number) => void }) {
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-between pt-1">
      <p className="text-muted-foreground" style={{ fontSize: 11 }}>
        {total.toLocaleString()} {noun} &middot; page {page} of {totalPages}
      </p>
      <div className="flex items-center gap-1.5">
        <button onClick={() => onPage(page - 1)} disabled={page <= 1} className="p-1.5 rounded-lg transition-colors hover:bg-white/[0.06] disabled:opacity-30" style={{ background: 'var(--muted)' }}>
          <ChevronLeft className="w-4 h-4 text-muted-foreground" />
        </button>
        <button onClick={() => onPage(page + 1)} disabled={page >= totalPages} className="p-1.5 rounded-lg transition-colors hover:bg-white/[0.06] disabled:opacity-30" style={{ background: 'var(--muted)' }}>
          <ChevronRight className="w-4 h-4 text-muted-foreground" />
        </button>
      </div>
    </div>
  );
}

function StandingsTab({ tournamentId, onOpenPlayer }: { tournamentId: string; onOpenPlayer: (id: string) => void }) {
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
  const estimate = data.dividends_paid === false;

  return (
    <div className="space-y-2">
      {myTotal > 0 && (
        <div className="rounded-xl p-3 flex items-center gap-2" style={{ background: 'rgba(251,191,36,0.12)', border: '1px solid rgba(251,191,36,0.5)' }}>
          <Coins className="w-4 h-4" style={{ color: GOLD }} />
          <p style={{ fontSize: 12.5, color: GOLD, fontWeight: 600 }}>
            You earned {money(myTotal)} from this tournament{data.total_pages > 1 ? ' (on this page)' : ''}.
          </p>
        </div>
      )}
      {estimate ? (
        <p className="text-muted-foreground rounded-xl p-3" style={{ fontSize: 11.5, lineHeight: 1.5, background: 'rgba(255,255,255,0.04)' }}>
          No dividends were paid for this event (it was recorded after the fact), so the payouts below are what each
          placement <em>would</em> pay at today&rsquo;s settings.
        </p>
      ) : (
        <p className="text-muted-foreground" style={{ fontSize: 11.5, lineHeight: 1.5 }}>
          Dividends are paid on the shares you held when the tournament started
          {data.record_date ? ` (${new Date(data.record_date).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })})` : ''}
          {' '}— shares bought afterwards don&rsquo;t count, and shares sold afterwards still do. Teams you own a piece of are outlined in gold.
        </p>
      )}

      {data.items.map(team => (
        <TeamCard
          key={`${team.placement}-${team.team_id ?? team.members[0].player_id}`}
          team={team}
          tournamentId={tournamentId}
          estimate={estimate}
          onOpenPlayer={onOpenPlayer}
        />
      ))}
      <Pager page={page} totalPages={data.total_pages} total={data.total} noun="teams" onPage={setPage} />
    </div>
  );
}

// "Game by game" tab: pick a game, see every team ranked by how they placed in THAT game, with their kills.
function GamesTab({ tournamentId, onOpenPlayer }: { tournamentId: string; onOpenPlayer: (id: string) => void }) {
  const [data, setData] = useState<TournamentGamesResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState(1);

  useEffect(() => {
    let cancelled = false;
    api
      .get<TournamentGamesResponse>(`/tournaments/${tournamentId}/games`)
      .then(r => { if (!cancelled) setData(r); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [tournamentId]);

  if (failed) return <p className="text-muted-foreground text-center py-8" style={{ fontSize: 13 }}>Couldn&rsquo;t load game results.</p>;
  if (!data) return <p className="text-muted-foreground text-center py-8" style={{ fontSize: 13 }}>Loading games…</p>;
  if (data.games.length === 0) {
    return <p className="text-muted-foreground text-center py-8" style={{ fontSize: 13 }}>Game-by-game results aren&rsquo;t available for this tournament.</p>;
  }

  const game = data.games.find(g => g.game === selected) ?? data.games[0];
  const COLS = '48px minmax(0,1fr) 64px 72px 72px 72px 56px';

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-muted-foreground uppercase mr-1" style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.08em' }}>Game</span>
        {data.games.map(g => (
          <button
            key={g.game}
            onClick={() => setSelected(g.game)}
            className="rounded-lg font-mono font-bold transition-colors"
            style={{
              fontSize: 12.5,
              minWidth: 34,
              padding: '5px 9px',
              background: g.game === game.game ? 'var(--primary)' : 'var(--muted)',
              color: g.game === game.game ? '#06101a' : 'var(--foreground)',
            }}
          >
            {g.game}
          </button>
        ))}
      </div>
      <p className="text-muted-foreground" style={{ fontSize: 11.5 }}>
        Game {game.game} &middot; {game.teams.length} teams
        {game.ended_at ? ` · ended ${new Date(game.ended_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}` : ''}
      </p>

      <div className="rounded-xl overflow-hidden" style={{ background: 'var(--muted)' }}>
        <div className="grid items-center gap-2 px-3 py-2 text-muted-foreground uppercase" style={{ gridTemplateColumns: COLS, fontSize: 10, letterSpacing: '0.06em', fontWeight: 600 }}>
          <span>Place</span><span>Team</span><span className="text-right">Elims</span><span className="text-right">Alive</span><span className="text-right">Dealt</span><span className="text-right">Taken</span><span className="text-right">Final</span>
        </div>
        {game.teams.map((t, i) => (
          <div
            key={`${t.final_placement}-${t.members[0]?.player_id ?? i}`}
            className="grid items-center gap-2 px-3 py-2"
            style={{ gridTemplateColumns: COLS, borderTop: '1px solid rgba(255,255,255,0.05)' }}
          >
            <span
              className="font-mono font-bold"
              style={{ fontSize: 13, color: t.game_placement === 1 ? GOLD : 'var(--foreground)' }}
            >
              {t.game_placement !== null ? `#${t.game_placement}${t.game_placement === 1 ? ' 🏆' : ''}` : '–'}
            </span>
            <div className="min-w-0 flex flex-wrap items-center gap-x-3 gap-y-0.5">
              {t.members.map(m => (
                <button key={m.player_id} onClick={() => onOpenPlayer(m.player_id)} className="text-foreground font-semibold truncate hover:opacity-80" style={{ fontSize: 13 }}>
                  {m.gamertag}
                  <VerifiedBadge show={m.is_verified} />
                </button>
              ))}
            </div>
            <span className="font-mono font-bold text-foreground text-right" style={{ fontSize: 13 }}>{t.eliminations ?? '–'}</span>
            <span className="font-mono text-foreground text-right" style={{ fontSize: 12.5 }}>{t.time_alive !== null ? mmss(t.time_alive) : '–'}</span>
            <span className="font-mono text-foreground text-right" style={{ fontSize: 12.5 }}>{t.damage_dealt !== null ? t.damage_dealt.toLocaleString() : '–'}</span>
            <span className="font-mono text-foreground text-right" style={{ fontSize: 12.5 }}>{t.damage_received !== null ? t.damage_received.toLocaleString() : '–'}</span>
            <span className="font-mono text-muted-foreground text-right" style={{ fontSize: 12 }}>#{t.final_placement}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Finalized/finalizing tournament results: a "Standings" tab (teams, per-player dividend pool + per-share, your
 * own payout highlighted) and a "Game by game" tab (pick a game, see every team ranked in it). */
export function TeamLeaderboard({
  tournamentId,
  onOpenPlayer,
}: {
  tournamentId: string;
  onOpenPlayer: (id: string) => void;
}) {
  const [tab, setTab] = useState<'standings' | 'games'>('standings');
  return (
    <div className="space-y-3">
      <div className="flex gap-1.5 p-1 rounded-xl w-fit" style={{ background: 'var(--muted)' }}>
        {([['standings', 'Standings & payouts'], ['games', 'Game by game']] as const).map(([id, label]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className="rounded-lg font-semibold transition-colors"
            style={{
              fontSize: 12.5,
              padding: '6px 14px',
              background: tab === id ? 'var(--card)' : 'transparent',
              color: tab === id ? 'var(--foreground)' : 'var(--muted-foreground)',
            }}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === 'standings' ? (
        <StandingsTab tournamentId={tournamentId} onOpenPlayer={onOpenPlayer} />
      ) : (
        <GamesTab tournamentId={tournamentId} onOpenPlayer={onOpenPlayer} />
      )}
    </div>
  );
}
