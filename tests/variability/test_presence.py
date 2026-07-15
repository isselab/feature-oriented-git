"""Table-driven tests for the presence-condition algebra."""

import pytest

from git_feature.domain.variability.ast import And, Not, Or, Ref
from git_feature.domain.variability.presence import (
    PresenceError,
    UnknownFeatureError,
    eval_presence,
    lint_presence,
    parse_presence,
    satisfiable,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("auth", Ref("auth")),
        ("!auth", Not(Ref("auth"))),
        ("a & b", And(Ref("a"), Ref("b"))),
        ("a && b", And(Ref("a"), Ref("b"))),
        ("a | b", Or(Ref("a"), Ref("b"))),
        ("a || b", Or(Ref("a"), Ref("b"))),
        ("a & b | c", Or(And(Ref("a"), Ref("b")), Ref("c"))),  # & binds tighter
        ("a & (b | c)", And(Ref("a"), Or(Ref("b"), Ref("c")))),
        ("!a & b", And(Not(Ref("a")), Ref("b"))),
        ("!(a | b)", Not(Or(Ref("a"), Ref("b")))),
        ("feature-x", Ref("feature-x")),
    ],
)
def test_parse(text: str, expected: object) -> None:
    assert parse_presence(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "a &", "& a", "a b", "(a", "a)", "a ? b", "a => b"],
)
def test_parse_errors(text: str) -> None:
    with pytest.raises(PresenceError):
        parse_presence(text)


@pytest.mark.parametrize(
    ("text", "assignment", "expected"),
    [
        ("auth", {"auth": True}, True),
        ("auth", {"auth": False}, False),
        ("!auth", {"auth": False}, True),
        ("a & b", {"a": True, "b": False}, False),
        ("a | b", {"a": True, "b": False}, True),
        ("a & !b | c", {"a": True, "b": True, "c": True}, True),
    ],
)
def test_eval(text: str, assignment: dict[str, bool], expected: bool) -> None:
    assert eval_presence(parse_presence(text), assignment) is expected


def test_unknown_feature_is_an_error_not_false() -> None:
    with pytest.raises(UnknownFeatureError) as excinfo:
        eval_presence(parse_presence("auth & typo"), {"auth": True})
    assert excinfo.value.names == {"typo"}


def test_satisfiability() -> None:
    assert satisfiable(parse_presence("a & b"))
    assert not satisfiable(parse_presence("a & !a"))
    assert satisfiable(parse_presence("a | !a"))


def test_lint_catches_unknown_and_unsatisfiable() -> None:
    assert lint_presence("auth", ["auth"]) == []
    problems = lint_presence("auth & ghost", ["auth"])
    assert len(problems) == 1 and "ghost" in problems[0]
    problems = lint_presence("a & !a", ["a"])
    assert len(problems) == 1 and "unsatisfiable" in problems[0]
    problems = lint_presence("a &", ["a"])
    assert len(problems) == 1
