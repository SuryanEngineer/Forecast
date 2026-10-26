import { useState } from 'react';
import { useAuth } from '../lib/auth';
import { useLeaderboard, useSeasonalLeaderboard } from '../lib/hooks';
import { toNumber, type LeaderboardEntry, type SeasonEntryRow } from '../lib/types';
import { RankBadge } from './RankBadge';
import { UserTag } from './UserTag';
import { colorForId } from '../lib/colors';
import { HelpButton } from './HelpModal';

interface Props {
  openPlayer: (id: string) => void;
  openTeam: (userId: string) => void;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function LeaderRow({ entry, isMe, onOpen }: { entry: LeaderboardEntry; isMe: boolean; onOpen: () => void }) {
  const color = colorForId(entry.user_id);
  return (
    <button
      onClick={onOpen}
      className="flex items-center gap-3 px-4 py-3.5 rounded-2xl w-full text-left transition-colors hover:bg-white/[0.03]"
      style={{
        background: isMe ? 'rgba(0,200,255,0.08)' : 'var(--muted)',
        border: isMe ? '1.5px solid rgba(0,200,255,0.25)' : '1.5px solid var(--border)',
      }}
    >
      <div className="w-8 text-center shrink-0">
        {entry.rank <= 3 ? (
          <span style={{ fontSize: 20 }}>{entry.rank === 1 ? '🥇' : entry.rank === 2 ? '🥈' : '🥉'}</span>
        ) : (
          <span className="font-mono font-bold text-muted-foreground" style={{ fontSize: 13 }}>#{entry.rank}</span>
        )}
      </div>
      <div
        className="w-9 h-9 rounded-full flex items-center justify-center font-mono font-bold shrink-0"
        style={{ fontSize: 11, background: color + '22', border: `2px solid ${color}55`, color }}
      >
        {initials(entry.display_name)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <p className="font-semibold" style={{ fontSize: 13, color: isMe ? 'var(--primary)' : 'var(--foreground)' }}>
            <UserTag tag={entry.tag} color={entry.tag_color} />{entry.display_name}
          </p>
          {isMe && (
            <span className="px-1.5 py-0.5 rounded-full font-bold" style={{ fontSize: 9, background: 'rgba(0,200,255,0.15)', color: 'var(--primary)' }}>YOU</span>
          )}
        </div>
        <p className="text-muted-foreground truncate" style={{ fontSize: 11 }}>
          ${toNumber(entry.holdings_value).toLocaleString('en-US', { maximumFractionDigits: 0 })} in holdings
        </p>
      </div>
      <div className="text-right shrink-0">
        <p className="font-mono font-bold text-foreground" style={{ fontSize: 13 }}>
          ${toNumber(entry.portfolio_value).toLocaleString('en-US', { maximumFractionDigits: 0 })}
        </p>
      </div>
    </button>
  );
}

function AllTimeBoard({ openTeam }: { openTeam: (userId: string) => void }) {
  const { user } = useAuth();
  const { data: entries, loading, error } = useLeaderboard();

  const myEntry = entries.find(e => e.user_id === user?.id);
  const podium = entries.slice(0, 3);
  const podiumColors = ['#fbbf24', '#9ca3af', '#cd7f32'];
  const podiumEmojis = ['🥇', '🥈', '🥉'];

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-2xl border p-4" style={{ borderColor: 'rgba(255,61,92,0.3)', background: 'rgba(255,61,92,0.06)' }}>
          <p style={{ fontSize: 13, color: 'var(--loss)' }}>Couldn't load the leaderboard ({error}).</p>
        </div>
      )}

      {myEntry && (
        <button
          onClick={() => openTeam(myEntry.user_id)}
          className="w-full rounded-2xl border p-5 flex items-center gap-5 text-left transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, rgba(0,200,255,0.08), rgba(155,111,255,0.06)), var(--card)', borderColor: 'rgba(0,200,255,0.2)' }}
        >
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center font-mono font-bold shrink-0"
            style={{ fontSize: 16, background: 'linear-gradient(135deg, var(--accent), var(--primary))', color: '#fff' }}
          >
            {initials(myEntry.display_name)}
          </div>
          <div className="flex-1">
            <p className="text-muted-foreground" style={{ fontSize: 13 }}>Your ranking</p>
            <p className="font-bold" style={{ fontSize: 22, color: 'var(--foreground)' }}>
              You're <span style={{ color: 'var(--primary)' }}>#{myEntry.rank}</span> out of {entries.length} investors!
            </p>
          </div>
          <div className="text-right shrink-0">
            <p className="font-mono font-bold" style={{ fontSize: 22, color: 'var(--foreground)' }}>
              ${toNumber(myEntry.portfolio_value).toLocaleString('en-US', { maximumFractionDigits: 0 })}
            </p>
          </div>
        </button>
      )}

