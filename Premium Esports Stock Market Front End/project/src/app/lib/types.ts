// TypeScript mirrors of forecast-backend's Pydantic response schemas.
// Kept intentionally minimal -- only fields the backend actually returns.
// See forecast-backend/app/schemas/*.py for the source of truth.
//
// Money fields (Decimal on the backend) are typed `Money` (number | string)
// rather than assuming one JSON representation: this codebase was never
// run against a live server while being written (no database available in
// the build environment), and Pydantic's default Decimal-to-JSON encoding
// depends on config that wasn't verified end-to-end. `toNumber()` below
// handles either shape safely -- if you confirm one way or the other once
// this is running against a real backend, this comment (and the union
// type) can be narrowed.
export type Money = number | string;

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  role: string;
}

export interface WalletResponse {
  id: string;
  user_id: string;
  cash_balance: Money;
  held_balance: Money;
  available_balance: Money;
}

export interface MarketSnapshot {
  id: string;
  gamertag: string;
  real_name: string | null;
  team: string | null;
  region: string | null;
  total_shares_outstanding: number;
  ipo_price: Money;
  last_price: Money;
  prev_close: Money;
  change: Money;
  change_pct: Money;
  volume_24h: number;
  market_cap: Money;
}

export interface PriceHistoryPoint {
  price: Money;
  volume: number;
  recorded_at: string;
}

export interface PositionResponse {
  player_id: string;
  quantity: number;
  held_quantity: number;
  available_quantity: number;
  average_cost: Money;
}

export interface OrderResponse {
  id: string;
  user_id: string;
  player_id: string;
  side: 'buy' | 'sell';
  order_kind: 'limit' | 'quick';
  limit_price: Money | null;
  quantity: number;
  filled_quantity: number;
  status: 'open' | 'partially_filled' | 'filled' | 'cancelled' | 'rejected';
  is_bot: boolean;
  created_at: string;
}

export interface TradeResponse {
  id: string;
  player_id: string;
  price: Money;
  quantity: number;
  buyer_user_id: string | null;
  seller_user_id: string | null;
  buyer_is_bot: boolean;
  seller_is_bot: boolean;
  executed_at: string;
}

export interface TournamentResponse {
  id: string;
  name: string;
  tournament_type: 'cash_cup' | 'fncs_qualifier' | 'fncs_finals' | 'global_championship' | 'major' | 'other';
  region: string | null;
  start_time: string | null;
  end_time: string | null;
  prize_pool: Money | null;
  status: 'scheduled' | 'results_pending' | 'finalized';
  created_at: string;
}

export interface LiveLeaderboardEntry {
  player_id: string;
  gamertag: string;
  placement: number;
  points: Money | null;
}

export interface LiveLeaderboardResponse {
  tournament_id: string;
  tournament_name: string;
  tournament_status: 'scheduled' | 'results_pending' | 'finalized';
  is_osirion_tracked: boolean;
  window_end_time: string | null;
  last_synced_at: string | null;
  entries: LiveLeaderboardEntry[];
}

export interface LeaderboardEntry {
  rank: number;
  user_id: string;
  display_name: string;
  cash_balance: Money;
  holdings_value: Money;
  portfolio_value: Money;
}

// Portfolio-value-over-time point, for ValueChart.tsx. NOTE: the real
// backend does not currently expose a portfolio value history/snapshot
// endpoint (see forecast-backend/app/api/v1) -- this type exists so
// ValueChart itself can be ported and reused once such an endpoint
// exists, but nothing in this app currently fetches real data into it.
// Do not synthesize fake history client-side; leave callers without a
// real data source omitted instead.
export interface ValueHistoryPoint {
  recorded_at: string;
  value: Money;
}

// Every money field above goes through this instead of a raw parseFloat
// call, so the one place that would need to change (if the backend turns
// out to serialize Decimal as a JSON number vs. a string) is here.
export function toNumber(value: Money | null | undefined): number {
  if (value === null || value === undefined) return 0;
  if (typeof value === 'number') return value;
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}
