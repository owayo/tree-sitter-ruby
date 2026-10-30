use tree_sitter::{InputEdit, Parser, Point};

fn parser() -> Parser {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_ruby::LANGUAGE.into())
        .unwrap();
    parser
}

fn snapshot(tree: &tree_sitter::Tree) -> Vec<String> {
    let mut result = Vec::new();
    let mut cursor = tree.walk();
    loop {
        let node = cursor.node();
        result.push(format!(
            "{}|{:?}|{:?}|{}|{}|{}",
            node.kind(),
            cursor.field_name(),
            node.range(),
            node.is_named(),
            node.is_extra(),
            node.child_count()
        ));
        if cursor.goto_first_child() {
            continue;
        }
        loop {
            if cursor.goto_next_sibling() {
                break;
            }
            if !cursor.goto_parent() {
                return result;
            }
        }
    }
}

#[test]
fn method_parameter_trailing_commas_preserve_fields_and_ranges() {
    for source in [
        "def m(a,); a; end",
        "def self.m(a,)\n a\nend",
        "def m(a,) = a",
        "def m(a=1,); end",
        "def m(*,); end",
        "def m(*args,); end",
        "def m(a:,); end",
        "def m(a: 1,); end",
        "def m(**,); end",
        "def m(**kwargs,); end",
        "def m(**nil,); end",
        "def m((a,b),); end",
        "def m(a, b=1, *rest, key:, **options,); end",
        "def m(\r\n a, # 最後の仮引数\r\n); end",
    ] {
        let tree = parser().parse(source, None).unwrap();
        let root = tree.root_node();
        assert!(!root.has_error(), "{source}: {}", root.to_sexp());
        let method = root.named_child(0).unwrap();
        let parameters = method.child_by_field_name("parameters").unwrap();
        assert_eq!(parameters.kind(), "method_parameters");
        assert_eq!(parameters.start_byte(), source.find('(').unwrap());
        assert_eq!(parameters.end_byte(), source.rfind(')').unwrap() + 1);
        assert!(parameters.named_child_count() > 0);
        assert_eq!(
            method.child_by_field_name("name").unwrap().kind(),
            "identifier"
        );
    }
}

#[test]
fn optional_parameters_remain_separate_with_and_without_trailing_commas() {
    for (source, expected_count) in [
        ("def m(a=false, b={}, &block); end", 3),
        ("def m(a=false, b={}); end", 2),
        ("def m(a=false, b={},); end", 2),
    ] {
        let tree = parser().parse(source, None).unwrap();
        let root = tree.root_node();
        assert!(!root.has_error(), "{source}: {}", root.to_sexp());
        let parameters = root
            .named_child(0)
            .unwrap()
            .child_by_field_name("parameters")
            .unwrap();
        assert_eq!(parameters.named_child_count(), expected_count, "{source}");
        for (index, name) in [(0, "a"), (1, "b")] {
            let parameter = parameters.named_child(index).unwrap();
            assert_eq!(parameter.kind(), "optional_parameter");
            assert_eq!(
                parameter
                    .child_by_field_name("name")
                    .unwrap()
                    .utf8_text(source.as_bytes())
                    .unwrap(),
                name
            );
        }
    }
}

#[test]
fn trailing_commas_do_not_extend_other_parameter_forms() {
    for source in [
        "def m(,); end",
        "def m(a,,); end",
        "def m((a,)); end",
        "def m((a,b,)); end",
        "def m(&,); end",
        "def m(&block,); end",
        "def m(&nil,); end",
        "def m(...,); end",
        "->(a,) {}",
        "def m a,\nend",
    ] {
        let tree = parser().parse(source, None).unwrap();
        assert!(tree.root_node().has_error(), "{source}");
    }
}

#[test]
fn adding_and_removing_a_trailing_comma_matches_fresh_parsing() {
    let source = "def m(a)\r\n a\r\nend";
    let edited = "def m(a,)\r\n a\r\nend";
    let mut parser = parser();
    let mut tree = parser.parse(source, None).unwrap();
    let offset = source.find(')').unwrap();
    tree.edit(&InputEdit {
        start_byte: offset,
        old_end_byte: offset,
        new_end_byte: offset + 1,
        start_position: Point::new(0, offset),
        old_end_position: Point::new(0, offset),
        new_end_position: Point::new(0, offset + 1),
    });
    let incremental = parser.parse(edited, Some(&tree)).unwrap();
    let fresh = parser.parse(edited, None).unwrap();
    assert!(!incremental.root_node().has_error());
    assert_eq!(snapshot(&incremental), snapshot(&fresh));
    let mut tree = incremental;
    tree.edit(&InputEdit {
        start_byte: offset,
        old_end_byte: offset + 1,
        new_end_byte: offset,
        start_position: Point::new(0, offset),
        old_end_position: Point::new(0, offset + 1),
        new_end_position: Point::new(0, offset),
    });
    let incremental = parser.parse(source, Some(&tree)).unwrap();
    let fresh = parser.parse(source, None).unwrap();
    assert!(!incremental.root_node().has_error());
    assert_eq!(snapshot(&incremental), snapshot(&fresh));
}