      {podium.length === 3 && (
        <div className="grid grid-cols-3 gap-3">
          {podium.map((e, idx) => {
            const color = colorForId(e.user_id);
            return (
              <button
                key={e.user_id}
                onClick={() => openTeam(e.user_id)}
                className="rounded-2xl border border-border p-4 flex flex-col items-center gap-2 text-center transition-opacity hover:opacity-90"
                style={{ background: idx === 0 ? 'rgba(251,191,36,0.06)' : 'var(--card)', borderColor: idx === 0 ? 'rgba(251,191,36,0.3)' : 'var(--border)' }}
              >
                <span style={{ fontSize: 28 }}>{podiumEmojis[idx]}</span>
                <div
                  className="w-12 h-12 rounded-full flex items-center justify-center font-mono font-bold"
                  style={{ fontSize: 14, background: color + '25', border: `2px solid ${podiumColors[idx]}66`, color }}
                >
                  {initials(e.display_name)}
                </div>
                <p className="text-foreground font-semibold" style={{ fontSize: 14 }}><UserTag tag={e.tag} color={e.tag_color} />{e.display_name}</p>
                <p className="font-mono text-foreground" style={{ fontSize: 13 }}>
                  ${toNumber(e.portfolio_value).toLocaleString('en-US', { maximumFractionDigits: 0 })}
                </p>
              </button>
            );
          })}
        </div>
      )}

