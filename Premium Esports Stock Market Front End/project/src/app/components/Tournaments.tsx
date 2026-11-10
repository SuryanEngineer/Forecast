import React, { useCallback, useEffect, useState } from 'react';
import { Calendar } from 'lucide-react';
import { tournamentDisplayName } from '../lib/tournamentName';
import { useAnnouncedTournaments, useTournamentCalendar } from '../lib/hooks';
import {
  toNumber,
  type AnnouncedTournament,
  type CalendarTournamentResponse,
  type TournamentResponse,
} from '../lib/types';
import { LiveLeaderboard } from './LiveLeaderboard';
import { HelpButton } from './HelpModal';
import { OpenRoundRow, OpenRoundsSection, RoundModal, roundName, useOpenRounds, type OpenRound } from './OpenRounds';
import { usd } from '../lib/format';

interface Props {
  navigate: (page: string, playerId?: string) => void;
  openTournament: (tournament: TournamentResponse) => void;
}

function useCountdown(targetDate: string | null) {
  const [t, setT] = useState({ d: 0, h: 0, m: 0, s: 0 });
  useEffect(() => {
    if (!targetDate) return;
    const update = () => {
      const diff = new Date(targetDate).getTime() - Date.now();
      if (diff <= 0) { setT({ d: 0, h: 0, m: 0, s: 0 }); return; }
      setT({
        d: Math.floor(diff / 86400000),
        h: Math.floor((diff % 86400000) / 3600000),
        m: Math.floor((diff % 3600000) / 60000),
        s: Math.floor((diff % 60000) / 1000),
      });
    };
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, [targetDate]);
  return t;
}

function CountdownBox({ value, label }: { value: number; label: string }) {
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="rounded-2xl flex items-center justify-center font-mono font-bold" style={{ width: 'clamp(38px, 12.5vw, 56px)', height: 'clamp(38px, 12.5vw, 56px)', fontSize: 'clamp(16px, 5vw, 22px)', background: 'var(--muted)', border: '1.5px solid var(--border)', color: 'var(--primary)' }}>
        {String(value).padStart(2, '0')}
      </div>
      <p className="text-muted-foreground uppercase" style={{ fontSize: 10, letterSpacing: '0.1em' }}>{label}</p>
    </div>
  );
}

const TYPE_PILL = (type: string) => type.replace(/_/g, ' ');

