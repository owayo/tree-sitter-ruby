#[path = "../bindings/rust/build_support.rs"]
mod build_support;

use build_support::optimized_parser_source;

#[test]
fn removes_known_msvc_clang_and_gcc_optimization_pragmas() {
    for pragma in [
        "#pragma optimize(\"\", off)",
        "#pragma clang optimize off",
        "#pragma GCC optimize (\"O0\")",
        "#pragma GCC optimize (\"O0\", \"jump-tables\")",
    ] {
        let source = format!("before\n  {pragma}\t\nafter\n");
        assert_eq!(optimized_parser_source(&source), "before\nafter\n");
        assert_eq!(optimized_parser_source(pragma), "");
    }
}

#[test]
fn preserves_other_pragmas_and_nonmatching_lines() {
    let source = concat!(
        "#pragma GCC diagnostic ignored \"-Wmissing-field-initializers\"\n",
        "#pragma GCC optimize (\"O2\")\n",
        "#pragma clang optimize on\n",
        "#pragma optimize(\"\", on)\n",
        "#pragma GCC optimize (\"O0\", \"no-jump-tables\")\n",
        "#pragma GCC optimize (\"O0\") // keep this distinct directive\n",
        "// #pragma clang optimize off\n",
        "const char *example = \"#pragma clang optimize off\";\n",
    );
    assert_eq!(optimized_parser_source(source), source);
}

#[test]
fn preserves_crlf_non_ascii_and_surrounding_whitespace() {
    let source = concat!(
        "  // 日本語のコメント\r\n",
        "\t#pragma clang optimize off \r\n",
        "\r\n",
        "  int 値 = 1;\t\r\n",
    );
    let expected = "  // 日本語のコメント\r\n\r\n  int 値 = 1;\t\r\n";
    assert_eq!(optimized_parser_source(source), expected);
}

#[test]
fn preserves_a_missing_final_newline() {
    let source = "#pragma GCC optimize (\"O0\")\nint value = 1;";
    assert_eq!(optimized_parser_source(source), "int value = 1;");
    assert_eq!(optimized_parser_source("int value = 1;"), "int value = 1;");
}

#[test]
fn preserves_empty_input_and_blank_lines() {
    for source in ["", "\n", "\r\n", " \t\r\n\n"] {
        assert_eq!(optimized_parser_source(source), source);
    }
}

#[test]
fn generated_parser_changes_only_known_optimization_pragmas() {
    let source = include_str!("../src/parser.c");
    let optimized = optimized_parser_source(source);
    let mut expected = source.to_owned();
    let mut removed = 0;

    for pragma in [
        "#pragma optimize(\"\", off)",
        "#pragma clang optimize off",
        "#pragma GCC optimize (\"O0\")",
        "#pragma GCC optimize (\"O0\", \"jump-tables\")",
    ] {
        for newline in ["\r\n", "\n"] {
            let line = format!("{pragma}{newline}");
            removed += expected.matches(&line).count();
            expected = expected.replace(&line, "");
        }
        assert!(!optimized.lines().any(|line| line.trim() == pragma));
    }

    assert_eq!(
        removed, 3,
        "the generated parser must exercise all compilers"
    );
    assert_eq!(optimized, expected);
    assert!(optimized.contains("#pragma GCC diagnostic ignored"));
}
