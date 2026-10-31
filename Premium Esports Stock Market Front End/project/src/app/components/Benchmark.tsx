import { useBenchmark } from '../lib/hooks';

const compact = (v: number) =>
  v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : `$${Math.round(v).toLocaleString('en-US')}`;

/** The market's projected growth rate, computed live from the real numbers (dividends over the next 12 months per dollar
 * of market value). Falls back to the 10% design target if it can't be loaded. */
export function useBenchmarkPct(): { pct: string; dividends: string | null; value: string | null } {
  const { data } = useBenchmark();
  if (!data || !data.market_value) return { pct: '10%', dividends: null, value: null };
  return {
    pct: `${(data.dividend_growth_rate * 100).toFixed(1)}%`,
    dividends: compact(data.projected_dividends_per_year),
    value: compact(data.market_value),
  };
}

export function BenchmarkText() {
  const { pct, dividends, value } = useBenchmarkPct();
  return (
    <>
      Tournament dividends keep adding money to the game, and new players bring their starting cash too. From dividends alone
      the market is projected to grow about <strong>{pct} a year</strong>
      {dividends && value ? <> ({dividends} of projected dividends on {value} of player value)</> : null}.
      Think of that as the market&rsquo;s return: if your portfolio grows faster than {pct} a year, you are beating the market.
    </>
  );
}
