import { useState } from 'react';
import { ArrowLeft, Star, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { getPlayer, MARKET_NEWS, DIVIDEND_HISTORY, TOURNAMENTS, formatCurrency, formatCompact } from './mockData';
import { PlayerAvatar } from './Dashboard';

interface Props {
  playerId: string;
  navigate: (page: string, playerId?: string) => void;
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl p-3 border border-border" style={{ background: 'var(--popover)' }}>
      <p className="text-muted-foreground" style={{ fontSize: 11 }}>{label}</p>
      <p className="font-mono font-bold text-foreground" style={{ fontSize: 16 }}>{formatCurrency(payload[0].value)}</p>
    </div>
  );
};

export function PlayerProfile({ playerId, navigate }: Props) {
  const player = getPlayer(playerId);
  const [tradeTab, setTradeTab] = useState<'buy' | 'sell'>('buy');
  const [quantity, setQuantity] = useState(1);

  if (!player) {
    return (
      <div className="p-6 flex items-center justify-center">
        <p className="text-muted-foreground">Player not found.</p>
      </div>
    );
  }

  const isUp = player.changePercent >= 0;
  const chartColor = isUp ? '#10d9a0' : '#ff3d5c';
  const total = quantity * player.price;

  const chartData = player.priceHistory90.map((price, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (89 - i));
    return { date: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }), price };
  });

  const playerDividends = DIVIDEND_HISTORY.filter(d => d.playerId === player.id);
  const totalDividendsEarned = playerDividends.reduce((s, d) => s + d.amount, 0);

  const recentTournament = TOURNAMENTS
    .filter(t => t.status === 'completed' && t.top5?.some(r => r.playerId === player.id))
    .slice(0, 3);

  const relevantNews = MARKET_NEWS.filter(n => n.playerId === player.id).slice(0, 2);

  return (
    <div className="p-6 max-w-[900px] mx-auto space-y-5">
      {/* Back */}
      <button
        onClick={() => navigate('markets')}
        className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground transition-colors"
        style={{ fontSize: 14 }}
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Market
      </button>

      {/* Player header */}
      <div
        className="rounded-2xl border border-border p-5"
        style={{ background: `linear-gradient(135deg, ${player.teamColor}12, rgba(0,0,0,0) 60%), var(--card)` }}
      >
        <div className="flex items-start gap-4">
          <PlayerAvatar name={player.name} color={player.teamColor} size={72} />
          <div className="flex-1">
            <div className="flex items-start justify-between">
              <div>
                <h1 className="text-foreground font-bold" style={{ fontSize: 28 }}>{player.name}</h1>
                <div className="flex items-center gap-2 mt-1">
                  <span className="px-2.5 py-0.5 rounded-lg" style={{ fontSize: 12, background: player.teamColor + '22', color: player.teamColor, fontWeight: 500 }}>
                    {player.team}
                  </span>
                  <span className="text-muted-foreground" style={{ fontSize: 13 }}>{player.region} · Age {player.age}</span>
                </div>
              </div>
              <button className="p-2 rounded-xl border border-border hover:bg-white/5 transition-colors">
                <Star className="w-5 h-5 text-muted-foreground" />
              </button>
            </div>

            <div className="flex items-end gap-4 mt-3">
              <div>
                <p className="font-mono font-bold" style={{ fontSize: 36, color: 'var(--foreground)', letterSpacing: '-1px' }}>
                  {formatCurrency(player.price)}
                </p>
                <span
                  className="inline-flex items-center gap-1 font-mono font-bold px-3 py-1 rounded-full mt-1"
                  style={{
                    fontSize: 14,
                    background: isUp ? 'rgba(16,217,160,0.12)' : 'rgba(255,61,92,0.12)',
                    color: isUp ? 'var(--gain)' : 'var(--loss)',
                  }}
                >
                  {isUp ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
                  {isUp ? '+' : ''}{player.change.toFixed(2)} today ({isUp ? '+' : ''}{player.changePercent.toFixed(2)}%)
                </span>
              </div>
            </div>

            {/* Recent form */}
            <div className="flex items-center gap-2 mt-3">
              <span className="text-muted-foreground" style={{ fontSize: 12 }}>Recent results:</span>
              {player.recentForm.map((f, i) => (
                <span
                  key={i}
                  className="w-7 h-7 rounded-lg flex items-center justify-center font-mono font-bold"
                  style={{
                    fontSize: 12,
                    background: f === 'W' ? 'rgba(16,217,160,0.2)' : f === 'L' ? 'rgba(255,61,92,0.2)' : 'rgba(251,191,36,0.2)',
                    color: f === 'W' ? 'var(--gain)' : f === 'L' ? 'var(--loss)' : '#fbbf24',
                  }}
                >
                  {f}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Price chart */}
      <div className="rounded-2xl border border-border p-5" style={{ background: 'var(--card)' }}>
        <p className="text-foreground font-semibold mb-4" style={{ fontSize: 16 }}>Price over last 90 days</p>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={`grad-${player.id}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={chartColor} stopOpacity={0.3} />
                <stop offset="95%" stopColor={chartColor} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="4 4" vertical={false} />
            <XAxis
              dataKey="date"
              tick={{ fill: '#5a6a82', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}
              axisLine={false} tickLine={false} interval={14}
            />
            <YAxis
              tick={{ fill: '#5a6a82', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}
              axisLine={false} tickLine={false}
              tickFormatter={v => `$${v.toFixed(0)}`}
              width={50}
              domain={['auto', 'auto']}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area type="monotone" dataKey="price" stroke={chartColor} fill={`url(#grad-${player.id})`} strokeWidth={2.5} dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Key stats */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          { label: '🏆 Tournament Wins', value: player.tournamentWins.toString() },
          { label: '💰 Win Bonus Rate', value: `${player.dividendYield}%`, color: 'var(--accent)' },
          { label: '📊 Reliability', value: `${player.consistency}/100` },
          { label: '💵 Total Earnings', value: formatCompact(player.totalPR) },
        ].map(stat => (
          <div key={stat.label} className="rounded-2xl border border-border p-4 text-center" style={{ background: 'var(--card)' }}>
            <p className="text-muted-foreground" style={{ fontSize: 12 }}>{stat.label}</p>
            <p className="font-mono font-bold mt-1" style={{ fontSize: 20, color: stat.color || 'var(--foreground)' }}>
              {stat.value}
            </p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-5 md:grid-cols-[1fr_320px]">
        {/* Left: news + results */}
        <div className="space-y-4">
          {relevantNews.length > 0 && (
            <div className="rounded-2xl border border-border p-5" style={{ background: 'var(--card)' }}>
              <p className="text-foreground font-semibold mb-3" style={{ fontSize: 16 }}>📰 Latest News</p>
              <div className="space-y-3">
                {relevantNews.map(n => (
                  <div key={n.id} className="p-3 rounded-xl border border-border" style={{ background: 'var(--muted)' }}>
                    <div className="flex items-start gap-2">
                      <p className="text-foreground font-medium flex-1" style={{ fontSize: 13, lineHeight: 1.4 }}>{n.title}</p>
                      <span
                        className="shrink-0 font-mono font-bold px-2 py-0.5 rounded-lg"
                        style={{
                          fontSize: 12,
                          background: n.impact === 'positive' ? 'rgba(16,217,160,0.12)' : 'rgba(255,61,92,0.12)',
                          color: n.impact === 'positive' ? 'var(--gain)' : 'var(--loss)',
                        }}
                      >
                        {n.priceImpact > 0 ? '+' : ''}{n.priceImpact}%
                      </span>
                    </div>
                    <p className="text-muted-foreground mt-1.5" style={{ fontSize: 12, lineHeight: 1.5 }}>{n.body}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {recentTournament.length > 0 && (
            <div className="rounded-2xl border border-border p-5" style={{ background: 'var(--card)' }}>
              <p className="text-foreground font-semibold mb-3" style={{ fontSize: 16 }}>🏆 Recent Tournaments</p>
              <div className="space-y-2.5">
                {recentTournament.map(t => {
                  const result = t.top5?.find(r => r.playerId === player.id)!;
                  return (
                    <div key={t.id} className="flex items-center gap-3 p-3 rounded-xl border border-border" style={{ background: 'var(--muted)' }}>
                      <div
                        className="w-10 h-10 rounded-xl flex items-center justify-center font-mono font-bold shrink-0"
                        style={{
                          fontSize: 14,
                          background: result.placement === 1 ? 'rgba(251,191,36,0.2)' : result.placement <= 3 ? 'rgba(156,163,175,0.15)' : 'rgba(255,255,255,0.05)',
                          color: result.placement === 1 ? '#fbbf24' : result.placement <= 3 ? '#9ca3af' : 'var(--muted-foreground)',
                        }}
                      >
                        #{result.placement}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-foreground font-medium" style={{ fontSize: 13 }}>{t.name}</p>
                        <p className="text-muted-foreground" style={{ fontSize: 11 }}>
                          {new Date(t.date).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}
                        </p>
                      </div>
                      <div className="text-right shrink-0">
                        <p className="font-mono font-bold" style={{ fontSize: 14, color: 'var(--gain)' }}>
                          {formatCompact(result.earnings)}
                        </p>
                        <p className="text-muted-foreground" style={{ fontSize: 11 }}>{result.points} pts</p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Win bonus history */}
          {playerDividends.length > 0 && (
            <div className="rounded-2xl border border-border p-5" style={{ background: 'var(--card)' }}>
              <div className="flex items-center justify-between mb-3">
                <p className="text-foreground font-semibold" style={{ fontSize: 16 }}>💰 Your Win Bonuses</p>
                <span className="font-mono font-bold" style={{ color: 'var(--accent)', fontSize: 16 }}>
                  +{formatCurrency(totalDividendsEarned)} total
                </span>
              </div>
              <div className="space-y-2">
                {playerDividends.map((d, i) => (
                  <div key={i} className="flex items-center gap-3 p-3 rounded-xl border border-border" style={{ background: 'var(--muted)' }}>
                    <div className="w-9 h-9 rounded-xl flex items-center justify-center font-mono font-bold shrink-0"
                      style={{ fontSize: 12, background: 'rgba(155,111,255,0.15)', color: 'var(--accent)' }}>
                      #{d.placement}
                    </div>
                    <div className="flex-1">
                      <p className="text-foreground" style={{ fontSize: 13 }}>{d.tournament}</p>
                      <p className="text-muted-foreground" style={{ fontSize: 11 }}>{d.shares} shares held</p>
                    </div>
                    <p className="font-mono font-bold" style={{ fontSize: 15, color: 'var(--gain)' }}>
                      +{formatCurrency(d.amount)}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Right: trade panel */}
        <div>
          <div className="rounded-2xl border border-border p-5 sticky top-5" style={{ background: 'var(--card)' }}>
            <p className="text-foreground font-bold mb-4" style={{ fontSize: 18 }}>Trade {player.name}</p>

            {/* Buy / Sell */}
            <div className="flex rounded-xl overflow-hidden border border-border mb-5">
              {(['buy', 'sell'] as const).map(t => (
                <button
                  key={t}
                  onClick={() => setTradeTab(t)}
                  className="flex-1 py-2.5 font-bold capitalize transition-all"
                  style={{
                    fontSize: 15,
                    background: tradeTab === t
                      ? (t === 'buy' ? 'rgba(16,217,160,0.12)' : 'rgba(255,61,92,0.12)')
                      : 'transparent',
                    color: tradeTab === t
                      ? (t === 'buy' ? 'var(--gain)' : 'var(--loss)')
                      : 'var(--muted-foreground)',
                  }}
                >
                  {t === 'buy' ? '↑ Buy' : '↓ Sell'}
                </button>
              ))}
            </div>

            {/* Price */}
            <div className="flex justify-between items-center py-2 mb-1">
              <span className="text-muted-foreground" style={{ fontSize: 14 }}>Share price</span>
              <span className="font-mono font-bold text-foreground" style={{ fontSize: 18 }}>{formatCurrency(player.price)}</span>
            </div>

            {/* Quick picks */}
            <p className="text-muted-foreground mb-2" style={{ fontSize: 12 }}>How many shares?</p>
            <div className="grid grid-cols-4 gap-2 mb-3">
              {[1, 5, 10, 25].map(n => (
                <button
                  key={n}
                  onClick={() => setQuantity(n)}
                  className="py-2.5 rounded-xl font-mono font-bold transition-all"
                  style={{
                    fontSize: 15,
                    background: quantity === n ? 'rgba(0,200,255,0.12)' : 'var(--muted)',
                    color: quantity === n ? 'var(--primary)' : 'var(--foreground)',
                    border: quantity === n ? '1.5px solid rgba(0,200,255,0.35)' : '1.5px solid var(--border)',
                  }}
                >
                  {n}
                </button>
              ))}
            </div>

            {/* Custom qty */}
            <input
              type="number"
              min={1}
              value={quantity}
              onChange={e => setQuantity(Math.max(1, parseInt(e.target.value) || 1))}
              className="w-full px-4 py-3 rounded-xl border border-border font-mono text-foreground text-center outline-none transition-colors focus:border-primary/50 mb-4"
              style={{ background: 'var(--muted)', fontSize: 18, fontWeight: 700 }}
            />

            {/* Total */}
            <div
              className="rounded-xl p-4 mb-4 flex justify-between items-center"
              style={{ background: tradeTab === 'buy' ? 'rgba(16,217,160,0.08)' : 'rgba(255,61,92,0.08)' }}
            >
              <div>
                <p className="text-muted-foreground" style={{ fontSize: 12 }}>
                  {quantity} share{quantity !== 1 ? 's' : ''} × {formatCurrency(player.price)}
                </p>
                <p className="text-muted-foreground" style={{ fontSize: 11 }}>Your cash: {formatCurrency(8432.10)}</p>
              </div>
              <div className="text-right">
                <p className="text-muted-foreground" style={{ fontSize: 11 }}>Total</p>
                <p className="font-mono font-bold" style={{ fontSize: 22, color: tradeTab === 'buy' ? 'var(--gain)' : 'var(--loss)' }}>
                  {formatCurrency(total)}
                </p>
              </div>
            </div>

            {/* CTA */}
            <button
              className="w-full py-4 rounded-xl font-bold transition-opacity hover:opacity-90"
              style={{
                fontSize: 16,
                background: tradeTab === 'buy'
                  ? 'linear-gradient(135deg, #10d9a0, #00c8ff)'
                  : 'linear-gradient(135deg, #ff3d5c, #ff8c42)',
                color: '#fff',
                letterSpacing: '0.3px',
              }}
            >
              {tradeTab === 'buy'
                ? `Buy ${quantity} Share${quantity !== 1 ? 's' : ''} →`
                : `Sell ${quantity} Share${quantity !== 1 ? 's' : ''} →`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
