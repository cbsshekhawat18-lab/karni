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
   another model's title ("Taught by Mia Chen") or key (a tag `whitening`
   naming the `whitening` treatment) is that relation: a foreign key the map
   reads `"by": "title"` or `"by": "key"`, or nothing when a link already
   points at the row. A detail page that links to the rows pointing back at
   it (a treatment page listing its stories, each story naming its
   treatment) holds the same relation from the other end: the page loops
   over `treatment.story_set`, and the report says so.
6. **One more row.** A single block on the page of a list, with the values
   that list's items hold (a class-named one among them), is proposed as one
   more row of that model, with a flag named after its own class: a founder's
   card above the team cards. It is a decision.
7. **What stays markup.** A list of one or two short values on one page
   (opening hours, figures in a row) stays in its template. So does a short
   run of figures, each item a number (`25`, `4,000`, `98%`, `10k+`) and one
   or two short labels with no picture, link or inner list: a row of
   statistics is the page's copy, never a model, and never the other half
   of a slider next to it. A list inside an
   item without pictures becomes a JSON field (a list of strings, of pairs for
   a `<dl>`, of objects), and one with pictures a child model. A `<dl>` with
   the same terms on every item (Duration, Price, Visits on each detail page)
   is one field per term instead, typed by its definitions. A section only
   some detail pages have stays in those pages' templates. A structure found
   on several pages with different items each time (a slider) is one model
   with a `page` field, and a foreign key to the detail page's model when it
   is on detail pages too. Two lists in one section with as many items each
   (a slider's pictures and its captions) are read as the same rows, item by
   item, and the report says so. Two lists in sections of their own
   (`<section>`, `<article>`, `<aside>`) are two things.

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
| A definition list with the same terms on every item | one field per term, named after it and typed by its definitions (`"term"` in the map) |
| A definition list whose terms differ between items | `json`, `[term, definition]` pairs |
| `<time datetime="...">` or a date written out ("14 March 2026") | `date` |
| A price ("€4.50", "From $12") | `decimal:10:2`, the symbol left in the template |
| A number with the same words around it ("12 weeks", "4,000 patients", or "1 visit" and "3 visits") | `int`, the words left in the template (with Django's `pluralize` filter for a plural) |
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

`karni explain map` lists every key of the map, and `karni explain
map.<key>` says what one does (`map.items`, `map.source.key`). The tables
below come from the same source, and extract refuses a source or value key
they do not list.

<!-- generated:map-keys -->
**The map itself, the top-level object.**

| Key | Write | What it does |
| --- | --- | --- |
| `version` | `"version": 1` | The map's format. This karni reads version 1. |
| `design` | `"design": "../design"` | The design folder, relative to the map file. |
| `app` | `"app": "website"` | The Django app the rows go to, as &lt;app&gt;.&lt;Model&gt;. |
| `marker` | `"marker": "=="` | What extract writes around highlighted words: "==" by default, KARNI_SITE_HIGHLIGHT's default. Change it only together with the setting's marker, so the site keeps one convention. |
| `decimal` | `"decimal": ","` | The decimal mark every page writes, "," or ".". Left out, each page's &lt;html lang&gt; decides: 4.000 is 4000 and 1.234,5 is 1234.5 where the language writes a decimal comma (de, fr, es and most of Europe), and a page without a language is read the English way. A separator between groups of three digits is dropped (4,000, 1 234). |
| `models` | `"models": [{"name": "Course", ...}]` | One object per model: its name, fields, key and sources. |

**A model, each object in "models".**

| Key | Write | What it does |
| --- | --- | --- |
| `name` | `"name": "Course"` | The model's class name. Rename it here and in every relation's "to" that names it. |
| `fields` | `"fields": {"title": "str:80", "slug": "slug:title", "teacher": "fk:Teacher?"}` | The model's fields, in karni make model's field types. A value reads into the field of its name, parsed by the field's type: a number from "12 weeks", an amount from "€4.50", a date from "14 March 2026" or a datetime attribute, a path for an image. |
| `key` | `"key": "slug"` | The field each row is matched on, so a second load updates the rows instead of adding new ones. |
| `order` | `"order": "position"` | The field the rows are ordered by. |
| `highlight` | `"highlight": {"tagline": "em"}` | Fields that keep the words a heading sets apart, as ==marked== words, with the markup the design wrote them in. |
| `parent` | `"parent": "Course"` | A child model: each row belongs to a row of the parent, read by a value named after "accessor" (see "rows"). |
| `accessor` | `"accessor": "courseimage_set"` | The name a child model's rows are read under in the parent's values. |
| `sources` | `"sources": [{"pages": [...], "values": {...}}]` | Where the model's items are: one object per page or list that shows them. |

**Where a model's items are, each object in a model's "sources".**

| Key | Write | What it does |
| --- | --- | --- |
| `page` | `"page": "courses.html"` | The page the items are on. |
| `pages` | `"pages": ["courses/pottery.html", "courses/drawing.html"]` | Several pages read the same way: the detail pages, or lists that repeat on every page. |
| `items` | `"items": "li.course-list__item"` | A selector for the items on the page. Left out, the page itself is the item (a detail page). |
| `within` | `"within": "section.menu"` | Items inside these parents: with "parent", each row points at the parent it is in. |
| `parent` | `"parent": {"field": "menu", "key": {"from": "attr", "name": "id"}}` | With "within": the field that points at the parent, and how the parent's key is read. |
| `key` | `"key": {"from": "page"}` | How each item's key is read, an object whose "from" says from what (karni explain map.key.from). An item read from several sources gets one key everywhere, so its values merge into one row: the first source with a value wins, and extract says where two pages disagree. |
| `position` | `"position": true` | Write each item's place in its list into the model's order field. |
| `create` | `"create": false` | Only add values to rows another source makes, never a row of its own. |
| `set` | `"set": {"page": "{page}"}` | Constant values for every item. {page} is the page's key. |
| `values` | `"values": {"title": "h1", "image": "img@src", "topics": {"select": "ul > li", "list": true}}` | What each field reads. A value is a place: a CSS selector relative to the item, @attribute for an attribute (img@src, @data-tags for the item's own), :scope for the item's own text. Or an object with "select" and the options of the value level. |

**How an item's key is read, a source's "key" (or its parent's).**

| Key | Write | What it does |
| --- | --- | --- |
| `from` | `"from": "link"` | What the key is read from: "page" (the page's file name, courses/pottery.html is pottery), "link" (the page or #anchor a link points at, with "select"), "attr" (an attribute of the item, with "name"), "field" (a field's value as a slug, with "field") or "position" (home-1, home-2, with "prefix"). Any other value is refused with C124. |
| `select` | `"select": "a.course-list__link@href"` | With "from": "link": the place of the link. |
| `name` | `"name": "id"` | With "from": "attr": the attribute. |
| `field` | `"field": "title"` | With "from": "field": the field whose value, as a slug, is the key. |
| `prefix` | `"prefix": "home"` | With "from": "position": the text before the number. {page} is the page's key. |
| `strip` | `"strip": "p-"` | Text taken off the front of the key read (p-whitening is whitening). |

**A value given as an object, in a source's "values".**

| Key | Write | What it does |
| --- | --- | --- |
| `select` | `"select": "ul.course__topics > li"` | The place, as in a value given as a string. Selectors support types, classes, ids, attributes, :nth-of-type(), :first-of-type, :last-of-type, :has(), :not() of one compound (p:not(.role)), the child and descendant combinators and comma groups. |
| `all` | `"all": true` | Every match's text, joined by blank lines (paragraphs). |
| `list` | `"list": true` | A list, one entry per match: true for the match's text, a place for that place inside each match. |
| `fields` | `"fields": {"name": "dt", "price": "dd"}` | A list of objects, {name: place} inside each match. |
| `pairs` | `"pairs": true` | A definition list as [term, definition] pairs, for a json field. |
| `term` | `"term": "Duration"` | The definition of that term in a definition list (&lt;dt&gt;Duration&lt;/dt&gt;&lt;dd&gt;45 minutes&lt;/dd&gt; gives "45 minutes"), parsed by the field's type. Case and spaces do not matter. Analyze writes it when every item's list has the same terms, one field per term. |
| `to` | `"to": "Teacher"` | A relation to that model of the map. "by" says how the place names the row. |
| `by` | `"by": "key"` | How a relation's place names the row: "link" (the default: a link to the row's page or #anchor), "key" (the row's key, as text or an attribute such as data-type="houses") or "title" (the row's title as text, &lt;p&gt;Mia Chen&lt;/p&gt;). Analyze writes it when a text names the row. Any other value is refused with C124. |
| `many` | `"many": true` | A relation to several rows: a many-to-many field. |
| `split` | `"split": true` | A relation read from an attribute that holds several keys (data-tags="a b"). |
| `rows` | `"rows": {"image": "img@src", "caption": "figcaption"}` | Child rows, {field: place} inside each match. The value's name is the child model's accessor (courseimage_set). |
| `present` | `"present": true` | true when the place matches anything, else false. |
| `drop` | `"drop": ["span.arrow"]` | Markup left out of the text. |
| `pattern` | `"pattern": "^\\d+\\s+(.+)$"` | A regular expression whose last group is the value ("01 Design" gives "Design"). |
| `link` | `"link": "path"` | A link to a page of the design, written as that page's URL path. Any other value is refused with C124. |
| `decide` | `"decide": "Is the price per visit or per course?"` | A question the analysis left open. Extract refuses to run until every decide is answered: remove it to keep the value, or delete the value (and the field). |
<!-- /generated:map-keys -->

## Extract

```text
$ karni design extract ../design --map content/design-map.json -o content/site.json
Wrote content/site.json:
  website.Teacher  3 row(s)
  website.Course   4 row(s) (8 child row(s))
```

The output is a [content file](content-loading.md): one list of rows per
model, models others point at first, child rows nested under their parent.
Each value is parsed by its field's type (`"12 weeks"` is `12`, `"4,000"` is
`4000`, `"€4.50"` is `"4.50"`, `"14 March 2026"` is `"2026-03-14"`), and
relations name their rows by key. The images the content names are copied
next to the output file, under `files/` at their path in the design
(`content/files/img/mia.jpg`), and the content file names those copies, so
`karni load` uploads the designer's own images and the project holds every
file it reads, wherever the design folder is. Commit `content/files/` with
the content file. A copy that has not changed is not written again.
`--keep-paths` names the design's own files instead (`../design/img/mia.jpg`).
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
