use tree_sitter_ruby::LANGUAGE;

fn parse(code: &str) -> tree_sitter::Tree {
    let mut parser = tree_sitter::Parser::new();
    parser.set_language(&LANGUAGE.into()).unwrap();
    parser.parse(code, None).unwrap()
}

#[test]
fn rejects_when_after_else() {
    for code in [
        "case x\nwhen 1\n  a\nelse\n  when 2\n    b\nend\n",
        "case x; when 1; a; else; when 2; b; end\n",
        "case\nwhen ready\n  a\nelse\n  when other\n    b\nend\n",
        "case x\nwhen 1\n  a\nelse\n  b\n  when 2\n    c\nend\n",
        "case x\nwhen 1\n  a\nelse\n  p(when 2)\nend\n",
        "case x\nwhen 1\n  a\nelse\n  x = [when 2]\nend\n",
        "case x\nwhen 1\n  a\nelse\n  foo(1, when 2)\nend\n",
        "case x\nwhen 1\n  a\nelse\n  p(when)\nend\n",
    ] {
        let tree = parse(code);
        assert!(
            tree.root_node().has_error(),
            "Invalid when clause was accepted: {code:?}\n{}",
            tree.root_node().to_sexp()
        );
    }
}

#[test]
fn rejects_when_as_ordinary_identifier() {
    for code in [
        "foo(when)\n",
        "x = [\n  when\n]\n",
        "def m(when); end\n",
        "[1].each { |when| }\n",
        "def when.foo; end\n",
        "x = when 1\n",
        "if a\n  when 1\nend\n",
        "case x\nwhen 1\n  begin\n    when 2\n  end\nend\n",
        "case x\nwhen 1\nend\nwhen 2\n",
        "obj.foo = when\n",
    ] {
        let tree = parse(code);
        assert!(
            tree.root_node().has_error(),
            "Reserved when was accepted as an identifier: {code:?}\n{}",
            tree.root_node().to_sexp()
        );
    }
}

#[test]
fn accepts_when_in_valid_contexts() {
    for code in [
        "case x\nwhen 1\n  a\nwhen 2, 3\n  b\nelse\n  c\nend\n",
        "case\nwhen ready\n  a\nwhen other\n  b\nelse\n  c\nend\n",
        "case x\nwhen 1\n  a\nelse\n  case y\n  when 2\n    b\n  else\n    c\n  end\nend\n",
        "def when; :ok; end\ndef self.when; :ok; end\n",
        "def when=(value); value; end\ndef self.when=(value); value; end\n",
        "obj.when = 1\nalias other when=\nalias when= other\nundef when=\n",
        "alias other when\nalias when other\nundef when\n",
        "obj.when\nobj.when(1)\nobj.when 1\nobj&.when\nobj::when\n",
        "items.each do |item| item end.when 1\n",
        "def m = obj.when 1\n",
        "{when: 1}\nfoo(when: 1)\n:when\n",
        "def m(when:); :ok; end\ndef n(when: 1); :ok; end\n->(when:) { :ok }\n",
        "case x\nin {when:}\n  :ok\nend\n",
        "case x\nin {when: value}\n  value\nend\n",
        "when_value = 1\nwhenever = 2\nwhen?\nwhen!\n",
        "case x\nwhen 1\n  a\nelse\n  obj.when 2\nend\n",
        "case x\nwhen 1\n  foo when: 2, if: 3\nwhen 2\n  bar\nend\n",
        "foo when: 1\nfoo.when when: 1\n",
        "proc { |when:| }\nproc { |when: 1| }\n",
        "case x\nin when: 1\nend\ncase x\nin Foo(when: 1)\nend\n",
        "def when = 1\ndef self.when = 1\ndef obj.when; end\n",
        "obj.when ||= 1\na, obj.when = 1, 2\n",
        "{when:}\nfoo(when:)\n",
    ] {
        let tree = parse(code);
        assert!(
            !tree.root_node().has_error(),
            "Valid when context was rejected: {code:?}\n{}",
            tree.root_node().to_sexp()
        );
    }
}
