#include "tree_sitter/alloc.h"
#include "tree_sitter/array.h"
#include "tree_sitter/parser.h"

#include <string.h>
#include <wctype.h>

typedef enum {
    LINE_BREAK,
    NO_LINE_BREAK,

    // 区切りリテラル
    SIMPLE_SYMBOL,
    STRING_START,
    SYMBOL_START,
    SUBSHELL_START,
    REGEX_START,
    STRING_ARRAY_START,
    SYMBOL_ARRAY_START,
    HEREDOC_BODY_START,
    STRING_CONTENT,
    HEREDOC_CONTENT,
    STRING_END,
    HEREDOC_BODY_END,
    HEREDOC_START,

    // 空白に依存するトークン
    FORWARD_SLASH,
    BLOCK_AMPERSAND,
    SPLAT_STAR,
    UNARY_MINUS,
    UNARY_MINUS_NUM,
    BINARY_MINUS,
    BINARY_STAR,
    SINGLETON_CLASS_LEFT_ANGLE_LEFT_ANGLE,
    HASH_KEY_SYMBOL,
    IDENTIFIER_SUFFIX,
    CONSTANT_SUFFIX,
    HASH_SPLAT_STAR_STAR,
    BINARY_STAR_STAR,
    ELEMENT_REFERENCE_BRACKET,
    SHORT_INTERPOLATION,
    BINARY_LEFT_SHIFT,
    BINARY_AMPERSAND,

    NONE
} TokenType;

typedef Array(char) String;

typedef struct {
    TokenType type;
    int32_t open_delimiter;
    int32_t close_delimiter;
    int32_t nesting_depth;
    bool allows_interpolation;
} Literal;

typedef struct {
    String word;
    bool end_word_indentation_allowed;
    bool allows_interpolation;
    bool started;
} Heredoc;

typedef struct {
    bool has_leading_whitespace;
    Array(Literal) literal_stack;
    Array(Heredoc) open_heredocs;
} Scanner;

enum {
    SERIALIZED_LITERAL_SIZE = 1 + 1 + 1 + sizeof(uint32_t) + 1,
    SERIALIZED_HEREDOC_HEADER_SIZE = 3 + sizeof(uint32_t),
};

const char NON_IDENTIFIER_CHARS[] = {
    '\0', '\n', '\r', '\t', ' ', ':', ';', '`',  '"', '\'', '@', '$', '#', '.', ',', '|', '^', '&',
    '<',  '=',  '>',  '+',  '-', '*', '/', '\\', '%', '?',  '!', '~', '(', ')', '[', ']', '{', '}',
};

static inline void skip(Scanner *scanner, TSLexer *lexer) {
    scanner->has_leading_whitespace = true;
    lexer->advance(lexer, true);
}

static inline void advance(TSLexer *lexer) { lexer->advance(lexer, false); }

static inline uint32_t encode_utf8_codepoint(int32_t codepoint, char encoded[4]) {
    if (codepoint < 0 || codepoint > 0x10FFFF || (codepoint >= 0xD800 && codepoint <= 0xDFFF)) {
        return 0;
    }

    if (codepoint <= 0x7F) {
        encoded[0] = (char)codepoint;
        return 1;
    }
    if (codepoint <= 0x7FF) {
        encoded[0] = (char)(0xC0 | (codepoint >> 6));
        encoded[1] = (char)(0x80 | (codepoint & 0x3F));
        return 2;
    }
    if (codepoint <= 0xFFFF) {
        encoded[0] = (char)(0xE0 | (codepoint >> 12));
        encoded[1] = (char)(0x80 | ((codepoint >> 6) & 0x3F));
        encoded[2] = (char)(0x80 | (codepoint & 0x3F));
        return 3;
    }

    encoded[0] = (char)(0xF0 | (codepoint >> 18));
    encoded[1] = (char)(0x80 | ((codepoint >> 12) & 0x3F));
    encoded[2] = (char)(0x80 | ((codepoint >> 6) & 0x3F));
    encoded[3] = (char)(0x80 | (codepoint & 0x3F));
    return 4;
}

static inline bool append_utf8_codepoint(String *string, int32_t codepoint) {
    char encoded[4];
    uint32_t length = encode_utf8_codepoint(codepoint, encoded);
    if (length == 0) return false;

    for (uint32_t i = 0; i < length; i++) {
        array_push(string, encoded[i]);
    }
    return true;
}

static inline uint32_t match_utf8_codepoint(const String *string, size_t position, int32_t codepoint) {
    char encoded[4];
    uint32_t length = encode_utf8_codepoint(codepoint, encoded);
    if (length == 0 || position >= string->size || length > string->size - position) {
        return 0;
    }
    return memcmp(&string->contents[position], encoded, length) == 0 ? length : 0;
}

static inline void reset(Scanner *scanner) {
    array_delete(&scanner->literal_stack);
    for (uint32_t i = 0; i < scanner->open_heredocs.size; i++) {
        array_delete(&array_get(&scanner->open_heredocs, i)->word);
    }
    array_delete(&scanner->open_heredocs);
}

static inline bool can_serialize_heredocs_with(Scanner *scanner, const Heredoc *new_heredoc) {
    size_t size = 2 + scanner->literal_stack.size * SERIALIZED_LITERAL_SIZE;
    for (uint32_t i = 0; i < scanner->open_heredocs.size; i++) {
        Heredoc *heredoc = array_get(&scanner->open_heredocs, i);
        size += SERIALIZED_HEREDOC_HEADER_SIZE + heredoc->word.size;
        if (size > TREE_SITTER_SERIALIZATION_BUFFER_SIZE) {
            return false;
        }
    }
    if (new_heredoc != NULL) {
        size += SERIALIZED_HEREDOC_HEADER_SIZE + new_heredoc->word.size;
        if (size > TREE_SITTER_SERIALIZATION_BUFFER_SIZE) {
            return false;
        }
    }
    return size <= TREE_SITTER_SERIALIZATION_BUFFER_SIZE;
}

