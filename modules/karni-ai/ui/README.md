# @karni/ai-ui

React components for the Karni AI extraction module: ExtractButton and the useExtract hook.

[![npm](https://img.shields.io/npm/v/@karni/ai-ui)](https://www.npmjs.com/package/@karni/ai-ui) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/cbsshekhawat18-lab/karni/blob/main/LICENSE) [![Docs](https://img.shields.io/badge/docs-online-FB5D08)](https://cbsshekhawat18-lab.github.io/karni/ai-extraction/)

Experimental. It composes [`@karni/ui`](https://www.npmjs.com/package/@karni/ui) for the [karni-ai](https://pypi.org/project/karni-ai/) module (`karni add ai`):

- **`ExtractButton`**: a button that opens a dialog, reads rows of a resource
  from a text, a web page or a PDF (`POST /api/ai/extract/`), shows the import
  preview (proposed rows, a problem per field, the counts), and commits through
  the import's own confirmation. Nothing is saved before the commit.
- **`useExtract(resource)`**: the mutation behind it, for a flow of your own.
- **`ExtractPreview`**: the preview and its commit, for a flow of your own.

## Install

```bash
npm install @karni/ai-ui @karni/ui @tanstack/react-query@5
```

Peer dependencies: `react` / `react-dom` (`^18 || ^19`), `@karni/ui` at this package's version (every Karni package is released at one version),
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

| Prop                  | Meaning                                                           |
| --------------------- | ----------------------------------------------------------------- |
| `resource`            | the router prefix (`products`)                                    |
| `resourceLabel`       | the resource in words, plural. Default: `resource`                |
| `sources`             | the forms offered: `text`, `url`, `pdf` (default: all three)      |
| `onExtracted(result)` | the preview arrived                                               |
| `onDone(job)`         | the commit saved the rows                                         |
| `slots`               | replace `Error`, `Rows`, `Problems`, `Summary` or `ConfirmCommit` |

Every other `@karni/ui` Button prop goes to the trigger. A refusal (an AI code:
a source that cannot be read, a refused address, a spent budget) shows the
backend's own words.

## useExtract

```tsx
import { useImportActions } from "@karni/ui";
import { useExtract } from "@karni/ai-ui";

const extract = useExtract("products");
const { commit } = useImportActions("products");

const preview = await extract.mutateAsync({ text }); // or { url } or { file }
// preview.rows, preview.problems, preview.result: nothing is saved yet
commit.mutate(preview.id); // the import's own commit
```

`extractRefusal(error)` returns `{code, detail}` for a refused extraction.

## Tests

```bash
npm test
```

## Links

- AI extraction: <https://cbsshekhawat18-lab.github.io/karni/ai-extraction/>
- The Python module: <https://pypi.org/project/karni-ai/>
- Karni, the framework this package is part of: <https://github.com/cbsshekhawat18-lab/karni>
- Changelog: <https://github.com/cbsshekhawat18-lab/karni/blob/main/CHANGELOG.md>
- Issues: <https://github.com/cbsshekhawat18-lab/karni/issues>
- License: Apache-2.0. @karni/ai-ui is released with every other Karni package, at one version.
