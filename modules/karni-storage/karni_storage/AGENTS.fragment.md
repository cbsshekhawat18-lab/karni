## Protected files (karni-storage)
- A file only the row's readers may download: `ProtectedFileField` /
  `ProtectedImageField` from `karni_storage.fields` (karni.yaml: `file:protected`,
  `image:protected`). Never hand-write download views, presigned URLs or boto3 calls.
- The API gives the field as its download path, `<resource>/<id>/files/<field>/`:
  the row is retrieved through its own viewset first, then a signed URL (bucket)
  or a stream (local storage). `?size=<name>` serves a thumbnail.
- Wire the URLs once in config/urls.py: `path("api/", include("karni_storage.urls"))`
- Direct uploads: `@karni/storage-ui`'s `ProtectedFileInput` in ResourceForm
  (`fields={{ photo: { component: ProtectedFileInput, props: { resource } } }}`).
- KARNI_STORAGE=local in development, s3 in production. KARNI_STORAGE_PROVIDER
  (aws|r2|minio|spaces|b2|gcs-interop) sets the endpoint. Credentials stay in .env:
  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_STORAGE_BUCKET_NAME,
  AWS_S3_REGION_NAME, R2_ACCOUNT_ID. Thumbnails run in Celery.