static inline unsigned serialize(Scanner *scanner, char *buffer) {
    unsigned size = 0;

    if (scanner->literal_stack.size * SERIALIZED_LITERAL_SIZE + 2 > TREE_SITTER_SERIALIZATION_BUFFER_SIZE) {
        return 0;
    }
    if (!can_serialize_heredocs_with(scanner, NULL)) {
        return 0;
    }

    buffer[size++] = (char)scanner->literal_stack.size;
    for (uint32_t i = 0; i < scanner->literal_stack.size; i++) {
        Literal *literal = array_get(&scanner->literal_stack, i);
        buffer[size++] = literal->type;
        buffer[size++] = (char)literal->open_delimiter;
        buffer[size++] = (char)literal->close_delimiter;
        uint32_t nesting_depth = (uint32_t)literal->nesting_depth;
        memcpy(&buffer[size], &nesting_depth, sizeof(uint32_t));
        size += sizeof(uint32_t);
        buffer[size++] = (char)literal->allows_interpolation;
    }

    buffer[size++] = (char)scanner->open_heredocs.size;
    for (uint32_t i = 0; i < scanner->open_heredocs.size; i++) {
        Heredoc *heredoc = array_get(&scanner->open_heredocs, i);

        // フラグ 3 つと 32 ビット長、終端語本体をシリアライズする。
        // バッファ上限ぴったりは有効なため、超過だけを拒否する。
        if (size + SERIALIZED_HEREDOC_HEADER_SIZE + heredoc->word.size > TREE_SITTER_SERIALIZATION_BUFFER_SIZE) {
            return 0;
        }
        buffer[size++] = (char)heredoc->end_word_indentation_allowed;
        buffer[size++] = (char)heredoc->allows_interpolation;
        buffer[size++] = (char)heredoc->started;
        memcpy(&buffer[size], &heredoc->word.size, sizeof(uint32_t));
        size += sizeof(uint32_t);
        memcpy(&buffer[size], heredoc->word.contents, heredoc->word.size);
        size += heredoc->word.size;
    }

    return size;
}

static inline void deserialize(Scanner *scanner, const char *buffer, unsigned length) {
    unsigned size = 0;
    scanner->has_leading_whitespace = false;
    reset(scanner);

    if (length == 0) {
        return;
    }

    uint8_t literal_depth = buffer[size++];
    for (unsigned j = 0; j < literal_depth; j++) {
        // リテラル 1 件あたり SERIALIZED_LITERAL_SIZE バイト必要
        if (size + SERIALIZED_LITERAL_SIZE > length) return;
        Literal literal = {0};
        literal.type = (TokenType)(buffer[size++]);
        literal.open_delimiter = (unsigned char)buffer[size++];
        literal.close_delimiter = (unsigned char)buffer[size++];
        uint32_t nesting_depth;
        memcpy(&nesting_depth, &buffer[size], sizeof(uint32_t));
        size += sizeof(uint32_t);
        literal.nesting_depth = (int32_t)nesting_depth;
        literal.allows_interpolation = buffer[size++];
        array_push(&scanner->literal_stack, literal);
    }

    if (size >= length) return;
    uint8_t open_heredoc_count = buffer[size++];
    for (unsigned j = 0; j < open_heredoc_count; j++) {
        // heredoc ヘッダー: フラグ 3 バイト + word_length 4 バイト = 最低 7 バイト
        if (size + SERIALIZED_HEREDOC_HEADER_SIZE > length) return;
        Heredoc heredoc = {0};
        heredoc.end_word_indentation_allowed = buffer[size++];
        heredoc.allows_interpolation = buffer[size++];
        heredoc.started = buffer[size++];

        heredoc.word = (String)array_new();
        uint32_t word_length;
        memcpy(&word_length, &buffer[size], sizeof(uint32_t));
        size += sizeof(uint32_t);
        // 終端語本体がバッファ内に収まるか検証する。
        // `size + word_length > length` の形だと word_length が極端に
        // 大きい場合に符号なし整数のオーバーフローでチェックを潜り抜けて
        // しまうため、`length - size` の引き算で比較する。
        // 上の SERIALIZED_HEREDOC_HEADER_SIZE チェックで size <= length が
        // 保証されているので length - size は安全に計算できる。
        if (word_length > length - size) {
            array_delete(&heredoc.word);
            return;
        }
        array_reserve(&heredoc.word, word_length);
        memcpy(heredoc.word.contents, &buffer[size], word_length);
        heredoc.word.size = word_length;
        size += word_length;
        array_push(&scanner->open_heredocs, heredoc);
    }

    assert(size == length);
}

static inline bool is_iden_char(int32_t c) {
    // ASCII 外（>= 0x80）は Unicode 識別子文字として常に許容する。
    // Ruby は識別子に Unicode 文字を許容するため、char に切り詰めると
    // 例えば `:Ĩ` (U+0128) の下位 8 bit が `(` (0x28) と衝突してしまう。
    if (c >= 0x80) {
        return true;
    }
    return memchr(&NON_IDENTIFIER_CHARS, (char)c, sizeof(NON_IDENTIFIER_CHARS)) == NULL;
}

