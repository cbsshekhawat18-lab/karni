---
description: "karni-ai, an optional Karni module: a language model reads text, a web page or a PDF into rows of any resource, validated against the resource's own schema and always previewed by Karni's import before a user saves them. Providers, settings, URL safety, usage, costs and budgets."
---

# AI extraction (karni-ai)

!!! warning "Experimental"
    The karni-ai module and `@karni/ai-ui` are
    [experimental](stability.md#experimental-names): their names may change
    in a minor release, with a CHANGELOG entry.

karni-ai turns a source into rows of one of your resources. The source is a
text, a web page or a PDF. A language model reads it and answers JSON that
follows the resource's own schema. Karni validates the answer and hands the
rows to its [import](import-export.md), which previews them. **Nothing is
written until a user confirms the preview** through the import's own commit,
the same step a spreadsheet import takes.

It is a module, not core: Karni never imports it, and a project without it
pays nothing for it.

```bash
pip install "karni-ai[anthropic]"   # or "karni-ai[openai]"
karni add ai
karni migrate
```

The API rides the auto-router, so there is no URL include.

## Providers and settings

A provider is one language model API behind one interface: a structured
answer for a JSON Schema, with the tokens it used. Three ship with the
module:

| `KARNI_AI_PROVIDER` | What it calls | It needs |
| --- | --- | --- |
| `anthropic` | the Anthropic Messages API, with a JSON-schema output format | `pip install "karni-ai[anthropic]"`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` |
| `openai` | the OpenAI Responses API, with a strict JSON-schema format | `pip install "karni-ai[openai]"`, `OPENAI_API_KEY`, `OPENAI_MODEL` |
| `test` | nothing: it reads `field: value` lines, one record per paragraph | nothing |
| a dotted path | your subclass of `karni_ai.providers.base.Provider` | what it reads |

The provider, the model name and the key come from settings and the
environment only, never from code. There is **no default provider and no
default model**: model names change, and choosing one is a cost and quality
decision. While the module is added without them, `karni check` fails with
one line per missing piece:

```text
ai: AI004: the anthropic provider: ANTHROPIC_API_KEY is not set (set it in the environment).
ai: AI005: the anthropic provider: ANTHROPIC_MODEL is not set: there is no default model, name one.
```

`AI001` is a missing provider, `AI002` one that does not load, `AI003` a
missing SDK. Use the `test` provider in your tests and CI: it needs no key
and no network.

In karni.yaml the provider is the module's option, and `karni plan
--questions` asks for it:

```yaml
modules:
  ai: {provider: anthropic}
```

The key and the model name are never options in karni.yaml. They stay in
`.env`:

```bash
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=...
```

Every setting, with its default:

| Setting | Default | Meaning |
| --- | --- | --- |
| `KARNI_AI_PROVIDER` | `""` | the provider (above) |
| `KARNI_AI_TIMEOUT` | `60` | seconds one provider call may take (`AI006` past it) |
| `KARNI_AI_MAX_RETRIES` | `1` | retries after a rate limit, an overload or a network failure |
| `KARNI_AI_MAX_OUTPUT_TOKENS` | `16000` | the longest answer. A longer one is cut off (`AI007`) |
| `KARNI_AI_MAX_ROWS` | `50` | rows proposed at once. The rest are left out, with a problem |
| `KARNI_AI_MAX_SOURCE_CHARS` | `100000` | the longest source text. A longer one is refused (`AI010`), never cut |
| `KARNI_AI_MAX_UPLOAD_BYTES` | `10485760` | the largest PDF upload |
| `KARNI_AI_MAX_PDF_PAGES` | `50` | the most pages read from a PDF |
| `KARNI_AI_FETCH_TIMEOUT` | `10` | seconds a URL fetch may take, redirects and reading included |
| `KARNI_AI_FETCH_MAX_BYTES` | `5242880` | the largest response a URL fetch reads |
| `KARNI_AI_FETCH_MAX_REDIRECTS` | `3` | redirects a URL fetch follows |
| `KARNI_AI_FETCH_PORTS` | `[80, 443]` | the ports a URL may name |
| `KARNI_AI_PRICES` | `{}` | prices per million tokens, by model name |
| `KARNI_AI_MONTHLY_TOKENS_PER_USER` | `None` | tokens one user may spend in a calendar month |
| `KARNI_AI_MONTHLY_TOKENS` | `None` | tokens the whole project may spend in a calendar month |
| `KARNI_AI_FETCHER` | `karni_ai.services.fetch.Fetcher` | the class that fetches a URL |
| `KARNI_AI_EXTRACTOR` | `karni_ai.extraction.Extractor` | the class that runs an extraction |

## Extraction

`POST /api/ai/extract/` takes the resource by its router prefix and exactly
one source: `text`, `url`, or `file` (a PDF, sent as multipart).

```http
POST /api/ai/extract/
Content-Type: application/json

{
  "resource": "products",
  "text": "Name: Garden hose\nSKU: GH-100\nPrice: 19.90\nCategory: Garden\n\nName: Rake\nSKU: RK-200\nPrice: abc\nCategory: Kitchen"
}
```

It answers `201` with the preview:

```json
{
  "id": "8c4d7c1a-7dfd-48eb-9281-6153ad90725d",
  "resource": "products",
  "source": {"kind": "text", "label": "text"},
  "status": "previewed",
  "rows": [
    {"name": "Garden hose", "sku": "GH-100", "price": "19.90", "category": "Garden"},
    {"name": "Rake", "sku": "RK-200", "category": "Kitchen"}
  ],
  "problems": [
    {"row": 2, "field": "price", "message": "'abc' is not in the expected form.", "source": "schema"},
    {"row": 2, "field": "category", "message": "no category with name 'Kitchen' (or it is not visible to you).", "source": "preview"}
  ],
  "result": {"rows_total": 2, "created": 1, "updated": 0, "unchanged": 0, "errors": 1, "skipped": 1},
  "commit": "/api/products/import/8c4d7c1a-7dfd-48eb-9281-6153ad90725d/commit/",
  "job": {"id": "8c4d7c1a-...", "status": "previewed", "file_name": "Extracted from text", "...": "..."},
  "usage": {"provider": "anthropic", "model": "...", "input_tokens": 912, "output_tokens": 88, "cost": "0.005408"}
}
```

`rows` are the rows the model proposed, after the schema check. `problems`
has one entry per field: `row` is the row's position in `rows` from 1,
`source` says who found it. `schema` means the model's value did not fit the
field (it is left out of the row, so the preview never sees a value of the
wrong type). `preview` means the import's dry run refused it: a relation
that names no row, a required field missing, a uniqueness clash, the
model's `clean()`. `result` is what the commit will do. `job` is the import
job as `GET /api/<resource>/import/<id>/` answers it.

### The schema

The model is asked for `{"rows": [<row>, ...]}`, where `<row>` comes from the
resource itself: the request component the
[OpenAPI document](api.md) gives its create body (`ProductRequest`), read
through the same inspector that serves `/api/schema/`. Only the fields this
user may import are in it, so a field `Karni.field_roles` keeps from their
role is not asked for. Nobody writes a schema or a prompt by hand: change
the model or its serializer and the extraction follows.

- Text, numbers, decimals, dates, booleans and choices keep their type,
  format, lengths, pattern, bounds and allowed values.
- A relation is the related row's natural key (`Karni.natural_key`), as the
  import reads it: "the name of a category". A to-many relation is a list of
  them. A relation to a model without a natural key is left out, because a
  text never carries row ids.
- Files and JSON fields are left out. A resource with nothing left is `AI015`.
- `null`, or a field left out, means "not in the source", and the field is
  left alone. Required fields are not checked against the schema: a row that
  matches an existing one by its key updates it and needs none, and the
  preview says what a new row lacks.

### Nothing is written before the commit

The rows become an import job, created by the caller, and its preview runs:
every row is validated and written inside a transaction that is rolled
back. The resource is unchanged until the same user confirms:

```http
POST /api/products/import/8c4d7c1a-7dfd-48eb-9281-6153ad90725d/commit/
```

That is the import's own commit, so every gate runs again: the access
declaration, the row scope, the fields the role may write, the audit batch.
Another user cannot commit the job. The extraction has no write path of
its own.

The preview runs inside the request, as a file import's does. When the rows
outnumber `KARNI_IMPORT_INLINE_ROWS`, it runs in Celery instead: the answer
says `previewing`, and `GET /api/<resource>/import/<id>/` gives the counts and
the problems once it is done.

### Who may extract

The caller must be signed in, and the resource's `access` declaration must
let them create rows (`AI009`, a `403`), checked before any token is spent.
A resource whose viewset turns its import off (`import_data = False`), or a
read-only one, is `AI008`. So is a prefix that is not routed.

## URLs

A URL the server fetches for a user is the classic way into the server's
own network. The fetcher refuses (`AI011`):

- a scheme other than `http` and `https`, a URL with a user name or a
  password, and a port outside `KARNI_AI_FETCH_PORTS`.
- a host with any address that is not public: private, loopback,
  link-local (the cloud metadata address `169.254.169.254` included),
  shared, reserved, multicast or unspecified, and IPv4 inside IPv6. The
  connection then goes to the address that was checked, never to a second
  DNS answer, and HTTPS still verifies the certificate for the host name.
- a redirect to any of these. Every redirect is checked like the first
  address, and more than `KARNI_AI_FETCH_MAX_REDIRECTS` is refused.

The response is refused (`AI012`) when it is an HTTP error, compressed (the
fetcher asks for none), larger than `KARNI_AI_FETCH_MAX_BYTES` (by its
`Content-Length`, or while reading), slower than `KARNI_AI_FETCH_TIMEOUT`
(one deadline for the whole fetch), or neither HTML, plain text nor a PDF.
An HTML page is reduced to its visible text: scripts, styles and templates
are left out.

## PDFs

PDF text comes from [pypdf](https://pypi.org/project/pypdf/): pure Python,
with no C library or system package to install, permissively licensed and
small. It reads a PDF's text layer, which is what a language model needs. A
locked PDF, one past `KARNI_AI_MAX_PDF_PAGES`, one past
`KARNI_AI_MAX_UPLOAD_BYTES`, and a scan without a text layer are refused
(`AI010`). Run text recognition on a scan first.

## Usage, costs and budgets

Every provider call is logged as an `AICall`: the user, the resource, the
source kind, the provider, the model, the input and output tokens, the
cost, the status, and the import job it previewed. Failed calls are logged
too, with their code and the tokens the provider still billed (a declined or
cut-off answer costs its tokens). The admin shows the log read-only. Each
user reads their own calls at `GET /api/ai/`.

The cost comes from `KARNI_AI_PRICES`, per million tokens, in whatever
currency you write the table in:

```python
KARNI_AI_PRICES = {
    "the-model-name": {"input": "1.00", "output": "4.00"},
}
```

A model the table does not name logs no cost, never a guessed one.

Two optional budgets, in tokens per calendar month (in the project's
`TIME_ZONE`), refuse the next call with a `429` once spent:

| Setting | Code |
| --- | --- |
| `KARNI_AI_MONTHLY_TOKENS_PER_USER` | `AI013` |
| `KARNI_AI_MONTHLY_TOKENS` (the whole project) | `AI014` |

A call that starts under the budget finishes, so the last one may go past
it. Calls are also rate limited per user with Karni's
[throttles](api.md): 30 an hour under the scope `ai.extract`. Change it, or
turn it off with `None`:

```python
REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_RATES": {"ai.extract": "100/day"},
}
```

## React

`@karni/ai-ui` has `ExtractButton`: a button that opens a dialog with a
form per source, shows the preview (the proposed rows, the problems, the
counts) and commits through the import's own confirmation.

```tsx
import { ExtractButton } from "@karni/ai-ui";

