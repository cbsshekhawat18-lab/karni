import type { FieldDef } from "../../schema/types";

/**
 * How a number reads in a detail row or a table cell: grouped for the
 * locale (`1,234`), except an id, which reads the way it is written in a URL
 * or a search (`1234`). An id is a field named `id`, which is the primary
 * key in Karni's generated serializers, with either key type.
 */
export function formatNumberValue(field: Pick<FieldDef, "name">, value: number): string {
  return field.name === "id" ? String(value) : value.toLocaleString();
}
