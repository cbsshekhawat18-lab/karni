---
description: "karni load puts a project's real content into the database from a JSON or YAML file. Rows are matched by natural key, relations and files are named, children nest, and the whole file loads in one validated transaction."
---

# Loading content

A site needs its real copy and images in the database: the services, the
projects with their galleries, the team. `karni load` reads them from a
content file kept in the repository and creates or updates the rows. Run it
again after editing the file and it changes only what changed. Run it with
an unchanged file and it changes nothing and says so.

```sh
karni load content/site.json              # create or update every row the file lists
karni load content/site.json --dry-run    # print what would change, write nothing
karni load content/site.json --refresh-files
karni load content/site.json --prune      # also delete children the file no longer lists
karni load content/site.json --as editor@example.com --json
```

It wraps `manage.py karni_load` through the project interpreter, like the
other runners. `karni.transfer.loading.load_content()` is the importable form.

When the content is in a designer's static pages, do not type it into the
file: [`karni design extract`](design-content.md) writes it from the pages,
in this format.

## Demo data or content

| | `karni seed` | `karni load` |
|---|---|---|
| What it writes | Random, realistic rows inferred from the models | The rows a content file lists, exactly |
| Where the data comes from | The value engine and `<app>/seeds.py` | A JSON or YAML file in your repository |
| Running it twice | Refuses, because the tables now hold rows (`--reset` or `--force`) | Changes nothing the second time |
| Where it runs | Development and demo databases | Every environment, production included |
| Deletes rows | `--reset` wipes the project's tables | Never a top-level row. `--prune` removes unlisted children |

Use [`karni seed`](seeding.md) to fill an empty development database. Use
`karni load` for anything a visitor of the live site reads. Seed refuses to
add demo rows to a table that already holds rows, so the two never mix by
accident.

## A full example

The models of a small portfolio site:

```python
# portfolio/models.py
from django.db import models

from karni.models import BaseModel


class Service(BaseModel):
    slug = models.SlugField(unique=True)          # the natural key, inferred
    title = models.CharField(max_length=100)
    image = models.ImageField(upload_to="services/", blank=True)


class Project(BaseModel):
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=100)
    published = models.BooleanField(default=False)
    services = models.ManyToManyField(Service, blank=True, related_name="projects")
    image = models.ImageField(upload_to="projects/", blank=True)


class ProjectImage(BaseModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="gallery")
    position = models.PositiveIntegerField()
    image = models.ImageField(upload_to="gallery/")
    alt = models.CharField(max_length=200, blank=True, default="")

    class Meta(BaseModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["project", "position"],
                condition=models.Q(deleted_at__isnull=True),
                name="gallery_position",
            )
        ]


class Slide(BaseModel):
    placement = models.CharField(max_length=20)
    service = models.ForeignKey(Service, null=True, blank=True, on_delete=models.CASCADE)
    position = models.PositiveIntegerField()
    heading = models.CharField(max_length=200)

    class Meta(BaseModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["placement", "service", "position"], name="slide_place"
            )
        ]


class Member(BaseModel):
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=100, blank=True, default="")
    photo = models.ImageField(upload_to="team/", blank=True)
    projects = models.ManyToManyField(Project, blank=True, related_name="team")

    class Karni:
        natural_key = "name"                      # declared: name is not unique
```

The content file and its images, side by side:

```text
content/
  site.json
  img/
    branding.jpg
    harbour-house.jpg
    harbour-house-1.jpg
    harbour-house-2.jpg
    lena.jpg
```

```json
{
  "portfolio.Service": [
    {"slug": "branding", "title": "Branding", "image": "img/branding.jpg"},
    {"slug": "web", "title": "Websites", "image": ""}
  ],
  "portfolio.Project": [
    {
      "slug": "harbour-house",
      "title": "Harbour House",
      "published": true,
      "services": ["branding", "web"],
      "image": "img/harbour-house.jpg",
      "gallery": [
        {"image": "img/harbour-house-1.jpg", "alt": "The new sign"},
        {"image": "img/harbour-house-2.jpg", "alt": "The menu"}
      ]
    }
  ],
  "portfolio.Slide": [
    {"placement": "home", "service": null, "position": 1, "heading": "Make it clear"},
    {"placement": "service", "service": "branding", "position": 1, "heading": "Branding"}
  ],
  "portfolio.Member": [
    {"name": "Lena", "role": "Founder", "photo": "img/lena.jpg", "projects": ["harbour-house"]}
  ]
}
```

