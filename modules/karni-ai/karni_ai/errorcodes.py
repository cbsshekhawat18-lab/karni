"""karni-ai's error codes (prefix ``AI``), registered with Karni's registry.

Exposed through the ``karni.errorcodes`` entry point, so ``karni explain AI004``
and ``docs/errors.md`` include them. Codes are permanent: never renumber or
reuse one, and append new codes at the end.
"""

from __future__ import annotations

from typing import Final

from karni.errorcodes import ErrorCode

__all__ = ["CODES"]

_SOURCE = "karni_ai"

CODES: Final[tuple[ErrorCode, ...]] = (
    ErrorCode(
        code="AI001",
        title="KARNI_AI_PROVIDER is not set",
        kind="check",
        source=f"{_SOURCE}.checks (and providers.base.get_provider)",
        why="karni-ai has no default provider: every extraction goes through the one the "
        "project names.",
        fix="Set KARNI_AI_PROVIDER to 'anthropic', 'openai' or 'test' (in .env, or in karni.yaml "
        "as modules: ai: provider), or to the dotted path of a karni_ai.providers.base.Provider "
        "subclass.",
    ),
    ErrorCode(
        code="AI002",
        title="KARNI_AI_PROVIDER cannot be loaded",
        kind="exception",
        source=f"{_SOURCE}.providers.base.get_provider",
        why="The setting names something that is not a shortcut and does not import as a "
        "Provider subclass.",
        fix="Use 'anthropic', 'openai' or 'test', or the dotted path of a "
        "karni_ai.providers.base.Provider subclass.",
    ),
    ErrorCode(
        code="AI003",
        title="The provider's SDK is not installed",
        kind="check",
        source=f"{_SOURCE}.providers (anthropic, openai)",
        why="Provider SDKs are optional extras, so a project installs only the one it uses.",
        fix="Install the extra: pip install 'karni-ai[anthropic]' or 'karni-ai[openai]'.",
    ),
    ErrorCode(
        code="AI004",
        title="The provider's API key is not set",
        kind="check",
        source=f"{_SOURCE}.providers (anthropic, openai)",
        why="The provider cannot answer without its key. The key comes from the environment "
        "only, never from code or karni.yaml.",
        fix="Set ANTHROPIC_API_KEY or OPENAI_API_KEY in the environment (.env in development). "
        "Use the 'test' provider for local work and CI without a key.",
    ),
    ErrorCode(
        code="AI005",
        title="The provider's model name is not set",
        kind="check",
        source=f"{_SOURCE}.providers (anthropic, openai)",
        why="karni-ai has no default model: model names change, and the choice of one is a cost "
        "and quality decision for the project.",
        fix="Set ANTHROPIC_MODEL or OPENAI_MODEL in the environment to the model the provider "
        "should use.",
    ),
    ErrorCode(
        code="AI006",
        title="The provider call failed",
        kind="api",
        source=f"{_SOURCE}.providers (answered with HTTP 502)",
        why="The provider refused the request, timed out or could not be reached. The call is "
        "logged with this code and nothing is previewed.",
        fix="Read the message for the provider's own reason (a rate limit, a bad key, an "
        "unknown model). Raise KARNI_AI_TIMEOUT for slow answers.",
    ),
    ErrorCode(
        code="AI007",
        title="The model's answer cannot be used",
        kind="api",
        source=f"{_SOURCE}.providers (answered with HTTP 502)",
        why="The model declined, its answer was cut off at KARNI_AI_MAX_OUTPUT_TOKENS, or it "
        "was not the JSON the schema asks for.",
        fix="Send a shorter source, raise KARNI_AI_MAX_OUTPUT_TOKENS, or try another model.",
    ),
    ErrorCode(
        code="AI008",
        title="The resource cannot be extracted into",
        kind="api",
        source=f"{_SOURCE}.extraction (answered with HTTP 400)",
        why="Extraction ends in the resource's import preview, so it needs a routed BaseViewSet "
        "whose import is on and whose model is writable.",
        fix="Name the resource by its router prefix (products, not Product), and keep its "
        "viewset's import_data on.",
    ),
    ErrorCode(
        code="AI009",
        title="You may not create rows of this resource",
        kind="api",
        source=f"{_SOURCE}.extraction (answered with HTTP 403)",
        why="Only a user the resource's access declaration lets create may extract into it, so "
        "nobody spends tokens on rows they could never save.",
        fix="Ask for a role the resource's create access admits.",
    ),
    ErrorCode(
        code="AI010",
        title="The source cannot be read",
        kind="api",
        source=f"{_SOURCE}.sources (answered with HTTP 400)",
        why="Give exactly one of text, url or file. The text has a size limit "
        "(KARNI_AI_MAX_SOURCE_CHARS), and a file must be a PDF with text in it, within "
        "KARNI_AI_MAX_UPLOAD_BYTES and KARNI_AI_MAX_PDF_PAGES.",
        fix="Send one source within the limits. A scanned PDF needs text recognition first.",
    ),
    ErrorCode(
        code="AI011",
        title="The URL is refused",
        kind="api",
        source=f"{_SOURCE}.services.fetch (answered with HTTP 400)",
        why="A URL the server fetches must not reach the server's own network: only http and "
        "https, no user name or password, a port of KARNI_AI_FETCH_PORTS, a public address, and "
        "every redirect checked the same way, at most KARNI_AI_FETCH_MAX_REDIRECTS of them.",
        fix="Use a public http or https address. Paste the text instead for a page on a private "
        "network.",
    ),
    ErrorCode(
        code="AI012",
        title="The URL's response is refused",
        kind="api",
        source=f"{_SOURCE}.services.fetch (answered with HTTP 400)",
        why="The response was larger than KARNI_AI_FETCH_MAX_BYTES, slower than "
        "KARNI_AI_FETCH_TIMEOUT, an HTTP error, or not HTML, plain text or a PDF.",
        fix="Download the document and send it as a file, or paste its text.",
    ),
    ErrorCode(
        code="AI013",
        title="Your monthly token budget is spent",
        kind="api",
        source=f"{_SOURCE}.usage (answered with HTTP 429)",
        why="KARNI_AI_MONTHLY_TOKENS_PER_USER caps the tokens one user spends in a calendar month.",
        fix="Wait for the next month, or ask for the budget to be raised.",
    ),
    ErrorCode(
        code="AI014",
        title="The project's monthly token budget is spent",
        kind="api",
        source=f"{_SOURCE}.usage (answered with HTTP 429)",
        why="KARNI_AI_MONTHLY_TOKENS caps the tokens the whole project spends in a calendar month.",
        fix="Wait for the next month, or raise KARNI_AI_MONTHLY_TOKENS.",
    ),
    ErrorCode(
        code="AI015",
        title="The resource has no field extraction can fill",
        kind="api",
        source=f"{_SOURCE}.schema (answered with HTTP 400)",
        why="Extraction fills text, number, date, choice and boolean fields, and relations to a "
        "model with a natural key. Files, JSON and relations without a natural key are left out.",
        fix="Give the related model a natural key (class Karni: natural_key = 'name'), or "
        "import the resource from a file.",
    ),
    ErrorCode(
        code="AI016",
        title="KARNI_AI_EXTRACTOR or KARNI_AI_FETCHER cannot be loaded",
        kind="exception",
        source=f"{_SOURCE}.extraction.get_extractor, {_SOURCE}.sources",
        why="Both settings are escape hatches: dotted paths to a subclass of the class they "
        "replace.",
        fix="Point KARNI_AI_EXTRACTOR at a karni_ai.extraction.Extractor subclass and "
        "KARNI_AI_FETCHER at a karni_ai.services.fetch.Fetcher subclass, or remove the setting.",
    ),
)