static inline bool scan_whitespace(Scanner *scanner, TSLexer *lexer, const bool *valid_symbols) {
    bool heredoc_body_start_is_valid = scanner->open_heredocs.size > 0 && !scanner->open_heredocs.contents[0].started &&
                                       valid_symbols[HEREDOC_BODY_START];
    bool crossed_newline = false;

    for (;;) {
        if (!valid_symbols[NO_LINE_BREAK] && valid_symbols[LINE_BREAK] && lexer->is_at_included_range_start(lexer)) {
            lexer->mark_end(lexer);
            lexer->result_symbol = LINE_BREAK;
            return true;
        }

        switch (lexer->lookahead) {
            case ' ':
            case '\t':
                skip(scanner, lexer);
                break;
            case '\r':
                if (heredoc_body_start_is_valid) {
                    lexer->result_symbol = HEREDOC_BODY_START;
                    scanner->open_heredocs.contents[0].started = true;
                    return true;
                } else {
                    skip(scanner, lexer);
                    break;
                }
            case '\n':
                if (heredoc_body_start_is_valid) {
                    lexer->result_symbol = HEREDOC_BODY_START;
                    scanner->open_heredocs.contents[0].started = true;
                    return true;
                } else if (!valid_symbols[NO_LINE_BREAK] && valid_symbols[LINE_BREAK] && !crossed_newline) {
                    lexer->mark_end(lexer);
                    advance(lexer);
                    crossed_newline = true;
                } else {
                    skip(scanner, lexer);
                }
                break;
            case '\\':
                advance(lexer);
                if (lexer->lookahead == '\r') {
                    skip(scanner, lexer);
                }
                if (iswspace(lexer->lookahead)) {
                    skip(scanner, lexer);
                } else {
                    return false;
                }
                break;
            default:
                if (crossed_newline) {
                    if (lexer->lookahead != '.' && lexer->lookahead != '&'
                        && lexer->lookahead != '|' && lexer->lookahead != '#') {
                        // 行頭の `or` キーワードは改行継続として扱う。
                        if (lexer->lookahead == 'o') {
                            advance(lexer);
                            if (lexer->lookahead == 'r') {
                                advance(lexer);
                                if (!is_iden_char(lexer->lookahead)) {
                                    return false;
                                }
                            }
                            lexer->result_symbol = LINE_BREAK;
                        // 行頭の `and` キーワードは改行継続として扱う。
                        } else if (lexer->lookahead == 'a') {
                            advance(lexer);
                            if (lexer->lookahead == 'n') {
                                advance(lexer);
                                if (lexer->lookahead == 'd') {
                                    advance(lexer);
                                    if (!is_iden_char(lexer->lookahead)) {
                                        return false;
                                    }
                                }
                            }
                            lexer->result_symbol = LINE_BREAK;
                        } else {
                            lexer->result_symbol = LINE_BREAK;
                        }
                    } else if (lexer->lookahead == '.') {
                        // 呼び出し演算子 (`.`) では LINE_BREAK を返さない。
                        // ただし範囲演算子 (`..` と `...`) では返す。
                        advance(lexer);
                        if (!lexer->eof(lexer) && lexer->lookahead == '.') {
                            lexer->result_symbol = LINE_BREAK;
                        } else {
                            return false;
                        }
                    } else if (lexer->lookahead == '|') {
                        // `||`（論理和や改行継続）では LINE_BREAK を返さない。
                        // 単独の `|`（ビット演算子）では返す。
                        advance(lexer);
                        if (!lexer->eof(lexer) && lexer->lookahead == '|') {
                            return false;
                        } else {
                            lexer->result_symbol = LINE_BREAK;
                        }
                    } else if (lexer->lookahead == '&') {
                        // `&&` と `&.` では LINE_BREAK を返さない。
                        // 単独の `&`（ビット演算子）では返す。
                        advance(lexer);
                        if (!lexer->eof(lexer) && (lexer->lookahead == '&' || lexer->lookahead == '.')) {
                            return false;
                        } else {
                            lexer->result_symbol = LINE_BREAK;
                        }
                    }
                    // `#` は LINE_BREAK を設定せずにそのまま扱う。
                }
                return true;
        }
    }
}

static inline bool scan_operator(TSLexer *lexer) {
    switch (lexer->lookahead) {
        // <, <=, <<, <=>
        case '<':
            advance(lexer);
            if (lexer->lookahead == '<') {
                advance(lexer);
            } else if (lexer->lookahead == '=') {
                advance(lexer);
                if (lexer->lookahead == '>') {
                    advance(lexer);
                }
            }
            return true;

        // >, >=, >>
        case '>':
            advance(lexer);
            if (lexer->lookahead == '>' || lexer->lookahead == '=') {
                advance(lexer);
            }
            return true;

        // ==, ===, =~
        case '=':
            advance(lexer);
            if (lexer->lookahead == '~') {
                advance(lexer);
                return true;
            }
            if (lexer->lookahead == '=') {
                advance(lexer);
                if (lexer->lookahead == '=') {
                    advance(lexer);
                }
                return true;
            }
            return false;

        // +, -, ~, +@, -@, ~@
        case '+':
        case '-':
        case '~':
            advance(lexer);
            if (lexer->lookahead == '@') {
                advance(lexer);
            }
            return true;

        // &, ^, |, /, %`
        case '&':
        case '^':
        case '|':
        case '/':
        case '%':
        case '`':
            advance(lexer);
            return true;

        // !, !=, !~
        case '!':
            advance(lexer);
            if (lexer->lookahead == '=' || lexer->lookahead == '~') {
                advance(lexer);
            }
            return true;

        // *, **
        case '*':
            advance(lexer);
            if (lexer->lookahead == '*') {
                advance(lexer);
            }
            return true;

        // [], []=
        case '[':
            advance(lexer);
            if (lexer->lookahead == ']') {
                advance(lexer);
            } else {
                return false;
            }
            if (lexer->lookahead == '=') {
                advance(lexer);
            }
            return true;

        default:
            return false;
    }
}

