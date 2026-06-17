use super::ast::{Clafer, Declaration, Element, Expr};
use anyhow::{Result, anyhow};
use std::collections::{HashMap, HashSet};

/// A resolved instance: each leaf feature classified as included or excluded.
/// Structural containers and the abstract supertype appear in neither set.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct Configuration {
    pub included: HashSet<String>,
    pub excluded: HashSet<String>,
}

/// Per-clafer state during resolution: active / inactive / undetermined.
type Assignment = HashMap<String, Option<bool>>;

pub struct Evaluator {
    // Global registry of every Clafer definition, keyed by name.
    pub registry: HashMap<String, Clafer>,
}

impl Evaluator {
    pub fn new(decls: Vec<Declaration>) -> Self {
        let mut registry = HashMap::new();

        // Index nested clafers too (e.g. SQLite inside Storage).
        fn index_recursive(elements: &[Element], map: &mut HashMap<String, Clafer>) {
            for el in elements {
                if let Element::Clafer(c) = el {
                    map.insert(c.name.clone(), c.clone());
                    index_recursive(&c.children, map);
                }
            }
        }

        for decl in decls {
            if let Declaration::Element(Element::Clafer(c)) = decl {
                registry.insert(c.name.clone(), c.clone());
                index_recursive(&c.children, &mut registry);
            }
        }

        Self { registry }
    }

    /// Resolves an instance against its abstract model into included/excluded leaf features.
    pub fn resolve_instance(&self, instance_name: &str) -> Result<Configuration> {
        let instance = self
            .registry
            .get(instance_name)
            .ok_or_else(|| anyhow!("Instance '{}' not found in model", instance_name))?;
        let super_name = instance
            .super_type
            .as_ref()
            .ok_or_else(|| anyhow!("Instance '{}' has no super type", instance_name))?;
        let supertype = self
            .registry
            .get(super_name)
            .ok_or_else(|| anyhow!("Super type '{}' of instance '{}' not found", super_name, instance_name))?;

        let mut subtree_names = HashSet::new();
        self.collect_subtree_names(supertype, &mut subtree_names);

        let mut assignment: Assignment = subtree_names.iter().map(|n| (n.clone(), None)).collect();
        try_assign(&mut assignment, super_name, true);

        // Seed explicit instance-body selections first so they win over inference.
        let mut instance_constraints = Vec::new();
        collect_constraints(&instance.children, &mut instance_constraints);
        for expr in &instance_constraints {
            propagate_expr(expr, true, &mut assignment);
        }

        // All subtree constraints for the fixed-point loop; re-asserting the
        // instance constraints is a harmless no-op.
        let mut constraints = instance_constraints;
        collect_constraints(&supertype.children, &mut constraints);

        loop {
            let mut changed = false;
            changed |= self.propagate_mandatory_children(&subtree_names, &mut assignment);
            changed |= self.propagate_group_cardinality(&subtree_names, &mut assignment);
            for expr in &constraints {
                changed |= propagate_expr(expr, true, &mut assignment);
            }
            if !changed {
                break;
            }
        }

        let mut config = Configuration::default();
        for name in &subtree_names {
            if name == super_name {
                continue;
            }
            let Some(clafer) = self.registry.get(name) else {
                continue;
            };
            if clafer.is_abstract {
                continue;
            }
            let is_structural_leaf = !clafer.children.iter().any(|e| matches!(e, Element::Clafer(_)));
            if !is_structural_leaf {
                continue;
            }
            match assignment.get(name).copied().flatten() {
                Some(true) => {
                    config.included.insert(name.clone());
                }
                _ => {
                    config.excluded.insert(name.clone());
                }
            }
        }
        Ok(config)
    }

    /// Collects every clafer name nested under `root` (inclusive), bounding the
    /// resolution so unrelated declarations elsewhere don't leak in.
    fn collect_subtree_names(&self, root: &Clafer, into: &mut HashSet<String>) {
        into.insert(root.name.clone());
        for el in &root.children {
            if let Element::Clafer(child) = el {
                self.collect_subtree_names(child, into);
            }
        }
    }

    /// For each active clafer without a `gcard`, forces its mandatory-`card`
    /// children active. Clafers with a `gcard` are handled by group-cardinality rules.
    fn propagate_mandatory_children(&self, subtree_names: &HashSet<String>, assignment: &mut Assignment) -> bool {
        let mut changed = false;
        for name in subtree_names {
            if assignment.get(name).copied().flatten() != Some(true) {
                continue;
            }
            let Some(clafer) = self.registry.get(name) else { continue };
            if clafer.gcard.is_some() {
                continue;
            }
            for el in &clafer.children {
                if let Element::Clafer(child) = el
                    && is_mandatory_card(&child.card)
                {
                    changed |= try_assign(assignment, &child.name, true);
                }
            }
        }
        changed
    }

