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
import { BadgeCheck, HelpCircle, X } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

export type HelpTopicId = 'orders' | 'dividends' | 'tournaments' | 'rankings' | 'portfolio' | 'market' | 'verified';

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
    intro: 'Every player has a live order book of resting buy and sell orders. You can trade against it in two ways: place a limit order at a price of your choosing, or use a quick trade to fill immediately.',
    sections: [
      {
        heading: 'Limit orders',
        body: (
          <>
            <p>A limit order sets the exact price you are willing to pay or accept, and rests on the book until another
            trader’s order meets it. Buy orders are ranked from the highest price down and sell orders from the lowest price
            up. At the same price, the order placed first is filled first.</p>
            <List
              items={[
                'You can cancel an open or partially filled limit order at any time before it completes.',
                'A limit order is not guaranteed to fill. If the market never reaches your price, it will remain open.',
                'The trader whose resting order is matched (the “maker”) pays no transaction fee.',
              ]}
            />
          </>
        ),
      },
      {
        heading: 'Quick trades',
        body: (
          <>
            <p>A quick trade executes immediately. It first takes the best prices available on the order book, and any
            remaining quantity is filled against the exchange’s own liquidity. The larger your order relative to a player’s
            available liquidity, the further the average fill price moves against you.</p>
            <List
              items={[
                'Small quick trades in an active market barely move the price; large trades in a thin market move it more.',
                'Choose a quick trade when speed matters more than securing a specific price.',
              ]}
            />
          </>
        ),
      },
      {
        heading: 'Fees',
        body: (
          <div className="space-y-1.5">
            <p>Only the “taker” pays a fee: the trader whose order executes against the book, whether through a limit order
            that crosses it or a quick trade. The fee is charged once, on the total value of that order’s fills.</p>
            <Fact label="Transaction fee (taker only)" value="0.25%" />
            <Fact label="Minimum share price" value="$0.01" />
          </div>
        ),
      },
    ],
  },
  dividends: {
    emoji: '💰',
    title: 'How Dividends Work',
    intro: 'When a player you own performs well in a tournament, a cash dividend is distributed to everyone who held that player’s shares when the event began, in proportion to the number of shares they own.',
    sections: [
      {
        heading: 'Where the money comes from',
        body: (
          <div className="space-y-1.5">
            <p>Cash Cup, FNCS, and Global Championship events each pay from a fixed dividend pool, scaled by region. Other
            event types use the prize pool recorded for that specific tournament.</p>
            <Fact label="Cash Cup pool" value="$300,000" />
            <Fact label="FNCS Qualifier / Finals pool" value="$1,500,000" />
            <Fact label="Global Championship pool" value="$3,000,000" />
          </div>
        ),
      },
      {
        heading: 'How placement sets the payout',
        body: (
          <>
            <p>Each finishing position earns a fixed share of the tournament’s pool: 1st place receives 20%, 2nd receives
            13%, 3rd receives 10%, and the share tapers gradually through 12th place at 2.5%. Positions beyond 12th continue
            to earn a smaller, steadily declining share, so a deep run in a large field is still rewarded.</p>
            <p className="mt-1.5">A team event’s result applies to every player on the team. Each player’s payout is
            divided across all outstanding shares of that player to produce a per-share rate, and you receive{' '}
            <strong>(shares you hold) × (per-share rate)</strong>.</p>
          </>
        ),
      },
      {
        heading: 'The record date',
        body: (
          <p>Dividends are paid to the shareholders of record at the moment a tournament <strong>starts</strong>. Shares
          bought after the start do not qualify for that event, and shares sold after the start still do. To earn a
          dividend, buy before the tournament begins.</p>
        ),
      },
    ],
  },
  tournaments: {
    emoji: '🏆',
    title: 'How Tournaments Work',
    intro: 'Forecast follows the official competitive Fortnite calendar. Results are synced from live tournament data, so standings update automatically while an event is in progress.',
    sections: [
      {
        heading: 'Where results come from',
        body: (
          <p>Tracked events are linked to live competitive data. Standings refresh automatically during play (look for the
          “LIVE” badge and the “updated” timestamp). Once a tournament is finalized, its placements and dividend payouts are
          permanent.</p>
        ),
      },
      {
        heading: 'Regions and event names',
        body: (
          <p>NAC and EU events frequently run on the same dates with the same format, so their names begin with the
          region: “NAC” or “EU”. LAN and global events, such as the Global Championship, draw players from every region and
          carry no regional prefix.</p>
        ),
      },
      {
        heading: 'Placements and game-by-game results',
        body: (
          <p>A placement is the official finishing position in the real event. Open any tournament to see team standings,
          each team’s payout, and the results of every individual game, including eliminations, time alive, and damage
          dealt and taken.</p>
        ),
      },
      {
        heading: 'Event types',
        body: (
          <p>Cash Cups are the most frequent events, FNCS Qualifiers and Finals occur less often, and the Global
          Championship is the rarest. Larger events carry larger dividend pools, so they have the greatest impact on your
          portfolio. See the Dividends guide for exact figures.</p>
        ),
      },
    ],
  },
  rankings: {
    emoji: '📊',
    title: 'How Rankings Work',
    intro: 'There are two leaderboards: a Seasonal ladder that resets every Fortnite season, and an All-Time board that never resets.',
    sections: [
      {
        heading: 'Seasonal Points & ranks',
        body: (
          <>
            <p>Every season you start at <strong>0 Seasonal Points (SP)</strong>. Your SP tracks how much your portfolio has grown
            relative to what it was worth when the season began: <strong>+1% return = +100 SP</strong>. If your portfolio loses money
            your SP — and your rank — drops back down (SP never goes below 0).</p>
            <p>Ranks: Bronze I–III, Gold I–III, Diamond I–III, then Unreal. When the season ends your final rank is saved to your
            profile and everyone starts the next season fresh.</p>
          </>
        ),
      },
      {
        heading: 'All-Time board',
        body: (
          <p><strong>Net worth = cash + the current market value of every share you hold</strong> (each valued at its player’s
          latest trade price) plus any treasury holdings. It never resets.</p>
        ),
      },
      {
        heading: 'View any investor’s team',
        body: <p>Select any row on the leaderboard to see that investor’s holdings and portfolio value.</p>,
      },
    ],
  },
  portfolio: {
    emoji: '💼',
    title: 'Understanding Your Portfolio',
    intro: 'Your portfolio combines your uninvested cash with the current value of every player you hold shares in.',
    sections: [
      {
        heading: 'Portfolio value',
        body: (
          <p><strong>Cash balance + holdings value</strong>, where each holding is its player’s current price multiplied by
          the number of shares you own. This is the figure used for your ranking. Moving cash into shares does not change
          your portfolio value on its own; only price movement, dividends, and trading fees do.</p>
        ),
      },
      {
        heading: 'Gain and loss',
        body: (
          <p>For each holding, gain or loss is the difference between what your shares are worth now and what you paid for
          them (your cost basis). It is unrealized until you sell, so it moves with the live price.</p>
        ),
      },
    ],
  },
  market: {
    emoji: '📈',
    title: 'Reading the Market',
    intro: 'Every price on the exchange is a real trade price set by buyers and sellers. There is no hidden “true value” behind a player.',
    sections: [
      {
        heading: 'Where prices come from',
        body: (
          <p>A player’s price is the price of their most recent executed trade, kept inside the current order book: if
          buyers are bidding above the last trade the price moves up to the highest bid, and if sellers are asking below it
          the price moves down to the lowest ask. It is not set by a model or by the platform.</p>
        ),
      },
      {
        heading: 'Why prices move',
        body: (
          <List
            items={[
              'Buying pressure pushes a price up, and selling pressure pushes it down.',
              'Strong tournament finishes raise expected dividends and tend to attract buyers; weak finishes tend to attract sellers.',
              'Prices often build ahead of a tournament, since only shareholders at the start receive its dividend.',
            ]}
          />
        ),
      },
      {
        heading: 'Sorting the market',
        body: <p>Use the price arrows to order players from highest to lowest price (↓) or lowest to highest (↑). Open
        Live Activity to follow recent trades across the market as they happen.</p>,
      },
    ],
  },
  verified: {
    emoji: '✅',
    title: 'Verified Pros',
    intro: 'A verified badge confirms that a listing is the genuine pro player, not a look-alike account.',
    sections: [
      {
        heading: 'What it means',
        body: (
          <p>We maintain a hand-checked list of professional players and the Epic accounts each one uses, including the
          separate accounts they play on at LAN events such as EWC and the Global Championship. A <strong>verified</strong>{' '}
          player has been matched to that list, and is shown under the name <em>we</em> list for them rather than whichever
          name an account used on a given day.</p>
        ),
      },
      {
        heading: 'Why it matters',
        body: (
          <p>Anyone can register a name that closely resembles a pro’s and enter an open qualifier. Without verification,
          that account could appear on the market beside the real player. If two similar names appear,{' '}
          <strong>choose the verified one</strong>.</p>
        ),
      },
      {
        heading: 'No badge?',
        body: (
          <List
            items={[
              'A missing badge does not mean a player is not real. Many legitimate players are not on our verified list yet.',
              'If a name resembles a verified pro’s but carries no badge, treat it as a different player and confirm before you buy.',
            ]}
          />
        ),
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

/** A small clickable "verified" check shown next to a pro's name. Clicking it opens the "Verified Pros"
 * explanation. Renders nothing unless `show` is true. A <span role="button"> (not a <button>) so it can sit
 * inside rows/cards that are themselves buttons without producing invalid nested-button markup. */
export function VerifiedBadge({ show, size = 14 }: { show?: boolean; size?: number }) {
  const [open, setOpen] = useState(false);
  if (!show) return null;
  const openIt = (e: { stopPropagation: () => void; preventDefault?: () => void }) => { e.stopPropagation(); e.preventDefault?.(); setOpen(true); };
  return (
    <>
      <span
        role="button"
        tabIndex={0}
        onClick={openIt}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') openIt(e); }}
        title="Verified pro. Select to learn what this means."
        className="inline-flex align-middle ml-1 cursor-pointer shrink-0"
        style={{ color: 'var(--primary)' }}
      >
        <BadgeCheck style={{ width: size, height: size }} />
      </span>
      <AnimatePresence>
        {open && <HelpModal topicId="verified" onClose={() => setOpen(false)} />}
      </AnimatePresence>
    </>
  );
}
