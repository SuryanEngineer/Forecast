import { useMemo, useState } from 'react';
import { X } from 'lucide-react';
import { motion } from 'motion/react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { MobileClose } from './MobileClose';
import { Spinner } from './Spinner';
import { UserTag } from './UserTag';
import { VerifiedBadge } from './HelpModal';
import { useInvestorProfile } from '../lib/hooks';
import { colorForId } from '../lib/colors';
import { usd, usdSigned } from '../lib/format';
import { axisMoney, niceAxis } from '../lib/chartAxis';

interface Props {
  userId: string;
  onClose: () => void;
  /** Tapping a holding opens that player (the caller closes this popup first). */
  onOpenPlayer?: (playerId: string) => void;
}

type Range = '1D' | '7D' | '1M' | 'ALL';
const RANGE_LABEL: Record<Range, string> = { '1D': '1 Day', '7D': '7 Days', '1M': '1 Month', ALL: 'All' };
const RANGE_PHRASE: Record<Range, string> = { '1D': 'past 24 hours', '7D': 'past 7 days', '1M': 'past month', ALL: 'all time' };
const RANGE_HOURS: Record<Range, number> = { '1D': 24, '7D': 168, '1M': 720, ALL: 0 };

const tone = (v: number) => (v > 0.005 ? 'var(--gain)' : v < -0.005 ? 'var(--loss)' : 'var(--muted-foreground)');

function Stat({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="rounded-xl border border-border p-3 text-center" style={{ background: 'var(--muted)' }}>
      <p className="text-muted-foreground" style={{ fontSize: 11 }}>{label}</p>
      <p className="font-mono font-bold mt-0.5 truncate" style={{ fontSize: 16, color: color ?? 'var(--foreground)' }}>{value}</p>
      {sub && <p className="text-muted-foreground truncate" style={{ fontSize: 10.5 }}>{sub}</p>}
    </div>
  );
}

/** The popup you get by tapping an investor on the leaderboard: a deliberately limited public view -- rank, net worth over
 * time, cash, what they hold, and their lifetime dividends and fees. No orders, trades or activity (those stay private to
 * the owner's own My Portfolio / My Stats pages). All of it comes from one request, GET /leaderboard/{user_id}. */
