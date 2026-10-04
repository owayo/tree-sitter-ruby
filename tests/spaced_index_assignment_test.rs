use tree_sitter_ruby::LANGUAGE;

fn parse_source(code: &str) -> tree_sitter::Tree {
    let mut parser = tree_sitter::Parser::new();
    parser.set_language(&LANGUAGE.into()).unwrap();
    let tree = parser.parse(code, None).unwrap();
    assert!(
        !tree.root_node().has_error(),
        "Unexpected parse error: {code:?}\n{}",
        tree.root_node().to_sexp()
    );
    tree
}

fn assert_index_assignment(node: tree_sitter::Node, code: &str, kind: &str, gap: &str) {
    assert_eq!(node.kind(), kind);
    let left = node.child_by_field_name("left").unwrap();
    assert_eq!(left.kind(), "element_reference");
    let object = left.child_by_field_name("object").unwrap();
    assert_eq!(object.kind(), "identifier");
    assert_eq!(&code[object.byte_range()], "v");
    let mut cursor = left.walk();
    let bracket = left
        .children(&mut cursor)
        .find(|child| child.kind() == "[")
        .unwrap();
    assert_eq!(&code[object.end_byte()..bracket.start_byte()], gap);
}

#[test]
fn known_limitation_spaced_assignment_does_not_resolve_local_bindings() {
    // Ruby rejects the unbound and later-bound forms. This test documents the
    // permissive syntax tree, not Ruby validity; revisit it if binding resolution
    // becomes part of the parser.
    for (operator, kind) in [("=", "assignment"), ("+=", "operator_assignment")] {
        let bare_code = format!("v [0] {operator} 1\n");
        let bare_tree = parse_source(&bare_code);
        let bare_node = bare_tree.root_node().named_child(0).unwrap();
        assert_index_assignment(bare_node, &bare_code, kind, " ");

        for (prefix, suffix, index) in [
            ("v = []\n", "", 1),
            ("v = [] if false\n", "", 1),
            ("", "v = []\n", 0),
        ] {
            let code = format!("{prefix}{bare_code}{suffix}");
            let tree = parse_source(&code);
            let node = tree.root_node().named_child(index).unwrap();
            assert_index_assignment(node, &code, kind, " ");
            assert_eq!(node.to_sexp(), bare_node.to_sexp());
        }

        let unspaced_code = format!("v[0] {operator} 1\n");
        let unspaced_tree = parse_source(&unspaced_code);
        let unspaced_node = unspaced_tree.root_node().named_child(0).unwrap();
        assert_index_assignment(unspaced_node, &unspaced_code, kind, "");
        assert_eq!(unspaced_node.to_sexp(), bare_node.to_sexp());
    }
}

#[test]
fn known_limitation_spaced_assignment_does_not_resolve_method_scope() {
    for (operator, kind) in [("=", "assignment"), ("+=", "operator_assignment")] {
        for (prefix, parameters, index) in [("", "(v)", 0), ("v = []\n", "", 1)] {
            // A parameter binds v, but an outer assignment is invisible inside
            // a Ruby method. Both currently yield the same assignment structure.
            let code = format!("{prefix}def update{parameters}\n  v [0] {operator} 1\nend\n");
            let tree = parse_source(&code);
            let method = tree.root_node().named_child(index).unwrap();
            let body = method.child_by_field_name("body").unwrap();
            assert_index_assignment(body.named_child(0).unwrap(), &code, kind, " ");
        }
    }
}

#[test]
fn spaced_array_argument_remains_a_method_call() {
    let code = "v [0]\n";
    let tree = parse_source(code);
    let call = tree.root_node().named_child(0).unwrap();
    assert_eq!(call.kind(), "call");
    let method = call.child_by_field_name("method").unwrap();
    assert_eq!(&code[method.byte_range()], "v");
    let arguments = call.child_by_field_name("arguments").unwrap();
    assert_eq!(arguments.kind(), "argument_list");
    let array = arguments.named_child(0).unwrap();
    assert_eq!(array.kind(), "array");
    assert_eq!(&code[array.byte_range()], "[0]");
}
