# @karni/storage-ui

React components for the Karni storage module: protected uploads straight to the bucket, download links and images.

[![npm](https://img.shields.io/npm/v/@karni/storage-ui)](https://www.npmjs.com/package/@karni/storage-ui) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/cbsshekhawat18-lab/karni/blob/main/LICENSE) [![Docs](https://img.shields.io/badge/docs-online-FB5D08)](https://cbsshekhawat18-lab.github.io/karni/storage/)

It composes [`@karni/ui`](https://www.npmjs.com/package/@karni/ui) for the [karni-storage](https://pypi.org/project/karni-storage/) module (`karni add storage`). **Experimental**: its names may change in a minor release, with a CHANGELOG entry.

- **`ProtectedFileInput`**: a protected file field of `<ResourceForm>`. The file goes
  straight to the bucket when the user picks it, with a progress bar, and the form
  saves the token the confirm step gives. On local storage the file goes with the
  form, as any file field does.
- **`ProtectedFileLink`**: a link that opens (or downloads) a protected file through a
  short-lived signed URL, in session and token auth alike.
- **`ProtectedImage`**: a protected image, or one of its thumbnails (`size="small"`).
- **`useProtectedUpload`** and **`useProtectedFileLink`**: the hooks under them, for
  screens of your own.

`@karni/ui` stays free of S3 knowledge: this package composes its `FileUpload`
(`uploading`, `error`, `value`) and plugs into `ResourceForm` through its documented
`fields` override.

## Install

```bash
npm install @karni/storage-ui @karni/ui @tanstack/react-query@5 react-hook-form@7
```

Peer dependencies: `react` / `react-dom` (`^18 || ^19`), `@karni/ui` at this package's version (every Karni package is released at one version),
`@tanstack/react-query` (`^5`), `react-hook-form` (`^7`).

## A form with a protected file

```tsx
import { ResourceForm } from "@karni/ui";
import { ProtectedFileInput } from "@karni/storage-ui";

<ResourceForm
  resource="products"
  fields={{ manual: { component: ProtectedFileInput, props: { resource: "products" } } }}
/>;
```

`props` takes `resource` (required: the resource's API path), `accept`, `maxSize` (both
checked again by the server) and `transport`.

## A link and an image

```tsx
import { ProtectedFileLink, ProtectedImage } from "@karni/storage-ui";

<ProtectedFileLink href={product.manual}>Manual</ProtectedFileLink>
<ProtectedImage src={product.photo} size="small" alt={product.name} />
```

`href` and `src` are the field's value as the API gives it: the download path.

## The bucket's CORS

The browser sends the file to the bucket's origin, so the bucket must allow your
frontend's origin for `POST` (or `PUT`) with the `Content-Type` header. See
[docs/storage.md](https://cbsshekhawat18-lab.github.io/karni/storage/).

## Escape hatches

- `transport` (`useProtectedUpload`, `ProtectedFileInput`'s props) replaces the request
  to the bucket (the default is XMLHttpRequest, for its progress events).
- `open` on `ProtectedFileLink` replaces how the signed URL opens.
- `fallback` on `ProtectedImage` shows while the link loads.

## Links

- Protected files: <https://cbsshekhawat18-lab.github.io/karni/storage/>
- The Python module: <https://pypi.org/project/karni-storage/>
- Karni, the framework this package is part of: <https://github.com/cbsshekhawat18-lab/karni>
- Changelog: <https://github.com/cbsshekhawat18-lab/karni/blob/main/CHANGELOG.md>
- Issues: <https://github.com/cbsshekhawat18-lab/karni/issues>
- License: Apache-2.0. @karni/storage-ui is released with every other Karni package, at one version.
