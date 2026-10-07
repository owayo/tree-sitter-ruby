use tree_sitter::Parser;

fn parse(source: &str) -> tree_sitter::Tree {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_ruby::LANGUAGE.into())
        .unwrap();
    parser.parse(source, None).unwrap()
}

#[test]
fn command_chains_preserve_arguments_and_blocks() {
    for source in [
        "1.upto 0 do end.foo(1, 2)",
        "1.upto 0 do end&.foo do end",
        "1.upto 0 do end.foo 1 do end",
        "1.upto 0 do end.foo(1) {}",
        "1.upto 0 do end.foo(1).bar",
        "1.upto 0 do end.foo do end.bar",
        "1.upto 0 do end.foo 1 do end.bar",
    ] {
        let tree = parse(source);
        let root = tree.root_node();
        assert!(!root.has_error(), "{source}: {}", root.to_sexp());
        let call = root.named_child(0).unwrap();
        assert_eq!(call.kind(), "call");
        let method = call.child_by_field_name("method").unwrap();
        assert_eq!(
            method.utf8_text(source.as_bytes()).unwrap(),
            if source.ends_with(".bar") {
                "bar"
            } else {
                "foo"
            },
            "{source}: {}",
            root.to_sexp()
        );
        let receiver = call.child_by_field_name("receiver").unwrap();
        assert_eq!(receiver.kind(), "call");
        let mut cursor = call.walk();
        assert_eq!(
            call.children_by_field_name("method", &mut cursor).count(),
            1
        );
        if source.ends_with(".bar") {
            assert_eq!(
                receiver
                    .child_by_field_name("method")
                    .unwrap()
                    .utf8_text(source.as_bytes())
                    .unwrap(),
                "foo"
            );
        }
        assert!(receiver.child_by_field_name("block").is_some() || source.ends_with(".bar"));
        if source.ends_with("do end") || source.ends_with("{}") {
            assert!(call.child_by_field_name("block").is_some(), "{source}");
        }
        if source.ends_with("(1, 2)") {
            assert_eq!(
                call.child_by_field_name("arguments")
                    .unwrap()
                    .named_child_count(),
                2
            );
        }
    }
}

#[test]
fn do_block_binds_to_outer_chained_command() {
    let source = "1.upto 0 do end.foo bar {}.baz do end";
    let tree = parse(source);
    let call = tree.root_node().named_child(0).unwrap();
    assert!(!tree.root_node().has_error());
    assert_eq!(
        call.child_by_field_name("method")
            .unwrap()
            .utf8_text(source.as_bytes())
            .unwrap(),
        "foo"
    );
    assert_eq!(
        call.child_by_field_name("block").unwrap().kind(),
        "do_block"
    );
    // Prism の AST と同じく、末尾の do を引数側の baz に束縛しない。
    let argument = call
        .child_by_field_name("arguments")
        .unwrap()
        .named_child(0)
        .unwrap();
    assert_eq!(
        argument
            .child_by_field_name("method")
            .unwrap()
            .utf8_text(source.as_bytes())
            .unwrap(),
        "baz"
    );
    assert!(argument.child_by_field_name("block").is_none());
    assert_eq!(
        argument
            .child_by_field_name("receiver")
            .unwrap()
            .child_by_field_name("block")
            .unwrap()
            .kind(),
        "block"
    );
}

#[test]
fn nonlocal_variables_and_self_are_not_bare_methods() {
    // Ruby の -c が拒否する、変数への引数・ブロックの付加を個別に検証する。
    for source in [
        "$a 0",
        "$a(0)",
        "@a 0",
        "@@a(0)",
        "self(0)",
        "self {}",
        "@a do end",
    ] {
        assert!(parse(source).root_node().has_error(), "{source}");
    }
    for source in [
        "Foo 0",
        "Foo(0)",
        "super 0",
        "super(0)",
        "self.foo(0)",
        "@a.foo(0)",
        "foo ?a",
        "(?A..?Z)",
    ] {
        assert!(!parse(source).root_node().has_error(), "{source}");
    }
}

#[test]
fn command_chain_rejects_a_second_argument_list() {
    for source in [
        "1.upto 0 do end.foo(1) 2",
        "1.upto 0 do end.foo {} 2",
        "1.upto 0 do end.foo(1) 2 do end",
        "1.upto 0 do end.foo do end 2",
    ] {
        assert!(parse(source).root_node().has_error(), "{source}");
    }
}

#[test]
fn bare_methods_preserve_binary_operators_and_outer_do_blocks() {
    let source = "range_between(begin_pos - delta, end_pos)";
    let tree = parse(source);
    assert!(!tree.root_node().has_error());
    let call = tree.root_node().named_child(0).unwrap();
    let argument = call
        .child_by_field_name("arguments")
        .unwrap()
        .named_child(0)
        .unwrap();
    assert_eq!(argument.kind(), "binary", "{}", tree.root_node().to_sexp());
    assert_eq!(
        argument
            .child_by_field_name("operator")
            .unwrap()
            .utf8_text(source.as_bytes())
            .unwrap(),
        "-"
    );

    let source = "Spec.describe Example do end";
    let tree = parse(source);
    assert!(!tree.root_node().has_error());
    let call = tree.root_node().named_child(0).unwrap();
    assert_eq!(
        call.child_by_field_name("method")
            .unwrap()
            .utf8_text(source.as_bytes())
            .unwrap(),
        "describe"
    );
    assert_eq!(
        call.child_by_field_name("block").unwrap().kind(),
        "do_block"
    );
    assert_eq!(
        call.child_by_field_name("arguments")
            .unwrap()
            .named_child(0)
            .unwrap()
            .kind(),
        "constant"
    );
}

