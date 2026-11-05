import { useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, ChevronRight } from 'lucide-react';
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useAuth } from '../lib/auth';
import { useMarketsByIds, useMyPositions, useMyStats } from '../lib/hooks';
import { toNumber, type MarketSnapshot } from '../lib/types';
import { colorForId } from '../lib/colors';
import { useCompact } from '../lib/useCompact';
import { PlayerAvatar } from './Dashboard';
import { HelpButton, VerifiedBadge } from './HelpModal';
import { ActivityHistory } from './ActivityHistory';
import { OpenOrders } from './OpenOrders';
import { usd, usdSigned } from '../lib/format';

interface Props {
  navigate: (page: string, playerId?: string) => void;
  openPlayer: (id: string) => void;
}

function playerName(m: MarketSnapshot): string {
  return m.real_name || m.gamertag;
}

const tone = (v: number) => (v > 0.005 ? 'var(--gain)' : v < -0.005 ? 'var(--loss)' : 'var(--muted-foreground)');
const toneBg = (v: number) => (v > 0.005 ? 'rgba(16,217,160,0.12)' : v < -0.005 ? 'rgba(255,61,92,0.12)' : 'rgba(255,255,255,0.06)');
const pctText = (v: number) => `${v > 0.005 ? '+' : v < -0.005 ? '-' : ''}${Math.abs(v).toFixed(2)}%`;

type SortKey = 'value' | 'pl' | 'plPct' | 'day' | 'name';
const SORTS: { key: SortKey; label: string }[] = [
  { key: 'value', label: 'Value' },
  { key: 'pl', label: 'Gain / loss $' },
  { key: 'plPct', label: 'Gain / loss %' },
  { key: 'day', label: 'Today' },
  { key: 'name', label: 'Name' },
];

type Range = '7D' | '30D' | 'ALL';

function Kpi({ label, value, sub, color, hint }: { label: string; value: string; sub?: string; color?: string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-border p-4" style={{ background: 'var(--card)' }} title={hint}>
      <p className="text-muted-foreground" style={{ fontSize: 12 }}>{label}</p>
      <p className="font-mono font-bold mt-1 truncate" style={{ fontSize: 'clamp(16px, 4.5vw, 20px)', color: color ?? 'var(--foreground)' }}>{value}</p>
      {sub && <p className="text-muted-foreground mt-0.5 truncate" style={{ fontSize: 11 }}>{sub}</p>}
    </div>
  );
}

