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
    use tree_sitter::StreamingIterator;

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

    #[test]
    fn test_locals_query_captures_singleton_method_scope() {
        let language: tree_sitter::Language = LANGUAGE.into();
        let mut parser = tree_sitter::Parser::new();
        parser.set_language(&language).unwrap();
        let query =
            tree_sitter::Query::new(&language, LOCALS_QUERY).expect("Error loading locals query");

        let code = "def self.foo\n  x = 1\nend\n";
        let tree = parser.parse(code, None).unwrap();
        assert!(!tree.root_node().has_error());

        // singleton_method が local.scope としてキャプチャされることを検証
        let scope_idx = query
            .capture_names()
            .iter()
            .position(|n| *n == "local.scope")
            .expect("local.scope キャプチャが見つかりません");
        let mut cursor = tree_sitter::QueryCursor::new();
        let mut matches = cursor.matches(&query, tree.root_node(), code.as_bytes());
        let mut scope_nodes = Vec::new();
        while let Some(m) = matches.next() {
            for c in m.captures {
                if c.index as usize == scope_idx {
                    scope_nodes.push(c.node.kind().to_string());
                }
            }
        }
        assert!(
            scope_nodes.iter().any(|k| k == "singleton_method"),
            "singleton_method が local.scope に含まれていません: {:?}",
            scope_nodes
        );
    }

    #[test]
    fn test_locals_query_captures_for_variable_definition() {
        let language: tree_sitter::Language = LANGUAGE.into();
        let mut parser = tree_sitter::Parser::new();
        parser.set_language(&language).unwrap();
        let query =
            tree_sitter::Query::new(&language, LOCALS_QUERY).expect("Error loading locals query");

        let code = "for x in [1, 2, 3]\n  puts x\nend\n";
        let tree = parser.parse(code, None).unwrap();
        assert!(!tree.root_node().has_error());

        // for ループの変数が local.definition としてキャプチャされることを検証
        let def_idx = query
            .capture_names()
            .iter()
            .position(|n| *n == "local.definition")
            .expect("local.definition キャプチャが見つかりません");
        let mut cursor = tree_sitter::QueryCursor::new();
        let mut matches = cursor.matches(&query, tree.root_node(), code.as_bytes());
        let mut def_texts = Vec::new();
        while let Some(m) = matches.next() {
            for c in m.captures {
                if c.index as usize == def_idx {
                    let text = &code[c.node.byte_range()];
                    def_texts.push(text.to_string());
                }
            }
        }
        assert!(
            def_texts.contains(&"x".to_string()),
            "for ループ変数 'x' が local.definition に含まれていません: {:?}",
            def_texts
        );
    }

    #[test]
    fn test_locals_query_captures_as_pattern_definition() {
        let language: tree_sitter::Language = LANGUAGE.into();
        let mut parser = tree_sitter::Parser::new();
        parser.set_language(&language).unwrap();
        let query =
            tree_sitter::Query::new(&language, LOCALS_QUERY).expect("Error loading locals query");

        let code = "case [1, 2]\nin [Integer => n, String => s]\n  puts n\nend\n";
        let tree = parser.parse(code, None).unwrap();
        assert!(!tree.root_node().has_error());

        // as_pattern の変数が local.definition としてキャプチャされることを検証
        let def_idx = query
            .capture_names()
            .iter()
            .position(|n| *n == "local.definition")
            .expect("local.definition キャプチャが見つかりません");
        let mut cursor = tree_sitter::QueryCursor::new();
        let mut matches = cursor.matches(&query, tree.root_node(), code.as_bytes());
        let mut def_texts = Vec::new();
        while let Some(m) = matches.next() {
            for c in m.captures {
                if c.index as usize == def_idx {
                    let text = &code[c.node.byte_range()];
                    def_texts.push(text.to_string());
                }
            }
        }
        assert!(
            def_texts.contains(&"n".to_string()),
            "as_pattern 変数 'n' が local.definition に含まれていません: {:?}",
            def_texts
        );
        assert!(
            def_texts.contains(&"s".to_string()),
            "as_pattern 変数 's' が local.definition に含まれていません: {:?}",
            def_texts
        );
    }

    #[test]
    fn test_highlights_query_captures_keywords() {
        let language: tree_sitter::Language = LANGUAGE.into();
        let mut parser = tree_sitter::Parser::new();
        parser.set_language(&language).unwrap();
        let query = tree_sitter::Query::new(&language, HIGHLIGHTS_QUERY)
            .expect("Error loading highlights query");

        let code = "def foo; end\n";
        let tree = parser.parse(code, None).unwrap();
        assert!(!tree.root_node().has_error());

        // ハイライトクエリが少なくとも1つのキャプチャを生成することを検証
        let mut cursor = tree_sitter::QueryCursor::new();
        let mut matches = cursor.matches(&query, tree.root_node(), code.as_bytes());
        let mut total_captures: usize = 0;
        while let Some(m) = matches.next() {
            total_captures += m.captures.len();
        }
        assert!(total_captures > 0, "ハイライトキャプチャが0件です");
    }
}
