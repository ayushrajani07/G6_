#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationError:
    path: str
    message: str
    value: Any | None = None


@dataclass
class ValidationRule:
    path: str
    message: str
    required: bool = False
    field_type: type | None = None
    allowed_values: list[Any] | None = None
    min_value: float | None = None
    max_value: float | None = None
    min_length: int | None = None
    regex: str | None = None
    custom_validator: Callable[[Any], bool] | None = None
    depends_on: str | None = None
    condition: Callable[[dict[str, Any]], bool] | None = None
    transform: Callable[[Any], Any] | None = None


@dataclass
class DependencyRule:
    path: str
    depends_on: str
    message: str
    required_value: Any | None = None
    condition: Callable[[dict[str, Any]], bool] | None = None


@dataclass
class SchemaValidationResult:
    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)


class ConfigSchemaValidator:
    def __init__(self) -> None:
        self.field_rules: list[ValidationRule] = []
        self.dependency_rules: list[DependencyRule] = []
        self.global_rules: list[Callable[[dict[str, Any]], list[ValidationError]]] = []

    def add_field_rule(self, rule: ValidationRule) -> None:
        self.field_rules.append(rule)

    def add_dependency_rule(self, rule: DependencyRule) -> None:
        self.dependency_rules.append(rule)

    def add_global_rule(self, rule: Callable[[dict[str, Any]], list[ValidationError]]) -> None:
        self.global_rules.append(rule)

    def _get(self, cfg: dict[str, Any], path: str) -> Any | None:
        cur: Any = cfg
        for p in path.split('.'):
            if not isinstance(cur, dict) or p not in cur:
                return None
            cur = cur[p]
        return cur

    def validate(self, cfg: dict[str, Any]) -> SchemaValidationResult:
        errs: list[ValidationError] = []
        warns: list[ValidationError] = []
        seen: set[str] = set()

        for rule in self.field_rules:
            if rule.condition and not rule.condition(cfg):
                continue
            val = self._get(cfg, rule.path)
            seen.add(rule.path)
            if rule.required and val is None:
                errs.append(ValidationError(rule.path, rule.message or f"Missing required: {rule.path}"))
                continue
            if val is None:
                continue
            if rule.transform:
                try:
                    val = rule.transform(val)
                except Exception as e:
                    errs.append(ValidationError(rule.path, f"Transform failed: {e}", val))
                    continue
            if rule.field_type and not isinstance(val, rule.field_type):
                errs.append(ValidationError(rule.path, f"Expected type {getattr(rule.field_type,'__name__','?')}", val))
                continue
            if rule.allowed_values is not None and val not in rule.allowed_values:
                errs.append(ValidationError(rule.path, f"Must be one of {rule.allowed_values}", val))
            if isinstance(val, (int, float)):
                if rule.min_value is not None and val < rule.min_value:
                    errs.append(ValidationError(rule.path, f"Must be >= {rule.min_value}", val))
                if rule.max_value is not None and val > rule.max_value:
                    errs.append(ValidationError(rule.path, f"Must be <= {rule.max_value}", val))
            if rule.min_length is not None and isinstance(val, (str, list, tuple, dict)) and len(val) < rule.min_length:
                errs.append(ValidationError(rule.path, f"Must have at least {rule.min_length} items", val))
            if rule.regex and isinstance(val, str):
                import re
                if not re.match(rule.regex, val):
                    errs.append(ValidationError(rule.path, f"Must match pattern {rule.regex}", val))
            if rule.custom_validator:
                try:
                    ok = rule.custom_validator(val)
                    if not ok:
                        errs.append(ValidationError(rule.path, rule.message or "Custom validation failed", val))
                except Exception as e:
                    errs.append(ValidationError(rule.path, f"Validator error: {e}", val))
            if rule.depends_on:
                dep = self._get(cfg, rule.depends_on)
                if dep is None:
                    errs.append(ValidationError(rule.path, f"Depends on {rule.depends_on}", val))

        for dr in self.dependency_rules:
            if dr.condition and not dr.condition(cfg):
                continue
            src = self._get(cfg, dr.path)
            if src is None:
                continue
            dep = self._get(cfg, dr.depends_on)
            if dep is None:
                errs.append(ValidationError(dr.path, dr.message or f"Missing dependency {dr.depends_on}", src))

        for gr in self.global_rules:
            try:
                errs.extend(gr(cfg))
            except Exception as e:
                errs.append(ValidationError("", f"Global rule error: {e}"))

        return SchemaValidationResult(valid=len(errs) == 0, errors=errs, warnings=warns)


def create_default_validator() -> ConfigSchemaValidator:
    v = ConfigSchemaValidator()
    # Core sections
    v.add_field_rule(ValidationRule(path="providers", message="providers required", required=True, field_type=dict))
    v.add_field_rule(ValidationRule(path="providers.primary", message="primary provider required", required=True, field_type=dict))
    v.add_field_rule(ValidationRule(path="index_params", message="index_params required", required=True, field_type=dict))
    v.add_field_rule(ValidationRule(path="storage", message="storage required", required=True, field_type=dict))
    # Influx deps
    v.add_field_rule(ValidationRule(path="storage.influx.enabled", message="bool", required=False, field_type=bool))
    v.add_dependency_rule(DependencyRule(path="storage.influx.enabled", depends_on="storage.influx.url", message="influx.url required when enabled", required_value=True))
    v.add_dependency_rule(DependencyRule(path="storage.influx.enabled", depends_on="storage.influx.token", message="influx.token required when enabled", required_value=True))
    v.add_dependency_rule(DependencyRule(path="storage.influx.enabled", depends_on="storage.influx.org", message="influx.org required when enabled", required_value=True))
    v.add_dependency_rule(DependencyRule(path="storage.influx.enabled", depends_on="storage.influx.bucket", message="influx.bucket required when enabled", required_value=True))
    # Health flags
    v.add_field_rule(ValidationRule(path="health.api.enabled", message="bool", required=False, field_type=bool))
    v.add_field_rule(ValidationRule(path="health.prometheus.enabled", message="bool", required=False, field_type=bool))
    v.add_field_rule(ValidationRule(path="health.alerts.enabled", message="bool", required=False, field_type=bool))
    return v


__all__ = [
    "ValidationError",
    "ValidationRule",
    "DependencyRule",
    "SchemaValidationResult",
    "ConfigSchemaValidator",
    "create_default_validator",
]
