"""Parser tests: the feature-modeling subset parses; everything beyond it is rejected."""

import pytest

from git_feature.domain.variability import ModelParseError, parse_model
from git_feature.domain.variability.ast import And, Implies, Not, Or, Ref


def test_feature_tree_shape() -> None:
    module = parse_model(
        """
abstract Shop {
    core
    payments ?
    xor Storage {
        SQLite
        Postgres
    }
}
"""
    )
    (shop,) = module.clafers
    assert shop.name == "Shop"
    assert shop.is_abstract
    names = [child.name for child in shop.children]
    assert names == ["core", "payments", "Storage"]
    core, payments, storage = shop.children
    assert core.card is None
    assert payments.card == "?"
    assert storage.gcard == "xor"
    assert [c.name for c in storage.children] == ["SQLite", "Postgres"]


def test_instance_with_super_type_and_constraints() -> None:
    module = parse_model(
        """
abstract App { a ?  b ? }
Full : App {
    [ a ]
    [ !b ]
}
"""
    )
    full = module.clafers[1]
    assert full.super_type == "App"
    assert full.constraints == [Ref("a"), Not(Ref("b"))]


def test_boolean_operators_and_precedence() -> None:
    module = parse_model("abstract M { x?  y?  z? } I : M { [ x || y && !z ] }")
    (expr,) = module.clafers[1].constraints
    assert expr == Or(Ref("x"), And(Ref("y"), Not(Ref("z"))))


def test_no_and_not_are_negation() -> None:
    module = parse_model("abstract M { x? } I : M { [ no x ] [ not x ] }")
    assert module.clafers[1].constraints == [Not(Ref("x")), Not(Ref("x"))]


def test_implies_and_parens() -> None:
    module = parse_model("abstract M { x?  y?  z? } I : M { [ (x || y) => z ] }")
    (expr,) = module.clafers[1].constraints
    assert expr == Implies(Or(Ref("x"), Ref("y")), Ref("z"))


def test_cardinalities() -> None:
    module = parse_model(
        """
abstract M {
    one_
    opt ?
    many *
    some +
    ranged 1..3
    open 2..*
}
"""
    )
    cards = {c.name: c.card for c in module.clafers[0].children}
    assert cards == {
        "one_": None,
        "opt": "?",
        "many": "*",
        "some": "+",
        "ranged": "1..3",
        "open": "2..*",
    }


def test_group_cardinality_as_range() -> None:
    module = parse_model("abstract M { 1..2 Group { a  b  c } }")
    (group,) = module.clafers[0].children
    assert group.gcard == "1..2"


def test_comments_are_ignored() -> None:
    module = parse_model(
        """
// line comment
abstract M {
    a ?   // trailing
    /* block
       comment */
    b ?
}
"""
    )
    assert [c.name for c in module.clafers[0].children] == ["a", "b"]


@pytest.mark.parametrize(
    "text",
    [
        "enum Color = red | green",  # enums
        "abstract M { ref -> Target }",  # reference clafers
        "abstract M { x = 5 }",  # initializers
        "abstract M { [ x + y ] }",  # arithmetic
        "abstract M { [ x > 3 ] }",  # comparisons
        'abstract M { [ x = "str" ] }',  # strings
        "abstract M { [ a.b ] }",  # dotted joins
        "abstract M { [ lone x ] }",  # set quantifiers
    ],
    ids=["enum", "reference", "init", "arithmetic", "comparison", "string", "join", "quantifier"],
)
def test_constructs_beyond_the_subset_are_rejected(text: str) -> None:
    with pytest.raises(ModelParseError):
        parse_model(text)


def test_parse_error_carries_location() -> None:
    with pytest.raises(ModelParseError) as excinfo:
        parse_model("abstract M {\n    [ a.b ]\n}")
    assert "line 2" in str(excinfo.value)
