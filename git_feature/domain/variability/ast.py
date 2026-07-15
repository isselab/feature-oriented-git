"""AST for the Clafer feature-modeling subset."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Ref:
    name: str


@dataclass(frozen=True)
class Not:
    operand: Expr


@dataclass(frozen=True)
class And:
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Or:
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Xor:
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Implies:
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Iff:
    left: Expr
    right: Expr


Expr = Ref | Not | And | Or | Xor | Implies | Iff


@dataclass
class Clafer:
    """One node of the feature tree (or an instance declaration)."""

    name: str
    is_abstract: bool = False
    gcard: str | None = None
    super_type: str | None = None
    card: str | None = None
    constraints: list[Expr] = field(default_factory=list)
    children: list[Clafer] = field(default_factory=list)


@dataclass
class Module:
    """A parsed model.cfr: top-level clafers and free-standing constraints."""

    clafers: list[Clafer] = field(default_factory=list)
    constraints: list[Expr] = field(default_factory=list)


def render(expr: Expr) -> str:
    """Human-readable form of an expression, for error messages."""
    match expr:
        case Ref(name):
            return name
        case Not(operand):
            return f"!{render(operand)}"
        case And(left, right):
            return f"({render(left)} && {render(right)})"
        case Or(left, right):
            return f"({render(left)} || {render(right)})"
        case Xor(left, right):
            return f"({render(left)} xor {render(right)})"
        case Implies(left, right):
            return f"({render(left)} => {render(right)})"
        case Iff(left, right):
            return f"({render(left)} <=> {render(right)})"


def referenced_features(expr: Expr) -> set[str]:
    """Every feature name mentioned in an expression."""
    match expr:
        case Ref(name):
            return {name}
        case Not(operand):
            return referenced_features(operand)
        case And(a, b) | Or(a, b) | Xor(a, b) | Implies(a, b) | Iff(a, b):
            return referenced_features(a) | referenced_features(b)