      <div className="rounded-2xl border border-border overflow-hidden p-4" style={{ background: 'var(--card)' }}>
        {loading && entries.length === 0 ? (
          <p className="text-muted-foreground text-center py-6" style={{ fontSize: 14 }}>Loading rankings…</p>
        ) : entries.length === 0 ? (
          <p className="text-muted-foreground text-center py-6" style={{ fontSize: 14 }}>No investors yet.</p>
        ) : (
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {entries.map(e => (
              <LeaderRow key={e.user_id} entry={e} isMe={e.user_id === user?.id} onOpen={() => openTeam(e.user_id)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SeasonRow({ row, isMe, onOpen }: { row: SeasonEntryRow; isMe: boolean; onOpen: () => void }) {
  const ret = row.return_pct;
  return (
    <button
      onClick={onOpen}
      className="flex items-center gap-3 px-4 py-3 rounded-2xl w-full text-left transition-colors hover:bg-white/[0.03]"
      style={{
        background: isMe ? 'rgba(0,200,255,0.08)' : 'var(--muted)',
        border: isMe ? '1.5px solid rgba(0,200,255,0.25)' : '1.5px solid var(--border)',
      }}
    >
      <div className="w-8 text-center shrink-0">
        {row.position <= 3 ? (
          <span style={{ fontSize: 20 }}>{row.position === 1 ? '🥇' : row.position === 2 ? '🥈' : '🥉'}</span>
        ) : (
          <span className="font-mono font-bold text-muted-foreground" style={{ fontSize: 13 }}>#{row.position}</span>
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <p className="font-semibold truncate" style={{ fontSize: 13, color: isMe ? 'var(--primary)' : 'var(--foreground)' }}>
            <UserTag tag={row.tag} color={row.tag_color} />{row.display_name}
          </p>
          {isMe && <span className="px-1.5 py-0.5 rounded-full font-bold" style={{ fontSize: 9, background: 'rgba(0,200,255,0.15)', color: 'var(--primary)' }}>YOU</span>}
        </div>
        <div className="mt-1"><RankBadge rank={row.rank_tier} size="sm" /></div>
      </div>
      <div className="text-right shrink-0">
        <p className="font-mono font-bold" style={{ fontSize: 14, color: 'var(--foreground)' }}>{row.season_points.toLocaleString()} <span className="text-muted-foreground" style={{ fontSize: 10 }}>SP</span></p>
        <p className="font-mono" style={{ fontSize: 11, color: ret >= 0 ? 'var(--gain)' : 'var(--loss)' }}>{ret >= 0 ? '+' : ''}{ret.toFixed(2)}%</p>
      </div>
    </button>
  );
}

function daysLeft(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return 'ending now';
  const d = Math.floor(ms / 86_400_000);
  if (d >= 1) return `${d} day${d === 1 ? '' : 's'} left`;
  return `${Math.max(1, Math.floor(ms / 3_600_000))}h left`;
}

function SeasonalBoard({ openTeam }: { openTeam: (userId: string) => void }) {
  const { user } = useAuth();
  const { data, loading, error } = useSeasonalLeaderboard();
  const season = data.season;

  if (!season && !loading) {
    return (
      <div className="rounded-2xl border border-border p-8 text-center" style={{ background: 'var(--card)' }}>
        <p className="font-semibold text-foreground" style={{ fontSize: 15 }}>No active season right now</p>
        <p className="text-muted-foreground mt-1" style={{ fontSize: 13 }}>The next ranked season will start soon. Check the All-Time board in the meantime.</p>
      </div>
    );
  }

  const mine = data.entries.find(e => e.user_id === user?.id) ?? data.me;
  return (
    <div className="space-y-5">
      {error && <p style={{ fontSize: 13, color: 'var(--loss)' }}>Couldn't load the seasonal ladder ({error}).</p>}
      {season && (
        <div className="rounded-2xl border p-5" style={{ background: 'linear-gradient(135deg, rgba(155,111,255,0.08), rgba(0,200,255,0.05)), var(--card)', borderColor: 'rgba(155,111,255,0.25)' }}>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <p className="text-muted-foreground" style={{ fontSize: 12 }}>Current season</p>
              <p className="font-bold text-foreground" style={{ fontSize: 20 }}>{season.name}</p>
              <p className="text-muted-foreground mt-0.5" style={{ fontSize: 12 }}>
                {season.finalized ? 'Season complete' : daysLeft(season.ends_at)} &middot; points reset every season &middot; +1% return = +50 SP
              </p>
            </div>
            {mine && (
              <div className="text-right">
                <RankBadge rank={mine.rank_tier} size="lg" />
                <p className="font-mono font-bold text-foreground mt-1.5" style={{ fontSize: 18 }}>{mine.season_points.toLocaleString()} SP</p>
                <p className="text-muted-foreground" style={{ fontSize: 11 }}>#{mine.position} of {data.total ?? data.entries.length}</p>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="rounded-2xl border border-border p-4" style={{ background: 'var(--card)' }}>
        {loading && data.entries.length === 0 ? (
          <p className="text-muted-foreground text-center py-6" style={{ fontSize: 14 }}>Loading ladder…</p>
        ) : (
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {data.entries.map(e => <SeasonRow key={e.user_id} row={e} isMe={e.user_id === user?.id} onOpen={() => openTeam(e.user_id)} />)}
            {data.me && data.me.position > data.entries.length && (
              <>
                <p className="text-muted-foreground text-center md:col-span-2" style={{ fontSize: 12 }}>…</p>
                <SeasonRow row={data.me} isMe onOpen={() => openTeam(data.me!.user_id)} />
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function Leaderboards({ openTeam }: Props) {
  const [tab, setTab] = useState<'seasonal' | 'alltime'>('seasonal');
  return (
    <div className="p-6 max-w-[900px] mx-auto space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-1.5">
            <h1 className="text-foreground font-bold" style={{ fontSize: 26 }}>Rankings</h1>
            <HelpButton topic="rankings" size={17} />
          </div>
          <p className="text-muted-foreground mt-0.5" style={{ fontSize: 14 }}>
            {tab === 'seasonal' ? 'Seasonal ladder · resets every Fortnite season' : 'All-time net worth · never resets'} &middot; tap anyone to view their team
          </p>
        </div>
        <div className="flex rounded-xl overflow-hidden border border-border">
          {([['seasonal', 'Seasonal'], ['alltime', 'All-Time']] as const).map(([id, label]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className="px-4 py-2 font-semibold transition-all"
              style={{
                fontSize: 13,
                background: tab === id ? 'rgba(0,200,255,0.1)' : 'transparent',
                color: tab === id ? 'var(--primary)' : 'var(--muted-foreground)',
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {tab === 'seasonal' ? <SeasonalBoard openTeam={openTeam} /> : <AllTimeBoard openTeam={openTeam} />}
    </div>
  );
}
