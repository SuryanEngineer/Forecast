import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { toNumber, type ValueHistoryPoint } from '../lib/types';

interface Props {
  id: string; // unique per instance -- becomes the SVG gradient id, so two charts on the same page never collide
  data: ValueHistoryPoint[];
  color?: string;
  height?: number;
  emptyLabel?: string;
}

function compactTick(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}

function makeTooltip(color: string) {
  return function ChartTooltip({ active, payload }: any) {
    if (!active || !payload?.length) return null;
    return (
      <div className="rounded-xl px-3 py-2 border border-border" style={{ background: 'var(--popover)' }}>
        <p className="font-mono font-bold" style={{ fontSize: 13, color }}>
          ${payload[0].value.toLocaleString('en-US', { maximumFractionDigits: 0 })}
        </p>
      </div>
    );
  };
}

/** Small reusable "value over time" area chart -- meant for a portfolio's
 * value history, whether that's your own or someone else's team. Purely
 * presentational: takes a timestamped value series as a prop and draws
 * it, with no opinion about where that data came from. NOTE: as of this
 * port, the real forecast-backend does not expose a portfolio value
 * history/snapshot endpoint, so nothing in this app currently feeds real
 * data into this component -- it's ported and ready to wire up the
 * moment such an endpoint exists (see lib/types.ts's ValueHistoryPoint
 * comment). Deliberately not wired to a fabricated client-side estimate
 * in the meantime. */
export function ValueChart({ id, data, color = '#00c8ff', height = 160, emptyLabel = 'Not enough history yet -- check back in a moment.' }: Props) {
  const points = data.map(d => ({
    t: new Date(d.recorded_at).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }),
    value: toNumber(d.value),
  }));

  if (points.length < 2) {
    return (
      <div className="flex items-center justify-center" style={{ height }}>
        <p className="text-muted-foreground text-center" style={{ fontSize: 13 }}>{emptyLabel}</p>
      </div>
    );
  }

  const Tip = makeTooltip(color);
  const gradId = `vc-${id}`;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.3} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="t" tick={{ fill: '#5a6a82', fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={40} />
        <YAxis tick={{ fill: '#5a6a82', fontSize: 10 }} axisLine={false} tickLine={false} width={50} domain={['auto', 'auto']} tickFormatter={compactTick} />
        <Tooltip content={<Tip />} />
        <Area type="monotone" dataKey="value" stroke={color} fill={`url(#${gradId})`} strokeWidth={2} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