static inline bool scan_symbol_identifier(TSLexer *lexer) {
    bool has_variable_prefix = false;
    bool can_have_setter_suffix = false;
    if (lexer->lookahead == '@') {
        has_variable_prefix = true;
        advance(lexer);
        if (lexer->lookahead == '@') {
            advance(lexer);
        }
    } else if (lexer->lookahead == '$') {
        has_variable_prefix = true;
        advance(lexer);
        // `$` の直後で有効だが、is_iden_char や scan_operator では
        // 認識できない特殊グローバル変数文字を処理する。
        // 対象: $" $' $; $, $\ $$ $? $: $@ $. $=
        switch (lexer->lookahead) {
            case '"':
            case '\'':
            case ';':
            case ',':
            case '\\':
            case '$':
            case '?':
            case ':':
            case '@':
                advance(lexer);
                return true;
            case '.':
            case '=':
                // scan_operator より先に処理しないと過剰に読み進めてしまう。
                // 例: scan_operator('.') は `..` を期待し、scan_operator('=')
                // は `==` または `=~` を期待する。
                advance(lexer);
                return true;
            default:
                break;
        }
    }

    if (is_iden_char(lexer->lookahead)) {
        can_have_setter_suffix = !has_variable_prefix;
        advance(lexer);
    } else if (!scan_operator(lexer)) {
        return false;
    }

    while (is_iden_char(lexer->lookahead)) {
        advance(lexer);
    }

    if (lexer->lookahead == '?' || lexer->lookahead == '!') {
        advance(lexer);
        can_have_setter_suffix = false;
    }

    if (can_have_setter_suffix && lexer->lookahead == '=') {
        lexer->mark_end(lexer);
        advance(lexer);
        if (lexer->lookahead != '>') {
            lexer->mark_end(lexer);
        }
    }

    return true;
}

static inline bool scan_open_delimiter(Scanner *scanner, TSLexer *lexer, Literal *literal, const bool *valid_symbols) {
    switch (lexer->lookahead) {
        case '"':
            literal->type = STRING_START;
            literal->open_delimiter = literal->close_delimiter = lexer->lookahead;
            literal->allows_interpolation = true;
            advance(lexer);
            return true;

        case '\'':
            literal->type = STRING_START;
            literal->open_delimiter = literal->close_delimiter = lexer->lookahead;
            literal->allows_interpolation = false;
            advance(lexer);
            return true;

        case '`':
            if (!valid_symbols[SUBSHELL_START]) {
                return false;
            }
            literal->type = SUBSHELL_START;
            literal->open_delimiter = literal->close_delimiter = lexer->lookahead;
            literal->allows_interpolation = true;
            advance(lexer);
            return true;

        case '/':
            if (!valid_symbols[REGEX_START]) {
                return false;
            }
            literal->type = REGEX_START;
            literal->open_delimiter = literal->close_delimiter = lexer->lookahead;
            literal->allows_interpolation = true;
            advance(lexer);
            if (valid_symbols[FORWARD_SLASH]) {
                if (!scanner->has_leading_whitespace) {
                    return false;
                }
                if (lexer->lookahead == ' ' || lexer->lookahead == '\t' || lexer->lookahead == '\n' ||
                    lexer->lookahead == '\r') {
                    return false;
                }
                if (lexer->lookahead == '=') {
                    return false;
                }
            }
            return true;

        case '%':
            advance(lexer);

            switch (lexer->lookahead) {
                case 's':
                    if (!valid_symbols[SIMPLE_SYMBOL]) {
                        return false;
                    }
                    literal->type = SYMBOL_START;
                    literal->allows_interpolation = false;
                    advance(lexer);
                    break;

                case 'r':
                    if (!valid_symbols[REGEX_START]) {
                        return false;
                    }
                    literal->type = REGEX_START;
                    literal->allows_interpolation = true;
                    advance(lexer);
                    break;

                case 'x':
                    if (!valid_symbols[SUBSHELL_START]) {
                        return false;
                    }
                    literal->type = SUBSHELL_START;
                    literal->allows_interpolation = true;
                    advance(lexer);
                    break;

                case 'q':
                    if (!valid_symbols[STRING_START]) {
                        return false;
                    }
                    literal->type = STRING_START;
                    literal->allows_interpolation = false;
                    advance(lexer);
                    break;

                case 'Q':
                    if (!valid_symbols[STRING_START]) {
                        return false;
                    }
                    literal->type = STRING_START;
                    literal->allows_interpolation = true;
                    advance(lexer);
                    break;

                case 'w':
                    if (!valid_symbols[STRING_ARRAY_START]) {
                        return false;
                    }
                    literal->type = STRING_ARRAY_START;
                    literal->allows_interpolation = false;
                    advance(lexer);
                    break;

                case 'i':
                    if (!valid_symbols[SYMBOL_ARRAY_START]) {
                        return false;
                    }
                    literal->type = SYMBOL_ARRAY_START;
                    literal->allows_interpolation = false;
                    advance(lexer);
                    break;

                case 'W':
                    if (!valid_symbols[STRING_ARRAY_START]) {
                        return false;
                    }
                    literal->type = STRING_ARRAY_START;
                    literal->allows_interpolation = true;
                    advance(lexer);
                    break;

                case 'I':
                    if (!valid_symbols[SYMBOL_ARRAY_START]) {
                        return false;
                    }
                    literal->type = SYMBOL_ARRAY_START;
                    literal->allows_interpolation = true;
                    advance(lexer);
                    break;

                default:
                    if (!valid_symbols[STRING_START]) {
                        return false;
                    }
                    literal->type = STRING_START;
                    literal->allows_interpolation = true;
                    break;
            }

            switch (lexer->lookahead) {
                case '(':
                    literal->open_delimiter = '(';
                    literal->close_delimiter = ')';
                    break;

                case '[':
                    literal->open_delimiter = '[';
                    literal->close_delimiter = ']';
                    break;

                case '{':
                    literal->open_delimiter = '{';
                    literal->close_delimiter = '}';
                    break;

                case '<':
                    literal->open_delimiter = '<';
                    literal->close_delimiter = '>';
                    break;

                case '\r':
                case '\n':
                case ' ':
                case '\t':
                    // 空白も区切り文字になり得る (`% abc ` は文字列 "abc") が、
                    // Ruby がそう解釈するのは式の開始位置 (EXPR_BEG) にいるときだけ。
                    // `/` 演算子が有効なら `%` 演算子も有効なので、そこは剰余演算子。
                    if (valid_symbols[FORWARD_SLASH]) {
                        return false;
                    }
                    // 文字列リテラルの連結 (`"a" "b"`) を待っている位置では
                    // 文字列だけが有効で `%w[]` などは現れない。この位置の `%` も
                    // Ruby では剰余演算子なので percent literal を成立させない。
                    // 例: `"%s" % [a, b]` を空白区切りの文字列として飲み込むと
                    // ファイル末尾まで巻き込んで解析全体が壊れる。
                    if (!valid_symbols[STRING_ARRAY_START]) {
                        return false;
                    }
                    break;

                case '|':
                case '!':
                case '#':
                case '/':
                case '\\':
                case '@':
                case '$':
                case '%':
                case '^':
                case '&':
                case '*':
                case ')':
                case ']':
                case '}':
                case '>':
                case '=':
                    if (lexer->lookahead == '=' && valid_symbols[FORWARD_SLASH]) {
                        return false;
                    }
                    literal->open_delimiter = lexer->lookahead;
                    literal->close_delimiter = lexer->lookahead;
                    break;
                case '+':
                case '-':
                case '~':
                case '`':
                case ',':
                case '.':
                case '?':
                case ':':
                case ';':
                case '_':
                case '"':
                case '\'':
                    literal->open_delimiter = lexer->lookahead;
                    literal->close_delimiter = lexer->lookahead;
                    break;
                default:
                    return false;
            }

            advance(lexer);
            return true;

        default:
            return false;
    }
}