/** The big card at the top of the calendar: the next event to start, with a countdown. */
function FeaturedEvent({ name, type, region, startTime, pool, note, onOpen }: {
  name: string; type: string; region: string | null; startTime: string | null; pool: number | null; note?: string; onOpen?: () => void;
}) {
  const cd = useCountdown(startTime);
  const Head = (
    <div className="flex flex-wrap items-start gap-x-3 gap-y-2 mb-4">
      <div className="min-w-0">
        <div className="flex items-center gap-2 mb-1.5">
          <span className="px-2.5 py-0.5 rounded-full font-bold uppercase" style={{ fontSize: 10, background: 'rgba(0,200,255,0.15)', color: 'var(--primary)' }}>NEXT EVENT</span>
          <span className="px-2.5 py-0.5 rounded-full font-bold uppercase" style={{ fontSize: 10, background: 'rgba(155,111,255,0.15)', color: 'var(--accent)' }}>{TYPE_PILL(type)}</span>
        </div>
        <h2 className="text-foreground font-bold" style={{ fontSize: 20, lineHeight: 1.3 }}>{tournamentDisplayName(name, region)}</h2>
        {region && <p className="text-muted-foreground mt-1" style={{ fontSize: 13 }}>{region}</p>}
      </div>
      {pool !== null && pool > 0 && (
        <div className="text-right ml-auto shrink-0">
          <p className="font-mono font-bold" style={{ fontSize: 26, color: 'var(--gain)' }}>{usd(pool)}</p>
          <p className="text-muted-foreground" style={{ fontSize: 12 }}>total dividend pool</p>
        </div>
      )}
    </div>
  );
  return (
    <div className="rounded-2xl border p-4 sm:p-6" style={{ background: 'linear-gradient(135deg, rgba(0,200,255,0.07), rgba(155,111,255,0.05)), var(--card)', borderColor: 'rgba(0,200,255,0.25)' }}>
      {onOpen ? <button onClick={onOpen} className="w-full text-left">{Head}</button> : Head}

      {startTime && (
        <div className="flex flex-wrap gap-4 mb-5 text-muted-foreground" style={{ fontSize: 13 }}>
          <span className="flex items-center gap-1.5">
            <Calendar className="w-4 h-4" />
            {new Date(startTime).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}
          </span>
        </div>
      )}

      {startTime && (
        <div>
          <p className="text-muted-foreground mb-3" style={{ fontSize: 13 }}>Starts in:</p>
          <div className="flex items-center gap-1.5 sm:gap-3">
            <CountdownBox value={cd.d} label="days" />
            <span className="text-muted-foreground font-mono" style={{ fontSize: 'clamp(16px, 5vw, 22px)', paddingBottom: 20 }}>:</span>
            <CountdownBox value={cd.h} label="hours" />
            <span className="text-muted-foreground font-mono" style={{ fontSize: 'clamp(16px, 5vw, 22px)', paddingBottom: 20 }}>:</span>
            <CountdownBox value={cd.m} label="min" />
            <span className="text-muted-foreground font-mono" style={{ fontSize: 'clamp(16px, 5vw, 22px)', paddingBottom: 20 }}>:</span>
            <CountdownBox value={cd.s} label="sec" />
          </div>
        </div>
      )}
      {note && <p className="text-muted-foreground mt-3" style={{ fontSize: 12 }}>{note}</p>}

      <div className="mt-4 p-3 rounded-xl" style={{ background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.2)' }}>
        <p style={{ fontSize: 13, color: '#fbbf24', lineHeight: 1.6 }}>
          💡 <strong>Tip:</strong> Owning shares in players who place well earns you a dividend once results are finalized. Buy shares before big events!
        </p>
      </div>
    </div>
  );
}

/** Same card, in red, for an event that is running right now, with the top of its live leaderboard. */
function LiveEvent({ tournament, onOpen }: { tournament: CalendarTournamentResponse; onOpen: () => void }) {
  const pool = tournament.total_dividend_pool !== null ? toNumber(tournament.total_dividend_pool) : null;
  return (
    <div className="rounded-2xl border p-6" style={{ background: 'linear-gradient(135deg, rgba(255,71,87,0.09), rgba(155,111,255,0.04)), var(--card)', borderColor: 'rgba(255,71,87,0.4)' }}>
      <button onClick={onOpen} className="w-full text-left">
        <div className="flex items-start gap-3 mb-4">
          <div>
            <div className="flex items-center gap-2 mb-1.5">
              <span className="px-2.5 py-0.5 rounded-full font-bold uppercase" style={{ fontSize: 10, background: 'rgba(255,71,87,0.15)', color: '#ff4757' }}>● LIVE</span>
              <span className="px-2.5 py-0.5 rounded-full font-bold uppercase" style={{ fontSize: 10, background: 'rgba(155,111,255,0.15)', color: 'var(--accent)' }}>{TYPE_PILL(tournament.tournament_type)}</span>
            </div>
            <h2 className="text-foreground font-bold" style={{ fontSize: 20, lineHeight: 1.3 }}>{tournamentDisplayName(tournament.name, tournament.region)}</h2>
            {tournament.region && <p className="text-muted-foreground mt-1" style={{ fontSize: 13 }}>{tournament.region}</p>}
          </div>
          {pool !== null && pool > 0 && (
            <div className="text-right ml-auto shrink-0">
              <p className="font-mono font-bold" style={{ fontSize: 26, color: 'var(--gain)' }}>{usd(pool)}</p>
              <p className="text-muted-foreground" style={{ fontSize: 12 }}>total dividend pool</p>
            </div>
          )}
        </div>
        <LiveLeaderboard tournamentId={tournament.id} compact />
        <p className="text-center mt-3" style={{ fontSize: 12, color: 'var(--primary)' }}>View full leaderboard →</p>
      </button>
    </div>
  );
}

const TIER_LABELS: Record<string, string> = {
  cash_cup: 'Cash Cup',
  fncs_qualifier: 'FNCS Qualifier',
  fncs_finals: 'FNCS Finals',
  global_championship: 'Global / EWC',
  major: 'Major',
  performance_eval: 'Performance Eval',
  other: 'Other',
};

function CalendarRow({ tournament, onOpen }: { tournament: CalendarTournamentResponse; onOpen: () => void }) {
  const pool = tournament.total_dividend_pool !== null ? toNumber(tournament.total_dividend_pool) : null;
  // `phase` is computed server-side from status + start_time + end_time
  // (see the backend's app/schemas/tournament.py compute_tournament_phase)
  // -- a single source of truth instead of re-deriving "is this live" here
  // from raw status/time fields, which used to disagree with how
  // LiveLeaderboard.tsx and the Tournaments tab filters derived the same
  // thing, producing contradictory badges (e.g. "Awaiting Results" on a
  // tournament that hadn't even started yet).
  const isLive = tournament.phase === 'live';
  const isFinalizing = tournament.phase === 'finalizing';
  const isCompleted = tournament.phase === 'completed';
  // No explicit `timeZone` option -- Date/toLocaleDateString/toLocaleTimeString
  // default to the browser's own local timezone, so this automatically
  // shows each viewer their own local date/time with no extra plumbing.
  const startDate = tournament.start_time ? new Date(tournament.start_time) : null;
  const dateLabel = startDate ? startDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : 'TBD';
  const timeLabel = startDate ? startDate.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) : null;

  return (
    <button
      onClick={onOpen}
      className="w-full flex items-center gap-3 p-3.5 rounded-2xl border border-border text-left transition-colors hover:bg-white/[0.03]"
      style={{ background: 'var(--card)' }}
    >
      <div className="flex flex-col items-center justify-center rounded-xl shrink-0" style={{ width: 60, height: 44, background: 'var(--muted)' }}>
        <p className="font-mono font-bold" style={{ fontSize: 12, color: 'var(--foreground)', lineHeight: 1.2 }}>{dateLabel}</p>
        {timeLabel && <p className="font-mono" style={{ fontSize: 9.5, color: 'var(--muted-foreground)', lineHeight: 1.2 }}>{timeLabel}</p>}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <p className="text-foreground font-semibold truncate" style={{ fontSize: 13.5 }}>{tournamentDisplayName(tournament.name, tournament.region)}</p>
          {isLive && (
            <span className="px-1.5 py-0.5 rounded-full font-bold uppercase shrink-0" style={{ fontSize: 9, background: 'rgba(255,71,87,0.15)', color: '#ff4757' }}>
              ● Live
            </span>
          )}
          {isCompleted && (
            <span className="px-1.5 py-0.5 rounded-full font-bold uppercase shrink-0" style={{ fontSize: 9, background: 'rgba(0,214,143,0.15)', color: '#00d68f' }}>
              ✓ Completed
            </span>
          )}
          {isFinalizing && (
            <span className="px-1.5 py-0.5 rounded-full font-bold uppercase shrink-0" style={{ fontSize: 9, background: 'rgba(255,171,64,0.15)', color: '#ffab40' }}>
              ⏳ Finalizing Results
            </span>
          )}
        </div>
        <p className="text-muted-foreground mt-0.5" style={{ fontSize: 11.5 }}>
          {TIER_LABELS[tournament.tournament_type] ?? tournament.tournament_type}
          {tournament.region ? ` · ${tournament.region}` : ''}
          {tournament.entrant_count > 0 ? ` · ${tournament.entrant_count} qualified` : ''}
        </p>
      </div>

      <div className="text-right shrink-0">
        {pool !== null && pool > 0 ? (
          <>
            <p className="font-mono font-bold" style={{ fontSize: 13.5, color: 'var(--gain)' }}>{usd(pool)}</p>
            <p className="text-muted-foreground" style={{ fontSize: 10 }}>total dividend pool</p>
          </>
        ) : (
          <p className="text-muted-foreground italic" style={{ fontSize: 11.5 }}>Pool TBD</p>
        )}
      </div>
    </button>
  );
}

