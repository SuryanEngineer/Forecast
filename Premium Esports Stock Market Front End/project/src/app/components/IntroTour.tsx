import { useState, type ReactNode } from 'react';
import { ArrowUpRight, ChevronLeft, ChevronRight, Sparkles, X } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

interface Props {
  onClose: () => void;
  // Lets a caller deep-link straight to one slide (e.g. Dashboard's "How
  // Dividends Work" box jumps right to the dividends slide) instead of
  // always starting the tour over from Welcome. Still fully navigable
  // (Back/Next) from wherever it opens.
  initialStep?: number;
  // Which localStorage key this specific viewing marks as "seen" once
  // dismissed. Callers key this per-account (see introSeenKey below and
  // App.tsx's usage) rather than sharing one global flag, so a brand new
  // account always gets the tour by default -- "has *this account* seen
  // it," not "has this browser ever seen it" -- even when a different
  // account has already dismissed it on the same machine.
  storageKey: string;
}

// Prefixed per-user-id rather than one shared `forecast_intro_seen` flag,
// so registering a new account always starts the tour fresh even on a
// browser where an earlier account already dismissed it.
export function introSeenKey(userId: string): string {
  return `forecast_intro_seen_${userId}`;
}

// --- tiny illustrative "snips" -- simplified mockups of the real UI
// (same colors/shapes as the actual components), not literal screenshots.
// Kept as plain divs/inline styles so this whole tour has zero runtime
// dependency on any chart library. ---

function TickerSnip() {
  const rows = [
    { name: 'Bugha', price: '134.20', pct: '+8.2%', up: true },
    { name: 'Clix', price: '96.40', pct: '+3.1%', up: true },
    { name: 'Mero', price: '54.10', pct: '-2.4%', up: false },
  ];
  return (
    <div className="rounded-xl border border-border overflow-hidden" style={{ background: 'var(--muted)' }}>
      {rows.map((r, i) => (
        <div key={r.name} className="flex items-center gap-2 px-3 py-2" style={{ borderTop: i > 0 ? '1px solid var(--border)' : 'none' }}>
          <div className="w-6 h-6 rounded-full shrink-0" style={{ background: r.up ? 'rgba(16,217,160,0.25)' : 'rgba(255,61,92,0.25)' }} />
          <span className="text-foreground font-semibold flex-1" style={{ fontSize: 12 }}>{r.name}</span>
          <span className="font-mono text-foreground" style={{ fontSize: 12 }}>${r.price}</span>
          <span className="font-mono font-bold" style={{ fontSize: 11, color: r.up ? 'var(--gain)' : 'var(--loss)' }}>{r.pct}</span>
        </div>
      ))}
    </div>
  );
}

