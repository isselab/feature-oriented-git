"""Evaluator spec ported from the Rust proof of concept, plus strictness upgrades."""

import pytest

from git_feature.domain.variability import (
    ConfigurationError,
    Evaluator,
    ModelError,
    parse_model,
)

# The reference model from the Rust test suite, verbatim.
MODEL = """
abstract POSSystem {
    xor Storage {
        SQLite
        Postgres
    }
    Scanner ?
    DigitalPayment ?
    PhysicalCash ?
    ReceiptPrinter ?

    // Dependencies
    [ PhysicalCash => ReceiptPrinter ]
    [ DigitalPayment || PhysicalCash ]
}

// Instance 1: A lightweight, digital-only tablet
MinimalistKiosk : POSSystem {
    [ SQLite ]
    [ DigitalPayment ]
    [ no PhysicalCash ]
    [ no Scanner ]
    [ no ReceiptPrinter ]
}

// Instance 2: A robust, hardware-heavy checkout
FullServiceStation : POSSystem {
    [ Postgres ]
    [ DigitalPayment ]
    [ PhysicalCash ]
    [ Scanner ]
}
"""


def _evaluator(text: str = MODEL) -> Evaluator:
    return Evaluator(parse_model(text))


def test_resolves_full_service_station() -> None:
    config = _evaluator().resolve_instance("FullServiceStation")
    assert config.included == {
        "Postgres",
        "DigitalPayment",
        "PhysicalCash",
        "Scanner",
        "ReceiptPrinter",
    }
    assert config.excluded == {"SQLite"}


def test_resolves_minimalist_kiosk() -> None:
    config = _evaluator().resolve_instance("MinimalistKiosk")
    assert config.included == {"SQLite", "DigitalPayment"}
    assert config.excluded == {"Postgres", "PhysicalCash", "Scanner", "ReceiptPrinter"}


def test_unknown_instance_errors() -> None:
    with pytest.raises(ModelError):
        _evaluator().resolve_instance("NoSuchInstance")


# --- beyond the Rust suite: total assignments, legality, inference ---


def test_assignment_is_total_over_the_feature_tree() -> None:
    assignment = _evaluator().resolve_assignment("MinimalistKiosk")
    assert assignment["SQLite"] is True
    assert assignment["Postgres"] is False
    assert assignment["Scanner"] is False
    assert assignment["Storage"] is True  # structural group node is active
    assert "MinimalistKiosk" not in assignment  # the instance is not a feature


def test_mandatory_children_are_forced_on() -> None:
    evaluator = _evaluator(
        """
abstract App {
    core
    extras ?
}

Plain : App {}
"""
    )
    config = evaluator.resolve_instance("Plain")
    assert "core" in config.included
    assert "extras" in config.excluded


def test_xor_group_infers_the_other_choice_off() -> None:
    config = _evaluator().resolve_instance("FullServiceStation")
    assert "SQLite" in config.excluded  # Postgres chosen, xor forces SQLite off


def test_implies_propagates() -> None:
    # FullServiceStation selects PhysicalCash but never mentions ReceiptPrinter:
    # [ PhysicalCash => ReceiptPrinter ] must pull it in.
    config = _evaluator().resolve_instance("FullServiceStation")
    assert "ReceiptPrinter" in config.included


def test_violated_constraint_is_a_hard_error() -> None:
    evaluator = _evaluator(
        """
abstract App {
    a ?
    b ?
    [ a => b ]
}

Broken : App {
    [ a ]
    [ no b ]
}
"""
    )
    with pytest.raises(ConfigurationError):
        evaluator.resolve_instance("Broken")


def test_xor_overselection_is_a_hard_error() -> None:
    evaluator = _evaluator(
        """
abstract App {
    xor Mode {
        fast
        safe
    }
}

Both : App {
    [ fast ]
    [ safe ]
}
"""
    )
    with pytest.raises(ConfigurationError):
        evaluator.resolve_instance("Both")


def test_instance_without_super_type_errors() -> None:
    evaluator = _evaluator("Lonely\n")
    with pytest.raises(ModelError):
        evaluator.resolve_instance("Lonely")
