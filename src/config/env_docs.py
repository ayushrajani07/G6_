#!/usr/bin/env python3
from __future__ import annotations

from .env_registry import EnvVarType, registry


def _type_to_str(t: EnvVarType) -> str:
    return {
        EnvVarType.STRING: "string",
        EnvVarType.INTEGER: "integer",
        EnvVarType.FLOAT: "float",
        EnvVarType.BOOLEAN: "boolean",
        EnvVarType.LIST: "list[str]",
        EnvVarType.DICT: "dict[str,str]",
    }[t]


def generate_markdown() -> str:
    lines: list[str] = []
    lines.append("# G6 Environment Variables\n")
    lines.append("This document is auto-generated from the Environment Registry.\n")
    lines.append("\n")
    lines.append("| Variable | Type | Required | Default | Description | Choices | Notes |\n")
    lines.append("|---|---|:---:|---|---|---|---|\n")
    for d in sorted(registry.get_documented_variables(), key=lambda x: x.name):
        default_str = "" if d.default is None else str(d.default)
        choices_str = "" if not d.choices else ", ".join(str(c) for c in d.choices)
        notes: list[str] = []
        if d.deprecated:
            repl = f"; use {d.replacement}" if d.replacement else ""
            notes.append(f"deprecated{repl}")
        if d.pattern:
            pat = getattr(d.pattern, 'pattern', str(d.pattern))
            notes.append(f"pattern: `{pat}`")
        if d.min_value is not None or d.max_value is not None:
            notes.append(f"range: {d.min_value}..{d.max_value}")
        if d.case_sensitive:
            notes.append("case-sensitive")
        lines.append(
            f"| G6_{d.name} | {_type_to_str(d.var_type)} | {'Y' if d.required else 'N'} | {default_str} | "
            f"{d.description} | {choices_str} | {'; '.join(notes)} |\n"
        )
    return "".join(lines)


__all__ = ["generate_markdown"]
