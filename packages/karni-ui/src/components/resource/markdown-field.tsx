/**
 * A MarkdownField in the resource components (experimental).
 *
 * A model's `MarkdownField` is a text property with `format: "markdown"` in
 * the OpenAPI schema. ResourceForm edits it with Write and Preview tabs (the
 * preview is MarkdownView, so it shows exactly what the detail page will),
 * ResourceDetail shows it formatted and sanitized, and a ResourceTable column
 * shows a one-line plain-text excerpt.
 *
 * Internal to @karni/ui. The public surface is the components' behaviour and
 * their per-field overrides (`fields` on ResourceForm and ResourceDetail,
 * `columns` on ResourceTable).
 */
import * as React from "react";
import { cn } from "../../lib/cn";
import type { FieldDef } from "../../schema/types";
import { MarkdownView } from "../markdown/markdown-view";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../primitives/tabs";
import { Textarea } from "../primitives/textarea";

/** True for a MarkdownField: text whose schema format is `markdown`. */
export function isMarkdownField(field: Pick<FieldDef, "kind" | "format">): boolean {
  return field.kind === "text" && field.format === "markdown";
}

const LINK = /!?\[([^\]]*)\]\([^)]*\)/g;
const MARKS = /(^|\s)(#{1,6}\s+|[-*+]\s+|\d+\.\s+|>\s*)/g;
const EMPHASIS = /[*_~`]+/g;

/** Markdown as one line of plain text: no heading, list or emphasis marks, link texts kept. */
export function markdownExcerpt(source: string): string {
  return source
    .replace(LINK, "$1")
    .split("\n")
    .map((line) => line.replace(MARKS, "$1").replace(EMPHASIS, "").trim())
    .filter((line) => line !== "")
    .join(" ");
}

/** What the form passes to the editor (the textarea's own props come through `textarea`). */
export interface MarkdownEditorProps {
  /** The field's label, to name the Write and Preview tabs. */
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** react-hook-form's ref: given a handle whose `focus()` opens Write and focuses the text. */
  registerFocus: (handle: { focus: () => void } | null) => void;
  /** Props of the textarea (id, name, aria-*, disabled, maxLength, onBlur, ...). */
  textarea: Omit<React.ComponentPropsWithoutRef<"textarea">, "value" | "onChange">;
}

/** Write and Preview tabs over one textarea. The textarea stays mounted while previewing. */
export function MarkdownEditor(props: MarkdownEditorProps): React.ReactElement {
  const { label, value, onChange, registerFocus, textarea } = props;
  const [mode, setMode] = React.useState<"write" | "preview">("write");
  const textareaRef = React.useRef<HTMLTextAreaElement | null>(null);
  const modeRef = React.useRef(mode);
  modeRef.current = mode;
  const focusAfterWrite = React.useRef(false);

  const handle = React.useMemo(
    () => ({
      focus: () => {
        if (modeRef.current === "write") {
          textareaRef.current?.focus();
          return;
        }
        focusAfterWrite.current = true;
        setMode("write");
      },
    }),
    [],
  );
  React.useEffect(() => {
    registerFocus(handle);
  }, [registerFocus, handle]);
  React.useEffect(() => {
    if (mode !== "write" || !focusAfterWrite.current) return;
    focusAfterWrite.current = false;
    textareaRef.current?.focus();
  }, [mode]);

  return (
    <Tabs
      value={mode}
      onValueChange={(next) => setMode(next === "preview" ? "preview" : "write")}
      data-karni-markdown-editor=""
    >
      <TabsList aria-label={`${label}: write or preview`} className="h-9">
        <TabsTrigger value="write" className="py-1">
          Write
        </TabsTrigger>
        <TabsTrigger value="preview" className="py-1">
          Preview
        </TabsTrigger>
      </TabsList>
      <TabsContent value="write" forceMount hidden={mode !== "write"}>
        <Textarea
          rows={8}
          {...textarea}
          ref={textareaRef}
          className={cn("font-mono text-sm", textarea.className)}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      </TabsContent>
      <TabsContent value="preview" className="rounded-md border border-border px-4 py-3">
        {value.trim() === "" ? (
          <p className="text-sm text-muted-foreground">Nothing to preview yet.</p>
        ) : (
          <MarkdownView source={value} />
        )}
      </TabsContent>
    </Tabs>
  );
}
