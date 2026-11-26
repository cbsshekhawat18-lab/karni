import { formatMoney } from "../../lib/money";
import type { FieldDef } from "../../schema/types";

/**
 * How a number reads in a detail row or a table cell: grouped for the
 * locale (`1,234`), except an id, a year or a number people quote, which
 * read the way they are written (`1234`, `2024`, order `1027`). That is a
 * field named `id`, `year` or `number`, or ending in `_year` or `_number`.
 */
export function formatNumberValue(field: Pick<FieldDef, "name">, value: number): string {
  return WRITTEN.test(field.name) ? String(value) : value.toLocaleString();
}

const WRITTEN = /^(id|year|number)$|_(year|number)$/;

/**
 * The currency of a money field's value: its fixed currency, or
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
 * A money field's value as people read it (`$1,234.50`), or
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
