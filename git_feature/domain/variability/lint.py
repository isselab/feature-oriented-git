"""Well-formedness checks for a parsed feature model."""

from .ast import Module, referenced_features, render
from .evaluator import Evaluator


def model_feature_names(module: Module) -> set[str]:
    """Names annotations may reference: every clafer that is not an instance."""
    evaluator = Evaluator(module)
    return {name for name, clafer in evaluator.registry.items() if clafer.super_type is None}


def instance_names(module: Module) -> list[str]:
    """Declared instances (clafers with a super type), in file order."""
    return [clafer.name for clafer in module.clafers if clafer.super_type is not None]


def lint_module(module: Module) -> list[str]:
    """Structural problems: duplicate names, missing supers, unknown constraint refs."""
    evaluator = Evaluator(module)
    problems = [f"duplicate feature name '{name}'" for name in evaluator.duplicates]
    for clafer in module.clafers:
        if clafer.super_type is not None and clafer.super_type not in evaluator.registry:
            problems.append(f"instance '{clafer.name}' extends unknown model '{clafer.super_type}'")
    known = set(evaluator.registry)
    all_constraints = list(module.constraints)
    for clafer in evaluator.registry.values():
        all_constraints.extend(clafer.constraints)
    for expr in all_constraints:
        unknown = referenced_features(expr) - known
        if unknown:
            problems.append(
                f"constraint {render(expr)} references unknown feature(s):"
                f" {', '.join(sorted(unknown))}"
            )
    return problems
