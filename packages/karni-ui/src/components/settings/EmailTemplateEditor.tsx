/**
 * Edits one email a business sends: the subject and the text,
 * with the merge fields the email offers, a preview, and a way back to the
 * default. Works on `/email-templates/<kind>/`.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { cn } from "../../lib/cn";
import { useKarniClient } from "../../schema/provider";
import { PendingButton } from "../../states/PendingButton";
import { Button } from "../primitives/button";
import { Input } from "../primitives/input";
import { Label } from "../primitives/label";
import { Textarea } from "../primitives/textarea";
import { useToast } from "../toast/use-toast";
import { readFormErrors, type FormErrors } from "./errors";

export interface EmailTemplateEditorProps {
  /** The email's kind, such as `commerce.order_paid`. */
  kind: string;
  /** Called when the person closes the editor. A close button shows when set. */
  onClose?: () => void;
}

interface MergeField {
  name: string;
  meaning: string;
}

interface EmailTemplate {
  kind: string;
  title: string;
  describe: string;
  audience: string;
  switchable: boolean;
  on: boolean;
  fields: MergeField[];
  edited: boolean;
  subject: string;
  text: string;
  updated_at: string | null;
}

interface Preview {
  subject: string;
  text: string;
  html: string;
}

const NO_ERRORS: FormErrors = { fields: {}, general: null };

