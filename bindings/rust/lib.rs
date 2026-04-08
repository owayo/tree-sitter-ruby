//! This crate provides Ruby language support for the [tree-sitter][] parsing library.
//!
//! Typically, you will use the [LANGUAGE][] constant to add this language to a
//! tree-sitter [Parser][], and then use the parser to parse some code:
//!
//! ```
//! use tree_sitter::Parser;
//!
//! let code = r#"
//! def hello(name)
//!  puts "Hello, #{name}!"
//! end
//! "#;
//! let mut parser = Parser::new();
//! let language = tree_sitter_ruby::LANGUAGE;
//! parser
//!     .set_language(&language.into())
//!     .expect("Error loading Ruby parser");
//! let tree = parser.parse(code, None).unwrap();
//! assert!(!tree.root_node().has_error());
//! ```
//!
//! [Parser]: https://docs.rs/tree-sitter/*/tree_sitter/struct.Parser.html
//! [tree-sitter]: https://tree-sitter.github.io/

use tree_sitter_language::LanguageFn;

extern "C" {
    fn tree_sitter_ruby() -> *const ();
}

/// The tree-sitter [`LanguageFn`][LanguageFn] for this grammar.
///
/// [LanguageFn]: https://docs.rs/tree-sitter-language/*/tree_sitter_language/struct.LanguageFn.html
pub const LANGUAGE: LanguageFn = unsafe { LanguageFn::from_raw(tree_sitter_ruby) };

/// The content of the [`node-types.json`][] file for this grammar.
///
/// [`node-types.json`]: https://tree-sitter.github.io/tree-sitter/using-parsers#static-node-types
pub const NODE_TYPES: &str = include_str!("../../src/node-types.json");

/// The syntax highlighting query for this language.
pub const HIGHLIGHTS_QUERY: &str = include_str!("../../queries/highlights.scm");

/// The local-variable syntax highlighting query for this language.
pub const LOCALS_QUERY: &str = include_str!("../../queries/locals.scm");

/// The symbol tagging query for this language.
pub const TAGS_QUERY: &str = include_str!("../../queries/tags.scm");

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_can_load_grammar() {
        let mut parser = tree_sitter::Parser::new();
        parser
            .set_language(&LANGUAGE.into())
            .expect("Error loading Ruby parser");
    }

    #[test]
    fn test_can_parse_basic_ruby() {
        let mut parser = tree_sitter::Parser::new();
        parser
            .set_language(&LANGUAGE.into())
            .expect("Error loading Ruby parser");
        let code = r#"
def hello(name)
  puts "Hello, #{name}!"
end

class Greeter
  attr_reader :name

  def initialize(name)
    @name = name
  end
end
"#;
        let tree = parser.parse(code, None).unwrap();
        let root = tree.root_node();
        assert!(!root.has_error());
        assert_eq!(root.kind(), "program");
    }

    #[test]
    fn test_highlights_query_valid() {
        let language: tree_sitter::Language = LANGUAGE.into();
        tree_sitter::Query::new(&language, HIGHLIGHTS_QUERY)
            .expect("Error loading highlights query");
    }

    #[test]
    fn test_locals_query_valid() {
        let language: tree_sitter::Language = LANGUAGE.into();
        tree_sitter::Query::new(&language, LOCALS_QUERY).expect("Error loading locals query");
    }

    #[test]
    fn test_tags_query_valid() {
        let language: tree_sitter::Language = LANGUAGE.into();
        tree_sitter::Query::new(&language, TAGS_QUERY).expect("Error loading tags query");
    }

    #[test]
    fn test_node_types_not_empty() {
        assert!(!NODE_TYPES.is_empty());
        assert!(NODE_TYPES.starts_with('['));
    }

    #[test]
    fn test_can_parse_heredoc() {
        let mut parser = tree_sitter::Parser::new();
        parser
            .set_language(&LANGUAGE.into())
            .expect("Error loading Ruby parser");
        let code = r#"
text = <<~HEREDOC
  Hello, world!
HEREDOC
"#;
        let tree = parser.parse(code, None).unwrap();
        assert!(!tree.root_node().has_error());
    }

    #[test]
    fn test_can_parse_pattern_matching() {
        let mut parser = tree_sitter::Parser::new();
        parser
            .set_language(&LANGUAGE.into())
            .expect("Error loading Ruby parser");
        let code = r#"
case [1, 2, 3]
in [Integer => a, Integer => b, Integer => c]
  puts a + b + c
end
"#;
        let tree = parser.parse(code, None).unwrap();
        assert!(!tree.root_node().has_error());
    }
}
