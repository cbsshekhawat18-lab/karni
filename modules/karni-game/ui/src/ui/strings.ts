/**
 * Every word the kit shows. Replace any of them (or all, for another
 * language) with the `strings` option of `createUi`. `{name}` marks a value
 * the kit fills in.
 */
export const defaultStrings = {
  ok: "OK",
  cancel: "Cancel",
  close: "Close",
  yes: "Yes",
  no: "No",
  dismiss: "Dismiss",
  notifications: "Notifications",

  settingsTitle: "Settings",
  soundHeading: "Sound",
  volumeMaster: "Master volume",
  volumeMusic: "Music volume",
  volumeEffects: "Effects volume",
  volumeValue: "{value}%",
  mute: "Mute all sound",
  displayHeading: "Display",
  reducedMotion: "Reduced motion",
  reducedMotionHint: "Fewer movements, shakes and fades.",
  colourSafe: "Colour-safe palette",
  colourSafeHint: "Colours that stay apart for colour blindness.",
  controlsHeading: "Controls",
  controlsHint: "Choose a control, then press the key you want.",
  controlNone: "No key",
  controlPress: "Press a key (Escape to cancel)",
  controlSet: "{action} is now {key}",
  controlTaken: "{key} was {action}, which now has no key",
  controlsReset: "Reset controls",
  controlsWereReset: "Controls were reset",

  pauseTitle: "Paused",
  resume: "Resume",
  settings: "Settings",
  quit: "Quit",
  quitTitle: "Quit the game?",
  quitMessage: "Progress that was not saved is lost.",

  bootFailedTitle: "The game could not start",
  bootFailedMessage: "Something went wrong while it was starting. You can try again.",
  retry: "Try again",
  details: "Details",

  touchControls: "Touch controls",

  devFrame: "frame",
  devSteps: "steps",
  devEntities: "entities",

  keyPointer: "Click or tap",
  keySpace: "Space",
  keyEnter: "Enter",
  keyEscape: "Escape",
  keyTab: "Tab",
  keyShift: "Shift",
  keyControl: "Control",
  keyAlt: "Alt",
  keyBackspace: "Backspace",
  keyArrowUp: "Up arrow",
  keyArrowDown: "Down arrow",
  keyArrowLeft: "Left arrow",
  keyArrowRight: "Right arrow",
} as const;

export type StringKey = keyof typeof defaultStrings;
export type Strings = Record<StringKey, string>;

/** Translates a key, filling `{name}` with the values given. */
export type Translate = (key: StringKey, values?: Record<string, string | number>) => string;

export function createTranslate(overrides: Partial<Strings> = {}): Translate {
  const table: Strings = { ...defaultStrings, ...overrides };
  return (key, values) =>
    table[key].replace(/\{(\w+)\}/g, (whole, name: string) =>
      values && name in values ? String(values[name]) : whole,
    );
}

/** A readable name for a `KeyboardEvent.code` ("KeyW" is "W", "ArrowUp" is "Up arrow"). */
export function keyName(code: string, t: Translate): string {
  if (code === "Pointer") return t("keyPointer");
  if (/^Key[A-Z]$/.test(code)) return code.slice(3);
  if (/^Digit\d$/.test(code)) return code.slice(5);
  if (/^Numpad\d$/.test(code)) return `Numpad ${code.slice(6)}`;
  const named: Record<string, StringKey> = {
    Space: "keySpace",
    Enter: "keyEnter",
    Escape: "keyEscape",
    Tab: "keyTab",
    Backspace: "keyBackspace",
    ArrowUp: "keyArrowUp",
    ArrowDown: "keyArrowDown",
    ArrowLeft: "keyArrowLeft",
    ArrowRight: "keyArrowRight",
  };
  const key = named[code];
  if (key) return t(key);
  if (/^Shift(Left|Right)$/.test(code)) return t("keyShift");
  if (/^Control(Left|Right)$/.test(code)) return t("keyControl");
  if (/^Alt(Left|Right)$/.test(code)) return t("keyAlt");
  return code;
}
