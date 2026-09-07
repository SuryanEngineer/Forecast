import { ArrowUpRight, ArrowDownRight, ChevronRight } from 'lucide-react';
import { useAuth } from '../lib/auth';
import { useMarkets, useMyPositions, usePickLiveTournament, useTournamentsList } from '../lib/hooks';
import { toNumber, type MarketSnapshot } from '../lib/types';
import { colorForId } from '../lib/colors';
import { LiveLeaderboard } from './LiveLeaderboard';

interface Props {
  navigate: (page: string, playerId?: string) => void;
  openPlayer: (id: string) => void;
  goToMarketWithSearch: (term: string) => void;
}

export function PlayerAvatar({ name, color, size = 40 }: { name: string; color: string; size?: number }) {
  return (
    <div
      className="rounded-2xl flex items-center justify-center shrink-0 font-mono font-bold select-none"
      style={{
        width: size, height: size, minWidth: size,
        background: color + '25',
        border: `2px solid ${color}50`,
        color,
        fontSize: Math.floor(size * 0.36),
      }}
    >
      {name.slice(0, 2).toUpperCase()}
    </div>
  );
}

function playerName(m: MarketSnapshot): string {
  return m.real_name || m.gamertag;
}

export function Dashboard({ navigate, openPlayer, goToMarketWithSearch }: Props) {
  const { user, wallet } = useAuth();
  const { data: markets, loading: marketsLoading } = useMarkets();
  const { data: positions } = useMyPositions();
  const { data: tournaments } = useTournamentsList();
  const liveTournament = usePickLiveTournament(tournaments);

  const marketById = new Map(markets.map(m => [m.id, m]));
  const cashBalance = wallet ? toNumber(wallet.cash_balance) : 0;

  const holdings = positions
    .map(p => {
      const market = marketById.get(p.player_id);
      if (!market) return null;
      const price = toNumber(market.last_price);
      const prevClose = toNumber(market.prev_close);
      const value = p.quantity * price;
      const dayChange = p.quantity * (price - prevClose);
      const costBasis = p.quantity * toNumber(p.average_cost);
      const allTimePl = value - costBasis;
      return { position: p, market, value, dayChange, allTimePl };
    })
    .filter((h): h is NonNullable<typeof h> => h !== null)
    .sort((a, b) => b.value - a.value);

  const holdingsValue = holdings.reduce((s, h) => s + h.value, 0);
  const dayChange = holdings.reduce((s, h) => s + h.dayChange, 0);
  const totalPortfolio = cashBalance + holdingsValue;
  const prevPortfolio = totalPortfolio - dayChange;
  const dayChangePct = prevPortfolio > 0 ? (dayChange / prevPortfolio) * 100 : 0;

  const topMovers = [...markets].sort((a, b) => Math.abs(toNumber(b.change_pct)) - Math.abs(toNumber(a.change_pct))).slice(0, 4);
  const upcoming = tournaments
    .filter(t => t.status === 'scheduled')
    .sort((a, b) => new Date(a.start_time || a.created_at).getTime() - new Date(b.start_time || b.created_at).getTime())
    .slice(0, 3);

  return (
    <div className="p-6 space-y-7 max-w-[1100px] mx-auto">

      {/* Hero */}
      <div
        className="rounded-2xl p-6 border border-border"
        style={{ background: 'linear-gradient(135deg, rgba(0,200,255,0.08), rgba(155,111,255,0.06))' }}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-muted-foreground mb-1" style={{ fontSize: 14 }}>
              {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
            </p>
            <p className="text-foreground font-bold" style={{ fontSize: 20, letterSpacing: '-0.3px' }}>
              {user ? `${user.display_name.split(' ')[0]}'s Portfolio Value` : 'Portfolio Value'}
            </p>
            <p className="font-mono font-bold" style={{ fontSize: 46, letterSpacing: '-1.5px', color: 'var(--foreground)', lineHeight: 1.1, marginTop: 4 }}>
              ${totalPortfolio.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </p>
            <div className="flex items-center gap-2 mt-3 flex-wrap">
              <span
                className="flex items-center gap-1 px-3 py-1.5 rounded-full font-mono font-bold"
                style={{ fontSize: 14, background: dayChange >= 0 ? 'rgba(16,217,160,0.15)' : 'rgba(255,61,92,0.15)', color: dayChange >= 0 ? 'var(--gain)' : 'var(--loss)' }}
              >
                {dayChange >= 0 ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
                {dayChange >= 0 ? '+' : ''}${Math.abs(dayChange).toLocaleString('en-US', { maximumFractionDigits: 2 })} today
              </span>
              <span
                className="px-3 py-1.5 rounded-full font-mono font-bold"
                style={{ fontSize: 14, background: dayChange >= 0 ? 'rgba(16,217,160,0.1)' : 'rgba(255,61,92,0.1)', color: dayChange >= 0 ? 'var(--gain)' : 'var(--loss)' }}
              >
                {dayChangePct >= 0 ? '+' : ''}{dayChangePct.toFixed(2)}%
              </span>
            </div>
          </div>
          <div className="hidden md:flex flex-col gap-2 shrink-0">
            <div className="rounded-2xl p-4 text-center border border-border min-w-[130px]" style={{ background: 'rgba(0,0,0,0.3)' }}>
              <p className="text-muted-foreground" style={{ fontSize: 11 }}>Cash to Invest</p>
              <p className="font-mono font-bold mt-1" style={{ fontSize: 22, color: 'var(--foreground)' }}>
                ${cashBalance.toLocaleString('en-US', { maximumFractionDigits: 0 })}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Hot right now */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <p className="text-foreground font-bold" style={{ fontSize: 18 }}>🔥 Hot Right Now</p>
          <button onClick={() => navigate('markets')} className="flex items-center gap-1 text-primary" style={{ fontSize: 13 }}>
            See all players <ChevronRight className="w-4 h-4" />
          </button>
        </div>
        {marketsLoading && topMovers.length === 0 ? (
          <p className="text-muted-foreground" style={{ fontSize: 13 }}>Loading markets…</p>
        ) : topMovers.length === 0 ? (
          <p className="text-muted-foreground" style={{ fontSize: 13 }}>No players are trading yet.</p>
        ) : (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {topMovers.map(m => {
              const changePct = toNumber(m.change_pct);
              const isUp = changePct >= 0;
              const color = colorForId(m.id);
              return (
                <button
                  key={m.id}
                  onClick={() => openPlayer(m.id)}
                  className="rounded-2xl border border-border p-4 text-left transition-all hover:-translate-y-0.5"
                  style={{ background: 'var(--card)', borderColor: isUp ? `${color}30` : 'var(--border)' }}
                >
                  <div className="flex items-start justify-between mb-3">
                    <PlayerAvatar name={playerName(m)} color={color} size={44} />
                    <span
                      className="flex items-center gap-0.5 px-2 py-0.5 rounded-full font-mono font-bold"
                      style={{ fontSize: 12, background: isUp ? 'rgba(16,217,160,0.15)' : 'rgba(255,61,92,0.15)', color: isUp ? 'var(--gain)' : 'var(--loss)', display: 'inline-flex' }}
                    >
                      {isUp ? '↑' : '↓'} {Math.abs(changePct).toFixed(1)}%
                    </span>
                  </div>
                  <p className="text-foreground font-bold" style={{ fontSize: 16 }}>{playerName(m)}</p>
                  <p className="text-muted-foreground mb-2" style={{ fontSize: 12 }}>{m.team ?? ' '}</p>
                  <p className="font-mono font-bold" style={{ fontSize: 20, color: 'var(--foreground)' }}>${toNumber(m.last_price).toFixed(2)}</p>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Your team + upcoming */}
      <div className="grid grid-cols-1 gap-5 md:grid-cols-[1fr_340px]">

        <div>
          <div className="flex items-center justify-between mb-3">
            <p className="text-foreground font-bold" style={{ fontSize: 18 }}>💼 Your Team</p>
            <button onClick={() => navigate('portfolio')} className="flex items-center gap-1 text-primary" style={{ fontSize: 13 }}>
              Full portfolio <ChevronRight className="w-4 h-4" />
            </button>
          </div>
          <div className="rounded-2xl border border-border overflow-hidden" style={{ background: 'var(--card)' }}>
            {holdings.length === 0 && (
              <p className="text-muted-foreground px-4 py-6 text-center" style={{ fontSize: 13 }}>
                You don't own any players yet.
              </p>
            )}
            {holdings.slice(0, 3).map((h, i) => (
              <button
                key={h.position.player_id}
                onClick={() => openPlayer(h.position.player_id)}
                className="w-full flex items-center gap-4 px-4 py-3.5 text-left transition-colors hover:bg-white/[0.03]"
                style={{ borderBottom: i < Math.min(holdings.length, 3) - 1 ? '1px solid var(--border)' : 'none' }}
              >
                <PlayerAvatar name={playerName(h.market)} color={colorForId(h.market.id)} size={40} />
                <div className="flex-1 min-w-0">
                  <p className="text-foreground font-semibold" style={{ fontSize: 15 }}>{playerName(h.market)}</p>
                  <p className="text-muted-foreground" style={{ fontSize: 12 }}>{h.position.quantity} shares{h.market.team ? ` · ${h.market.team}` : ''}</p>
                </div>
                <div className="text-right shrink-0">
                  <p className="font-mono font-bold text-foreground" style={{ fontSize: 15 }}>
                    ${h.value.toLocaleString('en-US', { maximumFractionDigits: 0 })}
                  </p>
                  <p className="font-mono" style={{ fontSize: 12, color: h.allTimePl >= 0 ? 'var(--gain)' : 'var(--loss)' }}>
                    {h.allTimePl >= 0 ? '+' : ''}${h.allTimePl.toLocaleString('en-US', { maximumFractionDigits: 0 })}
                  </p>
                </div>
              </button>
            ))}
            <button
              onClick={() => goToMarketWithSearch('')}
              className="w-full flex items-center justify-center gap-2 py-3.5 transition-colors hover:bg-white/[0.03]"
              style={{ fontSize: 14, fontWeight: 600, color: 'var(--primary)', borderTop: `1px solid var(--border)` }}
            >
              + Buy More Players <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="space-y-5">
          {liveTournament && (
            <div className="rounded-2xl border border-border p-4" style={{ background: 'var(--card)' }}>
              <LiveLeaderboard tournamentId={liveTournament.id} compact />
            </div>
          )}

          <div className="flex items-center justify-between mb-3">
            <p className="text-foreground font-bold" style={{ fontSize: 18 }}>⚡ Coming Up</p>
            <button onClick={() => navigate('tournaments')} className="flex items-center gap-1 text-primary" style={{ fontSize: 13 }}>
              All events <ChevronRight className="w-4 h-4" />
            </button>
          </div>
          <div className="space-y-2.5">
            {upcoming.length === 0 && (
              <p className="text-muted-foreground" style={{ fontSize: 13 }}>No upcoming tournaments scheduled.</p>
            )}
            {upcoming.map(t => {
              const startTime = t.start_time ? new Date(t.start_time) : null;
              const daysUntil = startTime ? Math.ceil((startTime.getTime() - Date.now()) / 86400000) : null;
              const prizePool = toNumber(t.prize_pool);
              const isBig = prizePool >= 1_000_000;
              return (
                <button
                  key={t.id}
                  onClick={() => navigate('tournaments')}
                  className="w-full rounded-2xl border border-border p-4 text-left transition-all hover:-translate-y-0.5"
                  style={{
                    background: isBig ? 'linear-gradient(135deg, rgba(0,200,255,0.06), rgba(155,111,255,0.04))' : 'var(--card)',
                    borderColor: isBig ? 'rgba(0,200,255,0.2)' : 'var(--border)',
                  }}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <p className="text-foreground font-semibold" style={{ fontSize: 13, lineHeight: 1.4 }}>{t.name}</p>
                      <p className="text-muted-foreground mt-0.5" style={{ fontSize: 11 }}>
                        {t.tournament_type.replace('_', ' ')}{prizePool > 0 ? ` · $${prizePool.toLocaleString()} prize` : ''}
                      </p>
                    </div>
                    {daysUntil !== null && (
                      <div
                        className="shrink-0 px-2.5 py-1 rounded-xl font-mono font-bold"
                        style={{ fontSize: 13, background: daysUntil <= 7 ? 'rgba(251,191,36,0.15)' : 'rgba(0,200,255,0.1)', color: daysUntil <= 7 ? '#fbbf24' : 'var(--primary)' }}
                      >
                        {daysUntil}d
                      </div>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="rounded-2xl border p-5" style={{ background: 'rgba(155,111,255,0.06)', borderColor: 'rgba(155,111,255,0.2)' }}>
        <p className="font-bold text-foreground mb-2" style={{ fontSize: 16 }}>💰 How Dividends Work</p>
        <p className="text-muted-foreground" style={{ fontSize: 14, lineHeight: 1.7 }}>
          When a player you own places well in a tournament, you earn a <span style={{ color: 'var(--accent)' }}>dividend</span> split
          across every shareholder. Buy shares before big events to maximize your earnings!
        </p>
      </div>
    </div>
  );
}
