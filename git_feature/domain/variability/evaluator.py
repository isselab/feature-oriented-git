"""Three-valued instance resolution over the feature tree (port of the Rust evaluator)."""

from dataclasses import dataclass, field

from .ast import And, Clafer, Expr, Iff, Implies, Module, Not, Or, Ref, Xor, render

Assignment = dict[str, bool | None]


class ModelError(Exception):
    """The model itself is unusable for the request (unknown instance, missing super)."""


class ConfigurationError(Exception):
    """The requested configuration violates the model's constraints."""


@dataclass
class Configuration:
    """A resolved instance: concrete leaf features classified as included or excluded."""

    included: set[str] = field(default_factory=set)
    excluded: set[str] = field(default_factory=set)


class Evaluator:
    """Resolves named instances of an abstract feature model into configurations."""

    def __init__(self, module: Module) -> None:
        self.module = module
        self.registry: dict[str, Clafer] = {}
        self.duplicates: list[str] = []
        for clafer in module.clafers:
            self._index(clafer)

    def _index(self, clafer: Clafer) -> None:
        if clafer.name in self.registry:
            self.duplicates.append(clafer.name)
        self.registry[clafer.name] = clafer
        for child in clafer.children:
            self._index(child)

    def resolve_instance(self, instance_name: str) -> Configuration:
        """Classify the concrete leaf features of an instance as included/excluded."""
        assignment, supertype = self._resolve(instance_name)
        config = Configuration()
        for name in assignment:
            if name == supertype.name:
                continue
            clafer = self.registry.get(name)
            if clafer is None or clafer.is_abstract or clafer.children:
                continue
            if assignment.get(name) is True:
                config.included.add(name)
            else:
                config.excluded.add(name)
        return config

    def resolve_assignment(self, instance_name: str) -> dict[str, bool]:
        """Total feature → bool map over the model subtree (undetermined = excluded)."""
        assignment, supertype = self._resolve(instance_name)
        return {
            name: value is True for name, value in assignment.items() if name != supertype.name
        } | {supertype.name: True}

    def _resolve(self, instance_name: str) -> tuple[Assignment, Clafer]:
        instance = self.registry.get(instance_name)
        if instance is None:
            raise ModelError(f"instance '{instance_name}' not found in model")
        if instance.super_type is None:
            raise ModelError(f"instance '{instance_name}' has no super type")
        supertype = self.registry.get(instance.super_type)
        if supertype is None:
            raise ModelError(
                f"super type '{instance.super_type}' of instance '{instance_name}' not found"
            )

        subtree_names: set[str] = set()
        self._collect_subtree_names(supertype, subtree_names)
        assignment: Assignment = dict.fromkeys(subtree_names)
        conflicts: list[str] = []
        _try_assign(assignment, supertype.name, True, conflicts)

        # Explicit instance-body selections are seeded first so they win over inference.
        instance_constraints: list[Expr] = []
        _collect_constraints(instance, instance_constraints)
        for expr in instance_constraints:
            _propagate_expr(expr, True, assignment, conflicts)

        constraints = list(instance_constraints)
        _collect_constraints(supertype, constraints)

        while True:
            changed = self._propagate_mandatory_children(subtree_names, assignment, conflicts)
            changed |= self._propagate_group_cardinality(subtree_names, assignment, conflicts)
            for expr in constraints:
                changed |= _propagate_expr(expr, True, assignment, conflicts)
            if not changed:
                break

        self._check_legality(instance_name, constraints, assignment, conflicts, subtree_names)
        return assignment, supertype

    def _check_legality(
        self,
        instance_name: str,
        constraints: list[Expr],
        assignment: Assignment,
        conflicts: list[str],
        subtree_names: set[str],
    ) -> None:
        """Hard-fail on any violated constraint, conflicting inference, or broken group."""
        problems = list(conflicts)
        for expr in constraints:
            if _eval_expr(expr, assignment) is False:
                problems.append(f"constraint {render(expr)} is violated")
        total: Assignment = {name: value is True for name, value in assignment.items()}
        for name in subtree_names:
            clafer = self.registry.get(name)
            if clafer is None or clafer.gcard is None or total.get(name) is not True:
                continue
            active = sum(1 for child in clafer.children if total.get(child.name) is True)
            minimum, maximum = _gcard_bounds(clafer.gcard)
            if active < minimum or (maximum is not None and active > maximum):
                problems.append(
                    f"group '{name}' ({clafer.gcard}) has {active} active children,"
                    f" allowed {minimum}..{maximum if maximum is not None else '*'}"
                )
        if problems:
            details = "; ".join(problems)
            raise ConfigurationError(f"configuration '{instance_name}' is illegal: {details}")

    def _collect_subtree_names(self, root: Clafer, into: set[str]) -> None:
        into.add(root.name)
        for child in root.children:
            self._collect_subtree_names(child, into)

    def _propagate_mandatory_children(
        self, subtree_names: set[str], assignment: Assignment, conflicts: list[str]
    ) -> bool:
        changed = False
        for name in subtree_names:
            if assignment.get(name) is not True:
                continue
            clafer = self.registry.get(name)
            if clafer is None or clafer.gcard is not None:
                continue
            for child in clafer.children:
                if _is_mandatory_card(child.card):
                    changed |= _try_assign(assignment, child.name, True, conflicts)
        return changed

    def _propagate_group_cardinality(
        self, subtree_names: set[str], assignment: Assignment, conflicts: list[str]
    ) -> bool:
        changed = False
        for name in subtree_names:
            if assignment.get(name) is not True:
                continue
            clafer = self.registry.get(name)
            if clafer is None or clafer.gcard is None:
                continue
            minimum, maximum = _gcard_bounds(clafer.gcard)
            children = [child.name for child in clafer.children]
            true_count = sum(1 for child in children if assignment.get(child) is True)
            unknown = [child for child in children if assignment.get(child) is None]
            if maximum is not None and true_count >= maximum:
                for child in unknown:
                    changed |= _try_assign(assignment, child, False, conflicts)
                continue
            if minimum > 0 and true_count + len(unknown) == minimum:
                for child in unknown:
                    changed |= _try_assign(assignment, child, True, conflicts)
        return changed


