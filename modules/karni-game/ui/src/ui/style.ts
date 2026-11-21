/**
 * The kit's stylesheet. Colours are custom properties on `.kg-ui`, so a game
 * restyles the kit by setting them (`--kg-accent`, `--kg-bg`...). Light is the
 * default, dark follows `prefers-color-scheme`, and `data-kg-theme="light"` or
 * `"dark"` on the root forces one. Text on every surface keeps a contrast of at
 * least 4.5 to 1 in both.
 */
const LIGHT = `
  --kg-bg: #ffffff;
  --kg-fg: #17202e;
  --kg-muted: #46536a;
  --kg-line: #6b7789;
  --kg-field: #eef1f6;
  --kg-accent: #1a47c8;
  --kg-accent-fg: #ffffff;
  --kg-danger: #a8261b;
  --kg-danger-fg: #ffffff;
  --kg-scrim: rgba(13, 22, 38, 0.6);
  --kg-focus: #1a47c8;
`;
const DARK = `
  --kg-bg: #172236;
  --kg-fg: #f2f5fa;
  --kg-muted: #b9c4d6;
  --kg-line: #7b89a3;
  --kg-field: #22314b;
  --kg-accent: #8db4ff;
  --kg-accent-fg: #0a1222;
  --kg-danger: #ffa79c;
  --kg-danger-fg: #2a0a06;
  --kg-scrim: rgba(3, 8, 18, 0.7);
  --kg-focus: #ffd166;
`;
/** Blue and vermillion from the Okabe-Ito set: they stay apart for the common kinds of colour blindness. */
const SAFE_LIGHT = `--kg-accent: #00629c; --kg-danger: #a33f00; --kg-focus: #00629c;`;
const SAFE_DARK = `--kg-accent: #6cc0f2; --kg-danger: #ffb27a; --kg-focus: #f0e442;`;

export const STYLE_ID = "kg-ui-style";

