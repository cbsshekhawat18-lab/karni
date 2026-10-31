# @karni/reports-ui

React components for the Karni reports module (`karni-reports`),
experimental: a `ReportButton` that requests the PDF report of one row and
downloads it when ready, and the `useReport` hook behind it.

```sh
npm install @karni/reports-ui
```

It peer-depends on `@karni/ui` (`^0.4.0`), React 18 or 19 and
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
