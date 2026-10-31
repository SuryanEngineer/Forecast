import { useEffect, useState, type ReactNode } from 'react';
import { ArrowUpRight, Check, ChevronLeft, ChevronRight, Sparkles, X } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { BenchmarkText, useBenchmarkPct } from './Benchmark';

interface Props {
  onClose: () => void;
  // Lets a caller deep-link straight to one slide instead of always starting from Welcome. Still fully navigable.
  initialStep?: number;
  // Which localStorage key this viewing marks as "seen" once dismissed. Keyed per account (see introSeenKey) so a
  // brand new account always gets the tour by default, even on a browser where another account already dismissed it.
  storageKey: string;
  // Used by the last slide's "first moves" buttons. Optional so the tour still works wherever it is mounted.
  onNavigate?: (page: string) => void;
  onOpenGuide?: () => void;
}

export function introSeenKey(userId: string): string {
  return `forecast_intro_seen_${userId}`;
}

// The tour is a short, hands-on warm-up, not a manual: every slide is two sentences plus something to tap. The full
// reference lives in the Guide (HelpModal.tsx), which the last slide links to. Nothing here is mandatory: Skip is
// visible on every slide, Esc / clicking outside closes it, and it only auto-opens once, right after sign-up.
//
// The numbers in the little demos are ILLUSTRATIVE (round numbers that show how the mechanics behave), and say so.
// The real figures live in the Guide and on each player's page.

const GAIN = 'var(--gain)';
const LOSS = 'var(--loss)';
const money = (n: number, d = 0) => `$${n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })}`;

