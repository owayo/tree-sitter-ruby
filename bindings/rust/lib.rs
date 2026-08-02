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
        let code = "def foo; end\n";
        let keywords = collect_highlight_captures(code, "keyword");
        for expected in ["def", "end"] {
            assert!(
                keywords.contains(&expected.to_string()),
                "{expected} が keyword に含まれていません: {:?}",
                keywords
            );
        }
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

    // highlights.scm の指定 capture をテキストとして抽出するユーティリティ
    fn collect_highlight_captures(code: &str, capture_name: &str) -> Vec<String> {
        let language: tree_sitter::Language = LANGUAGE.into();
        let mut parser = tree_sitter::Parser::new();
        parser.set_language(&language).unwrap();
        let query = tree_sitter::Query::new(&language, HIGHLIGHTS_QUERY)
            .expect("Error loading highlights query");
        let tree = parser.parse(code, None).unwrap();
        assert!(
            !tree.root_node().has_error(),
            "コードのパースに失敗しました: {code}"
        );

        let capture_idx = query
            .capture_names()
            .iter()
            .position(|n| *n == capture_name)
            .unwrap_or_else(|| panic!("{capture_name} キャプチャが見つかりません"));
        let mut cursor = tree_sitter::QueryCursor::new();
        let mut matches = cursor.matches(&query, tree.root_node(), code.as_bytes());
        let mut texts = Vec::new();
        while let Some(m) = matches.next() {
            for c in m.captures {
                if c.index as usize == capture_idx {
                    texts.push(code[c.node.byte_range()].to_string());
                }
            }
        }
        texts
    }

    fn parse_has_error(code: &str) -> bool {
        let mut parser = tree_sitter::Parser::new();
        parser
            .set_language(&LANGUAGE.into())
            .expect("Error loading Ruby parser");
        parser.parse(code, None).unwrap().root_node().has_error()
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

    #[test]
    fn test_scanner_handles_heredoc_boundaries() {
        // 終端語がファイル末尾にあり最後の改行がなくても heredoc_end として扱う。
        assert!(!parse_has_error("x = <<EOF\nbody\nEOF"));

        // quoted な空終端語は Ruby で有効。空行が heredoc_end になる。
        assert!(!parse_has_error("x = <<\"\"\n\n"));
        assert!(!parse_has_error("x = <<''\n\n"));

        // 終端語なし EOF や閉じ quote のない heredoc 開始は受理しない。
        for code in [
            "x = <<EOF\nbody",
            "x = <<\"EOF\nbody\nEOF\n",
            "x = <<'EOF\nbody\nEOF\n",
            "x = <<`EOF\nbody\nEOF\n",
        ] {
            assert!(
                parse_has_error(code),
                "不正な heredoc を受理しています: {code:?}"
            );
        }
    }

    #[test]
    fn test_scanner_accepts_unicode_heredoc_delimiters() {
        // scanner は終端語を UTF-8 バイト列として保持し、Unicode code point と
        // 比較する。下位 8 bit の衝突を含む非引用・引用終端語を検証する。
        for code in [
            "x = <<終端\n本文\n終端\n",
            "x = <<Ĩ\nbody\nĨ\n",
            "x = <<\"終 端\"\n本文\n終 端\n",
        ] {
            assert!(
                !parse_has_error(code),
                "Unicode heredoc 終端語をパースできません: {code:?}"
            );
        }
    }

    #[test]
    fn test_unicode_global_variable_short_interpolation() {
        let code = "$名前 = 42\nfirst = \"#$名前\"\nsecond = \"#$-名\"\n";
        let language: tree_sitter::Language = LANGUAGE.into();
        let mut parser = tree_sitter::Parser::new();
        parser.set_language(&language).unwrap();
        let tree = parser.parse(code, None).unwrap();
        assert!(
            !tree.root_node().has_error(),
            "Unicode グローバル変数のパースに失敗しました"
        );

        let query = tree_sitter::Query::new(
            &language,
            "(interpolation (global_variable) @global_variable)",
        )
        .expect("Unicode グローバル変数の interpolation クエリを作成できません");
        let mut cursor = tree_sitter::QueryCursor::new();
        let mut matches = cursor.matches(&query, tree.root_node(), code.as_bytes());
        let mut globals = Vec::new();
        while let Some(query_match) = matches.next() {
            for capture in query_match.captures {
                globals.push(&code[capture.node.byte_range()]);
            }
        }
        assert_eq!(globals, vec!["$名前", "$-名"]);
    }

    #[test]
    fn test_scanner_preserves_deep_literal_nesting_across_interpolation() {
        // literal_stack の nesting_depth は 256 を超えてもシリアライズで失われない。
        let depth = 260;
        let code = format!(
            "x = %Q{{{}#{{value}}{}}}",
            "{".repeat(depth),
            "}".repeat(depth)
        );
        assert!(
            !parse_has_error(&code),
            "深いネストを含む percent literal のパースに失敗しました"
        );
    }

    #[test]
    fn test_scanner_rejects_oversized_heredoc_delimiter() {
        // シリアライズ不能な長すぎる終端語は状態喪失による誤パースではなく ERROR にする。
        let word = "A".repeat(1100);
        let code = format!("x = <<{word}\nbody\n{word}\n");
        assert!(
            parse_has_error(&code),
            "長すぎる heredoc 終端語を誤って受理しています"
        );
    }

    #[test]
    fn test_scanner_accepts_exact_serialization_buffer_heredoc_delimiter() {
        // heredoc 1 件のシリアライズサイズは count 2 バイト + ヘッダー 7 バイト + 終端語本体。
        // 1015 文字なら 1024 バイト上限ぴったりに収まるため、拒否してはいけない。
        let fitting_word = "A".repeat(1015);
        let fitting_code = format!("x = <<{fitting_word}\nbody\n{fitting_word}\n");
        assert!(
            !parse_has_error(&fitting_code),
            "シリアライズ上限ぴったりの heredoc 終端語を拒否しています"
        );

        let oversized_word = "A".repeat(1016);
        let oversized_code = format!("x = <<{oversized_word}\nbody\n{oversized_word}\n");
        assert!(
            parse_has_error(&oversized_code),
            "シリアライズ上限を超える heredoc 終端語を誤って受理しています"
        );
    }

    #[test]
    fn test_scanner_symbol_regex_and_percent_equal_boundaries() {
        assert!(!parse_has_error(":foo=\n:Foo=\n:[]=\n/a/i\n"));
        assert!(!parse_has_error("x = %=abc=\nx %= 1\n"));

        for code in [
            ":foo?=",
            ":foo!=",
            ":+=",
            ":%=",
            ":..",
            "def ..; end",
            "undef ..",
            "/a/z",
        ] {
            assert!(
                parse_has_error(code),
                "Ruby と異なる不正構文を受理しています: {code}"
            );
        }
    }

    #[test]
    fn test_scanner_regex_option_at_eof_does_not_hang() {
        // scanner.c の scan_literal_content で正規表現オプション（imxouesn）を
        // 読む while ループは、lexer->lookahead == 0（EOF）のとき strchr が
        // 終端の NUL に一致して非 NULL を返すため、ファイル末尾で改行なく終わる
        // 正規表現で無限ループしていた。`lexer->lookahead != 0` 追加で防止する。
        // 無限ループが再発した場合、このテストはタイムアウトでハングする。
        for code in ["a = /x/", "b = /foo/i", "c = %r{baz}", "d = /q/im"] {
            assert!(
                !parse_has_error(code),
                "EOF 直後で終わる正規表現のパースに失敗しました: {code:?}"
            );
        }
    }

    #[test]
    fn test_scanner_accepts_non_ascii_unicode_identifier_symbols() {
        // is_iden_char に Unicode コードポイント（>= 0x80）が char に切り詰められて
        // 渡されると、例えば `:Ĩ` (U+0128) は下位 8 bit が `(` (0x28) と衝突して
        // NON_IDENTIFIER_CHARS と誤一致し、symbol が ERROR でパースされてしまう
        // 回帰を防ぐ。Ruby は識別子に Unicode 文字を許容する。
        for code in [":Ĩ\n", ":Ñ_test\n", ":λ_func\n", ":π_value\n", ":漢字\n"] {
            assert!(
                !parse_has_error(code),
                "Unicode 識別子 symbol のパースに失敗しています: {code:?}"
            );
        }
    }

    #[test]
    fn test_scanner_short_interpolation_ignores_non_ascii_unicode_chars() {
        // scanner.c の scan_short_interpolation で `lexer->lookahead` を `char` に
        // 切り詰めると、ASCII 範囲外で下位 8 bit が '@' (0x40) や '$' (0x24) と
        // 一致する Unicode 文字（例: `Ĥ` U+0124 → 0x24, `Ŀ` U+0140 → 0x40）が
        // 短縮 interpolation の起点として誤判定され、文字列が ERROR でパースされる
        // 回帰を防ぐ。`int32_t` のまま比較することで Unicode 文字を区別する。
        for code in ["\"#Ĥ\"\n", "\"#Ŀ\"\n", "\"#漢\"\n", "\"#Ą#Ɓ\"\n"] {
            assert!(
                !parse_has_error(code),
                "Unicode 文字を含む文字列のパースに失敗しています: {code:?}"
            );
        }
    }

    #[test]
    fn test_highlights_query_captures_operators_and_global_variables() {
        let code = "a == b\nx += 1\nrange = 1..2\nif $0\nend\n";
        let operators = collect_highlight_captures(code, "operator");
        for expected in ["==", "+=", "=", ".."] {
            assert!(
                operators.contains(&expected.to_string()),
                "{expected} が operator に含まれていません: {:?}",
                operators
            );
        }

        let globals = collect_highlight_captures(code, "variable.builtin");
        assert!(
            globals.contains(&"$0".to_string()),
            "$0 が variable.builtin に含まれていません: {:?}",
            globals
        );
    }

    #[test]
    fn test_locals_query_captures_pattern_match_bindings() {
        // case/in パターンの通常束縛は、参照ではなく local.definition として扱う。
        let code = "case value\nin target\n  target\nin [x, y]\n  x\nin {a: z, b:}\n  z\nend\n";
        let defs = collect_local_definitions(code);
        for expected in ["target", "x", "y", "z", "b"] {
            assert!(
                defs.contains(&expected.to_string()),
                "{expected} が local.definition に含まれていません: {:?}",
                defs
            );
        }
    }

    #[test]
    fn test_locals_query_captures_exception_variable() {
        // rescue Error => e の e は rescue 節内で束縛されるローカル変数。
        let code = "begin\n  work\nrescue Error => e\n  e\nend\n";
        let defs = collect_local_definitions(code);
        assert!(
            defs.contains(&"e".to_string()),
            "rescue 例外変数 e が local.definition に含まれていません: {:?}",
            defs
        );
    }

    #[test]
    fn test_can_parse_ruby_34_it_block_parameter() {
        // Ruby 3.4 で導入された暗黙のブロックパラメータ `it` が、
        // パイプ仮引数なしのブロック内で識別子として正しく扱えることを検証する。
        for code in [
            "[1, 2, 3].each { it * 2 }\n",
            "[1, 2, 3].map { it + 1 }\n",
            "[1, 2, 3].select { it > 1 }\n",
            "{a: 1, b: 2}.map { it.first }\n",
        ] {
            assert!(
                !parse_has_error(code),
                "Ruby 3.4 の it ブロックパラメータのパースに失敗しました: {code:?}"
            );
        }
    }

    #[test]
    fn test_can_parse_ruby_34_index_assignment_restrictions() {
        // Ruby 3.4 では index assignment に keyword 引数 / block 引数を渡せない。
        for code in ["arr[1, key: 2] = 3\n", "arr[1, &block] = 3\n"] {
            assert!(
                parse_has_error(code),
                "Ruby 3.4 で禁止された index assignment が誤って受理されました: {code:?}"
            );
        }
    }

    #[test]
    fn test_can_parse_ruby_40_splat_nil() {
        // Ruby 4.0 では `*nil` が `nil.to_a` を呼ばず、splat 展開 0 件として扱える。
        let code = "def bar(*args); args; end\nbar(*nil)\n";
        assert!(
            !parse_has_error(code),
            "Ruby 4.0 の *nil splat のパースに失敗しました"
        );
    }

    #[test]
    fn test_can_parse_ruby_40_leading_logical_operator_continuation() {
        // Ruby 4.0 では行頭の論理演算子（`||`, `&&`, `and`, `or`）が
        // 前行の継続として扱われる（fluent dot と同じ振る舞い）。
        for code in [
            "result = condition1\n  || condition2\n  || condition3\n",
            "result = condition1\n  && condition2\n",
            "result = a\n  or b\n",
            "result = a\n  and b\n",
            "if condition1\n  or condition2\nend\n",
            "if condition1\n  and condition2\nend\n",
        ] {
            assert!(
                !parse_has_error(code),
                "行頭論理演算子による継続のパースに失敗しました: {code:?}"
            );
        }
    }
}
