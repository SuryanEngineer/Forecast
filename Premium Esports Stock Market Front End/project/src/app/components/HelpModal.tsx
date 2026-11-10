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
import { BenchmarkText, TargetYield, BandLow, BandHigh } from './Benchmark';
import { useEffect, useState, type ReactNode } from 'react';
import { BadgeCheck, HelpCircle, X } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

export type HelpTopicId =
  | 'start' | 'pages' | 'market' | 'orders' | 'pricing' | 'dividends' | 'tournaments' | 'portfolio' | 'rankings'
  | 'bots' | 'tips' | 'costs' | 'glossary' | 'faq' | 'verified';

// The order topics appear in the Guide's topic bar: a sensible learning path, newcomer first, reference last.
export const HELP_TOPIC_ORDER: HelpTopicId[] = [
  'start', 'pages', 'market', 'orders', 'pricing', 'dividends', 'tournaments', 'portfolio', 'rankings',
  'bots', 'tips', 'costs', 'glossary', 'faq', 'verified',
];

// Short names for the topic buttons and the Next button (the full title still heads each topic).
const TAB_LABEL: Record<HelpTopicId, string> = {
  start: 'Getting Started',
  pages: 'Pages',
  market: 'Market',
  orders: 'Trading',
  pricing: 'Pricing',
  dividends: 'Dividends',
  tournaments: 'Tournaments',
  portfolio: 'Portfolio',
  rankings: 'Leaderboard',
  bots: 'Bots',
  tips: 'Tips',
  costs: 'Fees',
  glossary: 'Glossary',
  faq: 'FAQ',
  verified: 'Verified',
};

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

