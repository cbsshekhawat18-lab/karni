## AI extraction (karni-ai, experimental)
- `POST /api/ai/extract/` with `resource` (a router prefix) and one of `text`, `url`, `file` (PDF)
  answers the import preview of the rows a language model read. It writes nothing: the user
  confirms with `POST /api/<resource>/import/<id>/commit/`. Never save extracted rows another way.
- The schema comes from the resource's own writable fields. Change the model or its serializer,
  never write a schema or a prompt by hand. Never call a provider SDK directly.
- Settings: KARNI_AI_PROVIDER (anthropic|openai|test|dotted path), and in the environment only
  ANTHROPIC_API_KEY + ANTHROPIC_MODEL or OPENAI_API_KEY + OPENAI_MODEL. No default model:
  `karni check` fails (AI001-AI005) until they are set. Use `test` in tests and CI.
- Budgets and prices: KARNI_AI_MONTHLY_TOKENS_PER_USER, KARNI_AI_MONTHLY_TOKENS, KARNI_AI_PRICES.
  Every call is logged (AICall, read-only in the admin).
- React: `useExtract` and `ExtractButton` from `@karni/ai-ui`.
