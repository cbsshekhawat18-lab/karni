type Child = Node | string | null | undefined | false;

/** Make an element: `el("button", { class: "kg-btn", type: "button" }, "OK")`. */
export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attributes: Record<string, string | undefined> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (value !== undefined) node.setAttribute(name, value);
  }
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child);
  }
  return node;
}

const FOCUSABLE =
  'a[href], button, input, select, textarea, summary, [tabindex]:not([tabindex="-1"])';

/** The elements inside `root` that Tab can reach, in order. */
export function focusables(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (node) =>
      !node.hasAttribute("disabled") &&
      !node.closest("[inert]") &&
      node.getAttribute("aria-hidden") !== "true" &&
      !(node instanceof HTMLInputElement && node.type === "hidden"),
  );
}

let counter = 0;
/** A unique id for a label or a description. */
export function uid(prefix = "kg"): string {
  counter += 1;
  return `${prefix}-${counter}`;
}
