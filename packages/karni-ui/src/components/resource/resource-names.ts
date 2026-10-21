/**
 * How a resource is named in a sentence: "No venues yet", "You can't edit
 * this event". The router prefix is plural ("events", "loose-slots"); the
 * singular is derived with English rules that cover the common cases, and a
 * component's `resourceLabel` prop is the escape hatch for the rest
 * ("people" / "person").
 *
 * Internal to @karni/ui.
 */

/** The words a resource takes in a sentence, both lower case. */
export interface ResourceNames {
  /** "event", "loose slot". */
  singular: string;
  /** "events", "loose slots". */
  plural: string;
}

/** What a component's `resourceLabel` prop accepts: either word, or both. */
export interface ResourceLabel {
  singular?: string;
  plural?: string;
}

function singularOf(word: string): string {
  if (/ies$/i.test(word) && word.length > 3) return `${word.slice(0, -3)}y`;
  if (/(?:ss|sh|ch|x|z)es$/i.test(word)) return word.slice(0, -2);
  if (/ss$/i.test(word)) return word;
  if (/s$/i.test(word)) return word.slice(0, -1);
  return word;
}

/** "loose-slots" → { singular: "loose slot", plural: "loose slots" }, unless `label` says otherwise. */
export function resourceNames(resource: string, label?: ResourceLabel): ResourceNames {
  const plural = (label?.plural ?? resource.replace(/[_-]+/g, " ").trim()).toLowerCase();
  const words = plural.split(" ");
  const last = words.pop() ?? plural;
  const singular = label?.singular ?? [...words, singularOf(last)].join(" ");
  return { singular, plural };
}
