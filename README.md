# tree-sitter-ruby

[![CI][ci]](https://github.com/owayo/tree-sitter-ruby/actions/workflows/ci.yml)

Ruby grammar for [tree-sitter](https://github.com/tree-sitter/tree-sitter) with Ruby 3/4 syntax support.

See the [syntax validation report](docs/validation.md) for tested repository
snapshots, regression checks and remaining parsing limitations.

The [2026-10-29 maintenance report](docs/benchmarks/2026-10-29/README.md)
records dependency updates, Windows memory-monitor measurements and validation.
The corpus runner reads Windows RSS directly through the OS API and releases
its process handles after every observation. Interruptions and monitoring errors
terminate and collect the parser process before propagating the original error.
POSIX monitors the whole process group; Windows monitors the target PID.

## Usage (Rust)

Add to your `Cargo.toml`:

```toml
[dependencies]
tree-sitter = "0.27"
tree-sitter-ruby = { git = "https://github.com/owayo/tree-sitter-ruby.git" }
```

```rust
use tree_sitter::Parser;
use tree_sitter_ruby::LANGUAGE;

let mut parser = Parser::new();
parser.set_language(&LANGUAGE.into()).unwrap();

let tree = parser.parse("puts 'hello'", None).unwrap();
println!("{}", tree.root_node().to_sexp());
```

## Queries

This grammar ships with the following query files in `queries/`:

| File | Description |
|------|-------------|
| `highlights.scm` | Syntax highlighting (keywords, literals, operators, etc.) |
| `tags.scm` | Code navigation tags (definitions and references for methods, classes, modules, constants) |
| `locals.scm` | Local variable scoping |

## Known limitations

### Spaced index assignment and local variables

This grammar does not resolve Ruby local-variable bindings. For a bare identifier
followed by a space and `[`, Ruby uses the bindings visible at that point to
distinguish an index receiver from a method called with an array argument. These
two snippets are syntax errors in Ruby when parsed independently:

```ruby
v [0] = 1
```

```ruby
v [0] += 1
```

An earlier assignment or a parameter binding makes the spaced form valid Ruby:

```ruby
v = []
v [0] = 1
v [0] += 1

def update(v)
  v [0] += 1
end
```

The grammar accepts both the declared and undeclared forms without an `ERROR`
node. It produces an `assignment` or `operator_assignment` whose `left` field is
an `element_reference` with an `identifier` in its `object` field. The unspaced
form, `v[0] = 1`, has the same named-node structure and is syntactically valid
Ruby without a prior binding; its receiver can be a method call at runtime.
Without an assignment operator, this grammar parses `v [0]` as a `call` with an
array in its `argument_list`.

Consumers that need Ruby-valid syntax must perform additional validation. For
this bare-identifier ambiguity, inspect the fields above and compare the
object's end byte with the opening `[` token's start byte: a gap distinguishes
the spaced form from `v[0]`. Resolve the name using Ruby's bindings at that source
position, including parameters, enclosing block scopes, and declaration order.
A later assignment does not establish an earlier reference, and methods,
classes, and modules do not inherit outer local variables. Registration happens
during parsing rather than execution: `v = [] if false` still registers `v` for
subsequent statements. See [Ruby's local-variable rules](https://docs.ruby-lang.org/en/4.0/syntax/assignment_rdoc.html#label-Local+Variables+and+Methods).

The captures in [`queries/locals.scm`](queries/locals.scm) can help a binding
analysis, but do not implement all Ruby registration and scope rules. The check
above is specific to bare identifiers, not a complete rule for all receiver
forms: for example, the grammar also accepts `Foo [0] = 1` and `obj.foo [0] = 1`,
which Ruby rejects. An AST without `ERROR` nodes is not a guarantee of Ruby
syntax validity. These limitations should be revisited if binding-aware parsing
is introduced.

### Operators after local variables and the host hint

When an identifier is followed by a space and an operator with no space after it
(`foo +value`, `foo -1`, `foo *args`, `foo **opts`, `foo &blk`, `foo [0]`,
`foo <<X`, `foo /re/`, `foo %w[a]`), this grammar reads the operator as the start
of an argument to `foo`. That is how Ruby reads an unknown identifier, but when
`foo` is a local variable at that point, Ruby reads these as binary operators or
as an element reference (`count = 1; count +1` is `count + 1`).

A consumer that resolves bindings can replace the last whitespace character
before the operator with a form feed (U+000C) and parse again. The scanner then
reads the operator as a binary operator (`+`, `-`, `*`, `**`, `&`, `<<`, `/`,
`%`) and the `[` as an element reference. When a line continuation (`\` and a
newline) comes right before the operator, replace the whitespace before it: a
line continuation only removes the newline, so the hint carries across it. Ruby
treats a form feed as whitespace, so the meaning and the byte positions of the
source stay the same. The hint is not used when whitespace or a line break
(other than a line continuation) follows the form feed, or where a binary
operator cannot appear, such as at the start of an expression; a form feed
anywhere else reads as whitespace.

If the source already contains form feeds, replace the ones between tokens (in
whitespace) with spaces before adding hints; otherwise they act as hints too. A
form feed inside a string, a comment or a heredoc delimiter is part of the text
and must be kept. A hint can change how `<<` or `%` reads and with it where a
following heredoc or percent literal ends, so check the hints and the replaced
form feeds again against the tree parsed with them. The ternary `?` versus a
character literal, and `::`, are decided by the internal lexer and are not
covered by this hint.

## Full-parse benchmark (2026-10-30)

Single-threaded Rust APIs on Windows 11, Ryzen 7 5700X. Each file gets a new
parser; initialization, language setup, tree construction and destruction are
included. Input I/O, AST output, queries and Ruby VM startup are excluded. Both C
implementations use Release optimization. Rust 1.99.1, tree-sitter 0.27.1 and
[ruby-prism 2.0.0](https://github.com/ruby/prism/releases/tag/v2.0.0) are used;
ruby-prism 2.1.0 (released 2026-10-28) was still inside the one-week release age
policy. Two warmups precede seven alternating measurements; values are medians
[min–max].

| Corpus | Files | Bytes | Prism ms (range) | tree-sitter ms (range) | Prism/TS |
|---|---:|---:|---:|---:|---:|
| Rails | 3,481 | 20,011,502 | 204.393 [174.603–405.264] | 3126.046 [2845.781–6228.623] | 0.0654 |
| Ruby | 7,480 | 36,165,003 | 406.229 [388.464–800.066] | 7243.782 [6324.487–13260.486] | 0.0561 |
| RuboCop | 1,791 | 11,624,842 | 97.200 [85.682–174.849] | 1159.100 [1045.517–1618.507] | 0.0839 |
| Homebrew | 2,407 | 13,575,237 | 151.381 [138.107–228.735] | 2234.169 [2088.687–3140.624] | 0.0678 |
| Mastodon | 3,355 | 6,069,022 | 71.402 [63.656–115.726] | 1010.398 [948.143–1483.045] | 0.0707 |
| Total | 18,514 | 87,445,606 | 913.301 [870.940–1713.570] | 14731.034 [13358.444–25466.858] | 0.0620 |

The overall Prism/TS ratio is 0.0620; values above 1 would favor tree-sitter.
The goal of beating Prism on fresh full parses was **not achieved**. The wide
ranges come from other desktop load during this session; the per-round Prism/TS
ratio stayed between 0.059 and 0.074.
Both implementations accept the fixed 18,514-file comparison set. Across all
18,520 inputs, tree-sitter retains five known failures and introduces none, and
every tree (node kinds, fields, ranges and named/extra flags) is identical to
the one from the previous master (`c3c70a2`).

Function-level CPU sampling shows that the external scanner takes about 4% of the
time; most of it is in tree-sitter's GLR stack, subtree allocation, parse-table
lookups and the heap. This release inlines six hidden grammar rules that are
neither supertypes nor conflict members, which removes 7.97% of all reductions
without changing `node-types.json`. Because desktop noise made whole rounds vary
by up to 50% in this session, the speedup was measured by pinning the candidate
and the control to the same logical CPU and alternating short rounds: the median
candidate/control ratio was 0.968 and 0.964 in two independent runs (95%
bootstrap intervals 0.953–0.986 and 0.952–0.969). See the
[raw data and investigation report](docs/benchmarks/2026-10-30/README.md) and the
[reproduction harness](tools/parse-benchmark/README.md).

## Prerequisites

```bash
mise install
```

The versions of Node.js, pnpm, Python, Ruff, and Rust are defined in `mise.toml`. The project-local tree-sitter CLI is installed by pnpm.

## Development

```bash
# Install dependencies (also fetches the tree-sitter CLI binary)
mise exec -- pnpm install

# Generate parser from grammar.js
mise exec -- pnpm exec tree-sitter generate

# Re-indent the generated JSON with tabs, as committed
mise exec -- pnpm exec biome format --write src/grammar.json src/node-types.json

# Lint grammar.js
mise exec -- pnpm run lint

# Parse a file
mise exec -- pnpm exec tree-sitter parse example.rb
```

### Testing

**Do not run `tree-sitter test`.** It hangs with excessive memory use on this
large parser (RSS 8GB+, VSIZE 400GB+). Use the parse-based corpus runner below.
Build the shared library first; the runner never rebuilds it implicitly.

```bash
# macOS: parse 用の共有ライブラリを先に作成する
mkdir -p /tmp/ts-lib
cc -shared -fPIC -O0 -o /tmp/ts-lib/ruby.dylib -I src src/parser.c src/scanner.c

# コーパス・ランナー・Rust バインディングを検証する
mise exec -- python3 scripts/corpus_test.py
mise exec -- pnpm run test:unit
mise exec -- cargo test

# lint とフォーマットを確認する
mise exec -- pnpm run lint
mise exec -- ruff check scripts
mise exec -- ruff format --check scripts
mise exec -- cargo fmt --check
```

On Linux, build `ruby.so` instead of `ruby.dylib`; on Windows, build `ruby.dll`.
Set `TREE_SITTER_LIB_PATH` to use a different library file. Otherwise the runner
uses `TREE_SITTER_LIBDIR`, then `/tmp/ts-lib` on POSIX or the native temporary
directory on Windows. Paths passed to native Windows programs must be native
paths; the CI workflow converts Git Bash paths with `cygpath -am`.

Corpus tests cover Ruby 3/4 syntax, Unicode identifiers, forwarding, endless
methods, line continuation, literals and heredocs. Expected ASTs with field
names compare those names as well as node structure; fieldless expected ASTs
retain the legacy comparison behavior. Rust tests also cover query captures,
heredoc edits during incremental parsing (including nested heredocs opened in
heredoc bodies), the combined literal/heredoc storage limit, and truncated,
trailing or structurally invalid scanner state data. Runner unit tests cover
setup failures, timeouts, memory limits, output decoding and AST comparison.

The runner resolves the CLI from `TREE_SITTER_CLI`, the local native binary,
the local pnpm shim, then `PATH`. A missing library or a CLI that cannot start
within ten seconds causes a setup error before corpus cases run.

### C binding

CMake builds the committed parser sources without requiring the CLI or
regenerating files. It installs a C/C++ header, the library and pkg-config
metadata. The package version follows `Cargo.toml`.

```bash
cmake -S . -B build/c -DCMAKE_INSTALL_PREFIX="$HOME/.local"
cmake --build build/c
cmake --install build/c

# Python 3.7 以降と tree-sitter CLI がある環境でコーパスを検証する
cmake --build build/c --target ts-test
```

`ts-test` uses `scripts/corpus_test.py` with the built library's exact path.
It is available for shared builds when Python is found. Set
`BUILD_SHARED_LIBS=OFF` for a static library. The optional `ts-generate` target
regenerates `grammar.js` only when explicitly requested and the CLI is found.

### Scanner

The external scanner (`src/scanner.c`) handles context-sensitive tokens that cannot be expressed in `grammar.js` alone: heredocs, delimited literals (strings, regexes, subshells, symbol/string arrays), line breaks, whitespace-sensitive operators, and the serialized scanner state needed to resume those constructs correctly. Unlike the rest of `src/`, this file is manually maintained and should be edited directly when adding new token types.

A heredoc opened inside an interpolation of another heredoc body is read the way Ruby reads it: its body starts on the line after the one that opened it, before the rest of the outer body and before other heredocs that were opened on the outer line (`foo(<<~A, <<~B)` with `#{<<~C}` in A's body reads C, then the rest of A, then B). The scanner keeps open heredocs as frames, one per line that opened them, and marks the head of each nested frame with a bit packed into the existing flag byte, so the 7-byte serialized header and the terminator capacity are unchanged. The nested `heredoc_body` appears as an extra inside the outer `heredoc_body`. When the outer body line ends with a line continuation (`\`), the backslash stays in the outer content so that the line break still starts the nested body. Deserialization rejects frame layouts that scanning cannot produce.

A heredoc body also starts on the next line when the opening line continues in some other way: a line continuation in code (`foo(<<~A, \` + newline), or a literal that crosses the line break after the heredoc start (strings, regexes, symbols, subshells and `%w`-style arrays, as in `[<<~A, "x` + newline, including a `\` + newline inside the literal). Inside a literal, the body appears as an extra in the literal node. When a line continuation removed the opening line break, the last terminator of that frame is followed by a hidden token for the terminator's line break, so the code or literal continues on the next line, as Ruby reads it, and `heredoc_end` still covers only the terminator word. A lone CR in code is whitespace, as in Ruby, and does not start a body.

Long heredoc terminators over 255 characters are covered by a dedicated regression case in `test/corpus/literals.txt`; terminators that cannot fit in tree-sitter's scanner serialization buffer are rejected instead of being silently misparsed, also after a command name where `<<` could be a left shift (`puts <<WORD`), while a state that exactly fills the 1024-byte buffer remains valid. Unicode terminators are stored and compared as UTF-8 byte sequences, preserving the existing one-byte representation and capacity for ASCII terminators. Changes to scanner serialization should be validated with `pnpm run test`. The `deserialize()` function includes bounds checking to safely handle truncated or corrupted buffers, and uses subtraction (`word_length > length - size`) instead of addition for the word-length boundary check so that an attacker-controlled `word_length` cannot wrap around via unsigned integer overflow. Regex option scanning (`imxouesn`) and short interpolation scanning for special global variables avoid calling `strchr` on `lexer->lookahead` directly: `strchr` converts its second argument to `char`, so EOF (`0`) would match the terminating NUL and non-ASCII code points whose low 8 bits collide with an option letter (`ど` U+3069 and `ũ` U+0169 both end in 0x69 = `'i'`) would be consumed as options. The former compares against `int32_t` values directly; the latter narrows to `c > 0 && c < 0x80` before matching. Short-interpolation entry points (`@`/`$` after `#`) compare against `lexer->lookahead` (`int32_t`) directly instead of truncating to `char`, so Unicode characters whose low 8 bits collide with `'@'` (0x40) or `'$'` (0x24) — such as `Ĥ` (U+0124) or `Ŀ` (U+0140) — are not misclassified as interpolation starts.

### Unicode identifiers

tree-sitter-cli 0.26.11 stripped `ſ` (U+017F, simple-folded to `s`) and `K`
(U+212A, simple-folded to `k`) from generic lexer character sets to make
case-insensitive keyword extraction correct. Ruby accepts both characters in
identifiers, so `grammar.js` explicitly adds them back to the initial and
continuation character rules. Since 0.27.0 the CLI no longer strips them and the
explicit allowance is a no-op (`src/parser.c` is byte-identical either way), but it
is kept so the grammar does not break silently if the CLI regresses. Keep this
exception synchronized with `test/corpus/identifiers.txt` when changing identifier
token rules.
Named global variables reuse these Unicode identifier rules, including the
single-character option form (`$-名`) and short interpolation (`"#$名前"`).

### Endless method definitions

Since Ruby 3.1 the body of an endless method definition may be a parenthesis-less
command call (`endless_command : command` in `parse.y`), for example
`def greet(person) = "Hi, ".dup.concat person`. Reusing the existing `command_call`
rule for that position is not viable: its argument list loops back into
`_expression`, which drags pattern matching (`x in [1] | [2]`) and block binding
into the endless-body context and produces a cascade of LR conflicts. The grammar
therefore defines a narrowed `_endless_command_call` / `_endless_command_argument_list`
/ `_endless_command_argument` trio that reuses `_arg` only as a leaf.

`pair` (`def m = foo a: 1`) is deliberately excluded from the endless argument list:
the `_arg => _arg` form competes with `match_pattern` and doubles the LR state count
in this context alone, growing `src/parser.c` from 21MB to 32MB. Splat, double-splat
and block arguments cost almost nothing by comparison and are supported. Parenthesized
calls such as `def m = foo(a: 1)` are unaffected.

Do not add `_chained_command_call` to the receiver of `call` or
`command_call_with_block`. It improves the AST for `1.upto 0 do end.foo(1)`, but it
also makes whole files fail to parse across Rails, Homebrew and ruby itself, and
doubles `src/parser.c` to 37MB.

## References

- [AST Format of the Whitequark parser](https://github.com/whitequark/parser/blob/master/doc/AST_FORMAT.md)

[ci]: https://img.shields.io/github/actions/workflow/status/owayo/tree-sitter-ruby/ci.yml?logo=github&label=CI