def _collect_constraints(clafer: Clafer, out: list[Expr]) -> None:
    out.extend(clafer.constraints)
    for child in clafer.children:
        _collect_constraints(child, out)


def _try_assign(assignment: Assignment, name: str, value: bool, conflicts: list[str]) -> bool:
    """Assign only if currently unknown (monotonic); record conflicts and unknown names."""
    if name not in assignment:
        conflicts.append(f"reference to unknown feature '{name}'")
        return False
    current = assignment[name]
    if current is None:
        assignment[name] = value
        return True
    if current != value:
        conflicts.append(f"conflicting requirements for '{name}' (both on and off)")
    return False


def _eval_expr(expr: Expr, assignment: Assignment) -> bool | None:
    """Three-valued evaluation over a partial assignment."""
    match expr:
        case Ref(name):
            return assignment.get(name)
        case Not(operand):
            value = _eval_expr(operand, assignment)
            return None if value is None else not value
        case And(a, b):
            left, right = _eval_expr(a, assignment), _eval_expr(b, assignment)
            if left is False or right is False:
                return False
            if left is True and right is True:
                return True
            return None
        case Or(a, b):
            left, right = _eval_expr(a, assignment), _eval_expr(b, assignment)
            if left is True or right is True:
                return True
            if left is False and right is False:
                return False
            return None
        case Implies(a, b):
            left, right = _eval_expr(a, assignment), _eval_expr(b, assignment)
            if left is False or right is True:
                return True
            if left is True and right is False:
                return False
            return None
        case Xor(a, b):
            left, right = _eval_expr(a, assignment), _eval_expr(b, assignment)
            if left is None or right is None:
                return None
            return left != right
        case Iff(a, b):
            left, right = _eval_expr(a, assignment), _eval_expr(b, assignment)
            if left is None or right is None:
                return None
            return left == right


def _propagate_expr(
    expr: Expr, required: bool, assignment: Assignment, conflicts: list[str]
) -> bool:
    """Push a required truth value down the expression, asserting what follows."""
    match expr:
        case Ref(name):
            return _try_assign(assignment, name, required, conflicts)
        case Not(operand):
            return _propagate_expr(operand, not required, assignment, conflicts)
        case And(a, b):
            if required:
                changed = _propagate_expr(a, True, assignment, conflicts)
                return _propagate_expr(b, True, assignment, conflicts) or changed
            changed = False
            if _eval_expr(a, assignment) is True:
                changed |= _propagate_expr(b, False, assignment, conflicts)
            if _eval_expr(b, assignment) is True:
                changed |= _propagate_expr(a, False, assignment, conflicts)
            return changed
        case Or(a, b):
            if required:
                changed = False
                if _eval_expr(a, assignment) is False:
                    changed |= _propagate_expr(b, True, assignment, conflicts)
                if _eval_expr(b, assignment) is False:
                    changed |= _propagate_expr(a, True, assignment, conflicts)
                return changed
            changed = _propagate_expr(a, False, assignment, conflicts)
            return _propagate_expr(b, False, assignment, conflicts) or changed
        case Implies(a, b):
            if required:
                changed = False
                if _eval_expr(a, assignment) is True:
                    changed |= _propagate_expr(b, True, assignment, conflicts)
                if _eval_expr(b, assignment) is False:
                    changed |= _propagate_expr(a, False, assignment, conflicts)
                return changed
            changed = _propagate_expr(a, True, assignment, conflicts)
            return _propagate_expr(b, False, assignment, conflicts) or changed
        case Xor(a, b):
            changed = False
            left, right = _eval_expr(a, assignment), _eval_expr(b, assignment)
            if left is not None:
                changed |= _propagate_expr(b, left != required, assignment, conflicts)
            if right is not None:
                changed |= _propagate_expr(a, right != required, assignment, conflicts)
            return changed
        case Iff(a, b):
            changed = False
            left, right = _eval_expr(a, assignment), _eval_expr(b, assignment)
            if left is not None:
                changed |= _propagate_expr(b, left == required, assignment, conflicts)
            if right is not None:
                changed |= _propagate_expr(a, right == required, assignment, conflicts)
            return changed


def _is_mandatory_card(card: str | None) -> bool:
    """Mandatory means min >= 1: absent, '+', or a range/number with min >= 1."""
    if card is None or card == "+":
        return True
    if card in ("?", "*"):
        return False
    minimum = _ncard_min(card)
    return True if minimum is None else minimum >= 1


def _gcard_bounds(gcard: str) -> tuple[int, int | None]:
    """(min, max) for a group cardinality; max None means unbounded."""
    named = {"xor": (1, 1), "mux": (0, 1), "or": (1, None), "opt": (0, None)}
    if gcard in named:
        return named[gcard]
    return (_ncard_min(gcard) or 0, _ncard_max(gcard))


def _ncard_min(card: str) -> int | None:
    head = card.split("..")[0].strip()
    return int(head) if head.isdigit() else None


def _ncard_max(card: str) -> int | None:
    head, sep, tail = card.partition("..")
    part = tail.strip() if sep else head.strip()
    if part == "*":
        return None
    return int(part) if part.isdigit() else None
