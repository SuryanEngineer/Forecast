// A deep-dive reference for a single topic, opened from a small "ⓘ" info
// button dropped next to whatever UI it explains. Deliberately more
// thorough than IntroTour (which is a one-time, breezy 5-slide welcome
// tour) -- this is the "actually tell me exactly how the numbers work"
// version, meant to be reopened any time from any page.
//
// Every number quoted in HELP_TOPICS below is pulled from the REAL
// forecast-backend's actual economic parameters (see
// forecast-backend/app/services/economic_params_service.py and
// app/engine/dividend_calculator.py / quick_trade_pricing.py), NOT from
// ForecastDemo's in-browser engine -- the two copies' numbers differ in
// a few places (e.g. quick-trade pricing is a flat +/-10% premium in the
// demo but a market-impact/slippage model here), so this file was
// rewritten to match this app's real backend rather than translated
// verbatim from the demo. If those backend defaults ever change, this
// copy should be updated alongside them.
import { useState, type ReactNode } from 'react';
import { HelpCircle, X } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

export type HelpTopicId = 'orders' | 'dividends' | 'tournaments' | 'rankings' | 'portfolio' | 'market';

interface HelpSection {
  heading: string;
  body: ReactNode;
}

interface HelpTopic {
  emoji: string;
  title: string;
  intro: string;
  sections: HelpSection[];
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between px-3 py-2 rounded-lg" style={{ background: 'var(--muted)' }}>
      <span className="text-muted-foreground" style={{ fontSize: 12 }}>{label}</span>
      <span className="font-mono font-bold text-foreground" style={{ fontSize: 12.5 }}>{value}</span>
    </div>
  );
}

