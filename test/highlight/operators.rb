x = 1
# <- operator

x => y
# <- operator

-> { }
# <- operator

a + b
a - b
a * b
a / b
a % b
a ** b

a == b
# ^ operator
a != b
a === b
a <=> b
a =~ b
a !~ b

a > b
a >= b
a < b
a <= b

a & b
a | b
a ^ b
a << b
a >> b

a && b
a || b

!a
~a

a, b = 1, 2
# ^ punctuation.delimiter
#    ^ operator

foo(a, b)
#  ^ punctuation.bracket
#      ^ punctuation.bracket

[1, 2]
# <- punctuation.bracket
#    ^ punctuation.bracket

{a: 1}
# <- punctuation.bracket
#    ^ punctuation.bracket

foo.bar
#  ^ punctuation.delimiter

foo; bar
#  ^ punctuation.delimiter
