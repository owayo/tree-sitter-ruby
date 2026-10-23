use tree_sitter::{Parser, Tree};

fn parse(source: &str) -> Tree {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_ruby::LANGUAGE.into())
        .unwrap();
    parser.parse(source, None).unwrap()
}

#[test]
fn escaped_control_whitespace_is_part_of_the_character() {
    for control in ['\x0b', '\x0c'] {
        let source = format!("puts ?\\{control}\n");
        let tree = parse(&source);
        let root = tree.root_node();
        assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
        let character = root
            .named_child(0)
            .unwrap()
            .child_by_field_name("arguments")
            .unwrap()
            .named_child(0)
            .unwrap();
        assert_eq!(character.kind(), "character");
        assert_eq!(character.byte_range(), 5..8, "{source:?}");
        assert_eq!(
            character.utf8_text(source.as_bytes()).unwrap(),
            &source[5..8]
        );
    }
}

#[test]
fn percent_literals_keep_control_whitespace_delimiters() {
    for control in ['\x0b', '\x0c'] {
        for (prefix, kind) in [
            ("%", "string"),
            ("%q", "string"),
            ("%Q", "string"),
            ("%r", "regex"),
            ("%s", "delimited_symbol"),
            ("%x", "subshell"),
        ] {
            let source = format!("{prefix}{control}a b{control}\n");
            let tree = parse(&source);
            let root = tree.root_node();
            assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
            let literal = root.named_child(0).unwrap();
            assert_eq!(literal.kind(), kind, "{source:?}");
            assert_eq!(literal.byte_range(), 0..source.len() - 1, "{source:?}");
            let content = literal.named_child(0).unwrap();
            assert_eq!(content.kind(), "string_content");
            assert_eq!(content.utf8_text(source.as_bytes()).unwrap(), "a b");
        }
    }
}

#[test]
fn control_delimiters_close_empty_and_interpolated_literals() {
    for control in ['\x0b', '\x0c'] {
        for body in ["", "#{value}", "a\\DELIMb"] {
            let body = body.replace("DELIM", &control.to_string());
            let source = format!("puts %Q{control}{body}{control}; next_call");
            let tree = parse(&source);
            let root = tree.root_node();
            assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
            assert_eq!(root.named_child_count(), 2, "{source:?}");
            let literal = root
                .named_child(0)
                .unwrap()
                .child_by_field_name("arguments")
                .unwrap()
                .named_child(0)
                .unwrap();
            assert_eq!(literal.kind(), "string");
            assert_eq!(literal.byte_range(), 5..9 + body.len(), "{source:?}");
        }
        // 型のない `%` は識別子の後では剰余演算子になる。
        let source = format!("puts %{control}value");
        let tree = parse(&source);
        let root = tree.root_node();
        assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
        assert_eq!(root.named_child(0).unwrap().kind(), "binary");
    }
}

#[test]
fn control_whitespace_still_separates_array_words() {
    for control in ['\x0b', '\x0c'] {
        for prefix in ["%w", "%W", "%i", "%I"] {
            let source = format!("{prefix}[a{control}b]");
            let tree = parse(&source);
            let root = tree.root_node();
            assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
            let array = root.named_child(0).unwrap();
            assert_eq!(array.named_child_count(), 2, "{source:?}");
            for (index, expected) in ["a", "b"].into_iter().enumerate() {
                let word = array.named_child(index as u32).unwrap();
                assert_eq!(word.utf8_text(source.as_bytes()).unwrap(), expected);
            }

            let invalid = format!("{prefix}{control}a b{control}");
            assert!(parse(&invalid).root_node().has_error(), "{invalid:?}");
        }
    }
}
