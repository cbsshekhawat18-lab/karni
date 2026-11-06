---
description: "karni-storage (experimental): files a row owns, kept in a private S3-compatible bucket or on disk and downloaded only through the row's own viewset, with provider presets for AWS, R2, MinIO, Spaces, B2 and GCS, direct uploads with a confirm step, thumbnails and @karni/storage-ui."
---

# Protected files (karni-storage)

!!! warning "Experimental"
    The karni-storage module and `@karni/storage-ui` are
    [experimental](stability.md#experimental-names): their names may change in
    a minor release, with a CHANGELOG entry.

Some files belong to a row and must stay with it: a contract's scan, a
patient's form, a product's supplier price list. Anyone who can read the row
may download the file, and nobody else. karni-storage gives such a file a
field type, keeps it out of public URLs, and serves it only after the row's
own viewset has found the row for the caller.

It builds on core's S3 backend ([`KARNI_STORAGE = "s3"`](settings.md),
`karni.storage.S3Storage`) and core's thumbnailer
(`karni.storage.thumbnails.make_thumbnail`). It adds no second way to talk to
a bucket.

## Install

```bash
pip install "karni-storage[images]"   # the images extra brings Pillow, for thumbnails
karni add storage
```

Add the URLs once to `config/urls.py` (`karni build` places this line for you):

```python
path("api/", include("karni_storage.urls")),
```

Then `make migrate`: the module has one table, the thumbnails it made.

## A protected field

```python
from karni.models import BaseModel
from karni_storage.fields import ProtectedFileField, ProtectedImageField


class Product(BaseModel):
    name = models.CharField(max_length=100)
    manual = ProtectedFileField(
        upload_to="products/manuals/",
        blank=True,
        max_size=5 * 1024 * 1024,
        content_types=["application/pdf"],
    )
    photo = ProtectedImageField(upload_to="products/photos/", blank=True)
```

In `karni.yaml` the same fields are `manual: "file:protected?"` and
`photo: "image:protected?"`, and `karni make model Product
manual:file:protected?` writes them. Both need the module (`C720`).

`max_size` is in bytes (default: `KARNI_STORAGE_MAX_SIZE`, 10 MiB).
`content_types` lists the types the field takes. An image field takes JPEG,
PNG, GIF and WebP unless it lists its own. SVG is never in the default list,
because an SVG can carry script.

The API gives the field as the row's **download path**, never as a storage
URL:

```json
{"id": "6f1c...", "name": "Desk lamp", "manual": "https://example.com/api/products/6f1c.../files/manual/"}
```

The OpenAPI schema keeps the field a file field (binary in requests, a URI in
responses) and adds `x-karni-storage`: `{"protected": true, "max_size",
"content_types", "thumbnails"}`.

## Downloading

`GET /api/<resource>/<id>/files/<field>/` first retrieves the row through the
model's own viewset, exactly as its `retrieve` would:

