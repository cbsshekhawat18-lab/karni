/**
 * The words a resource's messages use: "events" → "event" ("Couldn't find
 * this event"), "loose-slots" → "loose slots" ("You can't import loose
 * slots"). English rules only; every component that words a message takes
 * a `resourceLabel` prop to name the resource in the project's own words.
 *
 * Internal to @karni/ui.
 */

/** The router prefix as words: "loose-slots" → "loose slots". */
export function pluralNoun(resource: string): string {
  const spaced = resource.replace(/[_-]+/g, " ").trim().toLowerCase();
  return spaced === "" ? resource : spaced;
}

/** One of the resource: "events" → "event", "categories" → "category", "addresses" → "address". */
export function singularNoun(resource: string): string {
  const plural = pluralNoun(resource);
  const words = plural.split(" ");
  const last = words.pop() ?? plural;
  let single = last;
  if (/[^aeiou]ies$/.test(last)) single = `${last.slice(0, -3)}y`;
  else if (/(?:ss|sh|ch|x|z)es$/.test(last)) single = last.slice(0, -2);
  else if (/[^s]s$/.test(last)) single = last.slice(0, -1);
  return [...words, single].join(" ");
}