/** An announced event that isn't a tracked tournament yet. It turns into a normal row (with live standings) on its own
 * once its payout details are published. */
function AnnouncedRow({ event }: { event: AnnouncedTournament }) {
  const pool = event.total_dividend_pool !== null ? toNumber(event.total_dividend_pool) : null;
  const startDate = event.start_time ? new Date(event.start_time) : null;
  const dateLabel = startDate ? startDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : 'TBD';
  const timeLabel = startDate ? startDate.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) : null;
  return (
    <div className="w-full flex items-center gap-3 p-3.5 rounded-2xl border border-border text-left" style={{ background: 'var(--card)' }}>
      <div className="flex flex-col items-center justify-center rounded-xl shrink-0" style={{ width: 60, height: 44, background: 'var(--muted)' }}>
        <p className="font-mono font-bold" style={{ fontSize: 12, color: 'var(--foreground)', lineHeight: 1.2 }}>{dateLabel}</p>
        {timeLabel && <p className="font-mono" style={{ fontSize: 9.5, color: 'var(--muted-foreground)', lineHeight: 1.2 }}>{timeLabel}</p>}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <p className="text-foreground font-semibold truncate" style={{ fontSize: 13.5 }}>{tournamentDisplayName(event.name, event.region)}</p>
          <span className="px-1.5 py-0.5 rounded-full font-bold uppercase shrink-0" style={{ fontSize: 9, background: 'rgba(0,200,255,0.12)', color: 'var(--primary)' }}>
            Announced
          </span>
        </div>
        <p className="text-muted-foreground mt-0.5" style={{ fontSize: 11.5 }}>
          {TIER_LABELS[event.tournament_type] ?? event.tournament_type}
          {event.region ? ` · ${event.region}` : ''}
          {!event.finals_confirmed ? ' · date may change (Finals not published yet)' : ''}
        </p>
      </div>
      <div className="text-right shrink-0">
        {pool !== null && pool > 0 ? (
          <>
            <p className="font-mono font-bold" style={{ fontSize: 13.5, color: 'var(--gain)' }}>{usd(pool)}</p>
            <p className="text-muted-foreground" style={{ fontSize: 10 }}>projected pool</p>
          </>
        ) : (
          <p className="text-muted-foreground italic" style={{ fontSize: 11.5 }}>Pool TBD</p>
        )}
      </div>
    </div>
  );
}

