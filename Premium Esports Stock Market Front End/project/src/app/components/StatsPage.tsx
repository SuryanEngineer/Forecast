import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { useMyStats, useSeasonInfo } from '../lib/hooks';
import { RankBadge, rankColor } from './RankBadge';

const money0 = (v: number) => `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
const signed = (v: number) => `${v >= 0 ? '+' : '-'}$${Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
const pct = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
const tone = (v: number) => (v > 0 ? 'var(--gain)' : v < 0 ? 'var(--loss)' : 'var(--foreground)');

function Tile({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="rounded-2xl border border-border p-4" style={{ background: 'var(--card)' }}>
      <p className="text-muted-foreground" style={{ fontSize: 12 }}>{label}</p>
      <p className="font-mono font-bold mt-1" style={{ fontSize: 20, color: color ?? 'var(--foreground)' }}>{value}</p>
      {sub && <p className="text-muted-foreground mt-0.5" style={{ fontSize: 11 }}>{sub}</p>}
    </div>
  );
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function fmtMinutes(m: number): string {
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function StatsPage() {
  const { data: stats, loading, error } = useMyStats();
  const { data: info } = useSeasonInfo();

  if (!stats) {
    return (
      <div className="p-6 max-w-[1000px] mx-auto">
        <h1 className="text-foreground font-bold" style={{ fontSize: 26 }}>Stats</h1>
        <p className="text-muted-foreground mt-3" style={{ fontSize: 14 }}>{error ? `Couldn't load your stats (${error}).` : loading ? 'Loading your stats…' : 'No stats yet.'}</p>
      </div>
    );
  }

  const s = stats.season;
  const chart = stats.history.map(h => ({ day: h.day.slice(5), value: h.net_worth }));

  return (
    <div className="p-6 max-w-[1000px] mx-auto space-y-6">
      <div>
        <h1 className="text-foreground font-bold" style={{ fontSize: 26 }}>Your Stats</h1>
        <p className="text-muted-foreground mt-0.5" style={{ fontSize: 14 }}>
          Lifetime performance &middot; member since {fmtDate(stats.member_since)}
        </p>
      </div>

      {/* Season / rank */}
      <div className="rounded-2xl border p-5" style={{ background: 'linear-gradient(135deg, rgba(155,111,255,0.08), rgba(0,200,255,0.05)), var(--card)', borderColor: 'rgba(155,111,255,0.25)' }}>
        {s ? (
          <>
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div>
                <p className="text-muted-foreground" style={{ fontSize: 12 }}>{s.season_name}</p>
                <div className="flex items-center gap-3 mt-1">
                  <RankBadge rank={s.rank} size="lg" />
                  <p className="font-mono font-bold text-foreground" style={{ fontSize: 24 }}>{s.season_points.toLocaleString()} SP</p>
                </div>
              </div>
              <div className="text-right">
                <p className="font-mono font-bold" style={{ fontSize: 18, color: tone(s.return_pct) }}>{pct(s.return_pct)} this season</p>
                <p className="text-muted-foreground" style={{ fontSize: 12 }}>Season rank #{s.position} &middot; started at {money0(Number(s.start_value))}</p>
              </div>
            </div>
            <div className="mt-4">
              <div className="h-2 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.07)' }}>
                <div className="h-full rounded-full" style={{ width: `${Math.round(s.progress * 100)}%`, background: rankColor(s.rank) }} />
              </div>
              <p className="text-muted-foreground mt-1.5" style={{ fontSize: 11 }}>
                {s.next_rank ? `${s.points_to_next.toLocaleString()} SP to ${s.next_rank}` : 'Top rank reached'}
                {' '}&middot; +1% return = +{info.points_per_percent} SP &middot; points reset each season
              </p>
            </div>
          </>
        ) : (
          <p className="text-muted-foreground" style={{ fontSize: 13 }}>No season is active right now. Your all-time stats below keep counting.</p>
        )}
      </div>

      {/* Headline numbers */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Tile label="Net worth" value={money0(stats.net_worth)} sub={`${money0(stats.cash)} cash · ${money0(stats.holdings_value)} shares${stats.treasury_value ? ` · ${money0(stats.treasury_value)} treasury` : ''}`} />
        <Tile label="Total change" value={signed(stats.total_change)} sub={pct(stats.total_change_pct) + ' vs. starting capital'} color={tone(stats.total_change)} />
        <Tile label="Trading earnings" value={signed(stats.trading_earnings)} sub="Buying & selling, before fees" color={tone(stats.trading_earnings)} />
        <Tile label="Dividend earnings" value={signed(stats.dividend_earnings)} sub={`${stats.dividend_payouts} payouts`} color={tone(stats.dividend_earnings)} />
      </div>

      {/* Net worth chart */}
      <div className="rounded-2xl border border-border p-5" style={{ background: 'var(--card)' }}>
        <p className="font-semibold text-foreground mb-3" style={{ fontSize: 15 }}>Net worth over time</p>
        {chart.length < 2 ? (
          <p className="text-muted-foreground text-center py-10" style={{ fontSize: 13 }}>Your chart appears after your first full day of play.</p>
        ) : (
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chart} margin={{ top: 6, right: 6, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="statsNw" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#00c8ff" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#00c8ff" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="day" tick={{ fontSize: 10, fill: '#7d8fae' }} axisLine={false} tickLine={false} minTickGap={24} />
                <YAxis domain={['auto', 'auto']} width={58} tick={{ fontSize: 10, fill: '#7d8fae' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => (Math.abs(v) >= 1e6 ? `$${(v / 1e6).toFixed(2)}M` : `$${(v / 1e3).toFixed(0)}K`)} />
                <Tooltip formatter={(v: number) => [money0(v), 'Net worth']} contentStyle={{ background: 'var(--popover)', border: '1px solid var(--border)', borderRadius: 12, fontSize: 12 }} />
                <Area type="monotone" dataKey="value" stroke="#00c8ff" strokeWidth={2} fill="url(#statsNw)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Records & activity */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Tile label="Total trades" value={stats.total_trades.toLocaleString()} sub={`${stats.buy_trades} buys · ${stats.sell_trades} sells`} />
        <Tile label="Trading volume" value={money0(stats.trade_volume)} sub="Total value traded" />
        <Tile label="Fees paid" value={money0(stats.fees_paid)} sub="Transaction fees" />
        <Tile label="Interest earned" value={signed(stats.interest_earnings)} sub="Treasury" color={tone(stats.interest_earnings)} />
        <Tile
          label="Biggest trade"
          value={stats.biggest_trade ? money0(stats.biggest_trade.value) : '—'}
          sub={stats.biggest_trade ? `${stats.biggest_trade.side === 'buy' ? 'Bought' : 'Sold'} ${stats.biggest_trade.quantity} ${stats.biggest_trade.gamertag}` : 'No trades yet'}
        />
        <Tile
          label="Best day"
          value={stats.best_day ? signed(stats.best_day.change) : '—'}
          sub={stats.best_day ? `${pct(stats.best_day.change_pct)} · ${fmtDate(stats.best_day.day)}` : 'Needs 2+ days of history'}
          color={stats.best_day ? 'var(--gain)' : undefined}
        />
        <Tile
          label="Worst day"
          value={stats.worst_day ? signed(stats.worst_day.change) : '—'}
          sub={stats.worst_day ? `${pct(stats.worst_day.change_pct)} · ${fmtDate(stats.worst_day.day)}` : 'No down days yet'}
          color={stats.worst_day ? 'var(--loss)' : undefined}
        />
        <Tile label="Time on site" value={fmtMinutes(stats.minutes_on_site)} sub={`${stats.sessions} sessions`} />
        <Tile
          label="Best holding"
          value={stats.best_holding ? stats.best_holding.gamertag : '—'}
          sub={stats.best_holding ? `${signed(stats.best_holding.unrealized)} (${pct(stats.best_holding.pct)}) unrealized` : 'No holdings'}
          color={stats.best_holding && stats.best_holding.unrealized > 0 ? 'var(--gain)' : undefined}
        />
        <Tile
          label="Worst holding"
          value={stats.worst_holding ? stats.worst_holding.gamertag : '—'}
          sub={stats.worst_holding ? `${signed(stats.worst_holding.unrealized)} (${pct(stats.worst_holding.pct)}) unrealized` : 'No holdings'}
          color={stats.worst_holding && stats.worst_holding.unrealized < 0 ? 'var(--loss)' : undefined}
        />
      </div>

      {/* Season history */}
      <div className="rounded-2xl border border-border p-5" style={{ background: 'var(--card)' }}>
        <p className="font-semibold text-foreground mb-3" style={{ fontSize: 15 }}>Season history</p>
        {stats.season_history.length === 0 ? (
          <p className="text-muted-foreground" style={{ fontSize: 13 }}>Finished seasons will show up here with your final rank.</p>
        ) : (
          <div className="space-y-2">
            {stats.season_history.map(h => (
              <div key={h.season_id} className="flex items-center justify-between px-4 py-3 rounded-xl" style={{ background: 'var(--muted)' }}>
                <div>
                  <p className="font-semibold text-foreground" style={{ fontSize: 13 }}>{h.name}</p>
                  <p className="text-muted-foreground" style={{ fontSize: 11 }}>Finished #{h.final_position ?? '—'}</p>
                </div>
                <div className="flex items-center gap-3">
                  <p className="font-mono text-foreground" style={{ fontSize: 13 }}>{(h.final_points ?? 0).toLocaleString()} SP</p>
                  {h.final_rank && <RankBadge rank={h.final_rank} />}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <p className="text-muted-foreground" style={{ fontSize: 11, lineHeight: 1.6 }}>
        Total change = net worth − starting capital. Trading earnings = total change − dividends − treasury interest + fees paid.
        Best/worst day compare your end-of-day (UTC) net worth to the day before.
      </p>
    </div>
  );
}
