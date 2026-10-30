/**
 * DataTable's exports: the rows as the table sorts them, every row (not only
 * the ones scrolled into view), each column's raw value (a number stays a
 * number in XLSX). CSV is written here. XLSX comes from ./xlsx, loaded on
 * the first XLSX export. Internal to @karni/ui.
 */
import { saveBlob } from "../../hooks/useResourceImport";
import type { XlsxCell } from "./xlsx";

export type DataTableExportFormat = "csv" | "xlsx";

/** A cell as an export writes it: Dates as ISO text, everything else as it is. */
export function exportCell(value: unknown): XlsxCell {
  if (value === null || value === undefined) return null;
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "string") {
    return value;
  }
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value.toISOString();
  if (typeof value === "bigint") return value.toString();
  return JSON.stringify(value);
}

/** A spreadsheet runs a text cell that starts with one of these as a formula. */
const FORMULA_START = /^[=+\-@\t\r]/;

function csvField(value: XlsxCell): string {
  if (value === null || value === undefined) return "";
  let text = String(value);
  // Text that a spreadsheet would run as a formula is kept as text (OWASP CSV injection).
  if (typeof value === "string" && FORMULA_START.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** The UTF-8 byte order mark: Excel reads the file as UTF-8 only with it. */
const BOM = String.fromCharCode(0xfeff);

/** RFC 4180 CSV (CRLF line ends) with a UTF-8 byte order mark, so Excel reads accents. */
export function toCsv(
  headers: readonly string[],
  rows: ReadonlyArray<readonly XlsxCell[]>,
): string {
  const lines = [headers, ...rows].map((row) => row.map(csvField).join(","));
  return `${BOM}${lines.join("\r\n")}\r\n`;
}

/** A file name from a caption: "Revenue by region" → "revenue-by-region". */
export function exportFileName(base: string, format: DataTableExportFormat): string {
  const slug =
    base
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[^\w\s-]/g, "")
      .trim()
      .replace(/[\s_]+/g, "-")
      .replace(/-+/g, "-") || "table";
  return `${slug}.${format}`;
}

/** Writes the file and hands it to the browser. Resolves with the file name. */
export async function downloadTable(
  format: DataTableExportFormat,
  name: string,
  headers: readonly string[],
  rows: ReadonlyArray<readonly XlsxCell[]>,
): Promise<string> {
  const filename = exportFileName(name, format);
  if (format === "csv") {
    saveBlob(new Blob([toCsv(headers, rows)], { type: "text/csv;charset=utf-8" }), filename);
    return filename;
  }
  const { xlsxBytes, XLSX_TYPE } = await import("./xlsx");
  const bytes = xlsxBytes(name, headers, rows);
  saveBlob(new Blob([bytes], { type: XLSX_TYPE }), filename);
  return filename;
}
