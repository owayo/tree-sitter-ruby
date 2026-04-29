use tree_sitter::StreamingIterator;
use tree_sitter_ruby::{LANGUAGE, TAGS_QUERY};

fn collect_tag_names(code: &str, capture_name: &str) -> Vec<String> {
    let language: tree_sitter::Language = LANGUAGE.into();
    let mut parser = tree_sitter::Parser::new();
    parser
        .set_language(&language)
        .expect("Ruby パーサーを読み込めません");

    let query =
        tree_sitter::Query::new(&language, TAGS_QUERY).expect("tags クエリを読み込めません");
    let tree = parser.parse(code, None).expect("構文木を生成できません");
    assert!(
        !tree.root_node().has_error(),
        "入力コードに構文エラーがあります"
    );

    let name_idx = query
        .capture_names()
        .iter()
        .position(|name| *name == "name")
        .expect("name キャプチャが見つかりません");
    let target_idx = query
        .capture_names()
        .iter()
        .position(|name| *name == capture_name)
        .unwrap_or_else(|| panic!("{capture_name} キャプチャが見つかりません"));

    let mut cursor = tree_sitter::QueryCursor::new();
    let mut matches = cursor.matches(&query, tree.root_node(), code.as_bytes());
    let mut names = Vec::new();
    while let Some(query_match) = matches.next() {
        if !query_match
            .captures
            .iter()
            .any(|capture| capture.index as usize == target_idx)
        {
            continue;
        }

        // タグ対象と同じマッチに含まれる name キャプチャだけを集める。
        for capture in query_match.captures {
            if capture.index as usize == name_idx {
                names.push(code[capture.node.byte_range()].to_string());
            }
        }
    }

    names
}

#[test]
fn test_tags_query_filters_builtin_calls() {
    let code = r#"
def boot_require
  require "json"
  require_relative "lib/helper"
  load "seed.rb"
  lambda { helper }
end
"#;

    let reference_calls = collect_tag_names(code, "reference.call");

    assert!(
        reference_calls.contains(&"helper".to_string()),
        "通常の呼び出し helper がタグ参照に含まれていません: {:?}",
        reference_calls
    );
    for builtin in ["require", "require_relative", "load", "lambda"] {
        assert!(
            !reference_calls.iter().any(|name| name == builtin),
            "組み込み擬似メソッド {builtin} がタグ参照に含まれています: {:?}",
            reference_calls
        );
    }
}

#[test]
fn test_tags_query_filters_pseudo_constants() {
    // __FILE__ / __LINE__ / __ENCODING__ は擬似定数で、メソッド呼び出しでは
    // ないため reference.call に含めない。highlights.scm の取り扱いと
    // 一致させるため、tags クエリ側でもまとめて除外する。
    let code = r#"
def report_origin
  puts __FILE__
  puts __LINE__
  puts __ENCODING__
end
"#;

    let reference_calls = collect_tag_names(code, "reference.call");

    for builtin in ["__FILE__", "__LINE__", "__ENCODING__"] {
        assert!(
            !reference_calls.iter().any(|name| name == builtin),
            "擬似定数 {builtin} がタグ参照に含まれています: {:?}",
            reference_calls
        );
    }
}

#[test]
fn test_tags_query_captures_nested_definitions() {
    let code = r#"
module Admin::Feature
  class Core::Worker
    STATUS = "ok"
    LIMIT = 10
  end
end
"#;

    let module_defs = collect_tag_names(code, "definition.module");
    let class_defs = collect_tag_names(code, "definition.class");
    let constant_defs = collect_tag_names(code, "definition.constant");

    assert_eq!(module_defs, vec!["Feature"], "モジュール定義タグが不正です");
    assert_eq!(class_defs, vec!["Worker"], "クラス定義タグが不正です");
    assert_eq!(
        constant_defs,
        vec!["STATUS", "LIMIT"],
        "定数定義タグが不正です"
    );
}

#[test]
fn test_tags_query_captures_method_definitions() {
    let code = r#"
class Example
  def instance_method
    :ok
  end

  def self.singleton_method
    :ok
  end

  alias short_name instance_method
end
"#;

    let method_defs = collect_tag_names(code, "definition.method");

    for expected in ["instance_method", "singleton_method", "short_name"] {
        assert!(
            method_defs.iter().any(|name| name == expected),
            "{expected} が definition.method に含まれていません: {:?}",
            method_defs
        );
    }
}
