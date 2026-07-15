"""Clafer subset parsing: Lark grammar → AST."""

from dataclasses import dataclass
from importlib import resources

from lark import Lark, Token, Transformer
from lark.exceptions import UnexpectedInput

from .ast import And, Clafer, Expr, Iff, Implies, Module, Not, Or, Ref, Xor


class ModelParseError(Exception):
    """The model text is not valid feature-modeling Clafer."""


@dataclass
class _Constraint:
    expr: Expr


@dataclass
class _Super:
    name: str


@dataclass
class _GCard:
    value: str


@dataclass
class _Card:
    value: str


@dataclass
class _Elements:
    items: list[Clafer | _Constraint]


class _ToAst(Transformer):
    def ref(self, items: list[Token]) -> Expr:
        return Ref(str(items[0]))

    def not_(self, items: list) -> Expr:
        return Not(items[-1])

    def and_(self, items: list) -> Expr:
        return And(items[0], items[-1])

    def or_(self, items: list) -> Expr:
        return Or(items[0], items[-1])

    def xor(self, items: list) -> Expr:
        return Xor(items[0], items[-1])

    def implies(self, items: list) -> Expr:
        return Implies(items[0], items[-1])

    def iff(self, items: list) -> Expr:
        return Iff(items[0], items[-1])

    def constraint(self, items: list) -> _Constraint:
        return _Constraint(items[0])

    def super_ref(self, items: list[Token]) -> _Super:
        return _Super(str(items[0]))

    def ncard(self, items: list[Token]) -> str:
        return f"{items[0]}..{items[1]}"

    def gcard(self, items: list) -> _GCard:
        return _GCard(str(items[0]))

    def card(self, items: list) -> _Card:
        return _Card(str(items[0]))

    def elements(self, items: list) -> _Elements:
        return _Elements(list(items))

    def clafer(self, items: list) -> Clafer:
        result = Clafer(name="")
        for item in items:
            match item:
                case Token(type="ABSTRACT"):
                    result.is_abstract = True
                case Token(type="NAME"):
                    result.name = str(item)
                case _GCard(value):
                    result.gcard = value
                case _Card(value):
                    result.card = value
                case _Super(name):
                    result.super_type = name
                case _Elements(children):
                    for child in children:
                        if isinstance(child, _Constraint):
                            result.constraints.append(child.expr)
                        else:
                            result.children.append(child)
        return result

    def module(self, items: list) -> Module:
        module = Module()
        for item in items:
            if isinstance(item, _Constraint):
                module.constraints.append(item.expr)
            else:
                module.clafers.append(item)
        return module


def _build_parser() -> Lark:
    grammar = resources.files(__package__).joinpath("clafer.lark").read_text("utf-8")
    return Lark(grammar, start="module", parser="earley")


_PARSER: Lark | None = None


def parse_model(text: str) -> Module:
    """Parse model.cfr text into a Module, or raise ModelParseError."""
    global _PARSER
    if _PARSER is None:
        _PARSER = _build_parser()
    try:
        tree = _PARSER.parse(text)
    except UnexpectedInput as exc:
        context = exc.get_context(text).strip()
        raise ModelParseError(
            f"not valid feature-model syntax at line {exc.line}, column {exc.column}: {context}"
        ) from None
    module = _ToAst().transform(tree)
    assert isinstance(module, Module)
    return module