export function Portfolio({ navigate, openPlayer }: Props) {
  const { wallet } = useAuth();
  const compact = useCompact();
  const { data: positions, loading: positionsLoading } = useMyPositions();
  const { data: stats } = useMyStats();
  const [sort, setSort] = useState<SortKey>('value');
  const [range, setRange] = useState<Range>('30D');
  const [focusId, setFocusId] = useState<string | null>(null);

  // Looks up each held player by id, not from a ranked page of the market -- see useMarketsByIds' docstring in
  // lib/hooks.ts for why.
  const holdingIds = useMemo(() => positions.map(p => p.player_id), [positions]);
  const { data: marketById, loading: marketsLoading } = useMarketsByIds(holdingIds);

  const cash = wallet ? toNumber(wallet.cash_balance) : 0;
  const lockedCash = wallet ? toNumber(wallet.held_balance) : 0; // cash tied up in open buy orders

  const holdings = useMemo(() => {
    const rows = positions
      .map(p => {
        const market = marketById.get(p.player_id);
        if (!market) return null;
        const price = toNumber(market.last_price);
        // A position is worth what selling ALL of it right now would pay (the server computes it: real bids first, then
        // the House's size-dependent price), so a very large position is worth slightly less per share. Falls back to
        // shares x listed price only if the server didn't send it.
        const value = p.value !== undefined ? toNumber(p.value) : p.quantity * price;
        const cost = p.quantity * toNumber(p.average_cost);
        const pl = value - cost;
        const plPct = cost > 0 ? (pl / cost) * 100 : 0;
        const dayDollar = p.quantity * toNumber(market.change);
        const dayPct = toNumber(market.change_pct);
        return {
          playerId: p.player_id, market, shares: p.quantity, locked: p.held_quantity ?? 0,
          price, avgCost: toNumber(p.average_cost), value, cost, pl, plPct, dayDollar, dayPct,
          color: colorForId(p.player_id),
        };
      })
      .filter((h): h is NonNullable<typeof h> => h !== null);
    const by: Record<SortKey, (a: (typeof rows)[number], b: (typeof rows)[number]) => number> = {
      value: (a, b) => b.value - a.value,
      pl: (a, b) => b.pl - a.pl,
      plPct: (a, b) => b.plPct - a.plPct,
      day: (a, b) => b.dayDollar - a.dayDollar,
      name: (a, b) => playerName(a.market).localeCompare(playerName(b.market)),
    };
    return rows.sort(by[sort]);
  }, [positions, marketById, sort]);

  const invested = holdings.reduce((s, h) => s + h.value, 0);
  const cost = holdings.reduce((s, h) => s + h.cost, 0);
  const pl = invested - cost;
  const plPct = cost > 0 ? (pl / cost) * 100 : 0;
  const dayDollar = holdings.reduce((s, h) => s + h.dayDollar, 0);
  const dayBase = invested - dayDollar;
  const dayPct = dayBase > 0 ? (dayDollar / dayBase) * 100 : 0;
  const total = invested + cash;
  const loading = marketsLoading || positionsLoading;

  // Net worth history (one point per day) from the stats endpoint, trimmed to the chosen range, ending on today's live value.
  const chart = useMemo(() => {
    const hist = (stats?.history ?? []).map(h => ({ day: h.day, label: h.day.slice(5), value: h.net_worth }));
    const keep = range === '7D' ? 7 : range === '30D' ? 30 : hist.length;
    return hist.slice(-keep);
  }, [stats, range]);
  const chartDelta = chart.length >= 2 ? chart[chart.length - 1].value - chart[0].value : 0;
  const chartColor = chartDelta >= 0 ? '#10d9a0' : '#ff3d5c';

  const slices = [
    ...holdings.map(h => ({ id: h.playerId, label: playerName(h.market), value: h.value, color: h.color })),
    ...(cash > 0 ? [{ id: 'cash', label: 'Cash', value: cash, color: 'rgba(148,163,184,0.55)' }] : []),
  ].sort((a, b) => b.value - a.value);

  return (
    <div className="p-6 page-pad max-w-[1000px] mx-auto space-y-5">
      <div>
        <div className="flex items-center gap-1.5">
          <h1 className="text-foreground font-bold" style={{ fontSize: 26 }}>My Portfolio</h1>
          <HelpButton topic="portfolio" size={17} />
        </div>
        <p className="text-muted-foreground mt-0.5" style={{ fontSize: 14 }}>What you own, what it is worth, and how it is doing.</p>
      </div>

      {/* Hero: value, today, and the net worth curve */}
      <div className="rounded-2xl border border-border overflow-hidden" style={{ background: 'linear-gradient(135deg, rgba(0,200,255,0.06), rgba(155,111,255,0.04)), var(--card)' }}>
        <div className="p-5 sm:p-6 pb-3">
          <p className="text-muted-foreground" style={{ fontSize: 13 }}>Total value</p>
          <p className="font-mono font-bold" style={{ fontSize: 'clamp(28px, 9vw, 42px)', letterSpacing: '-1px', lineHeight: 1.1 }}>{usd(total)}</p>
          <div className="flex items-center gap-2 mt-2.5 flex-wrap">
            {holdings.length > 0 && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full font-mono font-bold" style={{ fontSize: 13, background: toneBg(dayDollar), color: tone(dayDollar) }}>
                {dayDollar >= 0 ? <ArrowUp className="w-3.5 h-3.5" /> : <ArrowDown className="w-3.5 h-3.5" />}
                {usdSigned(dayDollar)} ({pctText(dayPct)}) today
              </span>
            )}
            {cost > 0 && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full font-mono font-bold" style={{ fontSize: 13, background: toneBg(pl), color: tone(pl) }}>
                {usdSigned(pl)} ({pctText(plPct)}) all time
              </span>
            )}
          </div>
        </div>

        <div className="px-3 sm:px-4 pb-4">
          <div className="flex items-center justify-between px-2 mb-1">
            <p className="text-muted-foreground" style={{ fontSize: 11, letterSpacing: '0.04em' }}>NET WORTH</p>
            <div className="flex gap-1">
              {(['7D', '30D', 'ALL'] as Range[]).map(r => (
                <button
                  key={r}
                  onClick={() => setRange(r)}
                  className="px-2.5 py-1 rounded-lg font-semibold transition-colors"
                  style={{ fontSize: 11.5, background: range === r ? 'rgba(0,200,255,0.15)' : 'transparent', color: range === r ? 'var(--primary)' : 'var(--muted-foreground)' }}
                >
                  {r === 'ALL' ? 'All' : r}
                </button>
              ))}
            </div>
          </div>
          {chart.length < 2 ? (
            <p className="text-muted-foreground text-center py-8" style={{ fontSize: 13 }}>Your value chart appears after your first full day of play.</p>
          ) : (
            <div style={{ height: compact ? 130 : 170 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chart} margin={{ top: 4, right: 6, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="pfNw" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={chartColor} stopOpacity={0.3} />
                      <stop offset="100%" stopColor={chartColor} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#7d8fae' }} axisLine={false} tickLine={false} minTickGap={28} />
                  <YAxis hide domain={['auto', 'auto']} />
                  <Tooltip
                    formatter={(v: number) => [usd(v), 'Net worth']}
                    labelFormatter={(l: string) => l}
                    contentStyle={{ background: 'var(--popover)', border: '1px solid var(--border)', borderRadius: 12, fontSize: 12 }}
                  />
                  <Area type="monotone" dataKey="value" stroke={chartColor} strokeWidth={2} fill="url(#pfNw)" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>

      {/* Key numbers */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Invested" value={usd(invested)} sub={`${holdings.length} player${holdings.length === 1 ? '' : 's'}`} hint="What selling every share you hold would pay right now" />
        <Kpi label="Cash" value={usd(cash)} sub={lockedCash > 0 ? `${usd(lockedCash)} tied up in orders` : 'Ready to invest'} color="var(--primary)" />
        <Kpi label="Gain / loss" value={cost > 0 ? usdSigned(pl) : '—'} sub={cost > 0 ? `${pctText(plPct)} on ${usd(cost)} cost` : 'No positions yet'} color={tone(pl)} />
        <Kpi label="Dividends earned" value={stats ? usd(stats.dividend_earnings) : '—'} sub={stats ? `${stats.dividend_payouts} payout${stats.dividend_payouts === 1 ? '' : 's'}` : undefined} color="var(--gain)" />
      </div>

      {loading && holdings.length === 0 ? (
        <p className="text-muted-foreground text-center py-10" style={{ fontSize: 14 }}>Loading your portfolio…</p>
      ) : holdings.length === 0 ? (
        <div className="rounded-2xl border border-border p-10 text-center" style={{ background: 'var(--card)' }}>
          <p className="text-foreground font-semibold" style={{ fontSize: 16 }}>You don't own any players yet</p>
          <p className="text-muted-foreground mt-1" style={{ fontSize: 13 }}>Buy shares before a tournament starts to earn its dividend.</p>
          <button
            onClick={() => navigate('markets')}
            className="mt-4 px-5 py-2.5 rounded-xl font-bold"
            style={{ fontSize: 14, background: 'linear-gradient(135deg, var(--primary), var(--accent))', color: '#fff' }}
          >
            Browse the Market
          </button>
        </div>
      ) : (
        <>
          {/* Allocation: every holding plus cash */}
          <div className="rounded-2xl border border-border p-4 sm:p-5" style={{ background: 'var(--card)' }}>
            <p className="text-foreground font-semibold mb-3" style={{ fontSize: 15 }}>Allocation</p>
            <div className="flex rounded-lg overflow-hidden h-3" style={{ gap: 2, background: 'var(--muted)' }}>
              {slices.map(s => (
                <button
                  key={s.id}
                  title={`${s.label}: ${usd(s.value)} (${total > 0 ? ((s.value / total) * 100).toFixed(1) : '0'}%)`}
                  onClick={() => s.id !== 'cash' && setFocusId(focusId === s.id ? null : s.id)}
                  style={{ width: `${total > 0 ? (s.value / total) * 100 : 0}%`, minWidth: 3, background: s.color, opacity: focusId && focusId !== s.id ? 0.35 : 1, cursor: s.id === 'cash' ? 'default' : 'pointer' }}
                  aria-label={s.label}
                />
              ))}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-3">
              {slices.slice(0, 8).map(s => (
                <span key={s.id} className="inline-flex items-center gap-1.5 text-muted-foreground" style={{ fontSize: 12 }}>
                  <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: s.color }} />
                  {s.label}
                  <span className="font-mono text-foreground">{total > 0 ? ((s.value / total) * 100).toFixed(1) : '0.0'}%</span>
                </span>
              ))}
              {slices.length > 8 && <span className="text-muted-foreground" style={{ fontSize: 12 }}>+{slices.length - 8} more</span>}
            </div>
          </div>

          {/* Holdings */}
          <div className="rounded-2xl border border-border overflow-hidden" style={{ background: 'var(--card)' }}>
            <div className="px-4 sm:px-5 py-3.5 border-b border-border flex items-center justify-between gap-3 flex-wrap">
              <p className="text-foreground font-semibold" style={{ fontSize: 15 }}>Holdings</p>
              <div className="flex items-center gap-2">
                <label className="text-muted-foreground" style={{ fontSize: 12 }} htmlFor="pf-sort">Sort by</label>
                <select
                  id="pf-sort"
                  value={sort}
                  onChange={e => setSort(e.target.value as SortKey)}
                  className="rounded-lg border border-border text-foreground px-2.5 py-1.5 outline-none"
                  style={{ background: 'var(--muted)', fontSize: 12.5 }}
                >
                  {SORTS.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
                </select>
                <button
                  onClick={() => navigate('markets')}
                  className="px-3 py-1.5 rounded-lg font-semibold"
                  style={{ fontSize: 12.5, background: 'var(--primary)', color: 'var(--primary-foreground)' }}
                >
                  + Buy more
                </button>
              </div>
            </div>

            {!compact && (
              <div className="grid items-center px-5 py-2 text-muted-foreground border-b border-border" style={{ gridTemplateColumns: 'minmax(0,2.2fr) 0.8fr 1fr 1fr 1.1fr 1.2fr 20px', fontSize: 11, letterSpacing: '0.04em' }}>
                <span>PLAYER</span>
                <span className="text-right">SHARES</span>
                <span className="text-right">PRICE</span>
                <span className="text-right">AVG COST</span>
                <span className="text-right">VALUE</span>
                <span className="text-right">GAIN / LOSS</span>
                <span />
              </div>
            )}

            {holdings.map((h, i) => {
              const weight = total > 0 ? (h.value / total) * 100 : 0;
              const focused = focusId === h.playerId;
              const nameBlock = (
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-1 self-stretch rounded-full shrink-0" style={{ background: h.color }} />
                  <PlayerAvatar name={playerName(h.market)} color={h.color} size={compact ? 38 : 40} />
                  <div className="min-w-0">
                    <p className="text-foreground font-semibold truncate" style={{ fontSize: 14.5 }}>{playerName(h.market)}<VerifiedBadge show={h.market.is_verified} /></p>
                    <p className="text-muted-foreground truncate" style={{ fontSize: 11.5 }}>
                      {h.market.team ? `${h.market.team} · ` : ''}{weight.toFixed(1)}% of portfolio
                    </p>
                  </div>
                </div>
              );
              const lockNote = h.locked > 0 ? (
                <span className="text-muted-foreground" style={{ fontSize: 10.5 }}>{h.locked.toLocaleString()} in open sell orders</span>
              ) : null;
              return compact ? (
                <button
                  key={h.playerId}
                  onClick={() => openPlayer(h.playerId)}
                  className="w-full text-left px-4 py-3.5 transition-colors hover:bg-white/[0.03]"
                  style={{ borderBottom: i < holdings.length - 1 ? '1px solid var(--border)' : 'none', background: focused ? 'rgba(0,200,255,0.06)' : undefined }}
                >
                  <div className="flex items-start justify-between gap-3">
                    {nameBlock}
                    <div className="text-right shrink-0">
                      <p className="font-mono font-bold text-foreground" style={{ fontSize: 15 }}>{usd(h.value)}</p>
                      <p className="font-mono font-bold" style={{ fontSize: 12, color: tone(h.pl) }}>{usdSigned(h.pl)} ({pctText(h.plPct)})</p>
                    </div>
                  </div>
                  <div className="flex items-center justify-between mt-2 text-muted-foreground font-mono" style={{ fontSize: 11.5 }}>
                    <span>{h.shares.toLocaleString()} sh · avg {usd(h.avgCost)}</span>
                    <span>
                      {usd(h.price)} <span style={{ color: tone(h.dayPct) }}>{pctText(h.dayPct)}</span>
                    </span>
                  </div>
                  {lockNote && <div className="mt-1">{lockNote}</div>}
                </button>
              ) : (
                <button
                  key={h.playerId}
                  onClick={() => openPlayer(h.playerId)}
                  className="w-full text-left grid items-center px-5 py-3 transition-colors hover:bg-white/[0.03]"
                  style={{ gridTemplateColumns: 'minmax(0,2.2fr) 0.8fr 1fr 1fr 1.1fr 1.2fr 20px', borderBottom: i < holdings.length - 1 ? '1px solid var(--border)' : 'none', background: focused ? 'rgba(0,200,255,0.06)' : undefined }}
                >
                  {nameBlock}
                  <div className="text-right font-mono text-foreground" style={{ fontSize: 13.5 }}>
                    {h.shares.toLocaleString()}
                    {lockNote && <div>{lockNote}</div>}
                  </div>
                  <div className="text-right font-mono">
                    <p className="text-foreground" style={{ fontSize: 13.5 }}>{usd(h.price)}</p>
                    <p style={{ fontSize: 11.5, color: tone(h.dayPct) }}>{pctText(h.dayPct)}</p>
                  </div>
                  <div className="text-right font-mono text-muted-foreground" style={{ fontSize: 13.5 }}>{usd(h.avgCost)}</div>
                  <div className="text-right font-mono font-bold text-foreground" style={{ fontSize: 14 }}>{usd(h.value)}</div>
                  <div className="text-right font-mono">
                    <p className="font-bold" style={{ fontSize: 13.5, color: tone(h.pl) }}>{usdSigned(h.pl)}</p>
                    <p style={{ fontSize: 11.5, color: tone(h.pl) }}>{pctText(h.plPct)}</p>
                  </div>
                  <ChevronRight className="w-4 h-4 text-muted-foreground justify-self-end" />
                </button>
              );
            })}

            {/* Cash and total, like the bottom of a brokerage statement */}
            <div className="flex items-center justify-between px-4 sm:px-5 py-3 border-t border-border" style={{ background: 'rgba(255,255,255,0.015)' }}>
              <span className="text-muted-foreground" style={{ fontSize: 13 }}>Cash</span>
              <span className="font-mono font-semibold text-foreground" style={{ fontSize: 14 }}>{usd(cash)}</span>
            </div>
            <div className="flex items-center justify-between px-4 sm:px-5 py-3 border-t border-border">
              <span className="text-foreground font-semibold" style={{ fontSize: 14 }}>Total</span>
              <span className="font-mono font-bold text-foreground" style={{ fontSize: 16 }}>{usd(total)}</span>
            </div>
          </div>

          <p className="text-muted-foreground px-1" style={{ fontSize: 11.5, lineHeight: 1.55 }}>
            Value is what selling the whole position right now would pay (real buy orders first, then the House), so a large position is worth slightly less per share than the listed price.
            Gain / loss compares that value with what you paid. Today's change uses each player's 24-hour price move.
          </p>
        </>
      )}

      <OpenOrders openPlayer={openPlayer} />
      <ActivityHistory openPlayer={openPlayer} />
    </div>
  );
}