function List({ items }: { items: ReactNode[] }) {
  return (
    <ul className="space-y-1.5 mt-1.5">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2" style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--muted-foreground)' }}>
          <span style={{ color: 'var(--primary)' }}>•</span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

export const HELP_TOPICS: Record<HelpTopicId, HelpTopic> = {
  orders: {
    emoji: '🎯',
    title: 'How Trading Works',
    intro: 'Every player has an order book -- a live list of resting buy and sell orders. There are two ways to trade against it.',
    sections: [
      {
        heading: 'Limit orders (the order book)',
        body: (
          <>
            <p>A limit order names your own price and rests on the book until another trader's order crosses it. Buy orders are
            sorted highest price first, sell orders lowest price first; within the same price, whoever placed their order first
            gets filled first.</p>
            <List
              items={[
                'You can cancel an open (or partially filled) limit order any time before it fully fills.',
                'A limit order can sit unfilled indefinitely if the market never reaches your price -- there’s no guarantee of a fill.',
                'The person whose resting order gets crossed (the "maker") pays no fee at all.',
              ]}
            />
          </>
        ),
      },
      {
        heading: 'Quick trade (instant, priced by liquidity)',
        body: (
          <>
            <p>Quick Buy/Sell fills immediately by first eating through whatever the order book can actually offer at the best
            available prices. For any quantity the book can't cover, the rest fills synthetically against the exchange's own
            liquidity -- priced worse the larger your order is relative to how much liquidity that player currently has, the
            same way a real illiquid stock's price moves against a large market order.</p>
            <List
              items={[
                'Small quick trades on a liquid player barely move the price; large trades on a thin market move it more.',
                'This is a documented placeholder pricing model pending further tuning -- see quick_trade_pricing.py in the backend.',
                'Use it when you need a fill right now and don’t want to wait on the book.',
              ]}
            />
          </>
        ),
      },
      {
        heading: 'Fees',
        body: (
          <div className="space-y-1.5">
            <p>Only the "taker" -- whoever’s order actually crosses and executes, whether that’s a limit order that
            crosses the book or a quick trade -- pays a transaction fee, charged once on the total value of everything that
            order fills.</p>
            <Fact label="Transaction fee (taker only)" value="0.25%" />
            <Fact label="Price floor" value="$0.01 / share" />
          </div>
        ),
      },
    ],
  },
  dividends: {
    emoji: '💰',
    title: 'How Dividends Work',
    intro: 'When a player you own shares in places well in a tournament, real cash flows to every current shareholder -- split proportionally by how many shares they hold.',
    sections: [
      {
        heading: 'Where the money comes from',
        body: (
          <div className="space-y-1.5">
            <p>Cash Cup, FNCS, and Global Championship tournaments each draw from their own fixed dividend pool. Other
            tournament types use whichever prize pool an admin entered for that specific event:</p>
            <Fact label="Cash Cup pool" value="$300,000" />
            <Fact label="FNCS Qualifier / Finals pool" value="$1,500,000" />
            <Fact label="Global Championship pool" value="$3,000,000" />
          </div>
        ),
      },
      {
        heading: 'How placement decides the payout',
        body: (
          <>
            <p>Each placement is worth a fixed slice of that tournament’s pool -- 1st place earns 20% of it, 2nd earns
            13%, 3rd earns 10%, tapering down through 12th place at 2.5%. Placements past 12th still earn a real (if
            small) share -- the payout keeps gently tapering off rather than dropping to zero, so even a lower finish in a
            big tournament is worth something.</p>
            <p className="mt-1.5">That placement’s dollar amount is then divided evenly across every share of that player
            outstanding, giving a per-share dividend rate. You get paid <strong>(shares you hold) × (per-share rate)</strong>.
            Own more shares of a player who does well, earn proportionally more.</p>
          </>
        ),
      },
      {
        heading: 'The record date -- this part matters',
        body: (
          <p>You’re paid based on the shares you hold at the moment the tournament’s results are finalized, not
          whatever you held during the event itself. That means buying shares before results are entered still qualifies
          you for the full dividend -- but it also means selling right before results land forfeits it, even if you held
          through the whole tournament. Buy ahead of big events you’re confident about; don’t sell right before
          results come in if you want the payout.</p>
        ),
      },
    ],
  },
  tournaments: {
    emoji: '🏆',
    title: 'How Tournaments Work',
    intro: 'Tournament results are entered by an admin once they\'re known -- either manually, or automatically synced from live Osirion data for tracked events.',
    sections: [
      {
        heading: 'Where results come from',
        body: (
          <p>Some tournaments are linked to a real, live Fortnite competitive event via Osirion -- for those, standings sync in
          automatically while the event is running (see the "● LIVE" badge and "updated Xs ago" label wherever you see one).
          Everything else is entered by an admin once results are known. Either way, once a tournament is finalized, its
          placements and dividend payouts are locked in and won't change.</p>
        ),
      },
      {
        heading: 'What "placement" means here',
        body: (
          <p>Whatever placement a player actually earned in the real tournament -- this exchange doesn't simulate lobbies or
          run its own bracket. A tournament's format (solos, duos, trios, or anything else) is just whatever the real event
          actually was; this app only tracks the outcome (who placed where), not the format itself.</p>
        ),
      },
      {
        heading: 'Types and how often they happen',
        body: (
          <p>Cash Cups run most often, FNCS Qualifiers and Finals less frequently, and a Global Championship is rare --
          matching the real competitive calendar’s cadence. Bigger, rarer tournament types carry proportionally larger
          prize pools (see the Dividends help for the exact numbers), so they matter more to your portfolio when they land.</p>
        ),
      },
    ],
  },
  rankings: {
    emoji: '📊',
    title: 'How Rankings Work',
    intro: 'The leaderboard ranks every investor by total portfolio value -- there’s no separate "skill score," just how much your account is worth right now.',
    sections: [
      {
        heading: 'What counts toward your rank',
        body: (
          <p><strong>Portfolio value = cash balance + the current market value of every share you hold</strong>, valued at
          each player’s most recent trade price. It updates continuously as prices move and as you (or anyone) trades --
          there’s no lag or daily snapshot, your rank reflects this exact moment.</p>
        ),
      },
      {
        heading: 'Tap anyone to see their team',
        body: <p>Every row on the leaderboard is clickable -- tap any investor to see a summary of their standing: rank, cash
        balance, holdings value, and total portfolio value.</p>,
      },
    ],
  },
  portfolio: {
    emoji: '💼',
    title: 'Understanding Your Portfolio',
    intro: 'Your portfolio combines cash you haven’t invested with the current value of every player you hold shares in.',
    sections: [
      {
        heading: 'Portfolio value',
        body: (
          <p><strong>Cash balance + holdings value</strong> (each holding valued at that player’s current price × shares
          you own). This is the same number used for your Rankings position -- moving cash into shares doesn’t change
          your portfolio value by itself, only price movement, dividends, and trading costs do.</p>
        ),
      },
      {
        heading: 'Gain / loss on a holding',
        body: (
          <p>Shown per player as the difference between what those shares are worth now versus what you originally paid for
          them (your cost basis) -- it’s unrealized until you actually sell, so it moves with the live price.</p>
        ),
      },
    ],
  },
  market: {
    emoji: '📈',
    title: 'Reading the Market',
    intro: 'Every price on this exchange is a real trade price -- there’s no hidden "true value" a player is supposed to be worth.',
    sections: [
      {
        heading: 'Where prices come from',
        body: (
          <p>A player’s price is simply the price of their most recent executed trade -- whether that trade came from
          you, another trader, or a resting order finally getting crossed. There’s no separate valuation model
          running underneath; the market price <em>is</em> the last trade, exactly like a real stock ticker.</p>
        ),
      },
      {
        heading: 'Why prices move',
        body: (
          <List
            items={[
              'Buying pressure (more/larger buy orders crossing the book) pushes price up; selling pressure pushes it down.',
              'A strong tournament placement drives real demand for that player’s shares -- and a bad one often triggers selling.',
            ]}
          />
        ),
      },
      {
        heading: 'The live feed',
        body: <p>Open "Live Activity" to see recent trades as they happen across the market -- a running pulse of activity instead of one abstract aggregate chart.</p>,
      },
    ],
  },
};

function HelpModal({ topicId, onClose }: { topicId: HelpTopicId; onClose: () => void }) {
  const topic = HELP_TOPICS[topicId];
  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(6px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <motion.div
        className="w-full rounded-2xl border border-border flex flex-col"
        style={{ background: 'var(--card)', maxWidth: 520, maxHeight: '85vh' }}
        initial={{ opacity: 0, scale: 0.95, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        <div className="px-6 pt-5 pb-4 flex items-start justify-between shrink-0 border-b border-border">
          <div className="flex items-center gap-3">
            <span style={{ fontSize: 28 }}>{topic.emoji}</span>
            <div>
              <h2 className="text-foreground font-bold" style={{ fontSize: 18 }}>{topic.title}</h2>
              <p className="text-muted-foreground mt-0.5" style={{ fontSize: 12.5, lineHeight: 1.5, maxWidth: 380 }}>{topic.intro}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/10 transition-colors shrink-0">
            <X className="w-4 h-4 text-muted-foreground" />
          </button>
        </div>

        <div className="px-6 py-5 overflow-y-auto space-y-5">
          {topic.sections.map((section, i) => (
            <div key={i}>
              <p className="font-bold uppercase tracking-wide" style={{ fontSize: 10.5, color: 'var(--primary)' }}>{section.heading}</p>
              <div className="mt-1.5" style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--foreground)' }}>{section.body}</div>
            </div>
          ))}
        </div>

        <div className="px-6 py-4 border-t border-border shrink-0">
          <button
            onClick={onClose}
            className="w-full py-2.5 rounded-xl font-bold transition-opacity hover:opacity-90"
            style={{ fontSize: 14, background: 'linear-gradient(135deg, var(--primary), var(--accent))', color: '#fff' }}
          >
            Got it
          </button>
        </div>
      </motion.div>
    </div>
  );
}

interface HelpButtonProps {
  topic: HelpTopicId;
  size?: number;
  title?: string;
  className?: string;
}

/** A small "ⓘ" trigger to drop next to any label/section that could use a
 * deep-dive explanation. Self-contained -- owns its own open/closed state
 * and renders its own modal, so it can be dropped in anywhere with zero
 * wiring from the parent. */
export function HelpButton({ topic, size = 15, title, className = '' }: HelpButtonProps) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(true); }}
        title={title ?? `Learn more: ${HELP_TOPICS[topic].title}`}
        className={`inline-flex items-center justify-center rounded-full text-muted-foreground hover:text-foreground transition-colors shrink-0 ${className}`}
        style={{ width: size + 6, height: size + 6 }}
      >
        <HelpCircle style={{ width: size, height: size }} />
      </button>
      <AnimatePresence>
        {open && <HelpModal topicId={topic} onClose={() => setOpen(false)} />}
      </AnimatePresence>
    </>
  );
}