The first run:

```text
$ karni load content/site.json
Loaded content/site.json:
  portfolio.Service       2 created, 0 updated, 0 unchanged, 1 file(s) uploaded
  portfolio.Project       1 created, 0 updated, 0 unchanged, 1 file(s) uploaded
  portfolio.ProjectImage  2 created, 0 updated, 0 unchanged, 2 file(s) uploaded
  portfolio.Slide         2 created, 0 updated, 0 unchanged
  portfolio.Member        1 created, 0 updated, 0 unchanged, 1 file(s) uploaded
```

The second run, with the same file:

```text
$ karni load content/site.json
Loaded content/site.json:
  portfolio.Service       0 created, 0 updated, 2 unchanged
  portfolio.Project       0 created, 0 updated, 1 unchanged
  portfolio.ProjectImage  0 created, 0 updated, 2 unchanged
  portfolio.Slide         0 created, 0 updated, 2 unchanged
  portfolio.Member        0 created, 0 updated, 1 unchanged
Nothing changed.
```

YAML works the same way: name the file `site.yaml` or `site.yml`. PyYAML
comes with drf-spectacular, which Karni depends on.

## The file format

The file is one object. Each key is a model label (`app_label.Model`) and
holds a list of rows. Each row is an object of field names and values, in
the form the model's API takes them: strings for text and dates, numbers,
`true` and `false`, `null` for an empty nullable field. The lists load in
the order the file gives them.

A field the API publishes read-only (`APIMeta.read_only`, owner fields,
timestamps, non-editable fields) cannot be set from the file. A name that is
not a field, a child list or a file field is refused, and the message lists
the names the model takes.

## How rows are matched

Every row carries its key, and the key decides whether the row updates an
existing row or creates a new one. The key is, in order:

1. `class Karni: import_key = "<field>"`. It is the same declaration the
   [importer](import-export.md#hooks) uses.
2. The model's [natural key](import-export.md#natural-keys):
   `class Karni: natural_key = "<field>"`, else the first unique slug, char
   or email field (`slug`, `email`, `sku`).
3. The fields of the model's first unique constraint (`unique_together`, or
   a `UniqueConstraint` on fields), such as `(placement, service, position)`
   for `Slide` above. A nullable field in the key matches `null`.
4. The primary key. The row then carries its `id`, and a created row keeps
   that id, so the next run finds it.

A row is **unchanged** when every value in it already matches the database,
many-to-many fields and files included. Nothing is saved for it, so
`updated_at`, `updated_by` and the change history stay as they are. A field
the row leaves out keeps its current value, and on a new row its default.

Rows are matched among all rows, soft-deleted ones included. A soft-deleted
row the file still lists is restored.

## Relations

A relation names its target by the target's natural key, or by its primary
key: one value for a foreign key, a list for a many-to-many field.
`Karni.import_lookup = {"service": "title"}` names a different target field,
as it does for the importer.

A foreign key's target must exist when its row loads: earlier in the file,
or already in the database. An optional many-to-many field is set once every
row of the file exists, so `Member.projects` above names a project that comes
later in the file, and two models may name each other. A required
many-to-many field (`blank=False`) is set with its row, so its targets come
first.

## Files and images

A file or image field holds a path relative to the content file. The file is
uploaded through the field's storage when the row has no file yet. Later
runs leave it alone, even when the file on disk changed, so a load never
re-uploads a gallery for nothing. `--refresh-files` uploads every file the
file names again. An empty string leaves the field as it is.

Every file is checked the way the API checks an upload before anything
reaches the storage: an image field's file must open as an image. A file
field the model requires (no `blank=True`) needs a path on a new row. Once
the row has its file, later runs may leave the path out. A path that does
not exist, a file the API would refuse and a missing required file are
errors naming the row and the field. Uploads happen only after every row is
valid, and a dry run uploads nothing.

## Children

A list under a reverse relation's accessor holds the row's children. The
accessor is the foreign key's `related_name` (`gallery` above), or
`<model>_set` without one. A child is matched by its parent plus its own
key:

- Its natural key (`Karni.import_key` or `Karni.natural_key`), among that
  parent's children only.
