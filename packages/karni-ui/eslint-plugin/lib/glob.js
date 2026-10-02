/**
 * Minimal glob matching for rule file-path options (no runtime dependency).
 *
 * Supported syntax (enough for the shipped defaults and documented options):
 * - `**` matches any number of path segments (crosses `/`).
 * - `*`  matches within a single path segment.
 * - `?`  matches a single character within a segment.
 *
 * Paths are normalized to posix separators before matching, and a pattern
 * matches if it matches the full path or any trailing sub-path, so a
 * "**" + "/pages/" + "**" pattern works for absolute and relative filenames.
 */

const SPECIALS = /[.+^${}()|[\]\\]/g;

/** @param {string} glob @returns {RegExp} */
export function globToRegExp(glob) {
  let out = "";
  let i = 0;
  while (i < glob.length) {
    const ch = glob[i];
    if (ch === "*") {
      if (glob[i + 1] === "*") {
        if (glob[i + 2] === "/") {
          // `**/` — zero or more whole segments.
          out += "(?:.*/)?";
          i += 3;
        } else {
          out += ".*";
          i += 2;
        }
      } else {
        out += "[^/]*";
        i += 1;
      }
    } else if (ch === "?") {
      out += "[^/]";
      i += 1;
    } else {
      out += ch.replace(SPECIALS, "\\$&");
      i += 1;
    }
  }
  return new RegExp(`(?:^|/)${out}$`);
}

/** @param {string} filename @param {readonly string[]} patterns @returns {boolean} */
export function matchesAny(filename, patterns) {
  const path = filename.replaceAll("\\", "/");
  return patterns.some((pattern) => globToRegExp(pattern).test(path));
}
