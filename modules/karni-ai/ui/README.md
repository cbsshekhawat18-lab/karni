# @karni/ai-ui

Experimental. React components for the Karni AI extraction module
(`karni add ai`), composing [`@karni/ui`](https://www.npmjs.com/package/@karni/ui):

- **`ExtractButton`**: a button that opens a dialog, reads rows of a resource
  from a text, a web page or a PDF (`POST /api/ai/extract/`), shows the import
  preview (proposed rows, a problem per field, the counts), and commits through
  the import's own confirmation. Nothing is saved before the commit.
- **`useExtract(resource)`**: the mutation behind it, for a flow of your own.
- **`ExtractPreview`**: the preview and its commit, for a flow of your own.

## Install

```bash
npm install @karni/ai-ui @karni/ui @tanstack/react-query
```

Peer dependencies: `react` / `react-dom` (`^18 || ^19`), `@karni/ui` (`^0.4.0`),
`@tanstack/react-query` (`^5`). Wrap your app in `<KarniProvider>` as the
`@karni/ui` README describes. The client's `baseUrl` carries `/api`.

## ExtractButton

```tsx
import { ExtractButton } from "@karni/ai-ui";

<ExtractButton
  resource="products"
  resourceLabel="products"
  sources={["text", "pdf"]}
  onDone={(job) => toast({ title: `${job.result?.created ?? 0} products added` })}
/>;
```

| Prop | Meaning |
| --- | --- |
| `resource` | the router prefix (`products`) |
| `resourceLabel` | the resource in words, plural. Default: `resource` |
| `sources` | the forms offered: `text`, `url`, `pdf` (default: all three) |
| `onExtracted(result)` | the preview arrived |
| `onDone(job)` | the commit saved the rows |
| `slots` | replace `Error`, `Rows`, `Problems`, `Summary` or `ConfirmCommit` |

Every other `@karni/ui` Button prop goes to the trigger. A refusal (an AI code:
a source that cannot be read, a refused address, a spent budget) shows the
backend's own words.

## useExtract

```tsx
import { useImportActions } from "@karni/ui";
import { useExtract } from "@karni/ai-ui";

const extract = useExtract("products");
const { commit } = useImportActions("products");

const preview = await extract.mutateAsync({ text });   // or { url } or { file }
// preview.rows, preview.problems, preview.result: nothing is saved yet
commit.mutate(preview.id);                             // the import's own commit
```

`extractRefusal(error)` returns `{code, detail}` for a refused extraction.

## Tests

```bash
npm test
```
