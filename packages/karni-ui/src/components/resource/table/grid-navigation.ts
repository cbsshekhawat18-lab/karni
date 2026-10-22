/**
 * ResourceTable's keyboard model in the table layout: the WAI-ARIA grid
 * pattern with a roving tabindex. The whole table is one Tab stop. The arrow
 * keys move between rows and cells, Home and End to the ends of a row, and
 * Ctrl+Home and Ctrl+End to the first and last cell of the grid.
 *
 * The stops are read from the DOM, so any cell content works: a cell that
 * holds controls (a checkbox, the row's button, links, the row actions, a
 * menu trigger) puts each control in the row's arrow order, and a cell
 * without one is a stop itself. Exactly one stop has tabindex 0 (the last
 * one focused). Every other stop has -1, and a MutationObserver keeps it so
 * when rows, pages or cell content change. Internal to @karni/ui.
 */
import * as React from "react";

/** What can take focus inside a cell. */
const CONTROL_SELECTOR = [
  "a[href]",
  "button",
  "input",
  "select",
  "textarea",
  "summary",
  "iframe",
  "audio[controls]",
  "video[controls]",
  '[contenteditable=""]',
  '[contenteditable="true"]',
  "[tabindex]",
].join(", ");

/** Controls that use the arrow keys themselves, so the grid leaves them alone. */
const FIELD_SELECTOR =
  'input:not([type="checkbox"]):not([type="radio"]):not([type="button"]):not([type="submit"]):not([type="reset"]), textarea, select, [contenteditable=""], [contenteditable="true"]';

/** Whether a control can take focus: not disabled, and not hidden inside its cell. */
function usable(element: HTMLElement, cell: HTMLTableCellElement): boolean {
  if (element.matches(":disabled")) return false;
  if (element instanceof HTMLInputElement && element.type === "hidden") return false;
  // Up to the cell only: a dialog hides the page around it with aria-hidden for a while.
  for (let node: HTMLElement | null = element; node !== null && node !== cell;) {
    if (node.hidden || node.hasAttribute("inert") || node.getAttribute("aria-hidden") === "true") {
      return false;
    }
    node = node.parentElement;
  }
  return true;
}

/** The controls of one cell, outermost only (a button's inner focusable is not a second stop). */
function controlsOf(cell: HTMLTableCellElement): HTMLElement[] {
  const found = Array.from(cell.querySelectorAll<HTMLElement>(CONTROL_SELECTOR)).filter((element) =>
    usable(element, cell),
  );
  return found.filter(
    (element) => !found.some((other) => other !== element && other.contains(element)),
  );
}

/** A cell's stop number `index`: its control at that position (clamped), or the cell itself. */
function stopIn(cell: HTMLTableCellElement, index: number): HTMLElement {
  const controls = controlsOf(cell);
  if (controls.length === 0) return cell;
  return controls[Math.min(index, controls.length - 1)] ?? cell;
}

/** Every stop of a row, left to right. */
function stopsOf(row: HTMLTableRowElement): HTMLElement[] {
  return Array.from(row.cells).flatMap((cell) => {
    const controls = controlsOf(cell);
    return controls.length === 0 ? [cell] : controls;
  });
}

interface Position {
  row: HTMLTableRowElement;
  rowIndex: number;
  cell: HTMLTableCellElement;
  cellIndex: number;
  /** Which control of the cell (0 for a cell without controls). */
  control: number;
  stop: HTMLElement;
}

/** Where an element sits in the grid, or null when it is not in one of its cells. */
function locate(table: HTMLTableElement, element: Element): Position | null {
  const cell = element.closest("td, th");
  if (!(cell instanceof HTMLTableCellElement)) return null;
  const row = cell.parentElement;
  if (!(row instanceof HTMLTableRowElement) || row.closest("table") !== table) return null;
  const controls = controlsOf(cell);
  const control = controls.findIndex((candidate) => candidate.contains(element));
  const stop = controls[control] ?? cell;
  return {
    row,
    rowIndex: row.rowIndex,
    cell,
    cellIndex: cell.cellIndex,
    control: Math.max(control, 0),
    stop,
  };
}

/** The remembered stop, by row id, then by the same place when its row is gone. */
interface Memory {
  stop: HTMLElement | null;
  rowId: string | null;
  rowIndex: number;
  cellIndex: number;
  control: number;
}

/** The row attribute that names a row across renders (TableView sets it to the row id). */
const ROW_ID_ATTRIBUTE = "data-row-id";

function resolve(table: HTMLTableElement, memory: Memory): HTMLElement | null {
  if (memory.stop !== null && memory.stop.isConnected && table.contains(memory.stop)) {
    const position = locate(table, memory.stop);
    if (position !== null && position.stop === memory.stop) return memory.stop;
  }
  const rows = Array.from(table.rows);
  if (rows.length === 0) return null;
  const byId =
    memory.rowId === null
      ? undefined
      : rows.find((row) => row.getAttribute(ROW_ID_ATTRIBUTE) === memory.rowId);
  const row = byId ?? rows[Math.min(memory.rowIndex, rows.length - 1)];
  if (row === undefined || row.cells.length === 0) return null;
  const cell = row.cells[Math.min(memory.cellIndex, row.cells.length - 1)];
  return cell === undefined ? null : stopIn(cell, memory.control);
}

