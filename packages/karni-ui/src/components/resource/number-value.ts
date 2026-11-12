import { formatMoney } from "../../lib/money";
import type { FieldDef } from "../../schema/types";

/**
 * How a number reads in a detail row or a table cell: grouped for the
 * locale (`1,234`), except an id or a year, which read the way they are
 * written (`1234`, `2024`). An id is a field named `id`, the primary key in
 * Karni's generated serializers, and a year is a field named `year` or
 * ending in `_year`.
 */
export function formatNumberValue(field: Pick<FieldDef, "name">, value: number): string {
  const name = field.name;
  if (name === "id" || name === "year" || name.endsWith("_year")) return String(value);
  return value.toLocaleString();
}

/**
 * Experimental. The currency of a money field's value: its fixed currency, or
 * the row's `currencyField`. `undefined` when the field is not money or the
 * row does not say.
 */
export function moneyCurrency(
  field: Pick<FieldDef, "money">,
  row?: Readonly<Record<string, unknown>> | null,
): string | undefined {
  const money = field.money;
  if (money === undefined) return undefined;
  if (money.currency) return money.currency;
  const found = money.currencyField !== undefined ? row?.[money.currencyField] : undefined;
  return typeof found === "string" && found !== "" ? found : undefined;
}

/**
 * Experimental. A money field's value as people read it (`$1,234.50`), or
 * `null` when the field is not money or its currency is not known.
 */
export function formatMoneyValue(
  field: Pick<FieldDef, "money">,
  value: unknown,
  row?: Readonly<Record<string, unknown>> | null,
): string | null {
  const currency = moneyCurrency(field, row);
  if (currency === undefined || (typeof value !== "string" && typeof value !== "number")) {
    return null;
  }
  return formatMoney(value, currency);
}
