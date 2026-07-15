"""Presence-condition algebra: `name`, `!`, `&`, `|`, parentheses."""

import re
from collections.abc import Iterable, Mapping
from itertools import product

from .ast import And, Expr, Not, Or, Ref, referenced_features

_TOKEN = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_-]*|&&|\|\||[!&|()])")

_MAX_SAT_FEATURES = 16


class PresenceError(Exception):
    """A presence condition is syntactically invalid."""


class UnknownFeatureError(Exception):
    """A presence condition references features the model doesn't know."""

    def __init__(self, names: set[str]) -> None:
        self.names = names
        super().__init__(f"unknown feature(s): {', '.join(sorted(names))}")


def parse_presence(text: str) -> Expr:
    """Parse a presence condition into an expression, or raise PresenceError."""
    tokens = _tokenize(text)
    expr, position = _parse_or(tokens, 0)
    if position != len(tokens):
        raise PresenceError(f"unexpected {tokens[position]!r} in presence condition {text!r}")
    return expr


def eval_presence(expr: Expr, assignment: Mapping[str, bool]) -> bool:
    """Evaluate under a total assignment; unknown features are an error, never False."""
    unknown = referenced_features(expr) - set(assignment)
    if unknown:
        raise UnknownFeatureError(unknown)
    return _eval(expr, assignment)


def satisfiable(expr: Expr) -> bool:
    """Brute-force satisfiability over the referenced features (small conditions only)."""
    names = sorted(referenced_features(expr))
    if len(names) > _MAX_SAT_FEATURES:
        return True  # too large to decide; do not flag
    return any(
        _eval(expr, dict(zip(names, values, strict=True)))
        for values in product((False, True), repeat=len(names))
    )


def lint_presence(text: str, known_features: Iterable[str]) -> list[str]:
    """Problems with one stored presence condition: syntax, unknown names, unsatisfiable."""
    try:
        expr = parse_presence(text)
    except PresenceError as exc:
        return [str(exc)]
    problems = []
    unknown = referenced_features(expr) - set(known_features)
    if unknown:
        problems.append(f"{text!r} references unknown feature(s): {', '.join(sorted(unknown))}")
    if not satisfiable(expr):
        problems.append(f"{text!r} is unsatisfiable (no configuration can enable this region)")
    return problems


def _eval(expr: Expr, assignment: Mapping[str, bool]) -> bool:
    match expr:
        case Ref(name):
            return assignment.get(name, False)
        case Not(operand):
            return not _eval(operand, assignment)
        case And(a, b):
            return _eval(a, assignment) and _eval(b, assignment)
        case Or(a, b):
            return _eval(a, assignment) or _eval(b, assignment)
        case _:
            raise PresenceError(f"operator not allowed in a presence condition: {expr}")


def _tokenize(text: str) -> list[str]:
    tokens = []
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None:
            if text[position:].strip():
                raise PresenceError(f"invalid character in presence condition: {text!r}")
            break
        tokens.append(match.group(1))
        position = match.end()
    if not tokens:
        raise PresenceError("empty presence condition")
    return tokens


def _parse_or(tokens: list[str], position: int) -> tuple[Expr, int]:
    left, position = _parse_and(tokens, position)
    while position < len(tokens) and tokens[position] in ("|", "||"):
        right, position = _parse_and(tokens, position + 1)
        left = Or(left, right)
    return left, position


def _parse_and(tokens: list[str], position: int) -> tuple[Expr, int]:
    left, position = _parse_unary(tokens, position)
    while position < len(tokens) and tokens[position] in ("&", "&&"):
        right, position = _parse_unary(tokens, position + 1)
        left = And(left, right)
    return left, position


def _parse_unary(tokens: list[str], position: int) -> tuple[Expr, int]:
    if position >= len(tokens):
        raise PresenceError("presence condition ends unexpectedly")
    token = tokens[position]
    if token == "!":
        operand, position = _parse_unary(tokens, position + 1)
        return Not(operand), position
    if token == "(":
        expr, position = _parse_or(tokens, position + 1)
        if position >= len(tokens) or tokens[position] != ")":
            raise PresenceError("missing closing parenthesis in presence condition")
        return expr, position + 1
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", token):
        return Ref(token), position + 1
    raise PresenceError(f"unexpected {token!r} in presence condition")
