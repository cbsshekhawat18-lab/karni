import * as React from "react";

/** Where a long word may wrap: after "@", and before ".", "/", "?", "&", "_" and "-". */
const BREAK_AFTER = /([@])/;
const BREAK_BEFORE = /(?=[./?&_-])/;
/** Shorter words never need a break. */
const LONG_WORD = 16;

function breakText(text: string, key: string): React.ReactNode {
  if (!text.split(/\s+/).some((word) => word.length > LONG_WORD)) return text;
  const pieces: string[] = [];
  for (const part of text.split(BREAK_AFTER)) {
    if (part === "@") {
      pieces[pieces.length - 1] = `${pieces[pieces.length - 1] ?? ""}@`;
      pieces.push("");
      continue;
    }
    const split = part.split(BREAK_BEFORE);
    if (pieces.length > 0 && pieces[pieces.length - 1] === "") {
      pieces[pieces.length - 1] = split[0] ?? "";
      pieces.push(...split.slice(1));
    } else {
      pieces.push(...split);
    }
  }
  const kept = pieces.filter((piece) => piece !== "");
  if (kept.length < 2) return text;
  return kept.map((piece, index) => (
    <React.Fragment key={`${key}-${String(index)}`}>
      {index > 0 ? <wbr /> : null}
      {piece}
    </React.Fragment>
  ));
}

/**
 * Experimental. `node` with wrap points in its long words: an email wraps after
 * "@" and before a ".", a link before a "/" or a "?", so a narrow column breaks
 * `lena.vogt@example.com` as `lena.vogt@` / `example.com`, never inside a word.
 * Text inside elements is handled too (a link around an email). Short words are
 * left as they are.
 */
export function softBreaks(node: React.ReactNode, key = "b"): React.ReactNode {
  if (typeof node === "string") return breakText(node, key);
  if (Array.isArray(node)) {
    return node.map((child, index) => (
      <React.Fragment key={`${key}-${String(index)}`}>
        {softBreaks(child as React.ReactNode, `${key}-${String(index)}`)}
      </React.Fragment>
    ));
  }
  if (React.isValidElement<{ children?: React.ReactNode }>(node)) {
    const children = node.props.children;
    if (children === undefined || children === null) return node;
    if (typeof children === "string" || Array.isArray(children) || React.isValidElement(children)) {
      return React.cloneElement(node, undefined, softBreaks(children, key));
    }
  }
  return node;
}
