"""Text renderings of the agent data for terminals, agents and docs."""

from __future__ import annotations

from typing import Any

from karni_cli.agent_data import AgentData

PROMPTS_START = "<!-- karni:procedures:start (generated: `karni rules --prompts-doc`) -->"
PROMPTS_END = "<!-- karni:procedures:end -->"


def render_rules(data: AgentData, fragments: dict[str, str] | None = None) -> str:
    """The ``karni rules`` listing: every rule's code + summary, grouped by category.

    Kept under 400 tokens for Karni's own rules; project rules and module
    guidance add to it (they are project-specific and needed to start work).
    """
    lines = ["Karni rules. ! = build-enforced."]
    for category in data.categories:
        lines.append(f"[{category}]")
        for rule in data.rules:
            if rule["category"] == category:
                mark = "!" if rule["severity"] == "error" else ""
                lines.append(f"{rule['code']}{mark} {rule['summary']}")
    for name, fragment in (fragments or {}).items():
        lines.append(f"[module:{name}]")
        lines.append(fragment.strip())
    lines.append("Why/fix: karni rules --explain CODE")
    return "\n".join(lines)


def render_explain(rule: dict[str, Any]) -> str:
    lines = [f"{rule['code']} [{rule['category']}, {rule['severity']}] {rule['rule']}"]
    if rule.get("rationale"):
        lines.append(f"Why: {rule['rationale']}")
    if rule.get("fix"):
        lines.append(f"Fix: {rule['fix']}")
    if rule.get("enforced_by"):
        lines.append("Enforced by: " + ", ".join(rule["enforced_by"]))
    return "\n".join(lines)


def render_procedure(procedure: dict[str, Any], arguments: str = "<arguments>") -> str:
    lines = [procedure["intro"].replace("{arguments}", arguments), ""]
    lines += [f"{i}. {step}" for i, step in enumerate(procedure["steps"], start=1)]
    if procedure.get("outro"):
        lines += ["", procedure["outro"]]
    if procedure.get("rules"):
        lines += ["", "Rules that apply: " + ", ".join(procedure["rules"])]
    return "\n".join(lines)


def render_findings(findings: list[dict[str, Any]]) -> str:
    lines = []
    for f in findings:
        lines.append(f"{f['path']}:{f['line']}: {f['code']} [{f['rule_id']}] {f['message']}")
        if f.get("fix"):
            lines.append(f"  fix: {f['fix']}")
    return "\n".join(lines)


def render_prompts_doc(data: AgentData) -> str:
    """Plain-language equivalents of the slash commands (docs/agents.md block)."""
    lines = [PROMPTS_START, ""]
    for procedure in data.procedures:
        name = procedure["name"]
        lines += [
            f"### `{name}` — {procedure['description']}",
            "",
            "Prompt for tools without slash commands (replace the placeholder):",
            "",
            (
                f"> Run `karni rules --procedure {name}` and follow every step for: "
                f"`{procedure['argument_hint']}`"
            ),
            "",
            "What `karni rules --procedure` returns:",
            "",
            "```text",
            render_procedure(procedure, procedure["argument_hint"]),
            "```",
            "",
        ]
    lines.append(PROMPTS_END)
    return "\n".join(lines)