    /// For each active clafer with a `gcard`, enforces its min/max bound: at max,
    /// remaining unknown children go false; when all are needed for min, they go
    /// true. Covers `xor`/`mux`/`or`/`opt`/explicit ncard.
    fn propagate_group_cardinality(&self, subtree_names: &HashSet<String>, assignment: &mut Assignment) -> bool {
        let mut changed = false;
        for name in subtree_names {
            if assignment.get(name).copied().flatten() != Some(true) {
                continue;
            }
            let Some(clafer) = self.registry.get(name) else { continue };
            let Some(gcard) = &clafer.gcard else { continue };
            let (min, max) = gcard_bounds(gcard);

            let direct_children: Vec<&str> = clafer
                .children
                .iter()
                .filter_map(|e| if let Element::Clafer(c) = e { Some(c.name.as_str()) } else { None })
                .collect();

            let true_count = direct_children
                .iter()
                .filter(|c| assignment.get(**c).copied().flatten() == Some(true))
                .count();
            let unknown: Vec<&str> = direct_children
                .iter()
                .filter(|c| assignment.get(**c).copied().flatten().is_none())
                .copied()
                .collect();

            if let Some(max) = max
                && true_count >= max
            {
                for child in &unknown {
                    changed |= try_assign(assignment, child, false);
                }
                continue;
            }
            if min > 0 && true_count + unknown.len() == min {
                for child in &unknown {
                    changed |= try_assign(assignment, child, true);
                }
            }
        }
        changed
    }
}

/// Gathers every `Element::Constraint` in `elements`, including nested clafers.
fn collect_constraints(elements: &[Element], out: &mut Vec<Expr>) {
    for el in elements {
        match el {
            Element::Constraint(expr) => out.push(expr.clone()),
            Element::Clafer(c) => collect_constraints(&c.children, out),
        }
    }
}

/// Sets `name` to `value` only if currently unknown; returns whether it changed.
/// Conflicts are dropped with a warning, keeping assignments monotonic
/// (`None -> Some` only) so the resolution loop terminates and explicit selections win.
fn try_assign(assignment: &mut Assignment, name: &str, value: bool) -> bool {
    match assignment.get(name).copied() {
        Some(Some(existing)) if existing == value => false,
        Some(Some(existing)) => {
            eprintln!(
                "warning: conflicting assignment for '{}': already {}, ignoring {}",
                name, existing, value
            );
            false
        }
        Some(None) => {
            assignment.insert(name.to_string(), Some(value));
            true
        }
        None => {
            eprintln!("warning: reference to unknown feature '{}'", name);
            false
        }
    }
}

/// Three-valued evaluation of an already-known (partial) assignment.
fn eval_expr(expr: &Expr, assignment: &Assignment) -> Option<bool> {
    match expr {
        Expr::Ref(name) => assignment.get(name).copied().flatten(),
        Expr::Not(a) => eval_expr(a, assignment).map(|v| !v),
        Expr::And(a, b) => match (eval_expr(a, assignment), eval_expr(b, assignment)) {
            (Some(false), _) | (_, Some(false)) => Some(false),
            (Some(true), Some(true)) => Some(true),
            _ => None,
        },
        Expr::Or(a, b) => match (eval_expr(a, assignment), eval_expr(b, assignment)) {
            (Some(true), _) | (_, Some(true)) => Some(true),
            (Some(false), Some(false)) => Some(false),
            _ => None,
        },
        Expr::Implies(l, r) => {
            let lv = eval_expr(l, assignment);
            let rv = eval_expr(r, assignment);
            if lv == Some(false) || rv == Some(true) {
                Some(true)
            } else if lv == Some(true) && rv == Some(false) {
                Some(false)
            } else {
                None
            }
        }
        Expr::Xor(a, b) => match (eval_expr(a, assignment), eval_expr(b, assignment)) {
            (Some(av), Some(bv)) => Some(av != bv),
            _ => None,
        },
        Expr::Iff(a, b) => match (eval_expr(a, assignment), eval_expr(b, assignment)) {
            (Some(av), Some(bv)) => Some(av == bv),
            _ => None,
        },
        Expr::Other(_) => None,
    }
}

