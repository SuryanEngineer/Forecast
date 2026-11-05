// One place for how money is written on the site: always a dollar sign, thousands commas, and exactly two decimals
// ($1,234.00, never $1234 or $1234.5). Compact forms like $1.5M are only for chart axes and tight labels.

const TWO = { minimumFractionDigits: 2, maximumFractionDigits: 2 } as const;

/** $1,234.50. Negative numbers come out as -$1,234.50. */
export function usd(n: number): string {
  const v = Number.isFinite(n) ? n : 0;
  const body = Math.abs(v).toLocaleString('en-US', TWO);
  return `${v < 0 && Number(body.replace(/,/g, '')) !== 0 ? '-' : ''}$${body}`;
}

/** +$1,234.50 / -$1,234.50 (zero gets a plus sign). */
export function usdSigned(n: number): string {
  const v = Number.isFinite(n) ? n : 0;
  const body = Math.abs(v).toLocaleString('en-US', TWO);
  return `${v < 0 && Number(body.replace(/,/g, '')) !== 0 ? '-' : '+'}$${body}`;
}

/** A per-share payout: at least two decimals, up to four for tiny amounts ($0.0125). */
export function usdPerShare(n: number): string {
  return `$${(Number.isFinite(n) ? n : 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
}