- Else the rest of a unique constraint that includes the parent foreign key,
  such as `(project, position)` above.

When that rest is one integer field and a child row leaves it out, the
child's position in the list is used, counted from 1. That is why the gallery
rows above carry no `position`. Reordering the list reorders the gallery.

`--prune` deletes the children of a listed parent that its list does not
name, the way the model deletes (a `BaseModel` row is soft-deleted). A row
that leaves its child list out keeps all its children, with or without
`--prune`. Top-level rows are never deleted: remove them in the admin.

## Validation and errors

Every row goes through the serializer the model's API uses: types, choices,
lengths, required fields, uniqueness and `Model.clean()`. The whole file
loads in one transaction. When any row fails, nothing is written, files
included, and the command exits with `E805` and every problem it found:

```text
CommandError: E805: content/site.json: 2 problem(s), so nothing was loaded. Fix the rows and run again.
  portfolio.Project (slug='harbour-house'): services: no service with slug or id 'print'.
  portfolio.ProjectImage (slug='harbour-house' > position=2): image: no such file 'img/harbour-house-2.jpg' (paths are relative to site.json).
See https://cbsshekhawat18-lab.github.io/karni/errors/#e805
```

Each line names the model, the row by its key (a child after its parent),
the field and the problem. A file that cannot be read at all (missing, not
valid JSON or YAML, the wrong shape, an unknown model) is `E804`.

`--dry-run` runs every step inside a transaction and rolls it back. Its
report is a diff per model: the counts, then each row it would create (`+`),
each row it would change (`~`) with the fields that change, the old value
and the new one, each file it would upload and each child `--prune` would
delete (`-`). A model lists its first 20 rows and counts the rest:

```text
$ karni load content/site.json --dry-run --prune
Dry run of content/site.json, nothing was written:
  portfolio.Service       1 created, 0 updated, 2 unchanged
      + slug='print'
  portfolio.Project       0 created, 1 updated, 0 unchanged
      ~ slug='harbour-house': title 'Harbour House' -> 'Harbour House, Kiel', services ['3f2c...', '9a1e...'] -> ['3f2c...']
  portfolio.ProjectImage  0 created, 0 updated, 1 unchanged, 1 pruned
      - slug='harbour-house' > The menu
```

`--json` prints the same report with each change under `"changes"` for every
model, on a real run too.

## Who made the change

Writes run as the user `--as` names (an email, a username or a primary key)
through `karni.middleware.current_user`. `created_by` and `updated_by` are
stamped with that user, and so are owner fields such as
`Owned("organizer")` on created rows. Without `--as` they stay empty.
[Change history](change-history.md) records the whole load as one batch of
kind `load`, labelled with the file name. `Karni.after_import` runs once per
model after a load commits, with that model's counts.

The loader is trusted like `migrate`. No `access` gate, row scope or field
role applies: whoever can run management commands can already change any
row. `--as` attributes the writes and grants nothing.

## In code

```python
from karni.transfer.loading import ContentImporter, load_content

report = load_content("content/site.json", actor=editor, dry_run=True)
print(report.render())             # or report.to_dict()
```

`load_content()` raises `karni.transfer.loading.LoadError` (`E804`, `E805`)
with `.problems`, one entry per refused row.

Escape hatches:

| Need | Do |
|---|---|
| A different key | `class Karni: import_key = "<field>"` or `natural_key = "<field>"` |
| A relation named by another field | `class Karni: import_lookup = {"service": "title"}` |
| Rewrite rows before validation | `class Karni: import_transform = "app.module.fn"` |
| Run something after a load | `class Karni: after_import = "app.module.fn"` |
| Put an access check back | Subclass `ContentImporter`, override `may_create`, `may_update`, `write_queryset` or `readable`, and pass `importer_class=` to `load_content()` |

## Replacing a hand-written loader

A project that wrote its own management command to load content (read a
JSON file, `update_or_create` by slug, link many-to-many fields by slug,
upload images once, sync a gallery by position) can delete it:

1. Rename the file's top-level keys to model labels and keep the rows.
2. Make sure each model has a key: a unique `slug`, a declared
   `Karni.natural_key`, or a unique constraint. Add `published: true` and
   any other value the command used to set to the rows themselves.
3. Move the image paths so they are relative to the content file.
4. Run `karni load content/site.json --dry-run`, then without it.
