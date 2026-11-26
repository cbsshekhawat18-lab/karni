/**
 * Experimental. `formatMoney("1234.5000", "USD")` is `$1,234.50`: an amount as people read it.
 *
 * The API sends money as a decimal string with four places (`"60.0000"`).
 * This rounds it to the currency's own digits with `Intl.NumberFormat`, in
 * the browser's language unless `locale` says otherwise. A value that is not
 * a number comes back as it was, and `null` as an empty string.
 *
 * Override / escape hatch: pass `locale`, or `options` for any
 * `Intl.NumberFormat` option (`currencyDisplay: "code"`).
 */
export function formatMoney(
  value: string | number | null | undefined,
  currency: string,
  locale?: string,
  options?: Intl.NumberFormatOptions,
): string {
  if (value === null || value === undefined || value === "") return "";
  const amount = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(amount)) return String(value);
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency: currency.toUpperCase(),
      ...options,
    }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency.toUpperCase()}`;
  }
}