export function EmailTemplateEditor({ kind, onClose }: EmailTemplateEditorProps) {
  const client = useKarniClient();
  const queryClient = useQueryClient();
  const { success, error: toastError } = useToast();
  const ids = { subject: useId(), text: useId() };
  const path = `/email-templates/${encodeURIComponent(kind)}/`;
  const key = ["karni", "email-template", kind];
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const [subject, setSubject] = useState("");
  const [text, setText] = useState("");
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);
  const [preview, setPreview] = useState<Preview | null>(null);

  const query = useQuery({ queryKey: key, queryFn: () => client.request<EmailTemplate>(path) });
  const data = query.data;
  useEffect(() => {
    if (data === undefined) return;
    setSubject(data.subject);
    setText(data.text);
  }, [data]);

  const previewIt = useMutation({
    mutationFn: () =>
      client.request<Preview>(`${path}preview/`, { method: "POST", body: { subject, text } }),
    onSuccess: (result) => {
      setErrors(NO_ERRORS);
      setPreview(result);
    },
    onError: (failure) => {
      setPreview(null);
      setErrors(readFormErrors(failure));
    },
  });
  const save = useMutation({
    mutationFn: () =>
      client.request<EmailTemplate>(path, { method: "PUT", body: { subject, text } }),
    onSuccess: (result) => {
      setErrors(NO_ERRORS);
      queryClient.setQueryData(key, result);
      void queryClient.invalidateQueries({ queryKey: ["karni", "preferences"] });
      success("The email is saved");
    },
    onError: (failure) => setErrors(readFormErrors(failure)),
  });
  const reset = useMutation({
    mutationFn: () => client.request<EmailTemplate>(path, { method: "DELETE" }),
    onSuccess: (result) => {
      setErrors(NO_ERRORS);
      setPreview(null);
      queryClient.setQueryData(key, result);
      void queryClient.invalidateQueries({ queryKey: ["karni", "preferences"] });
      success("The email is back to the default");
    },
    onError: () => toastError("The email was not reset", { description: "Try again." }),
  });

  function insert(name: string): void {
    const area = bodyRef.current;
    const token = `{{ ${name} }}`;
    const start = area?.selectionStart ?? text.length;
    const end = area?.selectionEnd ?? text.length;
    setText(text.slice(0, start) + token + text.slice(end));
    const caret = start + token.length;
    requestAnimationFrame(() => {
      area?.focus();
      area?.setSelectionRange(caret, caret);
    });
  }

  function askReset(): void {
    if (window.confirm("Go back to the default email? Your changes will be lost.")) reset.mutate();
  }

  if (query.isPending) return <p role="status">Loading the email…</p>;
  if (data === undefined) return <p role="alert">The email could not be loaded.</p>;

  // A field whose meaning starts with "Each" is one value per row of a list: the list is
  // its path less the last name (lines.name: the list lines, the value name).
  const listFields = data.fields.filter(
    (field) => field.name.includes(".") && /^each\b/i.test(field.meaning),
  );
  const example = listFields[0]?.name ?? "";
  const listPath = example.slice(0, example.lastIndexOf("."));
  const valueName = example.slice(example.lastIndexOf(".") + 1);
  const busy = save.isPending || reset.isPending;

  return (
    <div className="space-y-5">
      <header className="space-y-1">
        <h2 className="text-xl font-semibold">{data.title}</h2>
        <p className="text-sm text-muted-foreground">{data.describe}</p>
        <p className="text-sm text-muted-foreground">
          To: {data.audience}
          {data.edited ? " · Edited" : " · Using the default"}
        </p>
      </header>

      {errors.general !== null ? (
        <p role="alert" className="text-sm text-destructive">
          {errors.general}
        </p>
      ) : null}

      <div className="space-y-1">
        <Label htmlFor={ids.subject}>Subject</Label>
        <Input
          id={ids.subject}
          value={subject}
          aria-invalid={errors.fields["subject"] !== undefined || undefined}
          onChange={(event) => setSubject(event.target.value)}
        />
        {(errors.fields["subject"] ?? []).map((message) => (
          <p key={message} role="alert" className="text-sm text-destructive">
            {message}
          </p>
        ))}
      </div>

      <div className="space-y-1">
        <Label htmlFor={ids.text}>Text</Label>
        <Textarea
          id={ids.text}
          ref={bodyRef}
          rows={14}
          className="min-h-72 font-mono"
          value={text}
          aria-invalid={errors.fields["text"] !== undefined || undefined}
          onChange={(event) => setText(event.target.value)}
        />
        {(errors.fields["text"] ?? []).map((message) => (
          <p key={message} role="alert" className="text-sm text-destructive">
            {message}
          </p>
        ))}
      </div>

      {data.fields.length > 0 ? (
        <section aria-labelledby={`${ids.text}-fields`} className="space-y-2">
          <h3 id={`${ids.text}-fields`} className="text-base font-semibold">
            Merge fields
          </h3>
          <p className="text-sm text-muted-foreground">
            Choose a field to add it to the text where the cursor is.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th scope="col" className="py-1 pr-4 font-medium">
                    Field
                  </th>
                  <th scope="col" className="py-1 font-medium">
                    Meaning
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.fields.map((field) => (
                  <tr key={field.name} className="border-b border-border">
                    <td className="py-1 pr-4">
                      <button
                        type="button"
                        className="rounded-sm font-mono text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        onClick={() => insert(field.name)}
                      >
                        {`{{ ${field.name} }}`}
                      </button>
                    </td>
                    <td className="py-1">{field.meaning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {listFields.length > 0 ? (
            <p className="text-sm text-muted-foreground">
              A field that says &ldquo;each&rdquo;, such as{" "}
              <code className="font-mono">{example}</code>, is one per row, written in a loop:{" "}
              <code className="break-words font-mono">
                {`{% for row in ${listPath} %}{{ row.${valueName} }}{% endfor %}`}
              </code>
            </p>
          ) : null}
        </section>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <PendingButton
          variant="outline"
          pending={previewIt.isPending}
          pendingLabel="Preparing the preview…"
          onClick={() => previewIt.mutate()}
        >
          Preview
        </PendingButton>
        <PendingButton
          pending={save.isPending}
          pendingLabel="Saving…"
          onClick={() => save.mutate()}
        >
          Save
        </PendingButton>
        {data.edited ? (
          <Button variant="ghost" disabled={busy} onClick={askReset}>
            Back to the default
          </Button>
        ) : null}
        {onClose !== undefined ? (
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
        ) : null}
      </div>

      {preview !== null ? (
        <section
          aria-label="Preview"
          className={cn("space-y-2 rounded-md border border-border bg-muted p-4")}
        >
          <p className="text-sm text-muted-foreground">Preview</p>
          <p className="break-words font-semibold">{preview.subject}</p>
          <pre className="whitespace-pre-wrap break-words font-mono text-sm">{preview.text}</pre>
        </section>
      ) : null}
    </div>
  );
}
