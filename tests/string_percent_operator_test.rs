use tree_sitter::{Parser, Tree};

fn parse(source: &str) -> Tree {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_ruby::LANGUAGE.into())
        .unwrap();
    parser.parse(source, None).unwrap()
}

#[test]
fn formatting_after_a_string_preserves_operators_and_array_elements() {
    let source = "puts \"%3d %s\"%[l+1, line]";
    let tree = parse(source);
    let root = tree.root_node();
    assert!(!root.has_error(), "{}", root.to_sexp());
    let argument = root
        .named_child(0)
        .unwrap()
        .child_by_field_name("arguments")
        .unwrap()
        .named_child(0)
        .unwrap();
    assert_eq!(argument.kind(), "binary", "{}", root.to_sexp());
    assert_eq!(
        argument.child_by_field_name("left").unwrap().kind(),
        "string"
    );
    let percent = argument.child_by_field_name("operator").unwrap();
    assert_eq!(percent.kind(), "%");
    assert_eq!(percent.byte_range(), 13..14);
    let array = argument.child_by_field_name("right").unwrap();
    assert_eq!(array.kind(), "array");
    assert_eq!(array.named_child_count(), 2);
    let addition = array.named_child(0).unwrap();
    assert_eq!(addition.kind(), "binary");
    let plus = addition.child_by_field_name("operator").unwrap();
    assert_eq!(plus.kind(), "+");
    assert_eq!(plus.byte_range(), 16..17);
}

#[test]
fn percent_after_strings_and_characters_is_a_binary_operator() {
    for left in [
        "\"a\"",
        "'a'",
        "%q[a]",
        "%Q[a]",
        "%[a]",
        "?a",
        "\"#{value}\"",
    ] {
        for whitespace in ["", " ", "\t", " \\\n"] {
            for right in [
                "[x]", "q[x]", "Q[x]", "r[x]", "s[x]", "w[x]", "W[x]", "i[x]", "I[x]", "x[x]",
                "(x)", "%q[x]",
            ] {
                let source = format!("{left}{whitespace}%{right}");
                let tree = parse(&source);
                let root = tree.root_node();
                assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
                let binary = root.named_child(0).unwrap();
                assert_eq!(binary.kind(), "binary", "{source:?}: {}", root.to_sexp());
                let percent = binary.child_by_field_name("operator").unwrap();
                assert_eq!(percent.kind(), "%", "{source:?}");
                assert_eq!(percent.start_byte(), left.len() + whitespace.len());
                assert_eq!(percent.end_byte(), percent.start_byte() + 1);
                assert_eq!(
                    binary.child_by_field_name("right").unwrap().kind(),
                    match right {
                        "[x]" => "array",
                        "(x)" => "parenthesized_statements",
                        "%q[x]" => "string",
                        _ => "element_reference",
                    },
                    "{source:?}"
                );
            }
        }
    }
}

#[test]
fn quoted_strings_still_concatenate_after_percent_strings_and_characters() {
    for source in [
        "%q[a] \"b\"",
        "%Q[a] 'b'",
        "%[a]\"b\"",
        "?a \"b\"",
        "\"a\" 'b' \"c\"",
        "puts %q[a] \"b\"",
    ] {
        let tree = parse(source);
        let root = tree.root_node();
        assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
        let mut expression = root.named_child(0).unwrap();
        if expression.kind() == "call" {
            expression = expression
                .child_by_field_name("arguments")
                .unwrap()
                .named_child(0)
                .unwrap();
        }
        assert_eq!(expression.kind(), "chained_string", "{source:?}");
        assert!(expression.named_child_count() >= 2, "{source:?}");
    }
}

#[test]
fn percent_literals_still_start_expressions_and_command_arguments() {
    for source in [
        "%q[a]",
        "puts %q[a]",
        "foo(%Q[a])",
        "[%(a), %q[b]]",
        "return %q[a]",
        "def m = puts %q[a]",
        "\"#{%q[a]}\"",
        "0..%q[a]",
    ] {
        let tree = parse(source);
        assert!(
            !tree.root_node().has_error(),
            "{source:?}: {}",
            tree.root_node().to_sexp()
        );
    }
}