function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-border ${className}`} style={{ background: 'var(--muted)' }}>{children}</div>;
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      className="px-3 py-1.5 rounded-full font-semibold transition-colors"
      style={{
        fontSize: 12,
        background: active ? 'rgba(0,200,255,0.18)' : 'transparent',
        color: active ? 'var(--primary)' : 'var(--muted-foreground)',
        border: `1px solid ${active ? 'var(--primary)' : 'var(--border)'}`,
      }}
    >
      {children}
    </button>
  );
}

function Caption({ children }: { children: ReactNode }) {
  return <p className="text-muted-foreground mt-2" style={{ fontSize: 10.5, lineHeight: 1.4 }}>{children}</p>;
}

// --- 1. The loop: four steps that light up in turn -------------------------------------------------------------
function FlowSnip() {
  const steps = [
    { icon: '🔍', label: 'Pick a pro' },
    { icon: '🛒', label: 'Buy before the event' },
    { icon: '🏆', label: 'They compete' },
    { icon: '💵', label: 'Dividend lands' },
  ];
  const [active, setActive] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setActive(a => (a + 1) % steps.length), 1100);
    return () => clearInterval(t);
  }, [steps.length]);
  return (
    <div className="flex items-stretch gap-1.5">
      {steps.map((s, i) => (
        <div key={s.label} className="flex-1 flex items-center gap-1.5">
          <motion.div
            className="flex-1 rounded-xl border p-2 text-center"
            animate={{ scale: i === active ? 1.06 : 1, opacity: i === active ? 1 : 0.55 }}
            style={{ background: 'var(--muted)', borderColor: i === active ? 'var(--primary)' : 'var(--border)' }}
          >
            <p style={{ fontSize: 20 }}>{s.icon}</p>
            <p className="text-foreground font-semibold mt-0.5" style={{ fontSize: 10.5, lineHeight: 1.25 }}>{s.label}</p>
          </motion.div>
          {i < steps.length - 1 && <ChevronRight className="w-3 h-3 text-muted-foreground shrink-0" />}
        </div>
      ))}
    </div>
  );
}

// --- 2. Reading a price, and what trade size costs ---------------------------------------------------------------
function SpreadDemo() {
  const LISTED = 50;
  const FEE = 0.0025;
  const sizes = [1, 10, 100, 500];
  const [qty, setQty] = useState(10);
  // Illustrative: the House's price worsens with order size (see the Guide), on top of a tiny base gap.
  const half = 0.005 + Math.min(0.25, (0.15 * qty) / 1000);
  const buy = LISTED * (1 + half);
  const sell = LISTED * (1 - half);
  const roundTrip = buy * qty * (1 + FEE) - sell * qty * (1 - FEE);
  return (
    <div>
      <div className="flex gap-1.5 mb-2 items-center">
        <span className="text-muted-foreground" style={{ fontSize: 11 }}>Shares:</span>
        {sizes.map(s => <Chip key={s} active={qty === s} onClick={() => setQty(s)}>{s}</Chip>)}
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Card className="p-2 text-center">
          <p className="text-muted-foreground uppercase" style={{ fontSize: 9.5, letterSpacing: '0.05em' }}>Sell price</p>
          <p className="font-mono font-bold" style={{ fontSize: 15, color: LOSS }}>{money(sell, 2)}</p>
        </Card>
        <Card className="p-2 text-center">
          <p className="text-muted-foreground uppercase" style={{ fontSize: 9.5, letterSpacing: '0.05em' }}>Listed</p>
          <p className="font-mono font-bold text-foreground" style={{ fontSize: 15 }}>{money(LISTED, 2)}</p>
        </Card>
        <Card className="p-2 text-center">
          <p className="text-muted-foreground uppercase" style={{ fontSize: 9.5, letterSpacing: '0.05em' }}>Buy price</p>
          <p className="font-mono font-bold" style={{ fontSize: 15, color: GAIN }}>{money(buy, 2)}</p>
        </Card>
      </div>
      <p className="text-muted-foreground mt-2" style={{ fontSize: 12, lineHeight: 1.5 }}>
        Buy {qty} and instantly sell them back and you would lose about{' '}
        <strong style={{ color: LOSS }}>{money(roundTrip, 2)}</strong> to the gap and fees. Trading is for conviction, not for churning.
      </p>
      <Caption>Illustrative numbers. The gap grows with order size; limit orders let you skip it.</Caption>
    </div>
  );
}

// --- 3. Limit vs quick ----------------------------------------------------------------------------------------------
function TradeTypeDemo() {
  const [mode, setMode] = useState<'limit' | 'quick'>('limit');
  return (
    <div>
      <div className="flex gap-1.5 mb-2">
        <Chip active={mode === 'limit'} onClick={() => setMode('limit')}>Limit order</Chip>
        <Chip active={mode === 'quick'} onClick={() => setMode('quick')}>⚡ Quick trade</Chip>
      </div>
      <AnimatePresence mode="wait">
        <motion.div key={mode} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.12 }}>
          {mode === 'limit' ? (
            <Card className="p-3">
              <div className="flex items-center justify-between">
                <span className="text-foreground font-semibold" style={{ fontSize: 12.5 }}>Buy 20 @ $49.50</span>
                <span className="px-2 py-0.5 rounded-full font-bold" style={{ fontSize: 10, background: 'rgba(251,191,36,0.15)', color: '#fbbf24' }}>Resting on the book</span>
              </div>
              <p className="text-muted-foreground mt-1.5" style={{ fontSize: 12, lineHeight: 1.5 }}>
                You name the price and wait in line. It may fill later, partly, or never. You can cancel any time, or give it a time limit so it cancels itself. If it rests and someone trades into it, you pay no fee.
              </p>
            </Card>
          ) : (
            <Card className="p-3">
              <div className="flex items-center justify-between">
                <span className="text-foreground font-semibold" style={{ fontSize: 12.5 }}>Buy 20 now</span>
                <span className="px-2 py-0.5 rounded-full font-bold" style={{ fontSize: 10, background: 'rgba(16,217,160,0.15)', color: GAIN }}>Filled instantly</span>
              </div>
              <p className="text-muted-foreground mt-1.5" style={{ fontSize: 12, lineHeight: 1.5 }}>
                You take the best price available right now, even if you must pay the Buy price. Instant, certain, and you pay a 0.25% fee.
              </p>
            </Card>
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

// --- 4. Dividend calculator ----------------------------------------------------------------------------------------
function DividendCalc() {
  const POOL = 300_000; // a Cash Cup's dividend pool
  const SHARES_OUT = 100_000; // example player
  const places = [
    { label: '1st', pct: 0.2 },
    { label: '2nd', pct: 0.13 },
    { label: '5th', pct: 0.06 },
    { label: '12th', pct: 0.025 },
  ];
  const [pi, setPi] = useState(0);
  const [mine, setMine] = useState(1000);
  const perShare = (POOL * places[pi].pct) / SHARES_OUT;
  const payout = perShare * mine;
  return (
    <div>
      <div className="flex gap-1.5 mb-2 items-center">
        <span className="text-muted-foreground" style={{ fontSize: 11 }}>Your player finishes:</span>
        {places.map((p, i) => <Chip key={p.label} active={pi === i} onClick={() => setPi(i)}>{p.label}</Chip>)}
      </div>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-muted-foreground shrink-0" style={{ fontSize: 11 }}>You own:</span>
        <input
          type="range" min={100} max={5000} step={100} value={mine}
          onChange={e => setMine(Number(e.target.value))}
          className="flex-1"
          style={{ accentColor: 'var(--primary)' }}
          aria-label="Shares you own"
        />
        <span className="font-mono font-bold text-foreground w-20 text-right" style={{ fontSize: 12 }}>{mine.toLocaleString('en-US')} sh</span>
      </div>
      <Card className="p-3 flex items-center gap-3">
        <div className="flex-1">
          <p className="text-foreground font-semibold" style={{ fontSize: 12.5 }}>{places[pi].label} place in a Cash Cup</p>
          <p className="text-muted-foreground" style={{ fontSize: 10.5 }}>
            {money(POOL * places[pi].pct)} to the player's shareholders = {money(perShare, 2)} per share
          </p>
        </div>
        <motion.span
          key={`${pi}-${mine}`}
          initial={{ scale: 1.15 }} animate={{ scale: 1 }}
          className="font-mono font-bold px-2.5 py-1.5 rounded-lg"
          style={{ fontSize: 15, background: 'rgba(16,217,160,0.15)', color: GAIN }}
        >
          +{money(payout, 2)}
        </motion.span>
      </Card>
      <Caption>Example: a Cash Cup pool of $300,000 and a player with 100,000 shares. Bigger events have bigger pools, and every player's page shows their real numbers.</Caption>
    </div>
  );
}

// --- 5. Record-date quiz -------------------------------------------------------------------------------------------
function RecordDateQuiz() {
  const options = [
    { id: 'before', label: 'I buy before it starts', paid: true, why: 'Paid. You held shares when it started.' },
    { id: 'after', label: 'I buy after it starts', paid: false, why: 'Not paid. You were not a shareholder at the start.' },
    { id: 'sell', label: 'I sell after it starts', paid: true, why: 'Still paid. You held them when it started, so you keep that dividend.' },
  ];
  const [picked, setPicked] = useState<string | null>(null);
  const chosen = options.find(o => o.id === picked);
  return (
    <div>
      <div className="relative h-7 mb-3">
        <div className="absolute left-0 right-0 top-3 h-1 rounded-full" style={{ background: 'var(--border)' }} />
        <div className="absolute left-0 top-3 h-1 rounded-full" style={{ width: '45%', background: 'linear-gradient(90deg, transparent, var(--primary))' }} />
        <div className="absolute top-0 -translate-x-1/2 flex flex-col items-center" style={{ left: '45%' }}>
          <span className="px-2 py-0.5 rounded-full font-bold" style={{ fontSize: 9.5, background: 'rgba(251,191,36,0.2)', color: '#fbbf24' }}>EVENT STARTS</span>
        </div>
      </div>
      <p className="text-foreground font-semibold mb-1.5" style={{ fontSize: 12.5 }}>Do you get this event's dividend if...</p>
      <div className="space-y-1.5">
        {options.map(o => (
          <button
            key={o.id}
            onClick={() => setPicked(o.id)}
            className="w-full flex items-center justify-between px-3 py-2 rounded-xl text-left transition-colors"
            style={{
              fontSize: 12.5,
              background: picked === o.id ? 'rgba(0,200,255,0.1)' : 'var(--muted)',
              border: `1px solid ${picked === o.id ? 'var(--primary)' : 'var(--border)'}`,
              color: 'var(--foreground)',
            }}
          >
            {o.label}
            {picked === o.id && (o.paid ? <Check className="w-4 h-4" style={{ color: GAIN }} /> : <X className="w-4 h-4" style={{ color: LOSS }} />)}
          </button>
        ))}
      </div>
      <p className="mt-2" style={{ fontSize: 12, minHeight: 34, lineHeight: 1.45, color: chosen ? (chosen.paid ? GAIN : LOSS) : 'var(--muted-foreground)' }}>
        {chosen ? chosen.why : 'Tap one. Only shareholders at the start are paid.'}
      </p>
    </div>
  );
}

// --- 6. Bots --------------------------------------------------------------------------------------------------------
function BotsSnip() {
  const reads = ['Tournament earnings, last 12 months', 'How they have placed lately', 'Upcoming events (holders at the start get paid)', 'Missed qualifiers'];
  return (
    <Card className="p-3">
      <p className="text-muted-foreground uppercase font-bold mb-1.5" style={{ fontSize: 9.5, letterSpacing: '0.05em' }}>What the bots look at</p>
      <div className="space-y-1.5">
        {reads.map((r, i) => (
          <motion.div key={r} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.08 * i }} className="flex items-center gap-2">
            <span className="w-4 h-4 rounded-full flex items-center justify-center shrink-0" style={{ background: 'rgba(0,200,255,0.15)' }}>
              <Check className="w-2.5 h-2.5" style={{ color: 'var(--primary)' }} />
            </span>
            <span className="text-foreground" style={{ fontSize: 12 }}>{r}</span>
          </motion.div>
        ))}
      </div>
      <p className="text-muted-foreground mt-2 pt-2" style={{ fontSize: 11, borderTop: '1px solid var(--border)' }}>
        Bots are never on the leaderboard. They are the market you are trying to beat.
      </p>
    </Card>
  );
}

// --- 7. Beat the market -----------------------------------------------------------------------------------------------
function BeatMarketSnip() {
  const { pct } = useBenchmarkPct();
  const base = parseFloat(pct) || 10;
  const bars = [
    { label: 'The market', width: 55, value: `${pct} / yr`, color: 'rgba(255,255,255,0.35)' },
    { label: 'You, if you are good', width: 90, value: 'more?', color: 'var(--primary)' },
  ];
  return (
    <Card className="p-3 space-y-2.5">
      {bars.map((b, i) => (
        <div key={b.label}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-foreground font-semibold" style={{ fontSize: 12 }}>{b.label}</span>
            <span className="font-mono font-bold" style={{ fontSize: 12, color: i === 0 ? 'var(--foreground)' : 'var(--primary)' }}>{b.value}</span>
          </div>
          <div className="h-2.5 rounded-full" style={{ background: 'var(--border)' }}>
            <motion.div
              className="h-2.5 rounded-full"
              initial={{ width: 0 }}
              animate={{ width: `${b.width}%` }}
              transition={{ duration: 0.8, delay: 0.15 * i, ease: 'easeOut' }}
              style={{ background: b.color }}
            />
          </div>
        </div>
      ))}
      <Caption>Illustrative. Your own return shows up on My Stats; the market's {base.toFixed(1)}% is the bar to clear.</Caption>
    </Card>
  );
}

// --- 8. First moves --------------------------------------------------------------------------------------------------
function FirstMoves({ onNavigate, onOpenGuide, done }: { onNavigate?: (p: string) => void; onOpenGuide?: () => void; done: () => void }) {
  const moves: { icon: string; title: string; sub: string; run?: () => void }[] = [
    { icon: '📈', title: 'Browse the market', sub: 'Open a player to see their record and price', run: onNavigate ? () => { onNavigate('markets'); done(); } : undefined },
    { icon: '⚡', title: 'See upcoming events', sub: 'Buy before a tournament starts to earn its dividend', run: onNavigate ? () => { onNavigate('tournaments'); done(); } : undefined },
    { icon: '📖', title: 'Open the full Guide', sub: 'Every page, number and term explained', run: onOpenGuide ? () => { onOpenGuide(); } : undefined },
  ].filter(m => m.run);
  if (moves.length === 0) return null;
  return (
    <div className="space-y-1.5">
      {moves.map(m => (
        <button
          key={m.title}
          onClick={m.run}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left transition-colors hover:bg-white/[0.06]"
          style={{ background: 'var(--muted)', border: '1px solid var(--border)' }}
        >
          <span style={{ fontSize: 20 }}>{m.icon}</span>
          <span className="flex-1">
            <span className="block text-foreground font-semibold" style={{ fontSize: 13 }}>{m.title}</span>
            <span className="block text-muted-foreground" style={{ fontSize: 11 }}>{m.sub}</span>
          </span>
          <ChevronRight className="w-4 h-4 text-muted-foreground" />
        </button>
      ))}
    </div>
  );
}

interface Slide {
  emoji: string;
  title: string;
  body: ReactNode;
  visual: (p: { onNavigate?: (p: string) => void; onOpenGuide?: () => void; done: () => void }) => ReactNode;
  cta?: string; // label of the main button on this slide (default "Next")
}

const SLIDES: Slide[] = [
  {
    emoji: '🎮',
    title: 'Welcome to Forecast',
    body: 'Every pro Fortnite player is a stock. Buy the ones you believe in, collect cash when they win, and try to end up with more money than anyone. It takes about a minute to learn, and you can skip any time.',
    visual: () => <FlowSnip />,
    cta: 'Show me around',
  },
  {
    emoji: '🔎',
    title: 'Reading a price',
    body: 'Each player has a Buy price (what one share costs) and a Sell price (what it fetches). The listed price is the last trade, kept between the two. Try different sizes.',
    visual: () => <SpreadDemo />,
  },
  {
    emoji: '🎯',
    title: 'Two ways to trade',
    body: 'Set your own price and wait, or take the market price instantly. Tap each one.',
    visual: () => <TradeTypeDemo />,
  },
  {
    emoji: '💰',
    title: 'Dividends: how you get paid',
    body: 'When a player you own places well, everyone who holds shares of that player is paid. Slide your holding and pick a finish to see the cash.',
    visual: () => <DividendCalc />,
  },
  {
    emoji: '⏱️',
    title: 'The one rule to remember',
    body: 'Dividends go to whoever owns shares when the tournament starts. Test yourself.',
    visual: () => <RecordDateQuiz />,
  },
  {
    emoji: '🤖',
    title: 'You are trading against bots too',
    body: 'Not everyone here is a person. Bot traders run on algorithms that weigh a player’s recent form and long-term record, so there is always someone to trade with. They follow the same rules, see only public information, and are not ranked.',
    visual: () => <BotsSnip />,
  },
  {
    emoji: '🚀',
    title: 'Beat the market',
    body: <BenchmarkText />,
    visual: () => <BeatMarketSnip />,
  },
  {
    emoji: '🏁',
    title: 'Your first moves',
    body: 'One leaderboard, real players only, most money wins. Pick a start, or jump into the Guide any time from the sidebar.',
    visual: p => <FirstMoves {...p} />,
    cta: "Let's go",
  },
];

export function IntroTour({ onClose, initialStep = 0, storageKey, onNavigate, onOpenGuide }: Props) {
  const [step, setStep] = useState(() => Math.min(Math.max(initialStep, 0), SLIDES.length - 1));
  const last = step === SLIDES.length - 1;
  const slide = SLIDES[step];

  function finish() {
    try { localStorage.setItem(storageKey, '1'); } catch { /* ignore -- storage may be unavailable */ }
    onClose();
  }

  // Keyboard: arrows to move, Esc to leave. Never traps the user.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') finish();
      else if (e.key === 'ArrowRight') setStep(s => Math.min(s + 1, SLIDES.length - 1));
      else if (e.key === 'ArrowLeft') setStep(s => Math.max(s - 1, 0));
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(6px)' }}
      onClick={e => { if (e.target === e.currentTarget) finish(); }}
    >
      <motion.div
        className="w-full rounded-2xl border border-border overflow-hidden flex flex-col"
        style={{ background: 'var(--card)', maxWidth: 480, maxHeight: '94vh' }}
        initial={{ opacity: 0, scale: 0.95, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        {/* progress bar: always shows how little is left */}
        <div className="h-1 w-full" style={{ background: 'var(--border)' }}>
          <motion.div className="h-1" animate={{ width: `${((step + 1) / SLIDES.length) * 100}%` }} transition={{ duration: 0.25 }} style={{ background: 'linear-gradient(90deg, var(--primary), var(--accent))' }} />
        </div>

        <div className="px-6 pt-4 pb-1 flex items-center justify-between shrink-0">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full font-bold uppercase" style={{ fontSize: 10, background: 'rgba(0,200,255,0.12)', color: 'var(--primary)' }}>
            <Sparkles className="w-3 h-3" /> Quick tour · {step + 1}/{SLIDES.length}
          </span>
          <div className="flex items-center gap-1">
            {!last && (
              <button onClick={finish} className="px-2 py-1 rounded-lg font-semibold text-muted-foreground hover:text-foreground hover:bg-white/10 transition-colors" style={{ fontSize: 12 }}>
                Skip tour
              </button>
            )}
            <button onClick={finish} aria-label="Close" className="p-1.5 rounded-lg hover:bg-white/10 transition-colors">
              <X className="w-4 h-4 text-muted-foreground" />
            </button>
          </div>
        </div>

        <div className="overflow-y-auto">
          <AnimatePresence mode="wait">
            <motion.div
              key={step}
              initial={{ opacity: 0, x: 12 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -12 }}
              transition={{ duration: 0.15 }}
              className="px-6 pb-2"
            >
              <p style={{ fontSize: 32 }}>{slide.emoji}</p>
              <h2 className="text-foreground font-bold mt-1" style={{ fontSize: 19 }}>{slide.title}</h2>
              <p className="text-muted-foreground mt-1.5 mb-4" style={{ fontSize: 13.5, lineHeight: 1.6 }}>{slide.body}</p>
              {slide.visual({ onNavigate, onOpenGuide, done: finish })}
            </motion.div>
          </AnimatePresence>
        </div>

        <div className="px-6 pt-3 pb-5 shrink-0">
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
              <button onClick={finish} className="px-3 py-2.5 rounded-xl font-semibold transition-colors hover:bg-white/[0.06]" style={{ fontSize: 13, color: 'var(--muted-foreground)', border: '1px solid var(--border)' }}>
                Skip
              </button>
            )}
            <button
              onClick={() => (last ? finish() : setStep(s => s + 1))}
              className="flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-xl font-bold transition-opacity hover:opacity-90"
              style={{ fontSize: 14, background: 'linear-gradient(135deg, var(--primary), var(--accent))', color: '#fff' }}
            >
              {last ? (
                <>{slide.cta ?? "Let's go"} <ArrowUpRight className="w-4 h-4" /></>
              ) : (
                <>{slide.cta ?? 'Next'} <ChevronRight className="w-4 h-4" /></>
              )}
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
