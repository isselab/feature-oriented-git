#[derive(Debug, Clone)]
pub enum Declaration {
    EnumDecl(String, Vec<String>),
    Element(Element),
}

#[derive(Debug, Clone)]
pub enum Element {
    Clafer(Clafer),
    Constraint(Expr),
}

#[derive(Debug, Clone, PartialEq)]
pub enum Expr {
    Ref(String),
    Not(Box<Expr>),
    And(Box<Expr>, Box<Expr>),
    Or(Box<Expr>, Box<Expr>),
    Xor(Box<Expr>, Box<Expr>),
    Implies(Box<Expr>, Box<Expr>),
    Iff(Box<Expr>, Box<Expr>),
    /// Outside the boolean-feature subset; always "unknown" during resolution.
    Other(String),
}

#[derive(Debug, Clone)]
pub struct Clafer {
    pub is_abstract: bool,
    pub gcard: Option<String>,
    pub name: String,
    pub super_type: Option<String>,
    pub card: Option<String>,
    pub children: Vec<Element>,
}
