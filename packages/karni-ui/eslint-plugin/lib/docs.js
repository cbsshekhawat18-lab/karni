/**
 * Docs links for the rules. DOCS_BASE_URL must equal karni.errorcodes.DOCS_BASE_URL
 * (packages/karni/tests/test_errorcodes.py checks it), and each rule's anchor is
 * generated into docs/errors.md from ../rules.json.
 */
export const DOCS_BASE_URL = "https://github.com/karni/karni/blob/main/docs/";

/** @param {string} rule rule name without the plugin prefix, e.g. "no-raw-elements" */
export function docsUrl(rule) {
  return `${DOCS_BASE_URL}errors.md#karni-${rule}`;
}