static inline bool is_heredoc_word_char(int32_t c) { return c >= 0x80 || iswalnum(c) || c == '_'; }

static inline bool scan_heredoc_word(TSLexer *lexer, Heredoc *heredoc) {
    String word = array_new();
    int32_t quote = 0;

    switch (lexer->lookahead) {
        case '\'':
        case '"':
        case '`':
            quote = lexer->lookahead;
            advance(lexer);
            while (lexer->lookahead != quote && lexer->lookahead != '\n' && lexer->lookahead != '\r' &&
                   !lexer->eof(lexer)) {
                if (!append_utf8_codepoint(&word, lexer->lookahead)) {
                    array_delete(&word);
                    return false;
                }
                advance(lexer);
            }
            if (lexer->lookahead != quote) {
                array_delete(&word);
                return false;
            }
            advance(lexer);
            break;

        default:
            if (is_heredoc_word_char(lexer->lookahead)) {
                if (!append_utf8_codepoint(&word, lexer->lookahead)) {
                    array_delete(&word);
                    return false;
                }
                advance(lexer);
                while (is_heredoc_word_char(lexer->lookahead)) {
                    if (!append_utf8_codepoint(&word, lexer->lookahead)) {
                        array_delete(&word);
                        return false;
                    }
                    advance(lexer);
                }
            } else {
                array_delete(&word);
                return false;
            }
            break;
    }

    heredoc->word = word;
    heredoc->allows_interpolation = quote != '\'';
    return true;
}

static inline bool scan_short_interpolation(TSLexer *lexer, const bool has_content, const TSSymbol content_symbol) {
    // `lexer->lookahead` は `int32_t` で Unicode 文字を保持する。
    // `(char)` に切り詰めると、ASCII 範囲外で下位 8 bit が
    // '@' (0x40) や '$' (0x24) と一致する文字
    // （例: `Ĥ` U+0124 → 下位 8 bit 0x24 = '$',
    //  `Ŀ` U+0140 → 下位 8 bit 0x40 = '@'）が
    // 短縮 interpolation の起点として誤判定されてしまうため、
    // `int32_t` のまま比較する。
    int32_t start = lexer->lookahead;
    if (start == '@' || start == '$') {
        if (has_content) {
            lexer->result_symbol = content_symbol;
            return true;
        }
        lexer->mark_end(lexer);
        advance(lexer);
        bool is_short_interpolation = false;
        if (start == '$') {
            // EOF の NUL を特殊グローバル変数の 1 文字として扱わない。
            if (lexer->lookahead != 0 && strchr("!@&`'+~=/\\,;.<>*$?:\"", lexer->lookahead) != NULL) {
                is_short_interpolation = true;
            } else {
                if (lexer->lookahead == '-') {
                    advance(lexer);
                    is_short_interpolation =
                        lexer->lookahead >= 0x80 || iswalpha(lexer->lookahead) || lexer->lookahead == '_';
                } else {
                    is_short_interpolation =
                        lexer->lookahead >= 0x80 || iswalnum(lexer->lookahead) || lexer->lookahead == '_';
                }
            }
        }
        if (start == '@') {
            if (lexer->lookahead == '@') {
                advance(lexer);
            }
            is_short_interpolation = is_iden_char(lexer->lookahead) && !iswdigit(lexer->lookahead);
        }

        if (is_short_interpolation) {
            lexer->result_symbol = SHORT_INTERPOLATION;
            return true;
        }
    }
    return false;
}

