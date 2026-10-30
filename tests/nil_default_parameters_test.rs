use tree_sitter::{Parser, Tree};

fn parse(source: &str) -> Tree {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_ruby::LANGUAGE.into())
        .unwrap();
    parser.parse(source, None).unwrap()
}

#[test]
fn nil_defaults_stay_in_individual_parameters() {
    let cases: &[(&str, &[&str])] = &[
        ("def m(a=nil, b=nil); end", &["a", "b"]),
        ("def m(a=nil, b=nil, c=nil); end", &["a", "b", "c"]),
        ("def self.m(a=nil, b=nil); end", &["a", "b"]),
        ("def self.m(一=nil, 二=nil); end", &["一", "二"]),
        ("def m(a=nil, b=nil) = a", &["a", "b"]),
        ("def m(a=nil, b=nil,); end", &["a", "b"]),
    ];
    for &(source, names) in cases {
        let tree = parse(source);
        let root = tree.root_node();
        assert!(!root.has_error(), "{source}: {}", root.to_sexp());
        let parameters = root
            .named_child(0)
            .unwrap()
            .child_by_field_name("parameters")
            .unwrap();
        let mut cursor = parameters.walk();
        let children: Vec<_> = parameters.named_children(&mut cursor).collect();
        assert_eq!(children.len(), names.len(), "{source}: {}", root.to_sexp());
        for (parameter, expected_name) in children.iter().zip(names) {
            assert_eq!(parameter.kind(), "optional_parameter");
            let name = parameter.child_by_field_name("name").unwrap();
            let value = parameter.child_by_field_name("value").unwrap();
            assert_eq!(name.utf8_text(source.as_bytes()).unwrap(), *expected_name);
            assert_eq!(value.kind(), "nil");
            assert_eq!(parameter.start_byte(), name.start_byte());
            assert_eq!(parameter.end_byte(), value.end_byte());
        }
    }
}

#[test]
fn parenthesized_assignment_remains_inside_its_default_value() {
    let source = "def m(a=(x,y=[1,2]), b=nil); end";
    let tree = parse(source);
    let root = tree.root_node();
    assert!(!root.has_error(), "{}", root.to_sexp());
    let parameters = root
        .named_child(0)
        .unwrap()
        .child_by_field_name("parameters")
        .unwrap();
    assert_eq!(parameters.named_child_count(), 2);
    let first = parameters.named_child(0).unwrap();
    let value = first.child_by_field_name("value").unwrap();
    assert_eq!(value.kind(), "parenthesized_statements");
    assert_eq!(value.utf8_text(source.as_bytes()).unwrap(), "(x,y=[1,2])");
    let assignment = value.named_child(0).unwrap();
    assert_eq!(assignment.kind(), "assignment");
    assert_eq!(
        assignment.child_by_field_name("left").unwrap().kind(),
        "left_assignment_list"
    );
    assert_eq!(
        assignment.child_by_field_name("right").unwrap().kind(),
        "array"
    );
    let second = parameters.named_child(1).unwrap();
    assert_eq!(
        second
            .child_by_field_name("name")
            .unwrap()
            .utf8_text(source.as_bytes())
            .unwrap(),
        "b"
    );
    assert_eq!(second.child_by_field_name("value").unwrap().kind(), "nil");
}