export function TeamModal({ userId, onClose, onOpenPlayer }: Props) {
  const [range, setRange] = useState<Range>('1M');
  const { data: profile, loading, error } = useInvestorProfile(userId, RANGE_HOURS[range]);
  const color = colorForId(userId);

  const chart = useMemo(() => {
    const pts = (profile?.points ?? []).map(p => ({ ts: new Date(p.t).getTime(), value: p.net_worth }));
    return pts.length >= 2 ? pts : [];
  }, [profile]);
  const axis = useMemo(() => niceAxis(chart.map(c => c.value)), [chart]);
  const spanMs = chart.length >= 2 ? chart[chart.length - 1].ts - chart[0].ts : 0;
  const tickFmt = (ts: number) => new Date(ts).toLocaleString('en-US', spanMs <= 36 * 3600_000 ? { hour: 'numeric', minute: '2-digit' } : spanMs <= 10 * 86400_000 ? { month: 'numeric', day: 'numeric', hour: 'numeric' } : { month: 'short', day: 'numeric' });
  const delta = chart.length >= 2 ? chart[chart.length - 1].value - chart[0].value : 0;
  const deltaPct = chart.length >= 2 && chart[0].value > 0 ? (delta / chart[0].value) * 100 : 0;
  const chartColor = delta >= 0 ? '#10d9a0' : '#ff3d5c';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 modal-overlay"
      style={{ background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(6px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <motion.div
        className="w-full overflow-y-auto rounded-2xl border border-border modal-panel modal-scroll"
        style={{ background: 'var(--card)', maxWidth: 520, maxHeight: '88vh', scrollbarWidth: 'thin', scrollbarColor: 'rgba(255,255,255,0.08) transparent' }}
        initial={{ opacity: 0, scale: 0.96, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        <MobileClose onClose={onClose} />
        {!profile && loading ? (
          <div className="flex justify-center py-20"><Spinner size={22} label="Loading investor…" /></div>
        ) : !profile ? (
          <div className="p-6 text-center">
            <p style={{ fontSize: 14, color: 'var(--loss)' }}>{error && !/not found/i.test(error) ? "Couldn't load this investor. Try again in a moment." : "Couldn't find this investor on the leaderboard."}</p>
            <button onClick={onClose} className="mt-4 px-4 py-2 rounded-xl font-semibold" style={{ fontSize: 13, background: 'var(--muted)', color: 'var(--foreground)' }}>Close</button>
          </div>
        ) : (
          <>
            {/* Who, rank, net worth */}
            <div className="px-4 sm:px-6 pt-5 pb-3" style={{ background: `linear-gradient(135deg, ${color}14, transparent 60%)` }}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="text-foreground font-bold truncate" style={{ fontSize: 22 }}><UserTag tag={profile.tag} color={profile.tag_color} />{profile.display_name}</h2>
                  <p className="text-muted-foreground mt-0.5" style={{ fontSize: 12.5 }}>Rank #{profile.rank} of {profile.investors}</p>
                </div>
                <button onClick={onClose} className="p-2 rounded-xl hover:bg-white/10 transition-colors shrink-0" aria-label="Close">
                  <X className="w-5 h-5 text-muted-foreground" />
                </button>
              </div>
              <p className="font-mono font-bold mt-2" style={{ fontSize: 28, color: 'var(--foreground)', letterSpacing: '-0.5px' }}>{usd(profile.net_worth)}</p>
              <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                <p className="text-muted-foreground" style={{ fontSize: 12 }}>Portfolio value</p>
                {chart.length >= 2 && (
                  <span className="font-mono font-bold" style={{ fontSize: 12, color: tone(delta) }}>
                    {usdSigned(delta)} ({deltaPct >= 0 ? '+' : '-'}{Math.abs(deltaPct).toFixed(2)}%) {RANGE_PHRASE[range]}
                  </span>
                )}
              </div>
            </div>

            {/* Value over time */}
            <div className="px-3 sm:px-4 pb-2">
              <div className="flex items-center justify-between px-2 mb-1">
                <p className="text-muted-foreground" style={{ fontSize: 11, letterSpacing: '0.04em' }}>VALUE OVER TIME</p>
                <div className="flex gap-1">
                  {(['1D', '7D', '1M', 'ALL'] as Range[]).map(r => (
                    <button
                      key={r}
                      onClick={() => setRange(r)}
                      className="px-2 py-1 rounded-lg font-semibold transition-colors"
                      style={{ fontSize: 11, background: range === r ? 'rgba(0,200,255,0.15)' : 'transparent', color: range === r ? 'var(--primary)' : 'var(--muted-foreground)' }}
                    >
                      {RANGE_LABEL[r]}
                    </button>
                  ))}
                </div>
              </div>
              {chart.length < 2 ? (
                <p className="text-muted-foreground text-center py-8" style={{ fontSize: 13 }}>{loading ? 'Loading chart…' : 'Not enough history in this range yet.'}</p>
              ) : (
                <div style={{ height: 170 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chart} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <defs>
                        <linearGradient id="invNw" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={chartColor} stopOpacity={0.3} />
                          <stop offset="100%" stopColor={chartColor} stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <XAxis dataKey="ts" type="number" scale="time" domain={['dataMin', 'dataMax']} tickFormatter={tickFmt} tick={{ fontSize: 10, fill: '#7d8fae' }} axisLine={false} tickLine={false} minTickGap={28} />
                      <CartesianGrid vertical={false} stroke="rgba(125,143,174,0.14)" />
                      <YAxis orientation="left" domain={axis.domain} ticks={axis.ticks} width={46} tick={{ fontSize: 10, fill: '#7d8fae' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => axisMoney(v, axis.step)} />
                      <Tooltip
                        formatter={(v: number) => [usd(v), 'Net worth']}
                        labelFormatter={(l: number) => new Date(l).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
                        contentStyle={{ background: 'var(--popover)', border: '1px solid var(--border)', borderRadius: 12, fontSize: 12 }}
                      />
                      <Area type="linear" dataKey="value" stroke={chartColor} strokeWidth={2} fill="url(#invNw)" dot={false} isAnimationActive={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            {/* Key numbers */}
            <div className="px-4 sm:px-6 py-3 grid grid-cols-2 gap-3">
              <Stat label="Cash" value={usd(profile.cash)} color="var(--primary)" />
              <Stat label="Shares value" value={usd(profile.shares_value)} sub={profile.treasury_value > 0 ? `+ ${usd(profile.treasury_value)} in treasury` : `${profile.holdings_count} player${profile.holdings_count === 1 ? '' : 's'}`} />
              <Stat label="Dividends earned" value={usd(profile.dividend_earnings)} sub={`${profile.dividend_payouts} payout${profile.dividend_payouts === 1 ? '' : 's'}`} color="var(--gain)" />
              <Stat label="Fees paid" value={usd(profile.fees_paid)} />
            </div>

            {/* What they hold */}
            <div className="px-4 sm:px-6 pb-5">
              <p className="text-foreground font-semibold mb-2" style={{ fontSize: 14 }}>Holdings</p>
              {profile.holdings.length === 0 ? (
                <p className="text-muted-foreground text-center py-4" style={{ fontSize: 13 }}>Doesn't own any players right now.</p>
              ) : (
                <div className="rounded-xl border border-border overflow-hidden">
                  {profile.holdings.map((h, i) => (
                    <button
                      key={h.player_id}
                      onClick={() => onOpenPlayer?.(h.player_id)}
                      disabled={!onOpenPlayer}
                      className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-white/[0.03] transition-colors"
                      style={{ borderTop: i === 0 ? 'none' : '1px solid var(--border)', cursor: onOpenPlayer ? 'pointer' : 'default' }}
                    >
                      <div className="flex-1 min-w-0">
                        <p className="text-foreground font-semibold truncate" style={{ fontSize: 13.5 }}>{h.gamertag}<VerifiedBadge show={h.is_verified} /></p>
                        <p className="text-muted-foreground font-mono" style={{ fontSize: 11.5 }}>{h.shares.toLocaleString('en-US')} share{h.shares === 1 ? '' : 's'} @ {usd(h.price)}</p>
                      </div>
                      <p className="font-mono font-bold shrink-0" style={{ fontSize: 13.5, color: 'var(--foreground)' }}>{usd(h.value)}</p>
                    </button>
                  ))}
                </div>
              )}
              {profile.holdings_count > profile.holdings.length && (
                <p className="text-muted-foreground text-center mt-2" style={{ fontSize: 11.5 }}>Showing the {profile.holdings.length} biggest of {profile.holdings_count} holdings.</p>
              )}
              <p className="text-muted-foreground mt-3" style={{ fontSize: 11 }}>
                A holding's value is what selling that whole position would pay right now, so very large positions are worth a little less than shares x price.
              </p>
            </div>
          </>
        )}
      </motion.div>
    </div>
  );
}
