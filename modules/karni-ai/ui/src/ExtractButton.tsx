/**
 * <ExtractButton>: read rows of a resource from a text, a web page or a PDF. Experimental.
 *
 * The button opens a dialog with one form per source. Extract posts it to
 * `POST /api/ai/extract/` (`useExtract`) and the dialog then shows the
 * import preview of the rows (`<ExtractPreview>`). Commit saves them through
 * the import's own commit, after the same confirmation a file import asks
 * for. Nothing is saved before.
 *
 * The backend decides everything that matters: who may extract into the
 * resource, which fields the model fills, what each row's problems are. A
 * refusal (an AI code: the source, the URL, the budget) is shown in the
 * backend's words.
 *
 * Escape hatches: every `@karni/ui` Button prop passes through to the
 * trigger; `sources` limits the forms; `slots` replaces the error display
 * and the preview's parts; `useExtract` and `<ExtractPreview>` build another
 * flow.
 */
import {
  Button,
  ErrorState,
  Input,
  Label,
  Modal,
  PendingButton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
  type ButtonProps,
  type ImportJob,
} from "@karni/ui";
import * as React from "react";
import { ExtractPreview, type ExtractPreviewSlots } from "./ExtractPreview";
import { extractRefusal, useExtract } from "./hooks";
import type { ExtractInput, ExtractResult, ExtractSourceKind } from "./types";

/** What the `Error` slot receives: why the extraction was refused or failed. */
export interface ExtractErrorProps {
  error: unknown;
  resourceLabel: string;
}

export interface ExtractButtonSlots extends ExtractPreviewSlots {
  Error: React.ComponentType<ExtractErrorProps>;
}

export interface ExtractButtonProps extends Omit<ButtonProps, "onClick" | "onError"> {
  /** The resource's router prefix ("products"). */
  resource: string;
  /** The resource in words, plural ("products"). Default: the router prefix. */
  resourceLabel?: string;
  /** The forms offered, in order. Default: text, a web page, a PDF. */
  sources?: readonly ExtractSourceKind[];
  /** Called with the preview once the rows are read. */
  onExtracted?: (result: ExtractResult) => void;
  /** Called once the commit saved the rows. */
  onDone?: (job: ImportJob) => void;
  slots?: Partial<ExtractButtonSlots>;
}

const SOURCE_LABELS: Record<ExtractSourceKind, string> = {
  text: "Text",
  url: "Web page",
  pdf: "PDF",
};

const SOURCE_WORDS: Record<ExtractSourceKind, string> = {
  text: "a text",
  url: "a web page",
  pdf: "a PDF",
};

/** "a text, a web page or a PDF" for the sources offered. */
function sourceWords(sources: readonly ExtractSourceKind[]): string {
  const words = sources.map((source) => SOURCE_WORDS[source]);
  if (words.length <= 1) return words[0] ?? "a source";
  return `${words.slice(0, -1).join(", ")} or ${words[words.length - 1]}`;
}

const REFUSAL_TITLES: Record<string, string> = {
  AI008: "This resource can't be extracted into",
  AI009: "You can't add these rows",
  AI010: "This source can't be read",
  AI011: "This address can't be fetched",
  AI012: "This page can't be read",
  AI013: "Your monthly budget is spent",
  AI014: "The monthly budget is spent",
};

/** The default `Error` slot: an AI refusal in the backend's words, anything else as ErrorState. */
function DefaultExtractError({ error, resourceLabel }: ExtractErrorProps): React.ReactElement {
  const refusal = extractRefusal(error);
  if (refusal === undefined) {
    return (
      <ErrorState
        variant="inline"
        error={error}
        context={{ action: "extract", resource: resourceLabel }}
      />
    );
  }
  return (
    <div
      role="alert"
      className="rounded-md border border-destructive-border bg-destructive-subtle p-3 text-sm"
    >
      <p className="font-medium text-foreground">
        {REFUSAL_TITLES[refusal.code] ?? "The extraction failed"}
      </p>
      <p className="text-muted-foreground">{refusal.detail}</p>
    </div>
  );
}