#[test]
fn numeric_sign_spacing_preserves_method_and_power_binding() {
    // 符号と数値が隣接すると数値リテラル、空白があると式全体への単項演算になる。
    for sign in ["+", "-"] {
        for number in ["1", "1.5", "0x10", "1r", "1i"] {
            for space in ["", " ", "\t"] {
                let source = format!("{sign}{space}{number}.abs");
                let tree = parse(&source);
                assert!(!tree.root_node().has_error(), "{source}");
                let expression = tree.root_node().named_child(0).unwrap();
                let (outer_kind, field, inner_kind) = if space.is_empty() {
                    ("call", "receiver", "unary")
                } else {
                    ("unary", "operand", "call")
                };
                assert_eq!(expression.kind(), outer_kind, "{source}");
                assert_eq!(
                    expression.child_by_field_name(field).unwrap().kind(),
                    inner_kind,
                    "{source}"
                );
            }
        }
    }

    for (source, outer_kind, field, inner_kind) in [
        ("+1 ** 2", "binary", "left", "unary"),
        ("+ 1 ** 2", "binary", "left", "unary"),
        ("+value ** 2", "binary", "left", "unary"),
        ("-value ** 2", "unary", "operand", "binary"),
    ] {
        let tree = parse(source);
        let expression = tree.root_node().named_child(0).unwrap();
        assert!(!expression.has_error(), "{source}");
        assert_eq!(expression.kind(), outer_kind, "{source}");
        assert_eq!(
            expression.child_by_field_name(field).unwrap().kind(),
            inner_kind,
            "{source}"
        );
    }

    // 数値に隣接する + を二項演算として使う既存の構文も維持する。
    for source in ["1+2", "1 +2", "1+ 2", "item+2", "item + 2"] {
        let tree = parse(source);
        let expression = tree.root_node().named_child(0).unwrap();
        assert!(!expression.has_error(), "{source}");
        assert_eq!(expression.kind(), "binary", "{source}");
        assert_eq!(
            expression.child_by_field_name("operator").unwrap().kind(),
            "+",
            "{source}"
        );
    }
}

#[test]
fn command_sign_spacing_distinguishes_arguments_from_binary_operators() {
    for sign in ["+", "-"] {
        for operand in ["1", "value"] {
            for (space, expected) in [("", "binary"), (" ", "call")] {
                let source = format!("foo{space}{sign}{operand}");
                let tree = parse(&source);
                assert!(!tree.root_node().has_error(), "{source}");
                assert_eq!(tree.root_node().named_child(0).unwrap().kind(), expected);
            }
        }
        // 前後に空白がある符号をコマンド引数と誤認すると、Ruby が拒否するコードを受理する。
        let invalid = format!("foo {sign} 1.abs, 2");
        assert!(parse(&invalid).root_node().has_error(), "{invalid}");
        let valid = format!("foo ({sign} 1.abs), 2");
        assert!(!parse(&valid).root_node().has_error(), "{valid}");

        for operand in ["1", "value"] {
            for space in ["", " "] {
                let source = format!("1..{space}{sign}{operand}");
                let tree = parse(&source);
                assert!(!tree.root_node().has_error(), "{source}");
                let range = tree.root_node().named_child(0).unwrap();
                assert_eq!(range.kind(), "range", "{source}");
                assert_eq!(range.child_by_field_name("end").unwrap().kind(), "unary");
            }
        }
    }

    // 演算子のメソッド名や += は式中の符号判定に巻き込まない。
    for source in [
        "value.+(1)",
        "value&.+ 1",
        "def +(other); end",
        "def +@; end",
        ":+",
        ":+@",
        "alias + plus",
        "undef +",
        "value += 1",
        "value +=1",
        "value = ?+",
        "[+ value]",
        "value = + other",
        "2**+1",
        "foo !+value",
        "foo + # コメント\n1",
    ] {
        assert!(!parse(source).root_node().has_error(), "{source}");
    }
}

#[test]
fn jump_keywords_start_arguments_before_signed_expressions() {
    // return・break・next の直後は空白に依存せず引数の式が始まる。
    for keyword in ["return", "break", "next"] {
        for sign in ["+", "-"] {
            for before in ["", " "] {
                for after in ["", " "] {
                    let source = format!("{keyword}{before}{sign}{after}value");
                    let tree = parse(&source);
                    assert!(!tree.root_node().has_error(), "{source}");
                    let jump = tree.root_node().named_child(0).unwrap();
                    assert_eq!(jump.kind(), keyword, "{source}");
                    let arguments = jump.named_child(0).unwrap();
                    assert_eq!(arguments.kind(), "argument_list", "{source}");
                    assert_eq!(arguments.named_child(0).unwrap().kind(), "unary");
                }
            }
        }
        for space in ["", " "] {
            let source = format!("{keyword}{space}/pattern/");
            let tree = parse(&source);
            assert!(!tree.root_node().has_error(), "{source}");
            let jump = tree.root_node().named_child(0).unwrap();
            assert_eq!(jump.kind(), keyword, "{source}");
            assert_eq!(
                jump.named_child(0).unwrap().named_child(0).unwrap().kind(),
                "regex"
            );
        }
        let source = format!("{keyword}\n-1");
        let tree = parse(&source);
        assert!(!tree.root_node().has_error(), "{source}");
        assert_eq!(tree.root_node().named_child_count(), 2, "{source}");
        assert_eq!(
            tree.root_node().named_child(0).unwrap().named_child_count(),
            0
        );
    }

    // yield は同じ字句状態ではないため、符号の前後に空白がある場合は二項演算となる。
    let tree = parse("yield - value");
    assert_eq!(tree.root_node().named_child(0).unwrap().kind(), "binary");
}