function Fact({ label, value }: { label: string; value: ReactNode }) {
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

function Term({ name, children }: { name: string; children: ReactNode }) {
  return (
    <div className="py-1.5" style={{ borderBottom: '1px solid var(--border)' }}>
      <p className="text-foreground font-semibold" style={{ fontSize: 13 }}>{name}</p>
      <p className="text-muted-foreground" style={{ fontSize: 12.5, lineHeight: 1.55 }}>{children}</p>
    </div>
  );
}

function QA({ q, children }: { q: string; children: ReactNode }) {
  return (
    <div className="py-2" style={{ borderBottom: '1px solid var(--border)' }}>
      <p className="text-foreground font-semibold" style={{ fontSize: 13 }}>{q}</p>
      <div className="text-muted-foreground mt-0.5" style={{ fontSize: 12.5, lineHeight: 1.55 }}>{children}</div>
    </div>
  );
}

export const HELP_TOPICS: Record<HelpTopicId, HelpTopic> = {
  start: {
    emoji: '🚀',
    title: 'Getting Started',
    intro: 'Forecast is a fantasy stock market for competitive Fortnite. Every pro is a stock, tournament results pay the people who own them, and whoever ends up with the most money wins.',
    sections: [
      {
        heading: 'The goal',
        body: (
          <p>Grow your <strong>net worth</strong> (cash plus the value of your players) faster than everyone else, and faster
          than the market itself. It is all fantasy money: nothing to deposit, nothing to withdraw. The leaderboard shows real
          players only, so the race is simply who has the most.</p>
        ),
      },
      {
        heading: 'How money is made',
        body: (
          <List
            items={[
              <><strong>Dividends.</strong> When a player you own finishes well in a tournament, cash lands in your balance. Only people holding shares when the event <em>starts</em> are paid.</>,
              <><strong>Price changes.</strong> If you buy a player before the market recognizes how good they are, their price rises and your shares are worth more. The reverse is also true.</>,
            ]}
          />
        ),
      },
      {
        heading: 'Your first five minutes',
        body: (
          <List
            items={[
              'Open Events and find a tournament that has not started yet. Bigger events pay bigger dividends.',
              'Open Market and look at the players. Select one to see their price, tournament history, and dividends earned.',
              'Buy a few shares of players you believe in, ahead of the event. Spread across several players rather than putting everything on one.',
              'Watch the event on its live standings page, collect your dividend when it finalizes, then decide to hold, sell, or reinvest.',
              'Check the Leaderboard and My Stats to see how you are doing against everyone else and against the market.',
            ]}
          />
        ),
      },
      {
        heading: 'What can go wrong',
        body: (
          <p>Prices can fall, players have bad events, and trading costs a little every time (see Fees &amp; Costs). Nothing is
          guaranteed, which is the point: reading the field better than other investors, and the bots, is the skill.</p>
        ),
      },
    ],
  },
  pages: {
    emoji: '🧭',
    title: 'A Tour of Every Page',
    intro: 'What lives where, so nothing is a mystery.',
    sections: [
      {
        heading: 'Home',
        body: <p>Your portfolio value and 24-hour change, the top-priced players, your three biggest holdings, any live tournament
        with its standings, and the next events coming up.</p>,
      },
      {
        heading: 'Market',
        body: <p>Every player you can trade. Search by name or team, sort by price (↓ or ↑), and select a player to open their page.
        Two optional side panels show market-wide totals (Market Overview) and a stream of recent trades (Live Activity).</p>,
      },
      {
        heading: 'A player’s page',
        body: (
          <List
            items={[
              'Price chart over different ranges, with tournament and season markers so you can see what moved it.',
              'The Buy price, Sell price, and order book: resting orders from other traders plus the House’s own levels (shown as House, with no individual order behind them).',
              'The trade panel: quick buy/sell or a limit order at your own price.',
              'Their tournament history, with links into the exact placement, and the dividends they have paid.',
              'The recent trades in them, and a note on how dividends work.',
            ]}
          />
        ),
      },
      {
        heading: 'My Portfolio',
        body: <p>Everything you own: each holding’s value and gain or loss, a chart of your portfolio over time, your open limit
        orders (cancel any here), and an activity log of every buy, sell, dividend, and fee, filterable by type.</p>,
      },
      {
        heading: 'Leaderboard',
        body: <p>Real investors ranked by net worth. Select anyone to browse their holdings. Bots are never listed.</p>,
      },
      {
        heading: 'My Stats',
        body: <p>Your net worth over time, your best and worst days, your best holding, and lifetime totals. Day figures compare
        end-of-day (UTC) net worth to the day before.</p>,
      },
      {
        heading: 'Events',
        body: <p>The tournament calendar, live standings while an event is running, and results afterward: team standings, each
        team’s payout, and game-by-game breakdowns. Event times show in your local time.</p>,
      },
      {
        heading: 'Settings',
        body: <p>Your profile, a cosmetic tag shown next to your name (pick its color), password, and email.</p>,
      },
      {
        heading: 'Feedback and phones',
        body: <p>Feedback in the sidebar shows our email address; we would love to hear what you think. On a phone the sidebar is
        tucked away: tap the menu button (three lines) at the top to open it. Everything works the same on a small screen, in
        either orientation.</p>,
      },
    ],
  },
  pricing: {
    emoji: '🧮',
    title: 'How Prices Are Set',
    intro: 'Prices are set by what investors and bots are willing to pay. Dividends give every stock a starting reference, but the crowd decides where it trades.',
    sections: [
      {
        heading: 'The reference: fair price',
        body: (
          <div className="space-y-1.5">
            <p>Each player has a <strong>fair price</strong> based on the dividends they earned over the last 12 months:
            projected yearly dividends per share divided by a target yield. It decides how stocks compare with each other (a
            player who earns ten times the dividends starts at ten times the price) and where the market opens. It is a
            reference point, not a promise: if investors expect a player to get better, or just want him more, the price can
            rise well above it.</p>
            <Fact label="Target yield behind fair price" value={<TargetYield />} />
          </div>
        ),
      },
      {
        heading: 'One lucky result does not set the price',
        body: <p>A player with only a result or two is priced partly like a typical player, since one big finish may be a fluke.
        Their own results count for more as their record grows.</p>,
      },
      {
        heading: 'The band',
        body: (
          <div className="space-y-1.5">
            <p>Prices stay between <BandLow /> and <BandHigh /> of fair price (and never below $0.50). It is a guardrail
            against typos and against one trader dragging a thin market somewhere the player’s results can’t justify. Limit
            orders outside it are refused.</p>
          </div>
        ),
      },
      {
        heading: 'How trades move the price',
        body: <p>Each trade nudges the running price toward the trade’s price, in proportion to its size. The listed price is
        the last trade, kept between the Sell and Buy prices.</p>,
      },
      {
        heading: 'When results come in',
        body: <p>When a tournament finalizes, fair price is recomputed with the new result and the price drifts toward it:
        strong finishes lift it, weak ones lower it.</p>,
      },
    ],
  },
  bots: {
    emoji: '🤖',
    title: 'The Bots',
    intro: 'Not everyone trading here is a person, and we would rather you know exactly how that works.',
    sections: [
      {
        heading: 'What they are',
        body: <p>Bot traders are automated accounts that buy, sell, and post orders around the clock so there is always someone to
        trade with. They are the market’s background liquidity.</p>,
      },
      {
        heading: 'How they decide',
        body: (
          <p>Each bot values a player from public data (12 months of tournament earnings, recent placements, upcoming events and
          qualifier results), with its own spin so they don’t all agree. They buy what looks cheap and sell what looks expensive.</p>
        ),
      },
      {
        heading: 'What they are not',
        body: (
          <List
            items={[
              'Not on the leaderboard, and never competing for rank.',
              'Not insiders: same order book, fees and limits as you, and nothing hidden.',
              'Not always right. They work from past results, so you can win by anticipating what the record doesn’t show yet.',
            ]}
          />
        ),
      },
      {
        heading: 'Beating them',
        body: <p><BenchmarkText /></p>,
      },
    ],
  },
  tips: {
    emoji: '🧠',
    title: 'Playing Smart',
    intro: 'Nobody can promise you a winning strategy, but these ideas follow directly from how the market works.',
    sections: [
      {
        heading: 'Buy before the start',
        body: <p>The dividend goes to holders when an event starts. Buying early also means you are in before the crowd, though
        prices often build ahead of big events, so a late buy is a pricier one.</p>,
      },
      {
        heading: 'Compare price to income',
        body: <p>On a player’s page, look at how much they have paid in dividends against what a share costs. A player whose
        results keep beating what their price implies is the kind of stock the bots may be undervaluing.</p>,
      },
      {
        heading: 'Remember bigger events pay more',
        body: <p>Cash Cups are frequent but modest, FNCS events pay five times as much, and the Global Championship pays ten times
        a Cash Cup. Players who show up and place deep in the big ones are worth more.</p>,
      },
      {
        heading: 'Do not churn',
        body: <p>Every instant trade pays the gap and a 0.25% fee. Limit orders skip the gap and, if they rest, the fee. Buying and
        immediately selling always loses a little.</p>,
      },
      {
        heading: 'Spread your bets',
        body: <p>A bad weekend for one player is a small dent if you own several. Mix big names with rising players, and
        consider both regions.</p>,
      },
      {
        heading: 'Past results are a guide, not a promise',
        body: <p>Form changes, teams split, and qualifiers eliminate people. Check the Events calendar for who is entered before you buy.</p>,
      },
    ],
  },
  costs: {
    emoji: '🧾',
    title: 'Fees & Costs',
    intro: 'Everything it costs to trade, in one place.',
    sections: [
      {
        heading: 'The full list',
        body: (
          <div className="space-y-1.5">
            <Fact label="Transaction fee (taker only)" value="0.25%" />
            <Fact label="Fee if your limit order rests and is filled" value="None" />
            <Fact label="Minimum share price" value="$0.50" />
            <Fact label="Platform cut of dividends" value="None right now" />
          </div>
        ),
      },
      {
        heading: 'The gap between Buy and Sell',
        body: <p>Buying at the Buy price and selling at the Sell price means an instant round trip loses the gap. It is small for
        small orders and larger for big ones.</p>,
      },
      {
        heading: 'Large orders',
        body: <p>The exchange’s own liquidity gets more expensive the more you ask of it, and it will say so if an order is too
        large to fill right now. A limit order lets you wait for another trader instead.</p>,
      },
      {
        heading: 'Why your value dips after buying',
        body: <p>Your holdings are valued at what selling all of them would pay. Right after you buy you have paid the Buy price and
        the fee, so the number starts slightly below what you spent. Dividends and price moves are what grow it from there.</p>,
      },
    ],
  },
  glossary: {
    emoji: '📚',
    title: 'Glossary',
    intro: 'Every term used in the game, in plain language.',
    sections: [
      {
        heading: 'Trading',
        body: (
          <div>
            <Term name="Share">One unit of ownership in a player. Owning shares entitles you to that player’s dividends.</Term>
            <Term name="Buy price / Sell price">What one share costs right now, and what it fetches right now.</Term>
            <Term name="Listed price">The price of the last trade, kept between the Sell and Buy prices (above Buy shows Buy, below Sell shows Sell). It is the price shown for the player.</Term>
            <Term name="Order book">The list of resting buy and sell orders for a player, ranked by price.</Term>
            <Term name="Limit order">An order at your chosen price that waits on the book until it fills or you cancel it.</Term>
            <Term name="Quick trade">An instant order that takes the best available price now.</Term>
            <Term name="Maker / Taker">The maker is the resting order that gets hit; the taker is the order that hits it. Only the taker pays the fee.</Term>
            <Term name="The House">The exchange’s own account, a last resort for quick trades when the real orders run out. It is not one of the bots. It sells about 3% above, and buys about 3% below, what the market looks like it is worth (the middle of the best buy and sell orders).</Term>
            <Term name="Liquidity">How easily you can trade without moving the price. Thin markets move more.</Term>
          </div>
        ),
      },
      {
        heading: 'Money',
        body: (
          <div>
            <Term name="Dividend">Cash paid to shareholders when a player places in a tournament.</Term>
            <Term name="Pool">The total dividend money for one tournament, set by its type.</Term>
            <Term name="Per-share payout">A player’s dividend divided by their total shares. You receive this times your shares.</Term>
            <Term name="Record date">The moment a tournament starts. Whoever holds shares then gets paid.</Term>
            <Term name="Cost basis">What you paid for shares you hold. Gain or loss compares today’s value to it.</Term>
            <Term name="Market cap">What it would take to buy a player’s entire supply right now: resting bids first, then the House’s size-dependent sell price for the rest. It is not simply the listed price times every share.</Term>
            <Term name="Net worth">Cash plus what selling everything you own would pay right now. This ranks the leaderboard.</Term>
            <Term name="Market return">The growth the market gets from dividends alone. Beat it and you are outperforming.</Term>
          </div>
        ),
      },
      {
        heading: 'Pricing and people',
        body: (
          <div>
            <Term name="Fair price">A reference for what a player’s dividends are worth: projected yearly dividends per share divided by the target yield (<TargetYield />).</Term>
            <Term name="Band">The wide range, <BandLow /> to <BandHigh /> fair price, that prices must stay inside.</Term>
            <Term name="Bot">An automated trader that supplies liquidity using public data. Never ranked.</Term>
            <Term name="Placement">A player’s official finishing position in a real tournament.</Term>
            <Term name="Verified">A listing confirmed as the genuine pro on our hand-checked list.</Term>
          </div>
        ),
      },
    ],
  },
  faq: {
    emoji: '❓',
    title: 'Common Questions',
    intro: 'The things people ask in their first week.',
    sections: [
      {
        heading: 'Basics',
        body: (
          <div>
            <QA q="Is this real money?">No. Everything is fantasy cash, there is nothing to deposit or withdraw, and no real prizes are paid out of it.</QA>
            <QA q="How do I win?">Finish with the most money. The leaderboard counts only real players, ranked by net worth.</QA>
            <QA q="Where do tournament results come from?">Live competitive data, synced automatically. Standings update during play and become permanent once an event finalizes.</QA>
          </div>
        ),
      },
      {
        heading: 'Dividends',
        body: (
          <div>
            <QA q="I bought after the tournament started. Will I be paid?">No. Only holders at the start are paid for that event. You will be paid for the next one.</QA>
            <QA q="I sold after it started. Do I still get paid?">Yes. You held shares at the start, so that dividend is yours.</QA>
            <QA q="When does the cash arrive?">Once the event’s results are final and its dividends are distributed. Open the event to see its payouts.</QA>
          </div>
        ),
      },
      {
        heading: 'Prices and orders',
        body: (
          <div>
            <QA q="Why did my portfolio dip right after I bought?">You paid the Buy price plus the fee, while your value counts what selling would pay. See Fees &amp; Costs.</QA>
            <QA q="My limit order has not filled.">Normal. It fills only if the market reaches your price. Cancel it any time from My Portfolio.</QA>
            <QA q="It says the House can’t buy or sell that many.">The House’s liquidity has limits. Try a smaller size or a limit order.</QA>
            <QA q="It says my price is outside the allowed range.">Limit orders must sit inside the band around fair price. See How Prices Are Set.</QA>
            <QA q="Why can’t I trade with myself?">Orders that would match your own are blocked, so nobody can move a price by trading with themselves.</QA>
          </div>
        ),
      },
      {
        heading: 'Players and bots',
        body: (
          <div>
            <QA q="Two players have nearly the same name. Which one?">Choose the one with the verified badge. See Verified Pros.</QA>
            <QA q="Are bots cheating?">No. They use the same public data, order book, and fees as you, and are not on the leaderboard. See The Bots.</QA>
            <QA q="What does my tag do?">It is cosmetic: a short label with a color shown next to your name. Set it in Settings.</QA>
          </div>
        ),
      },
    ],
  },
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
                'Cancel any time from My Portfolio, or from that player’s page. An open order locks up the cash (buy) or shares (sell) it needs.',
                'Optional time limit (1 hour, 1 day, or 1 week): it cancels itself if unfilled and frees the cash or shares. Otherwise it stays open until it fills or you cancel.',
                'It may never fill if the market doesn’t reach your price.',
                'A resting order that gets filled pays no fee. See Fees & Costs.',
              ]}
            />
          </>
        ),
      },
      {
        heading: 'Quick trades',
        body: (
          <>
            <p>A quick trade fills immediately: first against the best orders on the book, then against the House. The larger
            the order, the worse the average price. Use it when speed matters more than the exact price.</p>
          </>
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
            <p>Every event pays from a fixed dividend pool, scaled by region, and the pool depends on how the event is run. The final of
            a set-lobby cup pays the Cash Cup pool, and every set-lobby round after the first round of a multi-round event pays the smaller
            Qualifier pool. A fully open lobby (anyone can enter, only the top places are paid, like the Arenas and Trios Cash Cups) is never a
            tournament here and pays no dividend; open rounds only appear in the “Open rounds” or “All” view of the Tournaments page, never in
            “Pays dividends”. FNCS events pay the FNCS pool online and the Global pool at a LAN.</p>
            <p>The split also follows each event's own scoring rules: an event that only scores game wins pays per game won, like
            Performance Evaluation cups, and an event whose payout table pays a limited number of places pays only those places.</p>
            <p>A tournament is only marked over when it really is: a set-lobby event is over once its last game (for example game 10 of 10) has a winner, and an open round is over once its lobbies have closed and the last games have had time to finish. The scheduled close time alone doesn't end an event, because games that started before it keep running.</p>
            <Fact label="Cash Cup pool (final set lobby)" value="$300,000" />
            <Fact label="Qualifier pool (later set-lobby round)" value="$150,000" />
            <Fact label="FNCS Finals / online Major pool" value="$1,500,000" />
            <Fact label="Global Championship / LAN Major pool" value="$3,000,000" />
          </div>
        ),
      },
      {
        heading: 'Performance Evaluation cups',
        body: (
          <div className="space-y-1.5">
            <p>Performance Evaluation cups are set-lobby events, and they pay per game won instead of by final placement. Each cup has a
            $300,000 pool, and every game win is worth a quarter of it, shared across the winning team. In a trio, each player who wins a game
            earns $25,000 for their shareholders, and a player who wins twice earns $50,000.</p>
            <Fact label="Performance Evaluation pool" value="$300,000" />
            <Fact label="One game win (trio, per player)" value="$25,000" />
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
          <p>Cash Cups are the most frequent events, FNCS Finals and Majors occur less often, and the Global
          Championship and LAN Majors are the rarest. Larger events carry larger dividend pools, so they have the greatest impact on your
          portfolio. See the Dividends guide for exact figures.</p>
        ),
      },
    ],
  },
  rankings: {
    emoji: '📊',
    title: 'How the Leaderboard Works',
    intro: 'One leaderboard, real investors only: whoever has the most money is on top.',
    sections: [
      {
        heading: 'Net worth',
        body: (
          <p><strong>Net worth = cash + what selling every share you hold would pay right now.</strong> It never resets, so
          everyone is simply racing to build the most money.</p>
        ),
      },
      {
        heading: 'Who is on it',
        body: <p>Real people only; bots never appear. Select any row to see that investor’s holdings.</p>,
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
          <p><strong>Cash + holdings value</strong>, the same figure used for your ranking. Only price moves and dividends
          change it, apart from the small cost of trading.</p>
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
    intro: 'Every player has a Buy price and a Sell price, and the listed price is the last trade, kept between the two.',
    sections: [
      {
        heading: 'Where prices come from',
        body: (
          <p>The <strong>Buy price</strong> is what one share costs right now (the cheapest seller, or the House if nobody is
          selling cheaper). The <strong>Sell price</strong> is what one share fetches right now (the best bidder, or the
          House). The listed price is the last trade, kept between the two.</p>
        ),
      },
      {
        heading: 'Why small trades barely move the price',
        body: (
          <p>Each trade moves the market’s running price in proportion to its size, so a small trade barely moves the price.
          Steady buying or selling adds up and can move it a long way, and if a price drifts too far, traders stop buying
          or selling at it and it settles.</p>
        ),
      },
      {
        heading: 'Big orders cost more per share',
        body: (
          <p>The House’s price gets worse the more you buy or sell at once, and your holdings are valued the same way (what
          selling all of them would pay). For a large order, a limit order lets you wait for another trader instead.</p>
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

/** The Guide. Opens on one topic (an ⓘ button's own topic, or Getting Started), but every topic is one tap away in the 3-column grid
 * under the header, so any ⓘ doubles as a doorway into the whole manual. `onReplayTour` adds a "Replay the quick tour" link. */
function HelpModal({ topicId, onClose, onReplayTour }: { topicId: HelpTopicId; onClose: () => void; onReplayTour?: () => void }) {
  const [current, setCurrent] = useState<HelpTopicId>(topicId);
  const topic = HELP_TOPICS[current];
  const idx = HELP_TOPIC_ORDER.indexOf(current);

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose(); }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center p-4 modal-overlay"
      style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(6px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <motion.div
        className="w-full rounded-2xl border border-border flex flex-col modal-panel"
        style={{ background: 'var(--card)', maxWidth: 720, maxHeight: '90vh' }}
        initial={{ opacity: 0, scale: 0.95, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        <div className="px-4 sm:px-6 pt-5 pb-3 flex items-start justify-between shrink-0">
          <div className="flex items-center gap-3">
            <span style={{ fontSize: 28 }}>{topic.emoji}</span>
            <div>
              <h2 className="text-foreground font-bold" style={{ fontSize: 18 }}>{topic.title}</h2>
              <p className="text-muted-foreground mt-0.5" style={{ fontSize: 12.5, lineHeight: 1.5, maxWidth: 460 }}>{topic.intro}</p>
            </div>
          </div>
          <button onClick={onClose} aria-label="Close" className="p-1.5 rounded-lg hover:bg-white/10 transition-colors shrink-0">
            <X className="w-4 h-4 text-muted-foreground" />
          </button>
        </div>

        {/* topic buttons: a fixed 3-column grid, never a sideways scroll */}
        <div className="px-4 sm:px-6 pb-3 shrink-0 border-b border-border">
          <div className="grid grid-cols-3 gap-1.5">
            {HELP_TOPIC_ORDER.map(id => {
              const t = HELP_TOPICS[id];
              const active = id === current;
              return (
                <button
                  key={id}
                  onClick={() => setCurrent(id)}
                  className="px-2 py-1.5 rounded-lg font-semibold transition-colors text-left truncate"
                  style={{
                    fontSize: 12,
                    background: active ? 'rgba(0,200,255,0.18)' : 'transparent',
                    color: active ? 'var(--primary)' : 'var(--muted-foreground)',
                    border: `1px solid ${active ? 'var(--primary)' : 'var(--border)'}`,
                  }}
                >
                  {t.emoji} {TAB_LABEL[id]}
                </button>
              );
            })}
          </div>
        </div>

        <div key={current} className="px-4 sm:px-6 py-5 overflow-y-auto space-y-5 flex-1 min-h-0">
          {topic.sections.map((section, i) => (
            <div key={i}>
              <p className="font-bold uppercase tracking-wide" style={{ fontSize: 10.5, color: 'var(--primary)' }}>{section.heading}</p>
              <div className="mt-1.5" style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--foreground)' }}>{section.body}</div>
            </div>
          ))}
        </div>

        <div className="px-4 sm:px-6 py-4 border-t border-border shrink-0 flex items-center gap-2">
          {onReplayTour && (
            <button
              onClick={onReplayTour}
              className="px-3 py-2.5 rounded-xl font-semibold transition-colors hover:bg-white/[0.06]"
              style={{ fontSize: 13, color: 'var(--muted-foreground)', border: '1px solid var(--border)' }}
            >
              Replay quick tour
            </button>
          )}
          {idx > 0 && (
            <button
              onClick={() => setCurrent(HELP_TOPIC_ORDER[idx - 1])}
              className="px-3 py-2.5 rounded-xl font-semibold transition-colors hover:bg-white/[0.06]"
              style={{ fontSize: 13, color: 'var(--muted-foreground)', border: '1px solid var(--border)' }}
            >
              Back
            </button>
          )}
          {idx < HELP_TOPIC_ORDER.length - 1 ? (
            <button
              onClick={() => setCurrent(HELP_TOPIC_ORDER[idx + 1])}
              className="flex-1 py-2.5 rounded-xl font-bold transition-opacity hover:opacity-90"
              style={{ fontSize: 14, background: 'linear-gradient(135deg, var(--primary), var(--accent))', color: '#fff' }}
            >
              Next: {TAB_LABEL[HELP_TOPIC_ORDER[idx + 1]]}
            </button>
          ) : (
            <button
              onClick={onClose}
              className="flex-1 py-2.5 rounded-xl font-bold transition-opacity hover:opacity-90"
              style={{ fontSize: 14, background: 'linear-gradient(135deg, var(--primary), var(--accent))', color: '#fff' }}
            >
              Got it
            </button>
          )}
          {idx < HELP_TOPIC_ORDER.length - 1 && (
            <button
              onClick={onClose}
              className="px-3 py-2.5 rounded-xl font-semibold transition-colors hover:bg-white/[0.06]"
              style={{ fontSize: 13, color: 'var(--muted-foreground)', border: '1px solid var(--border)' }}
            >
              Close
            </button>
          )}
        </div>
      </motion.div>
    </div>
  );
}

/** The full Guide, opened from the sidebar. Starts on Getting Started. */
export function HelpCenter({ onClose, onReplayTour, topic = 'start' }: { onClose: () => void; onReplayTour?: () => void; topic?: HelpTopicId }) {
  return <HelpModal topicId={topic} onClose={onClose} onReplayTour={onReplayTour} />;
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