const startMs = (iso: string | null) => (iso ? new Date(iso).getTime() : Number.POSITIVE_INFINITY);

const calendarToTournament = (t: CalendarTournamentResponse): TournamentResponse => ({
  id: t.id, name: t.name, tournament_type: t.tournament_type, region: t.region, start_time: t.start_time, end_time: t.end_time,
  prize_pool: t.total_dividend_pool, status: t.status, phase: t.phase, created_at: t.start_time ?? new Date().toISOString(),
});

/** The top of the Events page, reusable elsewhere (the landing page): live events with their leaderboard in red, or, when
 * nothing is live, the next event with its countdown. Same cards, same rules as the Events page. */
export function NextEventSection({ openTournament }: { openTournament: (tournament: TournamentResponse) => void }) {
  const { data: calendar } = useTournamentCalendar(true);
  const { data: announced } = useAnnouncedTournaments();
  const live = calendar.filter(t => t.phase === 'live' || t.phase === 'finalizing').sort((a, b) => startMs(a.start_time) - startMs(b.start_time));
  const lastCompleted = calendar.filter(t => t.phase === 'completed').sort((a, b) => startMs(b.start_time) - startMs(a.start_time))[0];
  const lastCard = lastCompleted && (
    <div className="space-y-2.5">
      <p className="font-bold pt-1" style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>Last completed event</p>
      <CalendarRow tournament={lastCompleted} onOpen={() => openTournament(calendarToTournament(lastCompleted))} />
    </div>
  );
  if (live.length > 0) {
    return <div className="space-y-4">{live.map(t => <LiveEvent key={t.id} tournament={t} onOpen={() => openTournament(calendarToTournament(t))} />)}{lastCard}</div>;
  }
  const upcoming = [
    ...calendar.filter(t => t.phase === 'upcoming').map(t => ({ start: startMs(t.start_time), tracked: t, announced: undefined as AnnouncedTournament | undefined })),
    ...announced.map(e => ({ start: startMs(e.start_time), tracked: undefined as CalendarTournamentResponse | undefined, announced: e })),
  ].sort((a, b) => a.start - b.start);
  const next = upcoming[0];
  if (!next) return lastCard ? <div>{lastCard}</div> : null;
  const nextCard = next.tracked ? (
    <FeaturedEvent
      name={next.tracked.name} type={next.tracked.tournament_type} region={next.tracked.region} startTime={next.tracked.start_time}
      pool={next.tracked.total_dividend_pool !== null ? toNumber(next.tracked.total_dividend_pool) : null}
      onOpen={() => openTournament(calendarToTournament(next.tracked!))}
    />
  ) : (
    <FeaturedEvent
      name={next.announced!.name} type={next.announced!.tournament_type} region={next.announced!.region} startTime={next.announced!.start_time}
      pool={next.announced!.total_dividend_pool !== null ? toNumber(next.announced!.total_dividend_pool) : null}
      note={!next.announced!.finals_confirmed ? 'Announced: the date may change until the Finals are published.' : undefined}
    />
  );
  return <div className="space-y-4">{nextCard}{lastCard}</div>;
}