<ExtractButton resource="products" resourceLabel="products" sources={["text", "pdf"]} />;
```

`useExtract(resource)` is the mutation behind it, and `ExtractPreview` the
preview with its commit, to build another flow. A refusal is shown in the
backend's words.

## Escape hatches

- **Another provider:** subclass `karni_ai.providers.base.Provider`
  (`structured()`, and `problems()` for `karni check`) and point
  `KARNI_AI_PROVIDER` at it. To add request options to a shipped provider
  (thinking or effort settings, a beta, a service tier), subclass
  `AnthropicProvider` or `OpenAIProvider` and override `request_params()`.
- **The prompt, the schema, the access rule or the budget rule:** subclass
  `karni_ai.extraction.Extractor` (`instructions()`, `schema_for()`,
  `check_access()`, `check_budget()`, `preview()`) and point
  `KARNI_AI_EXTRACTOR` at it.
- **URL fetching:** subclass `karni_ai.services.fetch.Fetcher` (an egress
  proxy, other allowed addresses) and point `KARNI_AI_FETCHER` at it.
- **The admin:** unregister `AICall` and register your own `KarniModelAdmin`.

## Tests

The `test` provider runs the whole pipeline with no network and no key.
Without a queued answer it reads `field: value` lines, one record per
paragraph. Script it from a test:

```python
from karni_ai.providers.test import TestProvider

TestProvider.answer_with({"rows": [{"name": "Hose", "price": "abc"}]})
TestProvider.calls  # every request it answered
TestProvider.reset()
```

Error codes `AI001` to `AI016` are in [the error list](errors.md#ai001).
