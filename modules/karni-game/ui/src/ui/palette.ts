/**
 * Eight colours that stay apart for the common kinds of colour blindness
 * (the Okabe-Ito set). Draw with these when the settings ask for the
 * colour-safe palette: `settings.colourSafe ? COLOUR_SAFE.blue : "#4a90d9"`.
 */
export const COLOUR_SAFE = {
  black: "#000000",
  orange: "#e69f00",
  skyBlue: "#56b4e9",
  green: "#009e73",
  yellow: "#f0e442",
  blue: "#0072b2",
  vermillion: "#d55e00",
  purple: "#cc79a7",
} as const;
