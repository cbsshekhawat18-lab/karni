# karni-ai

Structured extraction for [Karni](https://github.com/cbsshekhawat18-lab/karni),
experimental. A language model reads a source (text, a web page or a PDF)
into rows of any of your resources. The rows always go through Karni's import
preview: nothing is saved until a user confirms the preview through the
import's own commit. Every call is logged with its tokens and cost, and
monthly budgets cap the spending.

The full guide is [AI extraction](https://cbsshekhawat18-lab.github.io/karni/ai-extraction/).

```bash
pip install "karni-ai[anthropic]"   # or karni-ai[openai], or neither for the test provider
karni add ai
karni migrate
```

`karni add ai` adds the app. The API rides the auto-router, so there is no
URL include. Karni core never imports this module.

## The endpoint

`POST /api/ai/extract/` with `resource` (a router prefix, `products`) and one
of `text`, `url` or `file` (a PDF, multipart) answers `201` with the proposed
`rows`, a `problems` list (`row`, `field`, `message`, `source`: `schema` or
`preview`), the preview's counts, the import job's `id` and its `commit` path.
`POST /api/<resource>/import/<id>/commit/` saves the rows. Only a signed-in
user the resource's `access` lets create may call it, at most 30 times an
hour (throttle scope `ai.extract`). `GET /api/ai/` lists the caller's own
calls.

## Settings

| Setting | Env var | Default | Meaning |
| --- | --- | --- | --- |
| `KARNI_AI_PROVIDER` | same | `""` | `anthropic`, `openai`, `test` or a dotted path to a `Provider` subclass. No default: `karni check` fails without it (AI001) |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | same | `""` | the anthropic provider's key and model. Environment only, no default model (AI004, AI005) |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | same | `""` | the openai provider's key and model. Environment only, no default model (AI004, AI005) |
| `KARNI_AI_TIMEOUT` | same | `60` | seconds one provider call may take |
| `KARNI_AI_MAX_RETRIES` | same | `1` | retries after a rate limit, an overload or a network failure |
| `KARNI_AI_MAX_OUTPUT_TOKENS` | same | `16000` | the longest answer |
| `KARNI_AI_MAX_ROWS` | same | `50` | rows proposed at once |
| `KARNI_AI_MAX_SOURCE_CHARS` | same | `100000` | the longest source text. Longer is refused, never cut |
| `KARNI_AI_MAX_UPLOAD_BYTES`, `KARNI_AI_MAX_PDF_PAGES` | same | `10 MB`, `50` | PDF limits |
| `KARNI_AI_FETCH_TIMEOUT`, `KARNI_AI_FETCH_MAX_BYTES`, `KARNI_AI_FETCH_MAX_REDIRECTS`, `KARNI_AI_FETCH_PORTS` | same | `10`, `5 MB`, `3`, `[80, 443]` | URL fetch limits |
| `KARNI_AI_PRICES` | | `{}` | `{"<model>": {"input": "1.00", "output": "4.00"}}`, per million tokens |
| `KARNI_AI_MONTHLY_TOKENS_PER_USER`, `KARNI_AI_MONTHLY_TOKENS` | same | `None` | monthly token budgets (AI013, AI014) |
| `KARNI_AI_FETCHER`, `KARNI_AI_EXTRACTOR` | same | Karni's classes | escape hatches: dotted paths to subclasses |

In karni.yaml, `modules: ai: {provider: anthropic}` sets the provider. The
key and the model name are never options there: they stay in the
environment.

## Escape hatches

- A provider Karni does not ship: subclass `karni_ai.providers.base.Provider`
  and point `KARNI_AI_PROVIDER` at it. Subclass `AnthropicProvider` or
  `OpenAIProvider` and override `request_params()` to add request options.
- The prompt, the schema, the access check or the budget rule: subclass
  `karni_ai.extraction.Extractor` and point `KARNI_AI_EXTRACTOR` at it.
- URL fetching (through a proxy, other addresses): subclass
  `karni_ai.services.fetch.Fetcher` and point `KARNI_AI_FETCHER` at it.
- The rate: `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["ai.extract"]`.
- The admin: unregister `AICall` and register your own `KarniModelAdmin`.

## Tests

The `test` provider needs no network and no key. Without a queued answer it
reads `field: value` lines, one record per paragraph.
`TestProvider.answer_with(...)` and `TestProvider.fail_with(...)` script its
next answers, and `TestProvider.reset()` clears them.

```bash
cd modules/karni-ai && python -m pytest
```
