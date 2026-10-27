import { useEffect, useMemo, useRef, useState } from 'react';
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../lib/api';
import { useSeasonList } from '../lib/hooks';
import { seasonMarkersBetween } from '../lib/seasons';
import { toNumber, type PriceHistoryPoint } from '../lib/types';

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

const RANGES = [
  { key: '1d', label: '1D' },
  { key: '1w', label: '1W' },
  { key: '1m', label: '1M' },
  { key: 'all', label: 'All' },
] as const;
type RangeKey = (typeof RANGES)[number]['key'];

const TICK_STEPS = [HOUR, 2 * HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR, DAY, 2 * DAY, 7 * DAY, 14 * DAY, 30 * DAY];

/** A handful of evenly spaced ticks aligned to LOCAL hour / midnight boundaries, so axis labels read naturally. */
function niceTicks(start: number, end: number): { ticks: number[]; step: number } {
  const span = Math.max(end - start, HOUR);
  const step = TICK_STEPS.find(s => span / s <= 5) ?? TICK_STEPS[TICK_STEPS.length - 1];
  const offset = -new Date(start).getTimezoneOffset() * 60_000;
  const ticks: number[] = [];
  for (let t = Math.ceil((start + offset) / step) * step - offset; t <= end; t += step) ticks.push(t);
  return { ticks, step };
}

function formatTick(t: number, step: number, span: number): string {
  const d = new Date(t);
  if (step >= DAY) return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  if (span <= 36 * HOUR) return d.toLocaleTimeString('en-US', { hour: 'numeric' });
  return d.toLocaleString('en-US', { weekday: 'short', hour: 'numeric' });
}

const money = (v: number) => `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function ChartTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as { t: number; price: number };
  return (
    <div className="rounded-xl px-3 py-2 border border-border" style={{ background: 'var(--popover)' }}>
      <p className="font-mono font-bold text-foreground" style={{ fontSize: 14 }}>{money(p.price)}</p>
      <p className="text-muted-foreground" style={{ fontSize: 11 }}>
        {new Date(p.t).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
      </p>
    </div>
  );
}

/** Price history as a step function: a stock's price only changes when a trade executes, so the line stays flat
 * between trades and jumps straight to the next trade price (no smoothing). It always runs on to "now". */
export function PriceChart({ playerId, color, latestTradeId }: { playerId: string; color: string; latestTradeId?: string }) {
  const [range, setRange] = useState<RangeKey>('1w');
  const [raw, setRaw] = useState<PriceHistoryPoint[] | null>(null);
  const loadedKey = useRef('');
  const { data: seasons } = useSeasonList();

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .get<PriceHistoryPoint[]>(`/markets/${playerId}/price-history?range=${range}`)
        .then(r => { if (!cancelled) setRaw(r); })
        .catch(() => { if (!cancelled) setRaw(prev => prev ?? []); });
    // Show "Loading" only when the player or range changed -- a new trade just refreshes in place.
    const key = `${playerId}:${range}`;
    if (loadedKey.current !== key) {
      loadedKey.current = key;
      setRaw(null);
    }
    load();
    const id = setInterval(load, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [playerId, range, latestTradeId]);

  const view = useMemo(() => {
    if (!raw || raw.length === 0) return null;
    const now = Date.now();
    const pts = raw
      .map(p => ({ t: new Date(p.recorded_at).getTime(), price: toNumber(p.price) }))
      .filter(p => Number.isFinite(p.t) && Number.isFinite(p.price))
      .sort((a, b) => a.t - b.t);
    if (pts.length === 0) return null;
    const last = pts[pts.length - 1];
    if (last.t < now) pts.push({ t: now, price: last.price }); // the price in force right now
    const end = pts[pts.length - 1].t;
    const start = Math.min(pts[0].t, end - HOUR); // never a degenerate (zero-width) axis
    const prices = pts.map(p => p.price);
    const lo = Math.min(...prices);
    const hi = Math.max(...prices);
    const pad = Math.max((hi - lo) * 0.15, hi * 0.01, 0.01);
    const { ticks, step } = niceTicks(start, end);
    const first = pts[0].price;
    return { pts, start, end, ticks, step, yMin: Math.max(0, lo - pad), yMax: hi + pad, changePct: first > 0 ? ((last.price - first) / first) * 100 : 0 };
  }, [raw]);

  // Dashed lines where a Fortnite season begins -- only inside the span this chart actually has data for.
  const markers = useMemo(() => (view ? seasonMarkersBetween(seasons, view.start, view.end) : []), [view, seasons]);

  const up = (view?.changePct ?? 0) >= 0;
  const stroke = view ? (up ? '#10d9a0' : '#ff3d5c') : color;
  const gid = `pc-${playerId}`;

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <p className="text-muted-foreground" style={{ fontSize: 12 }}>
          Price history
          {view && (
            <span className="font-mono font-semibold ml-2" style={{ color: up ? 'var(--gain)' : 'var(--loss)' }}>
              {up ? '+' : ''}{view.changePct.toFixed(2)}%
            </span>
          )}
        </p>
        <div className="flex gap-1">
          {RANGES.map(r => (
            <button
              key={r.key}
              onClick={() => setRange(r.key)}
              className="rounded-lg font-semibold transition-colors"
              style={{
                fontSize: 11,
                padding: '3px 9px',
                background: range === r.key ? 'rgba(0,200,255,0.12)' : 'transparent',
                color: range === r.key ? 'var(--primary)' : 'var(--muted-foreground)',
              }}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {raw === null ? (
        <div className="flex items-center justify-center text-muted-foreground" style={{ height: 170, fontSize: 12.5 }}>Loading…</div>
      ) : !view ? (
        <div className="flex items-center justify-center text-muted-foreground" style={{ height: 170, fontSize: 12.5 }}>
          No trades yet. The chart starts with the first trade.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={170}>
          <AreaChart data={view.pts} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={stroke} stopOpacity={0.28} />
                <stop offset="95%" stopColor={stroke} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={[view.start, view.end]}
              ticks={view.ticks}
              tickFormatter={(t: number) => formatTick(t, view.step, view.end - view.start)}
              tick={{ fill: '#5a6a82', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              minTickGap={24}
            />
            <YAxis
              domain={[view.yMin, view.yMax]}
              tick={{ fill: '#5a6a82', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              width={52}
              tickFormatter={(v: number) => `$${v < 100 ? v.toFixed(2) : v.toFixed(0)}`}
              tickCount={4}
            />
            {markers.map(m => (
              <ReferenceLine
                key={m.t}
                x={m.t}
                stroke="rgba(155,111,255,0.75)"
                strokeDasharray="3 3"
                label={{ value: m.label, position: 'insideTopRight', fill: '#9b6fff', fontSize: 10 }}
              />
            ))}
            <Tooltip content={<ChartTooltip />} />
            <Area type="stepAfter" dataKey="price" stroke={stroke} strokeWidth={2} fill={`url(#${gid})`} dot={false} activeDot={{ r: 3 }} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      )}
      {markers.length > 0 && (
        <p className="text-muted-foreground mt-1" style={{ fontSize: 10.5 }}>
          Dashed line = start of a Fortnite season ({markers.map(m => m.full).join(', ')})
        </p>
      )}
    </div>
  );
}
