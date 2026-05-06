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

    #[test]
    fn test_locals_query_captures_block_scope() {
        let language: tree_sitter::Language = LANGUAGE.into();
        let mut parser = tree_sitter::Parser::new();
        parser.set_language(&language).unwrap();
        let query =
            tree_sitter::Query::new(&language, LOCALS_QUERY).expect("Error loading locals query");

        // block / do_block / lambda がスコープとして捕捉されることを確認
        let code = "items.each { |n| n }\nitems.each do |n| n end\n->(x) { x }\n";
        let tree = parser.parse(code, None).unwrap();
        assert!(!tree.root_node().has_error());

        let scope_idx = query
            .capture_names()
            .iter()
            .position(|n| *n == "local.scope")
            .expect("local.scope キャプチャが見つかりません");
        let mut cursor = tree_sitter::QueryCursor::new();
        let mut matches = cursor.matches(&query, tree.root_node(), code.as_bytes());
        let mut scope_kinds: Vec<String> = Vec::new();
        while let Some(m) = matches.next() {
            for c in m.captures {
                if c.index as usize == scope_idx {
                    scope_kinds.push(c.node.kind().to_string());
                }
            }
        }
        for expected in ["block", "do_block", "lambda"] {
            assert!(
                scope_kinds.iter().any(|k| k == expected),
                "{expected} が local.scope に含まれていません: {:?}",
                scope_kinds
            );
        }
    }

    #[test]
    fn test_can_parse_symbol_with_special_global_variable() {
        // scanner.c の scan_symbol_identifier で処理される
        // 特殊グローバル変数シンボルを構文エラーなくパースできることを検証
        let mut parser = tree_sitter::Parser::new();
        parser
            .set_language(&LANGUAGE.into())
            .expect("Error loading Ruby parser");
        let code = ":$\"\n:$;\n:$,\n:$$\n:$?\n:$:\n:$@\n:$.\n:$=\n";
        let tree = parser.parse(code, None).unwrap();
        assert!(
            !tree.root_node().has_error(),
            "特殊グローバル変数シンボルのパースに失敗しました"
        );
    }

    // locals.scm の @local.definition を captures から抽出するユーティリティ
    fn collect_local_definitions(code: &str) -> Vec<String> {
        let language: tree_sitter::Language = LANGUAGE.into();
        let mut parser = tree_sitter::Parser::new();
        parser.set_language(&language).unwrap();
        let query =
            tree_sitter::Query::new(&language, LOCALS_QUERY).expect("Error loading locals query");
        let tree = parser.parse(code, None).unwrap();
        assert!(
            !tree.root_node().has_error(),
            "コードのパースに失敗しました: {code}"
        );

        let def_idx = query
            .capture_names()
            .iter()
            .position(|n| *n == "local.definition")
            .expect("local.definition キャプチャが見つかりません");
        let mut cursor = tree_sitter::QueryCursor::new();
        let mut matches = cursor.matches(&query, tree.root_node(), code.as_bytes());
        let mut defs = Vec::new();
        while let Some(m) = matches.next() {
            for c in m.captures {
                if c.index as usize == def_idx {
                    defs.push(code[c.node.byte_range()].to_string());
                }
            }
        }
        defs
    }

    #[test]
    fn test_locals_query_captures_keyword_and_optional_parameters() {
        // keyword_parameter / optional_parameter の識別子が local.definition に捕捉されること
        let code = "def foo(a: 1, b: nil, c = 10)\n  a + b.to_s.size + c\nend\n";
        let defs = collect_local_definitions(code);
        for expected in ["a", "b", "c"] {
            assert!(
                defs.contains(&expected.to_string()),
                "{expected} が local.definition に含まれていません: {:?}",
                defs
            );
        }
    }

    #[test]
    fn test_locals_query_captures_splat_parameters() {
        // splat_parameter / hash_splat_parameter / block_parameter の
        // 識別子が local.definition に捕捉されること
        let code = "def foo(*args, **opts, &blk)\n  args\nend\n";
        let defs = collect_local_definitions(code);
        for expected in ["args", "opts", "blk"] {
            assert!(
                defs.contains(&expected.to_string()),
                "{expected} が local.definition に含まれていません: {:?}",
                defs
            );
        }
    }

    #[test]
    fn test_locals_query_captures_destructured_parameter() {
        // block パラメータの分解代入 (|a, (b, c)|) も local.definition として捕捉されること
        let code = "[[1, [2, 3]]].each { |a, (b, c)| a + b + c }\n";
        let defs = collect_local_definitions(code);
        for expected in ["a", "b", "c"] {
            assert!(
                defs.contains(&expected.to_string()),
                "{expected} が local.definition に含まれていません: {:?}",
                defs
            );
        }
    }

    #[test]
    fn test_can_parse_backslash_continuation_with_crlf() {
        // scanner.c の `\\` 行継続処理は CRLF 改行 (\r\n) 環境でも動作する必要がある。
        // `\\\r\n` で 2 行目に式が続く Ruby ソースを構文エラーなくパースできることを検証する。
        let mut parser = tree_sitter::Parser::new();
        parser
            .set_language(&LANGUAGE.into())
            .expect("Error loading Ruby parser");
        let code = "x = 1 + \\\r\n    2\r\n";
        let tree = parser.parse(code, None).unwrap();
        assert!(
            !tree.root_node().has_error(),
            "CRLF 改行でのバックスラッシュ行継続のパースに失敗しました"
        );
    }

    #[test]
    fn test_can_parse_leading_safe_navigation_continuation() {
        // 行頭の `&.`（safe navigation）は scanner.c の改行判定で行継続として扱われる。
        // ビット演算子 `&` 単独の場合と区別されることを検証する。
        let mut parser = tree_sitter::Parser::new();
        parser
            .set_language(&LANGUAGE.into())
            .expect("Error loading Ruby parser");
        let code = "foo\n  &.bar\n";
        let tree = parser.parse(code, None).unwrap();
        assert!(
            !tree.root_node().has_error(),
            "行頭 &. の改行継続パースに失敗しました"
        );
    }
}