function OrdersSnip() {
  return (
    <div className="grid grid-cols-2 gap-2">
      <div className="rounded-xl border border-border p-2" style={{ background: 'var(--muted)' }}>
        <p className="text-muted-foreground mb-1" style={{ fontSize: 9.5, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Limit order</p>
        {[{ p: '52.80', c: 'var(--loss)' }, { p: '52.40', c: 'var(--loss)' }, { p: '51.10', c: 'var(--gain)' }, { p: '50.90', c: 'var(--gain)' }].map((row, i) => (
          <div key={i} className="flex items-center justify-between px-1 py-0.5">
            <span className="font-mono font-bold" style={{ fontSize: 11, color: row.c }}>${row.p}</span>
            <span className="font-mono text-muted-foreground" style={{ fontSize: 10 }}>{20 + i * 5}</span>
          </div>
        ))}
      </div>
      <div className="rounded-xl border border-border p-2 flex flex-col items-center justify-center gap-2" style={{ background: 'var(--muted)' }}>
        <p className="text-muted-foreground" style={{ fontSize: 9.5, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Quick trade</p>
        <div className="w-full py-2 rounded-lg text-center font-bold" style={{ fontSize: 11, background: 'linear-gradient(135deg, #10d9a0, #00c8ff)', color: '#fff' }}>
          ⚡ Quick Buy
        </div>
        <p className="text-muted-foreground text-center" style={{ fontSize: 9, lineHeight: 1.4 }}>Instant, small premium</p>
      </div>
    </div>
  );
}

function DividendSnip() {
  return (
    <div className="rounded-xl border border-border p-3 flex items-center gap-3" style={{ background: 'var(--muted)' }}>
      <div className="w-9 h-9 rounded-xl flex items-center justify-center font-mono font-bold shrink-0" style={{ fontSize: 14, background: 'rgba(251,191,36,0.2)', color: '#fbbf24' }}>
        #1
      </div>
      <div className="flex-1">
        <p className="text-foreground font-semibold" style={{ fontSize: 12.5 }}>Your player wins a Cash Cup</p>
        <p className="text-muted-foreground" style={{ fontSize: 10.5 }}>Dividend split across every shareholder</p>
      </div>
      <span className="font-mono font-bold px-2 py-1 rounded-lg" style={{ fontSize: 12, background: 'rgba(16,217,160,0.15)', color: 'var(--gain)' }}>+$60.00</span>
    </div>
  );
}

function PortfolioSnip() {
  return (
    <div className="flex items-center gap-4">
      <div style={{ position: 'relative', width: 72, height: 72 }}>
        <div
          style={{
            width: 72, height: 72, borderRadius: '50%',
            background: 'conic-gradient(#00c8ff 0% 40%, #9b6fff 40% 65%, #10d9a0 65% 85%, rgba(255,255,255,0.15) 85% 100%)',
          }}
        />
        <div style={{ position: 'absolute', inset: 10, borderRadius: '50%', background: 'var(--card)' }} />
      </div>
      <div className="flex-1 space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground" style={{ fontSize: 11 }}>Portfolio value</span>
          <span className="font-mono font-bold text-foreground" style={{ fontSize: 13 }}>$1,118,420</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground" style={{ fontSize: 11 }}>Your rank</span>
          <span className="font-mono font-bold" style={{ fontSize: 13, color: 'var(--primary)' }}>#3</span>
        </div>
      </div>
    </div>
  );
}

interface Slide {
  emoji: string;
  title: string;
  body: ReactNode;
  visual: ReactNode;
}

const SLIDES: Slide[] = [
  {
    emoji: '🎮',
    title: 'Welcome to Forecast',
    body: 'A fantasy stock market for competitive Fortnite. Buy shares in real pro players, and build up your wealth as their value -- and your portfolio -- grows.',
    visual: <TickerSnip />,
  },
  {
    emoji: '📈',
    title: 'Browse the market',
    body: "Every active player has a live price that moves with real trading activity -- yours, other traders', and background market activity keeping things liquid.",
    visual: <TickerSnip />,
  },
  {
    emoji: '🎯',
    title: 'Two ways to trade',
    body: 'Place a Buy/Sell order at your own price and it rests on the order book until it fills -- usually cheaper. Or use Quick Buy/Sell to trade instantly, for a small premium.',
    visual: <OrdersSnip />,
  },
  {
    emoji: '🏆',
    title: 'Tournaments pay dividends',
    body: 'When a player you own places well in a tournament, everyone holding their stock gets paid a dividend -- straight to your cash balance.',
    visual: <DividendSnip />,
  },
  {
    emoji: '💼',
    title: 'Build your team',
    body: "Track your holdings, see how you rank on the leaderboard, and check out anyone else's team too.",
    visual: <PortfolioSnip />,
  },
];

export function IntroTour({ onClose, initialStep = 0, storageKey }: Props) {
  const [step, setStep] = useState(() => Math.min(Math.max(initialStep, 0), SLIDES.length - 1));
  const last = step === SLIDES.length - 1;
  const slide = SLIDES[step];

  function finish() {
    try { localStorage.setItem(storageKey, '1'); } catch { /* ignore -- storage may be unavailable */ }
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(6px)' }}
      onClick={e => { if (e.target === e.currentTarget) finish(); }}
    >
      <motion.div
        className="w-full rounded-2xl border border-border overflow-hidden"
        style={{ background: 'var(--card)', maxWidth: 440 }}
        initial={{ opacity: 0, scale: 0.95, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        <div className="px-6 pt-5 pb-1 flex items-center justify-between">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full font-bold uppercase" style={{ fontSize: 10, background: 'rgba(0,200,255,0.12)', color: 'var(--primary)' }}>
            <Sparkles className="w-3 h-3" /> Quick tour
          </span>
          <button onClick={finish} className="p-1.5 rounded-lg hover:bg-white/10 transition-colors">
            <X className="w-4 h-4 text-muted-foreground" />
          </button>
        </div>

        <AnimatePresence mode="wait">
          <motion.div
            key={step}
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
            transition={{ duration: 0.15 }}
            className="px-6 pb-2"
          >
            <p style={{ fontSize: 34 }}>{slide.emoji}</p>
            <h2 className="text-foreground font-bold mt-1" style={{ fontSize: 19 }}>{slide.title}</h2>
            <p className="text-muted-foreground mt-1.5 mb-4" style={{ fontSize: 13.5, lineHeight: 1.6 }}>{slide.body}</p>
            {slide.visual}
          </motion.div>
        </AnimatePresence>

        <div className="px-6 pt-4 pb-5">
          <div className="flex items-center justify-center gap-1.5 mb-4">
            {SLIDES.map((_, i) => (
              <span
                key={i}
                className="rounded-full transition-all"
                style={{ width: i === step ? 18 : 6, height: 6, background: i === step ? 'var(--primary)' : 'var(--border)' }}
              />
            ))}
          </div>
          <div className="flex items-center gap-2">
            {step > 0 && (
              <button
                onClick={() => setStep(s => s - 1)}
                className="flex items-center gap-1 px-3 py-2.5 rounded-xl font-semibold transition-colors hover:bg-white/[0.06]"
                style={{ fontSize: 13, color: 'var(--muted-foreground)', border: '1px solid var(--border)' }}
              >
                <ChevronLeft className="w-4 h-4" /> Back
              </button>
            )}
            {step === 0 && (
              <button onClick={finish} className="px-3 py-2.5 rounded-xl font-semibold transition-colors hover:bg-white/[0.06]" style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>
                Skip
              </button>
            )}
            <button
              onClick={() => (last ? finish() : setStep(s => s + 1))}
              className="flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-xl font-bold transition-opacity hover:opacity-90"
              style={{ fontSize: 14, background: 'linear-gradient(135deg, var(--primary), var(--accent))', color: '#fff' }}
            >
              {last ? (
                <>Let's go <ArrowUpRight className="w-4 h-4" /></>
              ) : (
                <>Next <ChevronRight className="w-4 h-4" /></>
              )}
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