export const css = `
.kg-ui { ${LIGHT} font: 16px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--kg-fg); box-sizing: border-box; }
@media (prefers-color-scheme: dark) { .kg-ui:not([data-kg-theme="light"]) { ${DARK} } }
.kg-ui[data-kg-theme="dark"] { ${DARK} }
.kg-ui[data-kg-palette="safe"] { ${SAFE_LIGHT} }
@media (prefers-color-scheme: dark) { .kg-ui[data-kg-palette="safe"]:not([data-kg-theme="light"]) { ${SAFE_DARK} } }
.kg-ui[data-kg-palette="safe"][data-kg-theme="dark"] { ${SAFE_DARK} }
.kg-ui *, .kg-ui *::before, .kg-ui *::after { box-sizing: inherit; }
.kg-root { -webkit-tap-highlight-color: transparent; -webkit-user-select: none; user-select: none; position: absolute; inset: 0; z-index: 10; overflow: hidden; pointer-events: none; }
.kg-root[data-kg-fixed] { position: fixed; }
.kg-hud { position: absolute; inset: 0; pointer-events: none; }

.kg-modal { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; padding: 16px; background: var(--kg-scrim); pointer-events: auto; }
.kg-dialog { display: flex; flex-direction: column; width: min(440px, 100%); max-height: 100%; overflow: hidden; overflow-wrap: anywhere; padding: 20px; border: 1px solid var(--kg-line); border-radius: 12px; background: var(--kg-bg); color: var(--kg-fg); }
.kg-dialog h2, .kg-screen h2, .kg-boot h1 { margin: 0 0 8px; font-size: 1.35rem; line-height: 1.2; }
.kg-dialog p, .kg-screen p, .kg-boot p { margin: 0 0 12px; }
.kg-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain; margin: 0 -6px; padding: 0 6px; }
.kg-dialog h2, .kg-panel h2 { flex: 0 0 auto; }
.kg-dialog .kg-actions, .kg-panel .kg-actions { flex: 0 0 auto; }
.kg-hint { color: var(--kg-muted); font-size: 0.875rem; }
.kg-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.kg-actions > .kg-btn { flex: 1 1 8rem; }

.kg-btn { min-width: 44px; min-height: 44px; padding: 8px 16px; border: 1px solid var(--kg-line); border-radius: 8px; background: var(--kg-field); color: var(--kg-fg); font: inherit; font-weight: 600; cursor: pointer; touch-action: manipulation; }
.kg-btn:hover { border-color: var(--kg-fg); }
.kg-btn[data-kg-primary] { background: var(--kg-accent); border-color: var(--kg-accent); color: var(--kg-accent-fg); }
.kg-btn[data-kg-danger] { background: var(--kg-danger); border-color: var(--kg-danger); color: var(--kg-danger-fg); }
.kg-ui :focus-visible { outline: 3px solid var(--kg-focus); outline-offset: 2px; }

.kg-screen { position: absolute; inset: 0; display: flex; padding: 16px; pointer-events: none; align-items: center; justify-content: center; }
.kg-screen[data-kg-align="bottom"] { align-items: flex-end; }
.kg-panel { display: flex; flex-direction: column; width: min(380px, 100%); max-height: 100%; overflow: hidden; overflow-wrap: anywhere; padding: 20px; border: 1px solid var(--kg-line); border-radius: 12px; background: var(--kg-bg); color: var(--kg-fg); pointer-events: auto; text-align: center; }
.kg-panel .kg-actions { flex-direction: column; }
.kg-panel .kg-actions > .kg-btn { flex: 0 0 auto; }

.kg-group { margin: 0 0 16px; padding: 0; border: 0; }
.kg-group > legend { margin: 0 0 8px; padding: 0; font-weight: 700; }
.kg-row { display: flex; align-items: center; gap: 12px; min-height: 44px; }
.kg-row > label, .kg-row > .kg-label { flex: 1 1 auto; min-width: 0; }
.kg-slider > label { flex: 0 0 6.5rem; }
.kg-row input[type="range"] { flex: 1 1 auto; min-width: 0; width: 100%; min-height: 44px; accent-color: var(--kg-accent); }
.kg-row output { flex: 0 0 3.5rem; text-align: right; font-variant-numeric: tabular-nums; }
.kg-row input[type="checkbox"] { flex: 0 0 auto; width: 24px; height: 24px; accent-color: var(--kg-accent); }
.kg-row .kg-btn { flex: 1 1 auto; text-align: left; }
.kg-row .kg-btn[aria-pressed="true"] { background: var(--kg-accent); border-color: var(--kg-accent); color: var(--kg-accent-fg); }

.kg-toasts { position: absolute; left: 0; right: 0; top: 0; display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 12px 16px; pointer-events: none; }
.kg-toast { display: flex; align-items: center; gap: 8px; max-width: 100%; padding: 4px 4px 4px 14px; border: 1px solid var(--kg-line); border-radius: 10px; background: var(--kg-bg); color: var(--kg-fg); overflow-wrap: anywhere; pointer-events: auto; animation: kg-in 0.18s ease-out; }
.kg-toast[data-kg-kind="error"] { border-color: var(--kg-danger); }
.kg-toast[data-kg-kind="error"] .kg-toast-text::before { content: "! "; font-weight: 800; color: var(--kg-danger); }
.kg-toast .kg-btn { min-height: 44px; padding: 4px 12px; background: transparent; border-color: transparent; }

.kg-touch { position: absolute; left: 0; right: 0; bottom: 0; display: none; justify-content: space-between; align-items: flex-end; gap: 12px; padding: 16px; padding-bottom: max(16px, env(safe-area-inset-bottom)); pointer-events: none; }
.kg-touch[data-kg-show] { display: flex; }
@media (pointer: coarse) { .kg-touch:not([data-kg-hide]) { display: flex; } }
.kg-touch-group { display: flex; gap: 12px; pointer-events: none; }
.kg-touch .kg-btn { min-width: 64px; min-height: 64px; border-radius: 32px; font-size: 1rem; opacity: 0.88; pointer-events: auto; touch-action: none; user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; background: var(--kg-bg); }
.kg-touch .kg-btn[data-kg-down] { background: var(--kg-accent); color: var(--kg-accent-fg); border-color: var(--kg-accent); opacity: 1; }

.kg-boot { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: 16px; background: var(--kg-bg); color: var(--kg-fg); overflow: auto; }
.kg-boot-card { width: min(480px, 100%); overflow-wrap: anywhere; }
.kg-boot details { margin: 12px 0; }
.kg-boot pre { margin: 8px 0 0; padding: 8px; max-height: 12rem; overflow: auto; border-radius: 8px; background: var(--kg-field); color: var(--kg-fg); font-size: 0.8125rem; white-space: pre-wrap; }

.kg-dev { position: absolute; left: 8px; top: 8px; padding: 4px 8px; border-radius: 6px; background: var(--kg-bg); color: var(--kg-fg); border: 1px solid var(--kg-line); font: 12px/1.3 ui-monospace, monospace; pointer-events: none; white-space: pre; }

@keyframes kg-in { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) { .kg-ui .kg-toast { animation: none; } }
.kg-ui[data-kg-motion="reduced"] .kg-toast { animation: none; }
`;

/** Put the stylesheet in the page once. A second call (or a second kit) finds it and does nothing. */
export function ensureStyles(doc: Document = document): void {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement("style");
  style.id = STYLE_ID;
  style.textContent = css;
  doc.head.appendChild(style);
}
