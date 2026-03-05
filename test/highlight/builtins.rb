require "foo"
# ^ function.method.builtin

defined? foo
# ^ function.method.builtin

self
# <- variable.builtin

super
# <- variable.builtin

@instance_var = 1
# <- property

@@class_var = 2
# <- property

"hello #{world}"
#       ^ punctuation.special
#              ^ punctuation.special

<<~HEREDOC
# <- string
  hello
HEREDOC
# <- string

'\escape'
# <- string

"\n"
# ^ escape