| Caller | Answer |
|---|---|
| refused by the viewset's gate (anonymous, a missing role) | 401 or 403, as the viewset answers |
| the row is out of their read scope (another user's row) | 404 |
| the row is soft-deleted or does not exist | 404 |
| `Karni.field_roles` hides the field from them | 404 (`STORE010`) |
| the field is empty | 404 (`STORE018`) |
| allowed | the file |

Then:

- **On a bucket** (`KARNI_STORAGE = "s3"`) the answer is a redirect (302) to a
  signed URL that lives `KARNI_STORAGE_URL_EXPIRY` seconds (default 300). The
  redirect is not cached (`Cache-Control: private, no-store`).
- **On local storage** the API streams the file itself, so the same code works
  in development without a bucket.

Images (other than SVG), PDF, plain text, audio and video are served inline.
Everything else is an attachment, and `?download=1` asks for an attachment
always. Streamed files carry `X-Content-Type-Options: nosniff`.

**A token in a header cannot ride on a link.** With JWT auth an `<a href>` or
an `<img src>` cannot send the `Authorization` header. Ask with
`Accept: application/json` and the answer is a link that opens without
credentials:

```json
{"url": "https://bucket.s3.eu-west-1.amazonaws.com/protected/...?X-Amz-Signature=...", "expires_in": 300, "name": "guide.pdf"}
```

On a bucket the url is the signed URL. On local storage it is the download
path with a signed `?sig=`, valid for the same time, and only while the file
is the same one: replacing the file invalidates the link (`STORE019`).
`@karni/storage-ui` does this for you.

## Where the files live

Where protected files go follows core's `KARNI_STORAGE`:

- `local` (the default, for development): a directory, `KARNI_STORAGE_ROOT`
  (default: `protected` next to `MEDIA_ROOT`). No URL serves it, so the media
  URL never exposes a protected file.
- `s3`: the bucket `KARNI_STORAGE_BUCKET` (default: `AWS_STORAGE_BUCKET_NAME`),
  under the key prefix `KARNI_STORAGE_LOCATION` (default: `protected`), on the
  service `KARNI_STORAGE_PROVIDER` names.

The bucket must not be public. Every download is a signed URL, so nothing
needs public read access.

### Provider presets

One setting names the service. The preset gives core's S3 backend the
endpoint, region and addressing style, from what is already in the
environment, so a project never writes an endpoint URL:

| `KARNI_STORAGE_PROVIDER` | Service | Endpoint | Region | Addressing | Direct upload |
|---|---|---|---|---|---|
| `aws` | Amazon S3 | AWS's own | `AWS_S3_REGION_NAME` (required) | virtual-hosted | POST |
| `r2` | Cloudflare R2 | `https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com` | `auto` | path | PUT |
| `minio` | MinIO | `AWS_S3_ENDPOINT_URL` (your server) | `us-east-1` | path | POST |
| `spaces` | DigitalOcean Spaces | `https://<region>.digitaloceanspaces.com` | `AWS_S3_REGION_NAME` (required) | virtual-hosted | PUT |
| `b2` | Backblaze B2 | `https://s3.<region>.backblazeb2.com` | `AWS_S3_REGION_NAME` (required) | virtual-hosted | PUT |
| `gcs-interop` | Google Cloud Storage (XML API, HMAC keys) | `https://storage.googleapis.com` | `auto` | path | PUT |

The credentials stay in the environment (`.env`), never in `karni.yaml`:
`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` hold the access key of
whichever service it is. On AWS with an instance or task role, set
`KARNI_STORAGE_CREDENTIALS=chain` and boto3 finds the credentials itself.

```bash
# .env in production, on Cloudflare R2
KARNI_STORAGE=s3
KARNI_STORAGE_PROVIDER=r2
R2_ACCOUNT_ID=...
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_STORAGE_BUCKET_NAME=product-files
```

Escape hatches: an explicit `AWS_S3_ENDPOINT_URL` wins over the preset's
endpoint (an R2 jurisdiction, a private endpoint), `AWS_S3_ADDRESSING_STYLE`
over its addressing style, and `KARNI_STORAGE_UPLOAD_METHOD` over its upload
method. A service no preset knows is `minio` with its endpoint in
`AWS_S3_ENDPOINT_URL`. `STORAGES["protected"]` (the alias
`KARNI_STORAGE_ALIAS` names) replaces the module's storage with any backend.

The preset configures the storage of protected files. Public media
(`STORAGES["default"]`, core) keeps reading the `AWS_*` settings as before.

## Direct uploads

A large file should not pass through the API server. A direct upload sends
it from the browser straight to the bucket, in three steps:

1. `POST /api/<resource>/files/<field>/upload/` with `{"name", "content_type",
   "size"}`. Only a caller the viewset lets create or change rows may ask, and
   only for a field they may write. The server checks the size and the type
   against the field and answers where to send the file:

    ```json
    {"method": "post", "url": "https://bucket.s3.eu-west-1.amazonaws.com/",
     "fields": {"key": "protected/products/manuals/9f2c.../guide.pdf", "policy": "...", "...": "..."},
     "token": "...", "max_size": 5242880, "content_types": ["application/pdf"], "expires_in": 900}
    ```

    A presigned POST carries a policy the service enforces: the key, the
    content type and a `content-length-range` up to the field's limit. Where
    the service takes no POST policy (R2, Spaces, B2, GCS), the answer is a
    presigned PUT (`"method": "put"`, with the `headers` it must carry). Each
    upload gets a key of its own under the field's `upload_to`.

2. The browser sends the file to `url`: a multipart form with `fields` first
   and the file last (POST), or the file as the body (PUT). The presigned
   request lives `KARNI_STORAGE_UPLOAD_EXPIRY` seconds (default 900).

3. `POST /api/<resource>/files/<field>/confirm/` with `{"token"}`. The server
   checks that the object is in the bucket (`STORE014` when not), that its
   size and type are ones the field takes and that the type is the one
   declared. A wrong object is deleted and refused (`STORE011`, `STORE012`).
   A right one gets a confirmed token:

    ```json
    {"token": "...", "name": "guide.pdf", "size": 48213, "content_type": "application/pdf"}
    ```

The row's create or update takes the confirmed token as the field's value,
as a string in JSON (`{"manual": "<token>"}`) or as a file part of type
`application/vnd.karni.upload` whose content is the token (what a multipart
form sends). A token is signed, lives a day, and only works for the user it
was given to and the field it was given for (`STORE013`), so nobody can point
a row at an object someone else uploaded.

On local storage the upload step answers `{"method": "api"}`: send the file
in the row's create or update, as for any file field. The same limits apply
to a file sent through the API.

### The bucket's CORS

The browser talks to the bucket's origin, so the bucket must allow the
frontend's origin. For AWS S3:

```json
[{"AllowedOrigins": ["https://app.example.com"], "AllowedMethods": ["POST", "PUT"],
  "AllowedHeaders": ["Content-Type"], "MaxAgeSeconds": 3600}]
```

Other services take the same rules in their own console or API.

## Thumbnails

A protected image gets thumbnails in the sizes `KARNI_STORAGE_THUMBNAIL_SIZES`
names (default `{"small": [160, 160], "medium": [640, 640]}`, bounding boxes,
never upscaled), in `KARNI_STORAGE_THUMBNAIL_FORMAT` (default WebP). A Celery
task makes them after the confirm step and after a row is saved with a new
image, with core's thumbnailer (`KARNI_THUMBNAILER` replaces it). They are
protected files too: `GET .../files/photo/?size=small` serves one after the
same access check. Until the task has run the answer is a 404 (`STORE017`).

`manage.py karni_thumbnails` makes the missing ones, for instance after a new
size is added. `thumbnails=False` on a field turns them off.

## The React side

`@karni/storage-ui` is a package of its own, so `@karni/ui` stays free of
any S3 knowledge. It composes `@karni/ui`'s `FileUpload` and plugs into
`ResourceForm` through its `fields` override:

```tsx
import { ResourceForm } from "@karni/ui";
import { ProtectedFileInput, ProtectedFileLink, ProtectedImage } from "@karni/storage-ui";

<ResourceForm
  resource="products"
  fields={{ manual: { component: ProtectedFileInput, props: { resource: "products" } } }}
/>

<ProtectedFileLink href={product.manual}>Manual</ProtectedFileLink>
<ProtectedImage src={product.photo} size="small" alt={product.name} />
```

- `ProtectedFileInput` runs the three steps as soon as a file is picked, with a
  progress bar, and the form saves the confirmed token. On local storage the
  file itself goes with the form.
- `ProtectedFileLink` asks the download path for a signed link on click and
  opens it, so it works with session and JWT auth alike. `ResourceDetail` and
  `ResourceTable` use it by themselves for every protected field: the schema's
  `x-karni-storage` marks the field, and importing `@karni/storage-ui` registers
  the link (`registerProtectedFileLink` from `@karni/ui` swaps in your own). A
  download path the API gives as an absolute URL on another host (behind a dev
  proxy) is asked at the client's own origin.
- `ProtectedImage` shows an image or one of its thumbnails through a signed
  link.
- `useProtectedUpload` and `useProtectedFileLink` are the hooks under them.
  `transport` replaces the request to the bucket (the default is
  XMLHttpRequest, for its progress events).

## Rate limits

Each endpoint is limited per caller (the user, else the client IP) under a
throttle scope of its own, with Karni's action throttle. Past the limit it
answers 429 with `Retry-After`. A signed download link counts against the IP
that opens it. The project-wide `anon` and `user` throttles still apply.

| Scope | Endpoint | Default |
|---|---|---|
| `storage.download` | `GET <resource>/<id>/files/<field>/` (a thumbnail too) | `1000/hour` |
| `storage.upload` | `POST <resource>/files/<field>/upload/` | `120/hour` |
| `storage.confirm` | `POST <resource>/files/<field>/confirm/` | `120/hour` |

`KARNI_STORAGE_THROTTLE_RATES` sets the module's rates:

```python
KARNI_STORAGE_THROTTLE_RATES = {"download": "3000/hour", "upload": "60/hour", "confirm": "60/hour"}
```

A rate under the scope in `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]` wins
over it, as for Karni's viewset throttles, and `None` in either turns that
limit off. A list page that shows many thumbnails asks for one link each, so
raise `download` for such pages rather than turning it off. A rate the
setting does not take fails `karni check` (`STORE005`).

## karni.yaml, karni plan and karni build

```yaml
modules:
  storage: {provider: r2}
apps:
  catalog:
    entities:
      Product:
        fields: {name: str, manual: "file:protected?", photo: "image:protected?"}
```

The module's options are its `KARNI_STORAGE_*` settings without the prefix
(`provider`, `url_expiry`, `thumbnail_sizes`, `throttle_rates`, ...). `karni plan --questions`
asks the provider until the spec names one. `karni plan` shows `+ storage:
provider r2` and the fields. `karni build` runs `karni add storage`, writes
`KARNI_STORAGE_PROVIDER` into the `karni:spec` block of `config/settings.py`,
places the URL include at the `# karni:urls` marker of `config/urls.py` and
migrates the module's table.

## karni check

| Code | Problem |
|---|---|
| [STORE001](errors.md#store001) | `KARNI_STORAGE_PROVIDER` names no preset |
| [STORE002](errors.md#store002) | `KARNI_STORAGE=s3` and the preset has no credentials |
| [STORE003](errors.md#store003) | the preset lacks its region, account id, endpoint or bucket |
| [STORE004](errors.md#store004) | `karni_storage.urls` is not included |
| [STORE005](errors.md#store005) | a setting has a value it does not take |
| [STORE006](errors.md#store006) | a model with protected fields has no viewset on the API |

The checks make no network request: they check that the values are there.
The API's answers are `STORE010` to `STORE020` ([error codes](errors.md)).

## Settings

| Setting | Default | What it does |
|---|---|---|
| `KARNI_STORAGE_PROVIDER` | `aws` | The service: `aws`, `r2`, `minio`, `spaces`, `b2`, `gcs-interop` |
| `KARNI_STORAGE_CREDENTIALS` | `keys` | `keys` (the two `AWS_*` keys) or `chain` (boto3's own) |
| `KARNI_STORAGE_BUCKET` | `""` | The bucket. Empty: `AWS_STORAGE_BUCKET_NAME` |
| `KARNI_STORAGE_LOCATION` | `protected` | The key prefix in the bucket |
| `KARNI_STORAGE_ROOT` | `""` | The local directory. Empty: `protected` next to `MEDIA_ROOT` |
| `KARNI_STORAGE_URL_EXPIRY` | `300` | Seconds a signed download link lives |
| `KARNI_STORAGE_UPLOAD_EXPIRY` | `900` | Seconds a presigned upload lives |
| `KARNI_STORAGE_UPLOAD_METHOD` | `""` | `post` or `put`. Empty: the preset's |
| `KARNI_STORAGE_MAX_SIZE` | `10485760` | The size limit of a field without `max_size` |
| `KARNI_STORAGE_THUMBNAIL_SIZES` | `{"small": [160, 160], "medium": [640, 640]}` | Thumbnail names and bounding boxes |
| `KARNI_STORAGE_THUMBNAIL_FORMAT` | `WEBP` | The thumbnails' format |
| `KARNI_STORAGE_THROTTLE_RATES` | `{"download": "1000/hour", "upload": "120/hour", "confirm": "120/hour"}` | The endpoints' rate limits, per caller (scopes `storage.download`, `storage.upload`, `storage.confirm`) |
| `KARNI_STORAGE_ALIAS` | `protected` | A `STORAGES` alias that replaces the module's storage |
| `R2_ACCOUNT_ID` | `""` | Cloudflare R2's account id |

Each one reads the environment variable of the same name.

## Testing

The module's own suite runs without a network. Signing a URL or a POST policy
is local work in botocore. For the bucket's answers (`head_object` in the
confirm step), wrap the storage's client in botocore's `Stubber`:

```python
from botocore.stub import Stubber
from django.test import override_settings
from karni_storage.storage import protected_storage, s3_client

with override_settings(KARNI_STORAGE="s3", KARNI_STORAGE_PROVIDER="aws"):
    with Stubber(s3_client(protected_storage())) as bucket:
        bucket.add_response("head_object", {"ContentLength": 2048, "ContentType": "application/pdf"})
        ...
```

A project's tests run on local storage by default, so a protected file is a
file on disk and the download path streams it.

## What it does not do yet

- An object uploaded but never confirmed, or confirmed but never saved on a
  row, stays in the bucket. Nothing cleans such objects up yet.
- A thumbnail of a replaced image is not deleted.
- Public media (`STORAGES["default"]`) does not follow the preset.