function remember(table: HTMLTableElement, memory: Memory, element: Element): HTMLElement | null {
  const position = locate(table, element);
  if (position === null) return null;
  memory.stop = position.stop;
  memory.rowId = position.row.getAttribute(ROW_ID_ATTRIBUTE);
  memory.rowIndex = position.rowIndex;
  memory.cellIndex = position.cellIndex;
  memory.control = position.control;
  return position.stop;
}

/** Gives the active stop tabindex 0 and every other stop -1. */
function sync(table: HTMLTableElement, memory: Memory): void {
  const active = resolve(table, memory);
  // Its row may have moved (a sort): remember where it is now.
  if (active !== null) remember(table, memory, active);
  for (const row of Array.from(table.rows)) {
    for (const cell of Array.from(row.cells)) {
      const controls = controlsOf(cell);
      if (controls.length === 0) {
        setTabIndex(cell, cell === active ? 0 : -1);
      } else {
        // A cell with controls is not a stop of its own.
        if (cell.hasAttribute("tabindex")) cell.removeAttribute("tabindex");
        for (const control of controls) setTabIndex(control, control === active ? 0 : -1);
      }
    }
  }
}

function setTabIndex(element: HTMLElement, value: 0 | -1): void {
  const text = String(value);
  if (element.getAttribute("tabindex") !== text) element.setAttribute("tabindex", text);
}

/** Where a navigation key goes from `from`, or null at the edge of the grid. */
function nextStop(
  table: HTMLTableElement,
  from: Position,
  event: React.KeyboardEvent,
): HTMLElement | null {
  const rows = Array.from(table.rows);
  const stops = stopsOf(from.row);
  const index = stops.indexOf(from.stop);
  const toRow = (row: HTMLTableRowElement | undefined): HTMLElement | null => {
    if (row === undefined || row.cells.length === 0) return null;
    const cell = row.cells[Math.min(from.cellIndex, row.cells.length - 1)];
    return cell === undefined ? null : stopIn(cell, from.control);
  };
  const toGridCorner = event.ctrlKey || event.metaKey;
  switch (event.key) {
    case "ArrowRight":
      return stops[index + 1] ?? null;
    case "ArrowLeft":
      return index > 0 ? (stops[index - 1] ?? null) : null;
    case "ArrowDown":
      return toRow(rows[from.rowIndex + 1]);
    case "ArrowUp":
      return from.rowIndex > 0 ? toRow(rows[from.rowIndex - 1]) : null;
    case "Home": {
      const row = toGridCorner ? rows[0] : from.row;
      return row === undefined ? null : (stopsOf(row)[0] ?? null);
    }
    case "End": {
      const row = toGridCorner ? rows[rows.length - 1] : from.row;
      return row === undefined ? null : (stopsOf(row).at(-1) ?? null);
    }
    default:
      return null;
  }
}

/** useLayoutEffect warns during server rendering, where there is no DOM to sync. */
const useIsomorphicLayoutEffect =
  typeof window === "undefined" ? React.useEffect : React.useLayoutEffect;

const NAVIGATION_KEYS = new Set(["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp", "Home", "End"]);

export interface GridNavigation {
  onKeyDown: (event: React.KeyboardEvent<HTMLTableElement>) => void;
  onFocus: (event: React.FocusEvent<HTMLTableElement>) => void;
}

/**
 * The roving tabindex of a table. Returns the handlers for the <table>. When
 * `enabled` is false they do nothing and the table is left as rendered.
 */
export function useGridNavigation(
  tableRef: React.RefObject<HTMLTableElement>,
  enabled: boolean,
): GridNavigation {
  // Enter the grid at its first body row (the header row when there is none).
  const memory = React.useRef<Memory>({
    stop: null,
    rowId: null,
    rowIndex: 1,
    cellIndex: 0,
    control: 0,
  });

  useIsomorphicLayoutEffect(() => {
    const table = tableRef.current;
    if (!enabled || table === null) return undefined;
    sync(table, memory.current);
    // Rows, pages and cell content change without this hook's knowledge.
    const observer = new MutationObserver(() => sync(table, memory.current));
    observer.observe(table, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["disabled", "hidden", "inert", "aria-hidden", "href"],
    });
    return () => observer.disconnect();
  }, [enabled, tableRef]);

  const onFocus = React.useCallback(
    (event: React.FocusEvent<HTMLTableElement>) => {
      if (!enabled) return;
      const table = event.currentTarget;
      if (!(event.target instanceof Element) || !table.contains(event.target)) return;
      // A click, a script or a closing dialog put focus here: Tab comes back to it.
      const before = memory.current.stop;
      const stop = remember(table, memory.current, event.target);
      if (stop !== null && (stop !== before || stop.getAttribute("tabindex") !== "0")) {
        sync(table, memory.current);
      }
    },
    [enabled],
  );

  const onKeyDown = React.useCallback(
    (event: React.KeyboardEvent<HTMLTableElement>) => {
      if (!enabled || event.defaultPrevented || event.altKey) return;
      if (!NAVIGATION_KEYS.has(event.key)) return;
      const table = event.currentTarget;
      const element = event.target;
      // Keys from a menu portalled out of a cell reach here through React: not ours.
      if (!(element instanceof HTMLElement) || !table.contains(element)) return;
      // A text field inside a cell keeps its arrows (Tab leaves it).
      if (element.matches(FIELD_SELECTOR)) return;
      const from = locate(table, element);
      if (from === null) return;
      event.preventDefault();
      const next = nextStop(table, from, event);
      if (next === null) return;
      remember(table, memory.current, next);
      sync(table, memory.current);
      next.focus();
    },
    [enabled],
  );

  return { onKeyDown, onFocus };
}
