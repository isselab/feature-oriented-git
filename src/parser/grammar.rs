use pest::Parser;
use pest::iterators::Pair;
use pest_derive::Parser;

use crate::parser::ast::{Clafer, Declaration, Element, Expr};

#[derive(Parser)]
#[grammar = "parser/clafer.pest"]
pub struct ClaferParser;

pub fn parse_clafer_module(input: &str) -> Vec<Declaration> {
    let pairs = ClaferParser::parse(Rule::module, input)
        .expect("Parsing                                                                                                   copied 128 chars to clipboard failed")
        .next()
        .unwrap();

    let mut declarations = Vec::new();

    for pair in pairs.into_inner() {
        match pair.as_rule() {
            Rule::declaration => {
                let inner = pair.into_inner().next().unwrap();
                match inner.as_rule() {
                    Rule::enum_decl => {
                        // Idents are flat in `.into_inner()`; the first is the enum's name.
                        let idents: Vec<String> =
                            inner.into_inner().map(|p| p.as_str().to_string()).collect();
                        if let Some((name, members)) = idents.split_first() {
                            declarations.push(Declaration::EnumDecl(name.clone(), members.to_vec()));
                        }
                    }
                    Rule::element => {
                        declarations.push(Declaration::Element(parse_element(inner)));
                    }
                    _ => {}
                }
            }
            Rule::EOI => (), // End of Input
            _ => unreachable!(),
        }
    }
    declarations
}

fn parse_element(pair: Pair<Rule>) -> Element {
    let inner = pair.into_inner().next().unwrap();
    match inner.as_rule() {
        Rule::clafer => Element::Clafer(parse_clafer(inner)),
        Rule::constraint => {
            // constraint = { "[" ~ expr ~ "]" }
            let expr_pair = inner.into_inner().next().unwrap();
            Element::Constraint(parse_expr(expr_pair))
        }
        _ => unreachable!(),
    }
}

/// Parses the boolean-expression grammar (`expr` through `primary`) into an `Expr`
/// tree. Anything outside the boolean subset is preserved as raw `Expr::Other` text,
/// staying inert (always "unknown") during evaluation instead of panicking.
fn parse_expr(pair: Pair<Rule>) -> Expr {
    match pair.as_rule() {
        Rule::expr => parse_expr(pair.into_inner().next().unwrap()),
        Rule::iff_expr => fold_connective(pair, Expr::Iff),
        Rule::implies_expr => fold_connective(pair, Expr::Implies),
        Rule::or_expr => fold_connective(pair, Expr::Or),
        Rule::xor_expr => fold_connective(pair, Expr::Xor),
        Rule::and_expr => fold_connective(pair, Expr::And),
        Rule::cmp_expr => parse_operator_chain(pair, Rule::cmp_op),
        Rule::add_expr => parse_operator_chain(pair, Rule::add_op),
        Rule::join_expr => {
            let text = pair.as_str().trim().to_string();
            let operands: Vec<Pair<Rule>> = pair.into_inner().collect();
            match <[Pair<Rule>; 1]>::try_from(operands) {
                Ok([only]) => parse_expr(only),
                Err(_) => Expr::Other(text), // dotted join, out of scope
            }
        }
        Rule::primary => parse_primary(pair),
        Rule::ident => Expr::Ref(pair.as_str().to_string()),
        _ => Expr::Other(pair.as_str().trim().to_string()),
    }
}

/// Left-folds a level like `and_expr = { cmp_expr ~ ("&&" ~ cmp_expr)* }` into a
/// chain of binary nodes. The operator is a bare literal (not in `.into_inner()`),
/// so the level's single connective applies to every operand join.
fn fold_connective(pair: Pair<Rule>, ctor: fn(Box<Expr>, Box<Expr>) -> Expr) -> Expr {
    let mut operands = pair.into_inner().map(parse_expr);
    let first = operands
        .next()
        .expect("expression level must have at least one operand");
    operands.fold(first, |acc, next| ctor(Box::new(acc), Box::new(next)))
}

/// Handles levels with a named operator rule (`cmp_op`, `add_op`). These are outside
/// the boolean subset: a lone operand passes through, a real chain becomes `Expr::Other`.
fn parse_operator_chain(pair: Pair<Rule>, op_rule: Rule) -> Expr {
    let text = pair.as_str().trim().to_string();
    let operands: Vec<Pair<Rule>> = pair.into_inner().filter(|p| p.as_rule() != op_rule).collect();
    match <[Pair<Rule>; 1]>::try_from(operands) {
        Ok([only]) => parse_expr(only),
        Err(_) => Expr::Other(text),
    }
}

/// `primary = { unary_op* ~ quantifier? ~ (ident | int | str | "(" ~ expr ~ ")") }`
fn parse_primary(pair: Pair<Rule>) -> Expr {
    let full_text = pair.as_str().trim().to_string();
    let parts: Vec<Pair<Rule>> = pair.into_inner().collect();
    let Some((terminal, prefixes)) = parts.split_last() else {
        return Expr::Other(full_text);
    };

    // Arithmetic negation ("-") is outside the boolean subset; bail out whole.
    if prefixes
        .iter()
        .any(|p| p.as_rule() == Rule::unary_op && p.as_str() == "-")
    {
        return Expr::Other(full_text);
    }

    let mut expr = parse_expr(terminal.clone());

    // Apply prefixes innermost-first: the one nearest the terminal binds first.
    for prefix in prefixes.iter().rev() {
        match prefix.as_rule() {
            Rule::unary_op if prefix.as_str() == "!" => {
                expr = Expr::Not(Box::new(expr));
            }
            Rule::quantifier if matches!(prefix.as_str(), "no" | "not") => {
                expr = Expr::Not(Box::new(expr));
            }
            // "lone"/"one"/"some"/"all": pass through; multiplicity quantifiers
            // have no precise meaning in this single-instance boolean subset.
            _ => {}
        }
    }

    expr
}

fn parse_clafer(pair: Pair<Rule>) -> Clafer {
    let mut is_abstract = false;
    let mut gcard = None;
    let mut name = String::new();
    let mut super_type = None;
    let mut card = None;
    let mut children = Vec::new();

    // Walk through the components of the clafer
    for inner in pair.into_inner() {
        match inner.as_rule() {
            Rule::abstract_mod => is_abstract = true,
            Rule::gcard => gcard = Some(inner.as_str().to_string()),
            Rule::ident => name = inner.as_str().to_string(),
            Rule::super_mod => {
                // super_mod is ":" ~ expr. Parse via parse_expr rather than raw
                // span text, which can leak trailing whitespace from pest.
                let expr_pair = inner.into_inner().next().unwrap();
                if let Expr::Ref(name) = parse_expr(expr_pair) {
                    super_type = Some(name);
                }
            }
            Rule::card => card = Some(inner.as_str().to_string()),
            Rule::elements => {
                // Recursively parse children inside { }
                for el in inner.into_inner() {
                    if el.as_rule() == Rule::element {
                        children.push(parse_element(el));
                    }
                }
            }
            // ref_mod/init_mod are UML/attribute concerns, not feature modeling.
            _ => {}
        }
    }

    Clafer {
        is_abstract,
        gcard,
        name,
        super_type,
        card,
        children,
    }
}
