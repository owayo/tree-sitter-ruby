use tree_sitter::{Node, Parser, Tree};

fn parse(source: &str) -> Tree {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_ruby::LANGUAGE.into())
        .unwrap();
    parser.parse(source, None).unwrap()
}

fn count_characters(node: Node) -> usize {
    let mut cursor = node.walk();
    usize::from(node.kind() == "character")
        + node
            .children(&mut cursor)
            .map(count_characters)
            .sum::<usize>()
}

#[test]
fn control_and_meta_escapes_preserve_the_entire_character() {
    for prefix in [
        r"\C-", r"\c", r"\M-", r"\C-\M-", r"\M-\C-", r"\c\M-", r"\M-\c",
    ] {
        for operand in [
            "A", "?", r"\x4", r"\x43", r"\1", r"\10", r"\103", r"\n", r"\\", r"\8", " ", "\t",
            "\x0b", "\x0c", "\n", "\r",
        ] {
            let source = format!("?{prefix}{operand}");
            let tree = parse(&source);
            let root = tree.root_node();
            assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
            assert_eq!(root.named_child_count(), 1, "{source:?}");
            let character = root.named_child(0).unwrap();
            assert_eq!(character.kind(), "character", "{source:?}");
            assert_eq!(character.byte_range(), 0..source.len(), "{source:?}");
        }
    }
}

#[test]
fn malformed_control_and_meta_escapes_do_not_form_shorter_characters() {
    for source in [
        r"?\C-",
        r"?\c",
        r"?\M-",
        r"?\C",
        r"?\M",
        r"?\C-\x",
        r"?\M-\xG",
        r"?\c\x",
        r"?\C-\C-A",
        r"?\C-\cA",
        r"?\c\C-A",
        r"?\c\cA",
        r"?\M-\M-A",
        r"?\M-\C-\M-A",
        r"?\C-\M-\cA",
        r"?\C-\u0041",
        r"?\M-\u{41}",
        "?\\C-é",
        "?\\M-\\é",
        "?\\C-\x01",
        "?\\M-\x7f",
    ] {
        let tree = parse(source);
        let root = tree.root_node();
        assert!(root.has_error(), "{source:?}: {}", root.to_sexp());
        assert_eq!(count_characters(root), 0, "{source:?}: {}", root.to_sexp());
    }
}

#[test]
fn static_regexp_interpolation_keeps_character_and_following_content() {
    for character_source in [r"?\C-\x43", r"?\M-\c\103", r"?\c\M-\x43"] {
        let source = format!("/#{{{character_source}}}(?<y>.)/ =~ \"\\x03b\"");
        let tree = parse(&source);
        let root = tree.root_node();
        assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
        let regex = root
            .named_child(0)
            .unwrap()
            .child_by_field_name("left")
            .unwrap();
        assert_eq!(regex.kind(), "regex");
        let interpolation = regex.named_child(0).unwrap();
        assert_eq!(interpolation.kind(), "interpolation");
        let character = interpolation.named_child(0).unwrap();
        assert_eq!(character.kind(), "character");
        assert_eq!(character.byte_range(), 3..3 + character_source.len());
        assert_eq!(
            character.utf8_text(source.as_bytes()).unwrap(),
            character_source
        );
        let content = regex.named_child(1).unwrap();
        assert_eq!(content.kind(), "string_content");
        assert_eq!(content.utf8_text(source.as_bytes()).unwrap(), "(?<y>.)");
    }
}

#[test]
fn character_escape_boundaries_leave_method_calls_outside_the_token() {
    for character_source in [
        r"?\x43",
        r"?\103",
        r"?\a",
        r"?\u0041",
        r"?\u{41}",
        r"?\C-\x43",
        r"?\M-\C-\103",
        "?é",
        "?\\é",
    ] {
        let source = format!("{character_source}.ord");
        let tree = parse(&source);
        let root = tree.root_node();
        assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
        let character = root
            .named_child(0)
            .unwrap()
            .child_by_field_name("receiver")
            .unwrap();
        assert_eq!(character.kind(), "character");
        assert_eq!(
            character.byte_range(),
            0..character_source.len(),
            "{source:?}"
        );
    }
}