type View = 'dividends' | 'open' | 'all';
const VIEW_KEY = 'forecast:tournament-view';
const VIEWS: { id: View; label: string; hint: string }[] = [
  { id: 'dividends', label: 'Pays dividends', hint: 'Tournaments that pay a dividend to the people who own the players in them.' },
  { id: 'open', label: 'Open rounds', hint: 'Open rounds anyone can enter. They pay nothing, but many lead into tournaments that do.' },
  { id: 'all', label: 'All', hint: 'Dividend tournaments and open rounds together. Open rounds are marked “No payout”.' },
];

const pad = (n: number) => String(n).padStart(2, '0');
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const addDays = (d: Date, n: number) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };

const PRESETS: { label: string; range: () => [string, string] }[] = [
  { label: 'Today', range: () => { const t = ymd(new Date()); return [t, t]; } },
  { label: 'Next 7 days', range: () => [ymd(new Date()), ymd(addDays(new Date(), 7))] },
  { label: 'Last 7 days', range: () => [ymd(addDays(new Date(), -7)), ymd(new Date())] },
  { label: 'Next 30 days', range: () => [ymd(new Date()), ymd(addDays(new Date(), 30))] },
  { label: 'Last 30 days', range: () => [ymd(addDays(new Date(), -30)), ymd(new Date())] },
];

// One list entry: a tracked tournament, an announced one, or an open round (no payout).
type Entry = { key: string; start: number; tracked?: CalendarTournamentResponse; announced?: AnnouncedTournament; open?: OpenRound };

