import { X } from 'lucide-react';
import { motion } from 'motion/react';
import { INVESTOR_PORTFOLIOS, LeaderboardEntry, formatCurrency, getPlayer } from './mockData';
import { Player } from './mockData';
import { PlayerAvatar } from './Dashboard';

interface Props {
  investor: LeaderboardEntry;
  onClose: () => void;
  onViewPlayer: (playerId: string) => void;
}

interface EnrichedHolding {
  playerId: string;
  shares: number;
  avgCost: number;
  player: Player;
  currentVal: number;
  pl: number;
  plPct: number;
}

export function InvestorModal({ investor, onClose, onViewPlayer }: Props) {
  const holdings = INVESTOR_PORTFOLIOS[investor.userId] ?? [];

  const enriched: EnrichedHolding[] = holdings.reduce<EnrichedHolding[]>((acc, h) => {
    const player = getPlayer(h.playerId);
    if (!player) return acc;
    const currentVal = h.shares * player.price;
    const pl = currentVal - h.shares * h.avgCost;
    const plPct = (pl / (h.shares * h.avgCost)) * 100;
    acc.push({ ...h, player, currentVal, pl, plPct });
    return acc;
  }, []);

  const totalVal = enriched.reduce((s, h) => s + h.currentVal, 0);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(6px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <motion.div
        className="w-full overflow-y-auto rounded-2xl border border-border"
        style={{
          background: 'var(--card)',
          maxWidth: 560,
          maxHeight: '88vh',
          scrollbarWidth: 'thin',
          scrollbarColor: 'rgba(255,255,255,0.08) transparent',
        }}
        initial={{ opacity: 0, scale: 0.96, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        {/* Header */}
        <div
          className="px-6 pt-5 pb-4 flex items-center gap-4"
          style={{ background: `linear-gradient(135deg, ${investor.color}12, transparent 60%)` }}
        >
          <div
            className="w-14 h-14 rounded-2xl flex items-center justify-center font-mono font-bold shrink-0"
            style={{ fontSize: 18, background: investor.color + '25', border: `2px solid ${investor.color}55`, color: investor.color }}
          >
            {investor.initials}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="text-foreground font-bold" style={{ fontSize: 20 }}>{investor.username}</h2>
              {investor.isCurrentUser && (
                <span className="px-2 py-0.5 rounded-full font-bold" style={{ fontSize: 10, background: 'rgba(0,200,255,0.15)', color: 'var(--primary)' }}>YOU</span>
              )}
            </div>
            <div className="flex items-center gap-3 mt-0.5">
              <span className="text-muted-foreground" style={{ fontSize: 13 }}>Rank #{investor.rank}</span>
              <span className="font-mono font-bold" style={{ fontSize: 13, color: 'var(--primary)' }}>{investor.elo.toLocaleString()} ELO</span>
              <span
                className="font-mono font-bold"
                style={{ fontSize: 13, color: investor.weeklyReturn >= 0 ? 'var(--gain)' : 'var(--loss)' }}
              >
                {investor.weeklyReturn >= 0 ? '+' : ''}{investor.weeklyReturn.toFixed(1)}% this week
              </span>
            </div>
          </div>
          <button onClick={onClose} className="p-2 rounded-xl hover:bg-white/10 transition-colors shrink-0">
            <X className="w-5 h-5 text-muted-foreground" />
          </button>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-3 px-6 pb-4">
          <div className="rounded-xl border border-border p-3 text-center" style={{ background: 'var(--muted)' }}>
            <p className="text-muted-foreground" style={{ fontSize: 11 }}>Portfolio Value</p>
            <p className="font-mono font-bold text-foreground" style={{ fontSize: 15, marginTop: 2 }}>{formatCurrency(investor.portfolioValue, 0)}</p>
          </div>
          <div className="rounded-xl border border-border p-3 text-center" style={{ background: 'var(--muted)' }}>
            <p className="text-muted-foreground" style={{ fontSize: 11 }}>Players Owned</p>
            <p className="font-mono font-bold text-foreground" style={{ fontSize: 15, marginTop: 2 }}>{enriched.length}</p>
          </div>
          <div className="rounded-xl border border-border p-3 text-center" style={{ background: 'var(--muted)' }}>
            <p className="text-muted-foreground" style={{ fontSize: 11 }}>Top Pick</p>
            <p className="font-mono font-bold" style={{ fontSize: 15, marginTop: 2, color: 'var(--accent)' }}>{investor.topHolding}</p>
          </div>
        </div>

        {/* Divider */}
        <div className="border-t border-border" />

        {/* Holdings */}
        <div className="px-6 py-4">
          <p className="text-muted-foreground font-semibold mb-3" style={{ fontSize: 12, letterSpacing: '0.06em' }}>
            {enriched.length > 0 ? `${investor.username.split(' ')[0]}'s Pro Picks` : 'No public holdings'}
          </p>
          {enriched.length === 0 ? (
            <p className="text-muted-foreground text-center py-8" style={{ fontSize: 14 }}>This investor's portfolio is private.</p>
          ) : (
            <div className="space-y-3">
              {enriched.map(h => (
                <div
                  key={h.playerId}
                  className="rounded-2xl border border-border p-4"
                  style={{ background: 'var(--muted)' }}
                >
                  <div className="flex items-start gap-3 mb-3">
                    <PlayerAvatar name={h.player.name} color={h.player.teamColor} size={44} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-foreground font-bold" style={{ fontSize: 15 }}>{h.player.name}</p>
                        <span
                          className="font-mono font-bold px-2 py-0.5 rounded-lg shrink-0"
                          style={{
                            fontSize: 12,
                            background: h.pl >= 0 ? 'rgba(16,217,160,0.12)' : 'rgba(255,61,92,0.12)',
                            color: h.pl >= 0 ? 'var(--gain)' : 'var(--loss)',
                          }}
                        >
                          {h.pl >= 0 ? '+' : ''}{h.plPct.toFixed(1)}%
                        </span>
                      </div>
                      <p className="text-muted-foreground" style={{ fontSize: 12 }}>
                        {h.shares} shares · {h.player.team} · {h.player.region}
                      </p>
                      <p className="font-mono font-bold" style={{ fontSize: 13, color: 'var(--foreground)', marginTop: 2 }}>
                        {formatCurrency(h.currentVal, 0)} value
                      </p>
                    </div>
                  </div>
                  {/* Description */}
                  <p className="text-muted-foreground mb-3" style={{ fontSize: 12, lineHeight: 1.6 }}>
                    {h.player.description}
                  </p>
                  <button
                    onClick={() => { onClose(); onViewPlayer(h.playerId); }}
                    className="w-full py-2 rounded-xl font-semibold transition-all hover:opacity-90"
                    style={{
                      fontSize: 13,
                      background: 'linear-gradient(135deg, var(--primary), var(--accent))',
                      color: '#fff',
                    }}
                  >
                    View &amp; Trade {h.player.name}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 pb-5">
          <div className="rounded-xl p-3 text-center" style={{ background: 'rgba(155,111,255,0.08)', border: '1px solid rgba(155,111,255,0.2)' }}>
            <p className="text-muted-foreground" style={{ fontSize: 12 }}>
              💡 See a player you like? Click <span style={{ color: 'var(--accent)' }}>View &amp; Trade</span> to check their price and buy shares!
            </p>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
