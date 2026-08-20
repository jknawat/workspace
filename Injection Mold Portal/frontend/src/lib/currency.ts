// Thin space between the baht sign and the digits — in tabular/mono
// numerals ฿ sits flush against the first digit without it.
const GAP = " ";

/** Whole-baht formatting for totals: ฿ 12,345 */
export function formatThb(amount: number): string {
  return `฿${GAP}${Math.round(amount).toLocaleString("en-US")}`;
}

/** Precise formatting for small per-part unit prices: ฿ 73.43 */
export function formatThbPrecise(amount: number, decimals = 2): string {
  return `฿${GAP}${amount.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
}