export function Tournaments({ openTournament }: Props) {
  // Views: tournaments that pay dividends (default), the open rounds that pay nothing, or both together.
  // Dividend view: live events first (red), then the next event (big card), then everything still to come in date order,
  // then completed events (newest first). A search or a date range turns it into one flat, filtered list.
  const { data: calendar, loading } = useTournamentCalendar(true);
  const { data: announced } = useAnnouncedTournaments();

  const [view, setView] = useState<View>(() => {
    try { const v = localStorage.getItem(VIEW_KEY); return v === 'open' || v === 'all' ? v : 'dividends'; } catch { return 'dividends'; }
  });
  const chooseView = (v: View) => { setView(v); try { localStorage.setItem(VIEW_KEY, v); } catch { /* storage unavailable */ } };

  // Date range (inclusive, local calendar days, applied to the event's start time).
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const rangeActive = Boolean(from || to);
  const inRange = useCallback((iso: string | null) => {
    if (!from && !to) return true;
    if (!iso) return false;
    const t = new Date(iso).getTime();
    if (from && t < new Date(`${from}T00:00:00`).getTime()) return false;
    if (to && t > new Date(`${to}T23:59:59.999`).getTime()) return false;
    return true;
  }, [from, to]);

  const { rounds: openRounds, error: openError } = useOpenRounds(view === 'all');
  const [openedRound, setOpenedRound] = useState<OpenRound | null>(null);

  const toTournament = (t: CalendarTournamentResponse): TournamentResponse => ({
    id: t.id,
    name: t.name,
    tournament_type: t.tournament_type,
    region: t.region,
    start_time: t.start_time,
    end_time: t.end_time,
    prize_pool: t.total_dividend_pool,
    status: t.status,
    phase: t.phase,
    created_at: t.start_time ?? new Date().toISOString(),
  });

  // "Finalizing" (started, results still being confirmed) counts as live: same card, blank leaderboard until results arrive.
  const live = calendar.filter(t => t.phase === 'live' || t.phase === 'finalizing').sort((a, b) => startMs(a.start_time) - startMs(b.start_time));
  const completed = calendar.filter(t => t.phase === 'completed').sort((a, b) => startMs(b.start_time) - startMs(a.start_time));
  const upcoming: Entry[] = [
    ...calendar.filter(t => t.phase === 'upcoming').map(t => ({ key: t.id, start: startMs(t.start_time), tracked: t })),
    ...announced.map(e => ({ key: `a-${e.event_id}`, start: startMs(e.start_time), announced: e })),
  ].sort((a, b) => a.start - b.start);
  // A live event IS the current "next event", so the Next Event card only appears when nothing is live.
  const [next, laterDividend] = live.length > 0 ? [undefined, upcoming] : [upcoming[0], upcoming.slice(1)];

  const openEntries: Entry[] = view === 'all'
    ? (openRounds ?? []).map(r => ({ key: `o-${r.leaderboard_event_id}/${r.leaderboard_event_window_id}`, start: startMs(r.start_time), open: r }))
    : [];
  const openUpcoming = openEntries.filter(e => e.open!.status !== 'finished');
  const openFinished = openEntries.filter(e => e.open!.status === 'finished');
  const comingUp = [...laterDividend, ...openUpcoming].sort((a, b) => a.start - b.start);
  const completedAll: Entry[] = [...completed.map(t => ({ key: t.id, start: startMs(t.start_time), tracked: t })), ...openFinished].sort((a, b) => b.start - a.start);

  const rowFor = (u: Entry) =>
    u.tracked
      ? <CalendarRow key={u.key} tournament={u.tracked} onOpen={() => openTournament(toTournament(u.tracked!))} />
      : u.open
        ? <OpenRoundRow key={u.key} round={u.open} onOpen={() => setOpenedRound(u.open!)} />
        : <AnnouncedRow key={u.key} event={u.announced!} />;

  const empty = !loading && calendar.length === 0 && announced.length === 0 && view !== 'open';

  // Search (name, region or type) and the date range turn the page into one flat list: live, then what is still to come by
  // date, then finished events newest first. Open rounds are included in the All view.
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();
  const filtering = Boolean(q) || rangeActive;
  const matches = (name: string, region: string | null, type: string) =>
    !q || [tournamentDisplayName(name, region), name, region ?? '', TIER_LABELS[type] ?? type].some(s => s.toLowerCase().includes(q));
  const entryMatches = (e: Entry) =>
    e.tracked ? matches(e.tracked.name, e.tracked.region, e.tracked.tournament_type) && inRange(e.tracked.start_time)
    : e.announced ? matches(e.announced.name, e.announced.region, e.announced.tournament_type) && inRange(e.announced.start_time)
    : !q || roundName(e.open!).toLowerCase().includes(q) ? inRange(e.open!.start_time) : false;

  const flatNodes: React.ReactNode[] = filtering
    ? [
        ...live.filter(t => matches(t.name, t.region, t.tournament_type) && inRange(t.start_time)).map(t => (
          <CalendarRow key={t.id} tournament={t} onOpen={() => openTournament(toTournament(t))} />
        )),
        ...comingUp.filter(entryMatches).map(rowFor),
        ...completedAll.filter(entryMatches).map(rowFor),
      ]
    : [];

  const presetActive = (p: typeof PRESETS[number]) => { const [a, b] = p.range(); return from === a && to === b; };
  const chip = (active: boolean): React.CSSProperties => ({
    fontSize: 12, borderColor: active ? 'var(--primary)' : 'var(--border)',
    color: active ? 'var(--foreground)' : 'var(--muted-foreground)', background: active ? 'rgba(255,255,255,0.06)' : 'transparent',
  });
  const dateInput = 'px-2.5 py-1.5 rounded-lg border border-border text-foreground outline-none focus:border-primary/50';

  return (
    <div className="p-6 page-pad max-w-[900px] mx-auto space-y-4">
      <div>
        <div className="flex items-center gap-1.5">
          <h1 className="text-foreground font-bold" style={{ fontSize: 26 }}>Tournaments</h1>
          <HelpButton topic="tournaments" size={17} />
        </div>
        <p className="text-muted-foreground mt-0.5" style={{ fontSize: 14 }}>
          Dividends go to whoever owns a player when the tournament starts. Buying or selling after it starts does not change your payout.
        </p>
        <p className="text-muted-foreground mt-1" style={{ fontSize: 12 }}>
          Updates automatically as tournaments are tracked and results come in. Times are shown in your local time.
        </p>
      </div>

      {/* What to show: dividend tournaments, the no-payout open rounds, or both. */}
      <div>
        <div className="inline-flex flex-wrap gap-1.5" role="tablist" aria-label="Which tournaments to show">
          {VIEWS.map(v => (
            <button
              key={v.id} role="tab" aria-selected={view === v.id} onClick={() => chooseView(v.id)}
              className="px-3.5 py-1.5 rounded-full border font-semibold" style={chip(view === v.id)}
            >
              {v.label}
            </button>
          ))}
        </div>
        <p className="text-muted-foreground mt-1.5" style={{ fontSize: 12 }}>{VIEWS.find(v => v.id === view)!.hint}</p>
      </div>

      {/* Date range */}
      <div className="rounded-xl border border-border p-3 space-y-2" style={{ background: 'rgba(255,255,255,0.02)' }}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-muted-foreground font-semibold" style={{ fontSize: 12 }}>Date range</span>
          <label className="flex items-center gap-1.5 text-muted-foreground" style={{ fontSize: 12 }}>
            From
            <input type="date" value={from} max={to || undefined} onChange={e => setFrom(e.target.value)} aria-label="From date" className={dateInput} style={{ background: 'var(--card)', fontSize: 13 }} />
          </label>
          <label className="flex items-center gap-1.5 text-muted-foreground" style={{ fontSize: 12 }}>
            To
            <input type="date" value={to} min={from || undefined} onChange={e => setTo(e.target.value)} aria-label="To date" className={dateInput} style={{ background: 'var(--card)', fontSize: 13 }} />
          </label>
          {rangeActive && (
            <button onClick={() => { setFrom(''); setTo(''); }} className="px-2.5 py-1 rounded-full border border-border text-muted-foreground hover:text-foreground" style={{ fontSize: 12 }}>
              Clear
            </button>
          )}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {PRESETS.map(p => (
            <button key={p.label} onClick={() => { const [a, b] = p.range(); setFrom(a); setTo(b); }} className="px-3 py-1 rounded-full border" style={chip(presetActive(p))}>
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {view !== 'open' && (
        <input
          type="search"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search tournaments by name, region or type"
          aria-label="Search tournaments"
          className="w-full px-4 py-2.5 rounded-xl border border-border text-foreground outline-none transition-colors focus:border-primary/50"
          style={{ background: 'var(--card)', fontSize: 14 }}
        />
      )}

      {view === 'open' ? (
        <OpenRoundsSection inRange={inRange} />
      ) : (<>
        {loading && calendar.length === 0 && (
          <p className="text-muted-foreground text-center py-10" style={{ fontSize: 14 }}>Loading calendar…</p>
        )}
        {empty && (
          <p className="text-muted-foreground text-center py-10" style={{ fontSize: 14 }}>No tournaments announced yet — new ones are picked up automatically.</p>
        )}
        {view === 'all' && openRounds === null && !openError && (
          <p className="text-muted-foreground text-center" style={{ fontSize: 12.5 }}>Loading open rounds…</p>
        )}
        {view === 'all' && openError && <p className="text-center" style={{ fontSize: 12.5, color: 'var(--loss)' }}>{openError}</p>}

        {filtering ? (
          flatNodes.length > 0
            ? <div className="space-y-2.5">{flatNodes}</div>
            : <p className="text-muted-foreground text-center py-10" style={{ fontSize: 14 }}>
                Nothing matches{q ? ` “${query.trim()}”` : ''}{rangeActive ? ' in that date range' : ''}.
              </p>
        ) : (<>
          {live.map(t => <LiveEvent key={t.id} tournament={t} onOpen={() => openTournament(toTournament(t))} />)}

          {next && (
            next.tracked ? (
              <FeaturedEvent
                name={next.tracked.name} type={next.tracked.tournament_type} region={next.tracked.region}
                startTime={next.tracked.start_time}
                pool={next.tracked.total_dividend_pool !== null ? toNumber(next.tracked.total_dividend_pool) : null}
                onOpen={() => openTournament(toTournament(next.tracked!))}
              />
            ) : (
              <FeaturedEvent
                name={next.announced!.name} type={next.announced!.tournament_type} region={next.announced!.region}
                startTime={next.announced!.start_time}
                pool={next.announced!.total_dividend_pool !== null ? toNumber(next.announced!.total_dividend_pool) : null}
                note={!next.announced!.finals_confirmed ? 'Announced: the date may change until the Finals are published.' : undefined}
              />
            )
          )}

          {comingUp.length > 0 && (
            <div className="space-y-2.5">
              <p className="font-bold pt-1" style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>Coming up</p>
              {comingUp.map(rowFor)}
            </div>
          )}

          {completedAll.length > 0 && (
            <div className="space-y-2.5">
              <p className="font-bold pt-1" style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>Completed</p>
              {completedAll.map(rowFor)}
            </div>
          )}
        </>)}
      </>)}

      {openedRound && <RoundModal round={openedRound} onClose={() => setOpenedRound(null)} />}
    </div>
  );
}