/// Pushes a required truth value down through `expr`, asserting whatever can be
/// inferred about its subexpressions. Returns whether any assignment changed.
fn propagate_expr(expr: &Expr, required: bool, assignment: &mut Assignment) -> bool {
    match expr {
        Expr::Ref(name) => try_assign(assignment, name, required),
        Expr::Not(a) => propagate_expr(a, !required, assignment),
        Expr::And(a, b) => {
            if required {
                propagate_expr(a, true, assignment) | propagate_expr(b, true, assignment)
            } else {
                let mut changed = false;
                if eval_expr(a, assignment) == Some(true) {
                    changed |= propagate_expr(b, false, assignment);
                }
                if eval_expr(b, assignment) == Some(true) {
                    changed |= propagate_expr(a, false, assignment);
                }
                changed
            }
        }
        Expr::Or(a, b) => {
            if required {
                let mut changed = false;
                if eval_expr(a, assignment) == Some(false) {
                    changed |= propagate_expr(b, true, assignment);
                }
                if eval_expr(b, assignment) == Some(false) {
                    changed |= propagate_expr(a, true, assignment);
                }
                changed
            } else {
                propagate_expr(a, false, assignment) | propagate_expr(b, false, assignment)
            }
        }
        Expr::Implies(l, r) => {
            if required {
                let mut changed = false;
                if eval_expr(l, assignment) == Some(true) {
                    changed |= propagate_expr(r, true, assignment);
                }
                if eval_expr(r, assignment) == Some(false) {
                    changed |= propagate_expr(l, false, assignment);
                }
                changed
            } else {
                propagate_expr(l, true, assignment) | propagate_expr(r, false, assignment)
            }
        }
        Expr::Xor(a, b) => {
            let mut changed = false;
            if let Some(av) = eval_expr(a, assignment) {
                changed |= propagate_expr(b, av != required, assignment);
            }
            if let Some(bv) = eval_expr(b, assignment) {
                changed |= propagate_expr(a, bv != required, assignment);
            }
            changed
        }
        Expr::Iff(a, b) => {
            let mut changed = false;
            if let Some(av) = eval_expr(a, assignment) {
                changed |= propagate_expr(b, av == required, assignment);
            }
            if let Some(bv) = eval_expr(b, assignment) {
                changed |= propagate_expr(a, bv == required, assignment);
            }
            changed
        }
        Expr::Other(_) => false,
    }
}

/// Whether a `card` is mandatory (min >= 1): absent, `"+"`, or a range with min >= 1.
/// `"?"`/`"*"`/min-0 ranges are optional.
fn is_mandatory_card(card: &Option<String>) -> bool {
    match card.as_deref() {
        None => true,
        Some("+") => true,
        Some("?") | Some("*") => false,
        Some(s) => ncard_min(s).map(|min| min >= 1).unwrap_or(true),
    }
}

/// (min, max) bounds for a group cardinality. `max = None` means unbounded.
fn gcard_bounds(gcard: &str) -> (usize, Option<usize>) {
    match gcard {
        "xor" => (1, Some(1)),
        "mux" => (0, Some(1)),
        "or" => (1, None),
        "opt" => (0, None),
        s => {
            let min = ncard_min(s).unwrap_or(0);
            let max = ncard_max(s);
            (min, max)
        }
    }
}

/// Parses the min of a cardinality string like `"1..3"`, `"1..*"`, or `"2"`.
fn ncard_min(s: &str) -> Option<usize> {
    let min_part = s.split("..").next().unwrap_or(s);
    min_part.trim().parse::<usize>().ok()
}

/// Parses the max of a cardinality string: `"1..3"` -> `Some(3)`, `"1..*"` -> `None`,
/// bare `"2"` -> `Some(2)`.
fn ncard_max(s: &str) -> Option<usize> {
    match s.split_once("..") {
        Some((_, "*")) => None,
        Some((_, max)) => max.trim().parse::<usize>().ok(),
        None => s.trim().parse::<usize>().ok(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parser::grammar::parse_clafer_module;

    const MODEL: &str = r#"
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
"#;

    fn set(names: &[&str]) -> HashSet<String> {
        names.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn resolves_full_service_station() {
        let decls = parse_clafer_module(MODEL);
        let eval = Evaluator::new(decls);
        let config = eval.resolve_instance("FullServiceStation").unwrap();
        assert_eq!(
            config.included,
            set(&["Postgres", "DigitalPayment", "PhysicalCash", "Scanner", "ReceiptPrinter"])
        );
        assert_eq!(config.excluded, set(&["SQLite"]));
    }

    #[test]
    fn resolves_minimalist_kiosk() {
        let decls = parse_clafer_module(MODEL);
        let eval = Evaluator::new(decls);
        let config = eval.resolve_instance("MinimalistKiosk").unwrap();
        assert_eq!(config.included, set(&["SQLite", "DigitalPayment"]));
        assert_eq!(
            config.excluded,
            set(&["Postgres", "PhysicalCash", "Scanner", "ReceiptPrinter"])
        );
    }

    #[test]
    fn unknown_instance_errors() {
        let decls = parse_clafer_module(MODEL);
        let eval = Evaluator::new(decls);
        assert!(eval.resolve_instance("NoSuchInstance").is_err());
    }
}
