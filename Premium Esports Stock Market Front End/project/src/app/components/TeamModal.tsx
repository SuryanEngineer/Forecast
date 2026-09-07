import { X } from 'lucide-react';
import { motion } from 'motion/react';
import { useLeaderboard } from '../lib/hooks';
import { toNumber } from '../lib/types';
import { colorForId } from '../lib/colors';

interface Props {
  userId: string;
  onClose: () => void;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** "View this investor" modal -- opened from Leaderboards.tsx by tapping
 * any row (parity with ForecastDemo's "view other users' holdings/stats"
 * feature).
 *
 * NOTE on scope: ForecastDemo's TeamModal has full "My Team" parity for
 * ANY user -- holdings list, a value-over-time chart, standing orders,
 * and trade history -- because its in-memory engine happily exposes that
 * for every account. The real forecast-backend does not: positions,
 * orders, and trades are all scoped to the *current* authenticated user
 * only (see app/api/v1/players.py's /players/positions/me,
 * orders.py's /orders/me, and there's no equivalent "for this other
 * user_id" route for any of them). Rather than fabricate that data
 * client-side, this shows exactly what GET /leaderboard already
 * legitimately exposes about another investor -- rank, cash balance,
 * holdings value, and total portfolio value -- and says so plainly
 * instead of implying more detail is available. Full parity would need
 * new read-only backend endpoints (e.g. GET /users/{id}/positions); see
 * this task's final report. */
export function TeamModal({ userId, onClose }: Props) {
  const { data: entries, loading } = useLeaderboard();
  const entry = entries.find(e => e.user_id === userId);
  const color = colorForId(userId);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(6px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <motion.div
        className="w-full overflow-y-auto rounded-2xl border border-border"
        style={{ background: 'var(--card)', maxWidth: 460, maxHeight: '85vh', scrollbarWidth: 'thin', scrollbarColor: 'rgba(255,255,255,0.08) transparent' }}
        initial={{ opacity: 0, scale: 0.96, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        {loading && !entry ? (
          <p className="text-muted-foreground text-center py-16" style={{ fontSize: 14 }}>Loading investor…</p>
        ) : !entry ? (
          <div className="p-6 text-center">
            <p style={{ fontSize: 14, color: 'var(--loss)' }}>Couldn't find this investor on the leaderboard.</p>
            <button
              onClick={onClose}
              className="mt-4 px-4 py-2 rounded-xl font-semibold"
              style={{ fontSize: 13, background: 'var(--muted)', color: 'var(--foreground)' }}
            >
              Close
            </button>
          </div>
        ) : (
          <>
            <div className="px-6 pt-5 pb-4 flex items-start gap-4" style={{ background: `linear-gradient(135deg, ${color}14, transparent 60%)` }}>
              <div
                className="rounded-2xl flex items-center justify-center shrink-0 font-mono font-bold select-none"
                style={{ width: 56, height: 56, background: color + '25', border: `2px solid ${color}50`, color, fontSize: 20 }}
              >
                {initials(entry.display_name)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-foreground font-bold" style={{ fontSize: 22 }}>{entry.display_name}</h2>
                    <p className="text-muted-foreground mt-0.5" style={{ fontSize: 12.5 }}>Rank #{entry.rank}</p>
                  </div>
                  <button onClick={onClose} className="p-2 rounded-xl hover:bg-white/10 transition-colors shrink-0">
                    <X className="w-5 h-5 text-muted-foreground" />
                  </button>
                </div>
                <p className="font-mono font-bold mt-2" style={{ fontSize: 26, color: 'var(--foreground)', letterSpacing: '-0.5px' }}>
                  ${toNumber(entry.portfolio_value).toLocaleString('en-US', { maximumFractionDigits: 0 })}
                </p>
                <p className="text-muted-foreground mt-1" style={{ fontSize: 12 }}>Total portfolio value</p>
              </div>
            </div>

            <div className="px-6 py-5 grid grid-cols-2 gap-3">
              <div className="rounded-xl border border-border p-3 text-center" style={{ background: 'var(--muted)' }}>
                <p className="text-muted-foreground" style={{ fontSize: 11 }}>Cash Balance</p>
                <p className="font-mono font-bold mt-0.5" style={{ fontSize: 17, color: 'var(--foreground)' }}>
                  ${toNumber(entry.cash_balance).toLocaleString('en-US', { maximumFractionDigits: 0 })}
                </p>
              </div>
              <div className="rounded-xl border border-border p-3 text-center" style={{ background: 'var(--muted)' }}>
                <p className="text-muted-foreground" style={{ fontSize: 11 }}>Holdings Value</p>
                <p className="font-mono font-bold mt-0.5" style={{ fontSize: 17, color: 'var(--foreground)' }}>
                  ${toNumber(entry.holdings_value).toLocaleString('en-US', { maximumFractionDigits: 0 })}
                </p>
              </div>
            </div>

            <div className="px-6 pb-6">
              <p className="text-muted-foreground text-center" style={{ fontSize: 11.5, lineHeight: 1.5 }}>
                A per-player holdings breakdown, value history, and trade history for other investors isn't available yet --
                only your own "My Team" page shows that level of detail right now.
              </p>
            </div>
          </>
        )}
      </motion.div>
    </div>
  );
}
