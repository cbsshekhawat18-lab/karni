# @karni/reports-ui

React components for the Karni reports module: ReportButton and its useReport hook.

[![npm](https://img.shields.io/npm/v/@karni/reports-ui)](https://www.npmjs.com/package/@karni/reports-ui) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/cbsshekhawat18-lab/karni/blob/main/LICENSE) [![Docs](https://img.shields.io/badge/docs-online-FB5D08)](https://cbsshekhawat18-lab.github.io/karni/reports/)

Experimental. `ReportButton` requests the PDF report of one row from the [karni-reports](https://pypi.org/project/karni-reports/) module and downloads it when ready. `useReport` is the hook behind it.

```sh
npm install @karni/reports-ui
```

It peer-depends on `@karni/ui` at its own version (every Karni package is
released at one version), React 18 or 19 and
`@tanstack/react-query` 5, and calls the API through the `KarniClient` of
the nearest `KarniProvider`.

## ReportButton

```tsx
import { ReportButton } from "@karni/reports-ui";

<ReportButton report="product-sheet" objectId={product.id} />;
```

One click posts `/reports/product-sheet/<id>/`. A cached file downloads at
once. Otherwise the button says "Preparing PDF...", follows the status and
downloads the file as soon as it is ready. A failed render, or a row the
user may not see (404), shows "Try again".

| Prop                 | Default                                         | Meaning                                                      |
| -------------------- | ----------------------------------------------- | ------------------------------------------------------------ |
| `report`, `objectId` | required                                        | the report's name and the row's id                           |
| `autoDownload`       | `true`                                          | download once ready (`false`: stop at ready, read `onReady`) |
| `pollInterval`       | `1500`                                          | milliseconds between status checks                           |
| `labels`             | `Download PDF`, `Preparing PDF...`, `Try again` | `{idle, working, failed}`                                    |
| `onReady`, `onError` | none                                            | called with the ready state, or with what was thrown         |
| `save`               | a browser download                              | `(blob, filename) => void`                                   |

Every other `Button` prop of `@karni/ui` passes through.

## useReport

```tsx
const { status, isWorking, request, download } = useReport("product-sheet", id, {
  pollInterval: 1500,
});
```

`request()` resolves with the API's answer and polls while the file is
`pending` or `rendering`. `download()` fetches the file with the client's
auth and resolves with its name. `watch: true` loads the last request's
status on mount. The state is cached under `reportKey(report, id)`.

## Links

- Reports (PDF): <https://cbsshekhawat18-lab.github.io/karni/reports/>
- The Python module: <https://pypi.org/project/karni-reports/>
- Karni, the framework this package is part of: <https://github.com/cbsshekhawat18-lab/karni>
- Changelog: <https://github.com/cbsshekhawat18-lab/karni/blob/main/CHANGELOG.md>
- Issues: <https://github.com/cbsshekhawat18-lab/karni/issues>
- License: Apache-2.0. @karni/reports-ui is released with every other Karni package, at one version.
