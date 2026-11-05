# karni-storage

Protected files for [Karni](https://github.com/cbsshekhawat18-lab/karni): files
a row owns, kept in S3 or an S3-compatible service (or on disk in
development) and handed only to whoever may read that row. It is
**experimental**: its names may change in a minor release, with a CHANGELOG
entry.

The full guide is [docs/storage.md](https://cbsshekhawat18-lab.github.io/karni/storage/).

## Install

```bash
pip install "karni-storage[images]"   # the images extra brings Pillow, for thumbnails
karni add storage
```

Then add the URLs once to `config/urls.py`:

```python
path("api/", include("karni_storage.urls")),
```

and run `make migrate` (the module has one table, its thumbnails).

## Use

```python
from karni_storage.fields import ProtectedFileField, ProtectedImageField


class Product(BaseModel):
    manual = ProtectedFileField(upload_to="products/manuals/", blank=True,
                                max_size=5 * 1024 * 1024, content_types=["application/pdf"])
    photo = ProtectedImageField(upload_to="products/photos/", blank=True)
```

In `karni.yaml` the same fields are `manual: "file:protected?"` and
`photo: "image:protected?"`.

The API gives `manual` as `/api/products/<id>/files/manual/`. A `GET` there
retrieves the row through `ProductViewSet` first: 401 or 403 from its gate,
404 for another user's row, a soft-deleted row or a missing one. Then it
redirects to a signed URL in the bucket (`KARNI_STORAGE=s3`) or streams the
file (`KARNI_STORAGE=local`). `?size=small` serves a thumbnail of an image.

## Settings

| Setting | Env | Default | Meaning |
| --- | --- | --- | --- |
| `KARNI_STORAGE_PROVIDER` | same | `aws` | The service: `aws`, `r2`, `minio`, `spaces`, `b2`, `gcs-interop`. Sets the endpoint, region and addressing style |
| `KARNI_STORAGE_CREDENTIALS` | same | `keys` | `keys` (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY) or `chain` (boto3's own: an AWS role or profile) |
| `KARNI_STORAGE_BUCKET` | same | `""` | The bucket of protected files. Empty: `AWS_STORAGE_BUCKET_NAME` |
| `KARNI_STORAGE_LOCATION` | same | `protected` | The key prefix inside the bucket |
| `KARNI_STORAGE_ROOT` | same | `""` | The local directory. Empty: `protected` next to `MEDIA_ROOT` |
| `KARNI_STORAGE_URL_EXPIRY` | same | `300` | Seconds a signed download URL lives |
| `KARNI_STORAGE_UPLOAD_EXPIRY` | same | `900` | Seconds a presigned upload lives |
| `KARNI_STORAGE_UPLOAD_METHOD` | same | `""` | `post` or `put`. Empty: the preset's |
| `KARNI_STORAGE_MAX_SIZE` | same | `10485760` | The size limit of a field without `max_size` |
| `KARNI_STORAGE_THUMBNAIL_SIZES` | same (JSON) | `{"small": [160, 160], "medium": [640, 640]}` | Thumbnail names and bounding boxes |
| `KARNI_STORAGE_THUMBNAIL_FORMAT` | same | `WEBP` | The thumbnails' format |
| `KARNI_STORAGE_THROTTLE_RATES` | same (JSON) | `{"download": "1000/hour", "upload": "120/hour", "confirm": "120/hour"}` | Rate limits per caller, scopes `storage.download`, `storage.upload`, `storage.confirm`. A rate under the scope in `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]` wins |
| `KARNI_STORAGE_ALIAS` | same | `protected` | A `STORAGES` alias that, when defined, replaces the module's storage |
| `R2_ACCOUNT_ID` | same | `""` | Cloudflare R2's account id (the `r2` preset builds its endpoint from it) |

Credentials stay in the environment: `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_REGION_NAME` and,
for R2, `R2_ACCOUNT_ID`. `karni check` fails (STORE001 to STORE006) on an
unknown preset, missing credentials, a missing region, account id, endpoint
or bucket, and a missing URL include.

## Escape hatches

- `STORAGES["protected"]` replaces the module's storage with any backend.
- `AWS_S3_ENDPOINT_URL` wins over a preset's endpoint, `AWS_S3_ADDRESSING_STYLE`
  over its addressing style, `KARNI_STORAGE_UPLOAD_METHOD` over its upload method.
- `storage=` on one field, `thumbnails=False` on an image field.
- `KARNI_THUMBNAILER` (core) replaces the thumbnail rendering.
- The row's viewset decides who may download and upload: its `access`.
- A `path()` of your own before the include replaces one endpoint.

## Admin

No `admin.py`: the thumbnails' admin is derived from `AdminMeta`.