interface SourceFormProps {
  sources: readonly ExtractSourceKind[];
  pending: boolean;
  onSubmit: (input: ExtractInput) => void;
}

function SourceForm({ sources, pending, onSubmit }: SourceFormProps): React.ReactElement {
  const ids = {
    text: React.useId(),
    url: React.useId(),
    pdf: React.useId(),
  };
  const [kind, setKind] = React.useState<ExtractSourceKind>(sources[0] ?? "text");
  const [text, setText] = React.useState("");
  const [url, setUrl] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);

  const submit = (event: React.FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (kind === "text") onSubmit({ text });
    else if (kind === "url") onSubmit({ url });
    else if (file !== null) onSubmit({ file });
  };

  const field = (source: ExtractSourceKind): React.ReactElement => {
    if (source === "text") {
      return (
        <div className="grid gap-1.5">
          <Label htmlFor={ids.text}>Text to read</Label>
          <Textarea
            id={ids.text}
            rows={8}
            required
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </div>
      );
    }
    if (source === "url") {
      return (
        <div className="grid gap-1.5">
          <Label htmlFor={ids.url}>Address of the page</Label>
          <Input
            id={ids.url}
            type="url"
            required
            placeholder="https://"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
          />
        </div>
      );
    }
    return (
      <div className="grid gap-1.5">
        <Label htmlFor={ids.pdf}>PDF file</Label>
        <Input
          id={ids.pdf}
          type="file"
          accept="application/pdf,.pdf"
          className="cursor-pointer"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
      </div>
    );
  };

  return (
    <form onSubmit={submit} className="space-y-3" aria-label="Source to read">
      {sources.length > 1 ? (
        <Tabs value={kind} onValueChange={(value) => setKind(value as ExtractSourceKind)}>
          <TabsList>
            {sources.map((source) => (
              <TabsTrigger key={source} value={source}>
                {SOURCE_LABELS[source]}
              </TabsTrigger>
            ))}
          </TabsList>
          {sources.map((source) => (
            <TabsContent key={source} value={source}>
              {field(source)}
            </TabsContent>
          ))}
        </Tabs>
      ) : (
        field(kind)
      )}
      <PendingButton
        type="submit"
        pending={pending}
        pendingLabel="Reading…"
        disabled={kind === "pdf" && file === null}
      >
        Extract
      </PendingButton>
    </form>
  );
}

/** Experimental. A button that reads rows from a source into the import preview. */
export function ExtractButton(props: ExtractButtonProps): React.ReactElement {
  const {
    resource,
    resourceLabel,
    sources = ["text", "url", "pdf"],
    onExtracted,
    onDone,
    slots,
    children,
    ...buttonProps
  } = props;
  const label = resourceLabel ?? resource;
  const ErrorSlot = slots?.Error ?? DefaultExtractError;
  const [open, setOpen] = React.useState(false);
  const [result, setResult] = React.useState<ExtractResult | undefined>(undefined);
  const extract = useExtract(resource);

  const startOver = (): void => {
    setResult(undefined);
    extract.reset();
  };

  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) startOver();
      }}
      title={`Extract ${label}`}
      description={`Read ${label} from ${sourceWords(sources)}. Nothing is saved until you commit the preview.`}
      className="max-w-3xl"
      trigger={
        <Button data-karni-role="extract-button" {...buttonProps}>
          {children ?? "Extract with AI"}
        </Button>
      }
    >
      {result === undefined ? (
        <div className="space-y-3">
          <SourceForm
            sources={sources}
            pending={extract.isPending}
            onSubmit={(input) =>
              extract.mutate(input, {
                onSuccess: (answer) => {
                  setResult(answer);
                  onExtracted?.(answer);
                },
              })
            }
          />
          {extract.error !== null && extract.error !== undefined ? (
            <ErrorSlot error={extract.error} resourceLabel={label} />
          ) : null}
        </div>
      ) : (
        <ExtractPreview
          result={result}
          resourceLabel={label}
          onDone={onDone}
          onStartOver={startOver}
          slots={slots}
        />
      )}
    </Modal>
  );
}
