---
description: "From a designer's static pages to models and real content: karni design analyze finds the content that repeats and proposes models, relations and decisions, karni design extract writes the pages' content as a karni load file, and karni load fills the database, the same way every time."
---

# From a design to content

A designer's pages hold the site's content as markup: six cards for six
services, a gallery in every project, a page per doctor. [`karni import
design`](public-site.md#import-a-design) turns the pages into templates. Three
commands turn the content into rows, so that nothing is retyped and nothing
is made up:

```bash
karni design analyze ../design --map content/design-map.json   # the models it needs
# run the karni make model commands it prints, answer its decisions in the map
karni make migration && karni migrate
karni design extract ../design --map content/design-map.json -o content/site.json
karni load content/site.json
```

`karni rules --procedure site-from-design` gives an agent these steps in
order: the analysis, the import (`karni import design --editable --map
content/design-map.json`, where the content the map reads into rows gets no
blocks, see [import a design](public-site.md#import-a-design)), the models,
the content, templates that loop over the rows, the forms and the page test.
`karni new "Name" --kind site --design ../design` runs the analysis and the
import on a new project and prints the rest
([start a site project](public-site.md#start-a-site-project)).

## What analyze reads

`karni design analyze <design folder>` reads every page of the folder the
import reads, and works from the markup alone:

1. **The layout is set aside.** The header, the footer and anything else
   every page shares is the layout, not content.
2. **Repeated structures.** Sibling elements with the same tag and classes and
   a similar inside, two or more times, are a list: cards, list items, the
   pictures of a gallery. A list inside an item (a project's gallery) is
   found inside each item. A class that only one item has (a slider's
   `is-active`) does not split a list, and utility classes (`col-md-4`,
   `mt-3`) never matter.
3. **Detail pages.** Pages that a list links to item by item (each card to its
   own page), or the pages of one folder, that share a structure are one
   model's detail pages. The values that differ between them are fields. What
   they share is the template.
4. **The same items in several places.** A card that links to a detail page,
   a link whose `#anchor` is a list item's `id`, the same `data-` key or the
   same title: those lists hold the same rows, so they are one model and their
   fields merge. A value that is the same for every row in two places is one
   field. The home page's three cards and the full list are one model.
5. **Relations.** A list of links to another model's items, inside an item or
   on a detail page, is a many-to-many field. A list nested in another
   model's items with each item in one place is a foreign key (cards under
   their menu section). An attribute whose tokens are another model's keys
   (`data-tags="houses interiors"`) is a relation too. A text that is always
   another model's title ("Taught by Mia Chen") is that relation's, not a
   field.
6. **One more row.** A single block on the page of a list, with the values
   that list's items hold (a class-named one among them), is proposed as one
   more row of that model, with a flag named after its own class: a founder's
   card above the team cards. It is a decision.
7. **What stays markup.** A list of one or two short values on one page
   (opening hours, figures in a row) stays in its template. A list inside an
   item without pictures becomes a JSON field (a list of strings, of pairs for
   a `<dl>`, of objects), and one with pictures a child model. A section only
   some detail pages have stays in those pages' templates. A structure found
   on several pages with different items each time (a slider) is one model
   with a `page` field, and a foreign key to the detail page's model when it
   is on detail pages too. Two lists in one section with as many items each
   (a slider's pictures and its captions) are read as the same rows, item by
   item, and the report says so.

Every model and field name comes from the design: a class (with BEM
elements and the item's prefix taken off, so `course-card__summary` is
`summary`), a heading, a label before a list, an `aria-label`, a page or a
folder name. Rename anything in the map.

### Fields and types

| The markup shows | The field |
|---|---|
| A heading, with words set apart (`<em>`, `<span class="accent">`) | `str`, the words kept as `==marked words==` |
| A paragraph, or several in a row | `str`, or `text` joined by blank lines |
| An image | `image`, and its `alt` as `<name>_alt` |
| A link to a page of the design that is not a row | `str:200`, the page's URL path |
| A list of short texts | `json`, a list of strings |
| A definition list | `json`, `[term, definition]` pairs |
| `<time datetime="...">` or a date written out ("14 March 2026") | `date` |
| A price ("€4.50", "From $12") | `decimal:10:2`, the symbol left in the template |
| A number with the same words around it ("12 weeks") | `int`, the words left in the template |
| `01`, `02`, `03` before the items | the rows' `position`, not a field |
| `01 — Design` | `position`, and `Design` as the field |
| A badge only some items have ("New", "Vegan") | `bool` |
| An arrow or an icon every item has | the template's, left out of the value |

Every model of rows gets a `slug` (from the detail page's file name, the
item's `id` or key, or its title) and a `position` (the order of the full
list). A child model (a gallery) is matched by its parent and its position.
A value some rows lack makes the field optional.

### Decisions

Some things look the same in markup and are not the same in a model:

- **A list of other items on a detail page.** "Selected work" on each service
  page may be chosen by hand, or be every project of that service. Analyze
  compares the lists with the relations it found the other way (does each
  project's own list of services agree?) and says what it sees, but it does
  not decide.
- **Some items shown on another page.** The home page shows three of the eight
  menu items: chosen by hand (a `featured` flag) or by a rule (the first, the
  newest).
- **One more row.** A card styled on its own holds a list item's values: one
  more row with a flag, or page copy.

Each decision is printed with its evidence and both choices, and marked
`decide` in the map. Extract refuses to run while one is open (`C122`).

### The output

```text
$ karni design analyze ../design
Design ../design: 7 page(s), 3 model(s) proposed from the markup.

Teacher: 3 row(s), on teachers.html
  title     str:80       Mia Chen
  slug      slug:title   mia-chen
  photo     image        img/mia.jpg
  subject   str:80       Ceramics
  ...

Course: 4 row(s), on courses.html, courses/drawing.html, ... and 2 more
  detail pages: 4 (courses/pottery.html, ...)
  title        str:80               Wheel pottery
  tagline      str:80               Shape clay ==by hand==
                                    note: highlighted words are ==marked==: render with {{ value|highlight }}
  weeks        int                  12 weeks
  start        date                 2026-09-01
  price        decimal:10:2         $240
  related      m2m:website.Course?  drawing, printing  (decide)
  teacher      fk:Teacher?          mia-chen
  featured     bool                 True  (decide)
  courseimage_set  child rows (courseimage)

CourseImage: 8 row(s), rows of Course, ...

Decide (2), the markup cannot tell:
  1. Course.featured: index.html shows some Course rows: chosen by hand, or by a rule?
     It shows 3 of 4: Wheel pottery, Life drawing, Weaving basics.
  ...

Highlighted words (kept as ==words==, one convention):
  - Course.tagline set words apart with <em>. Set `KARNI_SITE_HIGHLIGHT = {"marker": "==", "tag": "em", "class": ""}` in config/settings.py: then {{ value|highlight }} renders them, and a client types ==words== for the same in an editable block.

Commands (models others point at come first):
  karni make model Teacher title:str:80 slug:slug:title photo:image ... --app website --order position
  karni make model Course title:str:80 slug:slug:title ... 'teacher:fk:Teacher?' position:int --app website --order position
  karni make model CourseImage course:fk:Course image:image ... --app website --order position --key position
```

The commands run as printed. `--order position` keeps the rows in the
design's order, and `--key position` lets `karni load` match a child row by
its parent and position. A field a decision names joins its model's command
once you keep it (a list of the same model, once the model exists, with
`--force`). `--app` defaults to the app `karni import design` used.

### Highlighted words: one convention

A site has one convention for highlighted words, `KARNI_SITE_HIGHLIGHT`
([karni-site](public-site.md#the-karni-site-module)): the marker a client
types around them (`==words==` by default) and the element they render in.
Editable blocks use it, and the fields analyze proposes use it too: extract
keeps the words a heading sets apart as `==crafted for place==`, so staff
edit a field and a block the same way. A marker the text itself holds is
written with a backslash before it (`\==`).

The report says which markup the design uses and where. When `karni import
design --editable` already wrote `KARNI_SITE_HIGHLIGHT` with that markup,
it says so. Otherwise it gives the setting to add, so that
`{{ value|highlight }}` needs no argument. A field whose markup differs (an
icon in a badge, `<span class="dot">`) names its own:
`{{ slide.badge|highlight:"span.dot" }}`.

`--json` prints the same as stable JSON: the pages, the models with every
field (type, optional, example, the relation's target, the decision), the
decisions, the page copy, the commands and the draft map.

## The content map

`--map <file>` writes a draft map. It is the one place that says which
structure is which model and which element is which field, and it is yours
to edit: rename a model or a field (in its `fields` and in the `values` that
read it), delete what should stay markup, fix a selector. Analyze never
overwrites it (`C123`) unless you pass `--force`.

```json
{
  "version": 1,
  "design": "../../design",
  "app": "website",
  "marker": "==",
  "models": [
    {
      "name": "Course",
      "fields": {"title": "str:80", "slug": "slug:title", "start": "date", "teacher": "fk:Teacher?", ...},
      "key": "slug",
      "order": "position",
      "highlight": {"tagline": "em"},
      "sources": [
        {
          "pages": ["courses/pottery.html", "courses/drawing.html", "..."],
          "key": {"from": "page"},
          "values": {
            "title": "h1.course__title",
            "image": "img.course__image@src",
            "topics": {"select": "ul.course__topics > li", "list": true},
            "teacher": {"select": "p.course__teacher > a@href", "to": "Teacher"},
            "related": {"select": "ul.related__list > li a.related__link@href", "to": "Course", "many": true},
            "courseimage_set": {"select": "figure.gallery__item", "rows": {"image": "img@src", "caption": "figcaption"}}
          }
        },
        {
          "page": "courses.html",
          "items": "li.course-list__item",
          "key": {"from": "link", "select": "a.course-list__link@href"},
          "position": true,
          "values": {"start": "time.course-list__start@datetime", "price": "span.course-list__price"}
        }
      ]
    }
  ]
}
```

The top-level `"marker"` is what extract writes around highlighted words:
`"=="` by default, `KARNI_SITE_HIGHLIGHT`'s default. Change it only together
with the setting's `"marker"`, so the site keeps one convention.

A **source** is where a model's items are: `page` (or `pages`, for detail
pages and lists on them), `items` (a selector for the items, absent when the
page itself is the item), `within` and `parent` (items inside parents, each
row pointing at its parent), `key` (how an item's key is read), `position`
(write the item's place in its list), `create: false` (only add values to rows
another source makes) and `set` (constant values, `{page}` being the page's
key).

A **key** is read `{"from": "page"}` (the page's file name),
`{"from": "link", "select": "...", "strip": "p-"}` (the page or `#anchor`
a link points at), `{"from": "attr", "name": "id", "strip": "p-"}`,
`{"from": "field", "field": "title"}` (the title as a slug) or
`{"from": "position", "prefix": "home"}` (`home-1`, `home-2`). An item read
from several sources gets one key everywhere, and its values merge into one
row: the first source with a value wins, and extract says where two pages
disagree.

A **value** is a place: a CSS selector relative to the item, `@attribute`
for an attribute (`img@src`, `@data-tags` for the item's own), `:scope` for
the item's own text. Selectors support types, classes, ids, attributes,
`:nth-of-type()`, `:first-of-type`, `:last-of-type`, `:has()`, `:not()` of one
compound (`p:not(.role)`), the child and descendant combinators and comma
groups. A value can also be an object with
`select` and one of: `all` (every match's text, joined), `list` (a list),
`fields` (a list of objects), `pairs` (a definition list), `to` with `many`,
`split` or `by` (a relation, by link, by key or by title), `rows` (child rows),
`present` (true when the place matches), `drop` (markup to leave out),
`pattern` (a regular expression whose last group is the value), `link:
"path"` (a page's URL path) and `decide` (an open decision).

## Extract

```text
$ karni design extract ../design --map content/design-map.json -o content/site.json
Wrote content/site.json:
  website.Teacher  3 row(s)
  website.Course   4 row(s) (8 child row(s))
```

The output is a [content file](content-loading.md): one list of rows per
model, models others point at first, child rows nested under their parent.
Each value is parsed by its field's type (`"12 weeks"` is `12`, `"€4.50"` is
`"4.50"`, `"14 March 2026"` is `"2026-03-14"`), relations name their rows by
key, and image paths are relative to the output file, pointing into the
design folder, so `karni load` uploads the designer's own images once.
Extract lists what to check: an image the design does not have, two pages
that disagree on a value, a required field some row has no value for. A
map it cannot follow stops it before anything is written (`C121`).

Run it again after the designer changes a page: the same map gives the same
file, and `karni load` changes only what changed.

## Load, then loop

```text
$ karni load content/site.json
Loaded content/site.json:
  website.Teacher      3 created, 0 updated, 0 unchanged, 3 file(s) uploaded
  website.Course       4 created, 0 updated, 0 unchanged, 4 file(s) uploaded
  website.CourseImage  8 created, 0 updated, 0 unchanged, 8 file(s) uploaded
$ karni load content/site.json
...
Nothing changed.
```

`karni load --dry-run` shows the diff per model first. The models now hold
the content, and `karni seed` refuses their tables. Each page's repeated
markup becomes one copy inside a loop, and a model's detail pages become one
view and template:

```python
def course(request: HttpRequest, slug: str) -> HttpResponse:
    course = get_object_or_404(
        Course.objects.select_related("teacher").prefetch_related("courseimage_set"), slug=slug
    )
    return render(request, "website/course.html", {"course": course})
```

```django
{% load static karni_site %}
<h1 class="course__title">{{ course.title }}</h1>
<h2 class="course__tagline">{{ course.tagline|highlight }}</h2>
<div class="gallery">
  {% for picture in course.courseimage_set.all %}
  <figure class="gallery__item"><img src="{{ picture.image.url }}" alt="{{ picture.image_alt }}"><figcaption>{{ picture.caption }}</figcaption></figure>
  {% endfor %}
</div>
```

`{{ value|highlight }}` (from [karni-site](public-site.md#the-karni-site-module))
writes the `==marked words==` back in `KARNI_SITE_HIGHLIGHT`'s markup (here
`{"marker": "==", "tag": "em", "class": ""}`), everything else escaped.
`|highlight:"span.dot"` names another markup for one value, and
`|highlight:""` drops the marks, for a `<title>` or an `alt`.

An editable import with the map (`karni import design --editable --map
content/design-map.json`) left these parts without blocks, so a loop needs
none: the client edits a course in the admin's Courses, not in a block. What
stays a block is the page's own copy around the loop, and on detail pages it
has one key for all of them (`{% editable "course.course.from_past_classes" %}`),
which the one template keeps. An import without the map made blocks of the
items too: take the `{% editable %}` tags out of the markup you turn into a
loop, because every row would show the first item's block.

## Limits and escape hatches

- A one-off block styled like a list's items (a founder's card above the team
  cards) is proposed as one more row when it holds the values the items hold,
  a class-named one among them (`p.role`). It brings a flag named after its
  class (`founder`) and its own extra fields, all as a decision. A block that
  shares less is left as page copy: add a source for it to the map.
- Analyze proposes. The map is the contract: edit it rather than the content
  file, so the next extract keeps your edits.
- `karni_cli.design.analyze.analyze(design, app, namer=...)` takes a `Namer`
  subclass that names models and fields another way, and
  `karni_cli.design.extract.extract(design, map, output, reader=...)` a
  `Reader` subclass that reads values another way.