static inline bool scan_heredoc_content(Scanner *scanner, TSLexer *lexer) {
    Heredoc *heredoc = array_get(&scanner->open_heredocs, 0);
    size_t position_in_word = 0;
    bool look_for_heredoc_end = true;
    bool has_content = false;

    for (;;) {
        if (position_in_word == heredoc->word.size) {
            if (!has_content) {
                lexer->mark_end(lexer);
            }
            while (lexer->lookahead == ' ' || lexer->lookahead == '\t') {
                advance(lexer);
            }
            if (lexer->lookahead == '\n' || lexer->lookahead == '\r' || lexer->eof(lexer)) {
                if (has_content) {
                    lexer->result_symbol = HEREDOC_CONTENT;
                } else {
                    array_delete(&heredoc->word);
                    array_erase(&scanner->open_heredocs, 0);
                    lexer->result_symbol = HEREDOC_BODY_END;
                }
                return true;
            }
            has_content = true;
            position_in_word = 0;
        }

        if (lexer->eof(lexer)) {
            lexer->mark_end(lexer);
            if (has_content) {
                lexer->result_symbol = HEREDOC_CONTENT;
                return true;
            } else {
                return false;
            }
        }

        // 終端語は UTF-8 バイト列で保持する。lookahead の Unicode code point を
        // 同じ表現に変換して比較し、char への切り詰めによる誤不一致を防ぐ。
        uint32_t matched_bytes = look_for_heredoc_end
                                     ? match_utf8_codepoint(&heredoc->word, position_in_word, lexer->lookahead)
                                     : 0;
        if (matched_bytes > 0) {
            advance(lexer);
            position_in_word += matched_bytes;
        } else {
            position_in_word = 0;
            look_for_heredoc_end = false;

            if (heredoc->allows_interpolation && lexer->lookahead == '\\') {
                if (has_content) {
                    lexer->result_symbol = HEREDOC_CONTENT;
                    return true;
                }
                return false;
            }

            if (heredoc->allows_interpolation && lexer->lookahead == '#') {
                lexer->mark_end(lexer);
                advance(lexer);
                if (lexer->lookahead == '{') {
                    if (has_content) {
                        lexer->result_symbol = HEREDOC_CONTENT;
                        return true;
                    }
                    return false;
                }
                if (scan_short_interpolation(lexer, has_content, HEREDOC_CONTENT)) {
                    return true;
                }
            } else if (lexer->lookahead == '\r' || lexer->lookahead == '\n') {
                if (lexer->lookahead == '\r') {
                    advance(lexer);
                    if (lexer->lookahead == '\n') {
                        advance(lexer);
                    }
                } else {
                    advance(lexer);
                }
                has_content = true;
                look_for_heredoc_end = true;
                while (lexer->lookahead == ' ' || lexer->lookahead == '\t') {
                    advance(lexer);
                    if (!heredoc->end_word_indentation_allowed) {
                        look_for_heredoc_end = false;
                    }
                }
                lexer->mark_end(lexer);
            } else {
                has_content = true;
                advance(lexer);
                lexer->mark_end(lexer);
            }
        }
    }
}

static inline bool scan_literal_content(Scanner *scanner, TSLexer *lexer) {
    Literal *literal = array_back(&scanner->literal_stack);
    bool has_content = false;
    bool stop_on_space = literal->type == SYMBOL_ARRAY_START || literal->type == STRING_ARRAY_START;

    for (;;) {
        if (stop_on_space && iswspace(lexer->lookahead)) {
            if (has_content) {
                lexer->mark_end(lexer);
                lexer->result_symbol = STRING_CONTENT;
                return true;
            }
            return false;
        }
        if (lexer->lookahead == literal->close_delimiter) {
            lexer->mark_end(lexer);
            if (literal->nesting_depth == 1) {
                if (has_content) {
                    lexer->result_symbol = STRING_CONTENT;
                } else {
                    advance(lexer);
                    if (literal->type == REGEX_START) {
                        // lexer->lookahead が 0（EOF）のとき strchr は終端の NUL に
                        // マッチして非 NULL を返すため、`!= 0` で EOF を除外しないと
                        // ファイル末尾の正規表現（改行なし）で無限ループになる。
                        while (lexer->lookahead != 0 && strchr("imxouesn", lexer->lookahead) != NULL) {
                            advance(lexer);
                        }
                    }
                    array_pop(&scanner->literal_stack);
                    lexer->result_symbol = STRING_END;
                    lexer->mark_end(lexer);
                }
                return true;
            }
            literal->nesting_depth--;
            advance(lexer);

        } else if (lexer->lookahead == literal->open_delimiter) {
            literal->nesting_depth++;
            advance(lexer);
        } else if (literal->allows_interpolation && lexer->lookahead == '#') {
            lexer->mark_end(lexer);
            advance(lexer);
            if (lexer->lookahead == '{') {
                if (has_content) {
                    lexer->result_symbol = STRING_CONTENT;
                    return true;
                }
                return false;
            }
            if (scan_short_interpolation(lexer, has_content, STRING_CONTENT)) {
                return true;
            }
        } else if (lexer->lookahead == '\\') {
            if (literal->allows_interpolation) {
                if (has_content) {
                    lexer->mark_end(lexer);
                    lexer->result_symbol = STRING_CONTENT;
                    return true;
                }
                return false;
            }
            advance(lexer);
            advance(lexer);

        } else if (lexer->eof(lexer)) {
            advance(lexer);
            lexer->mark_end(lexer);
            return false;
        } else {
            advance(lexer);
        }

        has_content = true;
    }
}

static inline bool scan(Scanner *scanner, TSLexer *lexer, const bool *valid_symbols) {
    scanner->has_leading_whitespace = false;

    // 一部の閉じ区切り文字を除く任意文字に一致するリテラル内容を処理する。
    if (!valid_symbols[STRING_START]) {
        if ((valid_symbols[STRING_CONTENT] || valid_symbols[STRING_END]) && scanner->literal_stack.size > 0) {
            return scan_literal_content(scanner, lexer);
        }
        if ((valid_symbols[HEREDOC_CONTENT] || valid_symbols[HEREDOC_BODY_END]) && scanner->open_heredocs.size > 0) {
            return scan_heredoc_content(scanner, lexer);
        }
    }

    // 空白を処理する。
    lexer->result_symbol = NONE;
    if (!scan_whitespace(scanner, lexer, valid_symbols)) {
        return false;
    }
    if (lexer->result_symbol != NONE) {
        return true;
    }

    switch (lexer->lookahead) {
        case '&':
            if (valid_symbols[BLOCK_AMPERSAND] || valid_symbols[BINARY_AMPERSAND]) {
                advance(lexer);
                if (lexer->lookahead == '&' || lexer->lookahead == '.' || lexer->lookahead == '=') {
                    // `&&` / `&.` / `&=` は内部レキサに任せる。
                    return false;
                }
                // `&` の直後に空白があっても、二項 `&` が使えない位置
                // (`f(& blk)` のように直前に完結した式が無い位置) なら
                // Ruby はブロック引数の `&` として扱う。
                if (valid_symbols[BLOCK_AMPERSAND] &&
                    (!iswspace(lexer->lookahead) || !valid_symbols[BINARY_AMPERSAND])) {
                    lexer->result_symbol = BLOCK_AMPERSAND;
                    return true;
                }
                if (valid_symbols[BINARY_AMPERSAND]) {
                    lexer->result_symbol = BINARY_AMPERSAND;
                    return true;
                }
                return false;
            }
            break;

        case '<':
            if (valid_symbols[SINGLETON_CLASS_LEFT_ANGLE_LEFT_ANGLE]) {
                advance(lexer);
                if (lexer->lookahead == '<') {
                    advance(lexer);
                    lexer->result_symbol = SINGLETON_CLASS_LEFT_ANGLE_LEFT_ANGLE;
                    return true;
                }
                return false;
            }
            // 左シフト演算子が使える位置、つまり直前に完結した式がある位置での `<<`。
            // Ruby の字句規則では、この位置の `<<` が heredoc になるのは
            // `<<` の直前に空白がある場合だけで、`r<<i` のように空白がなければ
            // 常に左シフト演算子として扱われる。
            if (valid_symbols[BINARY_LEFT_SHIFT]) {
                advance(lexer);
                if (lexer->lookahead != '<') {
                    return false;
                }
                advance(lexer);
                if (lexer->lookahead == '=') {
                    // `<<=` は複合代入演算子なので内部レキサに任せる。
                    return false;
                }
                lexer->mark_end(lexer);

                if (valid_symbols[STRING_START] && scanner->has_leading_whitespace) {
                    Heredoc heredoc = {0};
                    if (lexer->lookahead == '-' || lexer->lookahead == '~') {
                        advance(lexer);
                        heredoc.end_word_indentation_allowed = true;
                    }
                    if (scan_heredoc_word(lexer, &heredoc)) {
                        if (can_serialize_heredocs_with(scanner, &heredoc)) {
                            lexer->mark_end(lexer);
                            array_push(&scanner->open_heredocs, heredoc);
                            lexer->result_symbol = HEREDOC_START;
                            return true;
                        }
                        array_delete(&heredoc.word);
                    }
                }

                lexer->result_symbol = BINARY_LEFT_SHIFT;
                return true;
            }
            break;

        case '*':
            if (valid_symbols[SPLAT_STAR] || valid_symbols[BINARY_STAR] || valid_symbols[HASH_SPLAT_STAR_STAR] ||
                valid_symbols[BINARY_STAR_STAR]) {
                advance(lexer);
                if (lexer->lookahead == '=') {
                    return false;
                }
                if (lexer->lookahead == '*') {
                    if (valid_symbols[HASH_SPLAT_STAR_STAR] || valid_symbols[BINARY_STAR_STAR]) {
                        advance(lexer);
                        if (lexer->lookahead == '=') {
                            return false;
                        }
                        if (valid_symbols[BINARY_STAR_STAR] && !scanner->has_leading_whitespace) {
                            lexer->result_symbol = BINARY_STAR_STAR;
                            return true;
                        }
                        if (valid_symbols[HASH_SPLAT_STAR_STAR] && !iswspace(lexer->lookahead)) {
                            lexer->result_symbol = HASH_SPLAT_STAR_STAR;
                            return true;
                        }
                        if (valid_symbols[BINARY_STAR_STAR]) {
                            lexer->result_symbol = BINARY_STAR_STAR;
                            return true;
                        }
                        if (valid_symbols[HASH_SPLAT_STAR_STAR]) {
                            lexer->result_symbol = HASH_SPLAT_STAR_STAR;
                            return true;
                        }
                        return false;
                    }
                    return false;
                }
                if (valid_symbols[BINARY_STAR] && !scanner->has_leading_whitespace) {
                    lexer->result_symbol = BINARY_STAR;
                    return true;
                }
                if (valid_symbols[SPLAT_STAR] && !iswspace(lexer->lookahead)) {
                    lexer->result_symbol = SPLAT_STAR;
                    return true;
                }
                if (valid_symbols[BINARY_STAR]) {
                    lexer->result_symbol = BINARY_STAR;
                    return true;
                }
                if (valid_symbols[SPLAT_STAR]) {
                    lexer->result_symbol = SPLAT_STAR;
                    return true;
                }
                return false;
            }
            break;

        case '-':
            if (valid_symbols[UNARY_MINUS] || valid_symbols[UNARY_MINUS_NUM] || valid_symbols[BINARY_MINUS]) {
                advance(lexer);
                if (lexer->lookahead != '=' && lexer->lookahead != '>') {
                    if (valid_symbols[UNARY_MINUS_NUM] &&
                        (!valid_symbols[BINARY_STAR] || scanner->has_leading_whitespace) &&
                        iswdigit(lexer->lookahead)) {
                        lexer->result_symbol = UNARY_MINUS_NUM;
                        return true;
                    }
                    if (valid_symbols[UNARY_MINUS] && scanner->has_leading_whitespace && !iswspace(lexer->lookahead)) {
                        lexer->result_symbol = UNARY_MINUS;
                    } else if (valid_symbols[BINARY_MINUS]) {
                        lexer->result_symbol = BINARY_MINUS;
                    } else {
                        lexer->result_symbol = UNARY_MINUS;
                    }
                    return true;
                }
                return false;
            }
            break;

        case ':':
            if (valid_symbols[SYMBOL_START]) {
                Literal literal = {0};
                literal.type = SYMBOL_START;
                literal.nesting_depth = 1;
                advance(lexer);

                switch (lexer->lookahead) {
                    case '"':
                        advance(lexer);
                        literal.open_delimiter = '"';
                        literal.close_delimiter = '"';
                        literal.allows_interpolation = true;
                        array_push(&scanner->literal_stack, literal);
                        lexer->result_symbol = SYMBOL_START;
                        return true;

                    case '\'':
                        advance(lexer);
                        literal.open_delimiter = '\'';
                        literal.close_delimiter = '\'';
                        literal.allows_interpolation = false;
                        array_push(&scanner->literal_stack, literal);
                        lexer->result_symbol = SYMBOL_START;
                        return true;

                    default:
                        if (scan_symbol_identifier(lexer)) {
                            lexer->result_symbol = SIMPLE_SYMBOL;
                            return true;
                        }
                }

                return false;
            }
            break;

        case '[':
            // 次のいずれかを満たす `[` は要素参照として扱う。
            // * 直前に空白がない
            // * 現在位置で任意式が妥当ではない
            if (valid_symbols[ELEMENT_REFERENCE_BRACKET] &&
                (!scanner->has_leading_whitespace || !valid_symbols[STRING_START])) {
                advance(lexer);
                lexer->result_symbol = ELEMENT_REFERENCE_BRACKET;
                return true;
            }
            break;

        default:
            break;
    }

    // 識別子接尾辞やハッシュキー記法を処理する。
    if (((valid_symbols[HASH_KEY_SYMBOL] || valid_symbols[IDENTIFIER_SUFFIX]) &&
         (iswalpha(lexer->lookahead) || lexer->lookahead == '_')) ||
        (valid_symbols[CONSTANT_SUFFIX] && iswupper(lexer->lookahead))) {
        TokenType validIdentifierSymbol = iswupper(lexer->lookahead) ? CONSTANT_SUFFIX : IDENTIFIER_SUFFIX;
        while (iswalnum(lexer->lookahead) || lexer->lookahead == '_') {
            advance(lexer);
        }

        if (valid_symbols[HASH_KEY_SYMBOL] && lexer->lookahead == ':') {
            lexer->mark_end(lexer);
            advance(lexer);
            if (lexer->lookahead != ':') {
                lexer->result_symbol = HASH_KEY_SYMBOL;
                return true;
            }
        } else if (valid_symbols[validIdentifierSymbol] && lexer->lookahead == '!') {
            advance(lexer);
            if (lexer->lookahead != '=') {
                lexer->result_symbol = validIdentifierSymbol;
                return true;
            }
        }

        return false;
    }

    // リテラル開始用の区切り文字を処理する。
    if (valid_symbols[STRING_START]) {
        Literal literal = {0};
        literal.nesting_depth = 1;

        if (lexer->lookahead == '<') {
            advance(lexer);
            if (lexer->lookahead != '<') {
                return false;
            }
            advance(lexer);

            Heredoc heredoc = {0};
            if (lexer->lookahead == '-' || lexer->lookahead == '~') {
                advance(lexer);
                heredoc.end_word_indentation_allowed = true;
            }

            if (!scan_heredoc_word(lexer, &heredoc)) {
                return false;
            }
            // 状態に保存できない長さの終端語は、後続行を誤って通常コードとして
            // パースしないため heredoc 開始自体を不成立にする。
            if (!can_serialize_heredocs_with(scanner, &heredoc)) {
                array_delete(&heredoc.word);
                return false;
            }
            array_push(&scanner->open_heredocs, heredoc);
            lexer->result_symbol = HEREDOC_START;
            return true;
        }

        if (scan_open_delimiter(scanner, lexer, &literal, valid_symbols)) {
            array_push(&scanner->literal_stack, literal);
            lexer->result_symbol = literal.type;
            return true;
        }
        return false;
    }

    return false;
}

void *tree_sitter_ruby_external_scanner_create() {
    Scanner *scanner = (Scanner *)ts_calloc(1, sizeof(Scanner));
    return scanner;
}

bool tree_sitter_ruby_external_scanner_scan(void *payload, TSLexer *lexer, const bool *valid_symbols) {
    Scanner *scanner = (Scanner *)payload;
    return scan(scanner, lexer, valid_symbols);
}

unsigned tree_sitter_ruby_external_scanner_serialize(void *payload, char *buffer) {
    Scanner *scanner = (Scanner *)payload;
    return serialize(scanner, buffer);
}

void tree_sitter_ruby_external_scanner_deserialize(void *payload, const char *buffer, unsigned length) {
    Scanner *scanner = (Scanner *)payload;
    deserialize(scanner, buffer, length);
}

void tree_sitter_ruby_external_scanner_destroy(void *payload) {
    Scanner *scanner = (Scanner *)payload;
    for (uint32_t i = 0; i < scanner->open_heredocs.size; i++) {
        array_delete(&array_get(&scanner->open_heredocs, i)->word);
    }
    array_delete(&scanner->open_heredocs);
    array_delete(&scanner->literal_stack);
    ts_free(scanner);
}
