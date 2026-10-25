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
    LAMBDA_BODY_BRACE,
    COMMAND_BLOCK_BRACE,
    RANGE_OPERAND,
    UNARY_PLUS_NUM,
    UNARY_PLUS,
    BINARY_PLUS,
    JUMP_ARGUMENT,
    HEREDOC_END_CONTINUED,
    HEREDOC_LINE_END,

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
    // 本文トークンを返した位置が終端行の先頭かどうかを保持する。
    bool end_line_pending;
    // 外側の heredoc 本文の行で開いた段の先頭かどうかを保持する。
    bool nested;
    // この段を開いた行が行継続 (`\` + 改行) で終わったかどうかを、段の先頭に保持する。
    bool continued;
} Heredoc;

typedef struct {
    bool has_leading_whitespace;
    // 演算子の直前の空白の最後の 1 文字が改ページ (U+000C) だったか。利用側が
    // 「直前の識別子はローカル変数」と判定した位置に置く手がかりで、Ruby の
    // EXPR_END と同じく、その演算子を引数の始まりではなく二項演算として読む。
    bool binary_operator_hint;
    Array(Literal) literal_stack;
    // 同じ行で開いた heredoc の列 (段) を、外側の段から順に連結して持つ。
    // index 0 以外の段の先頭には nested が立つ。その段は 1 つ前の段の先頭の
    // 本文の行で開いたもので、外側の本文の続きより先に、その行の次から読む。
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
    scanner->binary_operator_hint = false;
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

static inline bool can_serialize_with(Scanner *scanner, const Heredoc *new_heredoc, unsigned extra_literals) {
    size_t size = 2 + ((size_t)scanner->literal_stack.size + extra_literals) * SERIALIZED_LITERAL_SIZE;
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

    if (!can_serialize_with(scanner, NULL, 0)) {
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
        // フラグを同じバイトに詰め、終端語を保存できる容量を維持する。
        buffer[size++] = (char)(heredoc->started | (heredoc->end_line_pending << 1) | (heredoc->nested << 2) |
                                (heredoc->continued << 3));
        memcpy(&buffer[size], &heredoc->word.size, sizeof(uint32_t));
        size += sizeof(uint32_t);
        if (heredoc->word.size > 0) {
            memcpy(&buffer[size], heredoc->word.contents, heredoc->word.size);
        }
        size += heredoc->word.size;
    }

    return size;
}

// 復元した heredoc の段の並びが、走査で作りうる形かを確かめる。
// index 0 に入れ子の印 (nested) は付かず、入れ子の段は開始済みの段の先頭の本文の中で開く。
// 開始済みと行継続の印は段の先頭にだけ付き、終端行の保留は開始済みの本文にだけ付く。
static inline bool heredoc_frames_are_valid(const Scanner *scanner) {
    bool head_started = false;
    for (uint32_t i = 0; i < scanner->open_heredocs.size; i++) {
        const Heredoc *heredoc = array_get(&scanner->open_heredocs, i);
        bool is_head = i == 0 || heredoc->nested;
        if ((i == 0 && heredoc->nested) || (i > 0 && heredoc->nested && !head_started)) {
            return false;
        }
        if (((heredoc->started || heredoc->continued) && !is_head) ||
            (heredoc->end_line_pending && !heredoc->started)) {
            return false;
        }
        if (is_head) {
            head_started = heredoc->started;
        }
    }
    return true;
}

static inline void deserialize(Scanner *scanner, const char *buffer, unsigned length) {
    unsigned size = 0;
    scanner->has_leading_whitespace = false;
    scanner->binary_operator_hint = false;
    reset(scanner);

    if (length == 0) {
        return;
    }

    uint8_t literal_depth = buffer[size++];
    for (unsigned j = 0; j < literal_depth; j++) {
        // リテラル 1 件あたり SERIALIZED_LITERAL_SIZE バイト必要
        if (size + SERIALIZED_LITERAL_SIZE > length) goto invalid;
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

    if (size >= length) goto invalid;
    uint8_t open_heredoc_count = buffer[size++];
    for (unsigned j = 0; j < open_heredoc_count; j++) {
        // heredoc ヘッダー: フラグ 3 バイト + word_length 4 バイト = 最低 7 バイト
        if (size + SERIALIZED_HEREDOC_HEADER_SIZE > length) goto invalid;
        Heredoc heredoc = {0};
        heredoc.end_word_indentation_allowed = buffer[size++];
        heredoc.allows_interpolation = buffer[size++];
        uint8_t flags = (uint8_t)buffer[size++];
        if (flags & ~15) goto invalid;
        heredoc.started = flags & 1;
        heredoc.end_line_pending = flags & 2;
        heredoc.nested = flags & 4;
        heredoc.continued = flags & 8;

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
            goto invalid;
        }
        if (word_length > 0) {
            array_reserve(&heredoc.word, word_length);
            memcpy(heredoc.word.contents, &buffer[size], word_length);
        }
        heredoc.word.size = word_length;
        size += word_length;
        array_push(&scanner->open_heredocs, heredoc);
    }

    if (size != length || !heredoc_frames_are_valid(scanner)) goto invalid;
    return;

invalid:
    // 破損した入力では、途中まで復元した状態と確保した終端語をすべて破棄する。
    reset(scanner);
}

// end より手前で最後に始まる段の先頭の位置を返す。index 0 は常に段 0 の先頭。
static inline uint32_t frame_head_before(const Scanner *scanner, uint32_t end) {
    while (end > 1) {
        end--;
        if (array_get(&scanner->open_heredocs, end)->nested) {
            return end;
        }
    }
    return 0;
}

static inline uint32_t last_frame_head(const Scanner *scanner) {
    return frame_head_before(scanner, scanner->open_heredocs.size);
}

// 次の改行から本文を読む heredoc を返す。最後の段の先頭が未開始のときだけある。
static inline Heredoc *pending_heredoc(Scanner *scanner) {
    if (scanner->open_heredocs.size == 0) {
        return NULL;
    }
    Heredoc *head = array_get(&scanner->open_heredocs, last_frame_head(scanner));
    return head->started ? NULL : head;
}

// 本文を読んでいる heredoc (最も内側の開始済みの段の先頭) を探す。
// 最後の段が未開始なら、その段を開いた 1 つ前の段の先頭の本文を読んでいる。
static inline bool find_current_heredoc(const Scanner *scanner, uint32_t *index) {
    if (scanner->open_heredocs.size == 0) {
        return false;
    }
    uint32_t head = last_frame_head(scanner);
    if (!array_get(&scanner->open_heredocs, head)->started) {
        if (head == 0) {
            return false;
        }
        head = frame_head_before(scanner, head);
    }
    *index = head;
    return true;
}

// heredoc を開く。開始済みの本文の行で開いたものは、その本文の中で読む新しい段にする。
static inline void open_heredoc(Scanner *scanner, Heredoc heredoc) {
    heredoc.nested = scanner->open_heredocs.size > 0 &&
                     array_get(&scanner->open_heredocs, last_frame_head(scanner))->started;
    array_push(&scanner->open_heredocs, heredoc);
}

// 本文を読み終えた heredoc を外し、同じ段の次の heredoc を段の先頭にする。
// 引き継ぐのは段の先頭の印 (nested と continued) だけで、started と end_line_pending は引き継がない。
// 行継続で終わる行で開いた段を読み終えたら true を返す。
static inline bool close_heredoc(Scanner *scanner, uint32_t index) {
    // この本文の行で開いたまま始まらなかった段は、同じ段の後ろへ回して後で読む。
    uint32_t head = last_frame_head(scanner);
    if (head > index && !array_get(&scanner->open_heredocs, head)->started) {
        array_get(&scanner->open_heredocs, head)->nested = false;
        array_get(&scanner->open_heredocs, head)->continued = false;
    }

    Heredoc *heredoc = array_get(&scanner->open_heredocs, index);
    bool nested = heredoc->nested;
    bool continued = heredoc->continued;
    array_delete(&heredoc->word);
    array_erase(&scanner->open_heredocs, index);
    Heredoc *next = index < scanner->open_heredocs.size ? array_get(&scanner->open_heredocs, index) : NULL;
    if (next != NULL && !next->nested) {
        next->nested = index > 0 && nested;
        next->continued = continued;
        return false;
    }
    return continued;
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

// 正規表現リテラル末尾のオプション文字（`/x/im` の `im`）か判定する。
// `strchr("imxouesn", c)` では c が char へ切り詰められ、下位 8 bit が
// 一致する ASCII 外の文字（`ど` U+3069 → 0x69 = 'i'、`ũ` U+0169 も同じ）が
// オプションとして誤って消費されてしまう。int32_t のまま比較する。
static inline bool is_regex_option_char(int32_t c) {
    return c == 'i' || c == 'm' || c == 'x' || c == 'o' || c == 'u' || c == 'e' || c == 's' || c == 'n';
}

// 特殊グローバル変数（`$!` `$&` `$"` など）の 1 文字目か判定する。
// strchr は第 2 引数を char へ変換するため、`lexer->lookahead` をそのまま
// 渡すと下位 8 bit が一致する ASCII 外の文字が誤って一致する。EOF (0) も
// 終端 NUL に一致してしまうので、先に ASCII 範囲へ絞り込んでから照合する。
static inline bool is_special_global_variable_char(int32_t c) {
    return c > 0 && c < 0x80 && strchr("!@&`'+~=/\\,;.<>*$?:\"", (char)c) != NULL;
}

static inline bool scan_whitespace(Scanner *scanner, TSLexer *lexer, const bool *valid_symbols) {
    // heredoc 本文の補間の中でも、その行で開いた heredoc は次の改行から読む。
    Heredoc *pending = valid_symbols[HEREDOC_BODY_START] ? pending_heredoc(scanner) : NULL;
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
            case '\f':
                // Ruby は改ページを空白として読む。利用側は演算子の直前の空白 1 文字を
                // 改ページに置き換え、バイト位置を変えずに二項演算の手がかりを渡す。
                skip(scanner, lexer);
                scanner->binary_operator_hint = true;
                break;
            case '\r':
                if (pending != NULL) {
                    // CRLF の '\r' から本文を始める。終端の '\r' が先頭より前になるので、
                    // トークンは '\r' の位置の幅 0 になる。単独 CR は Ruby と同じく空白として
                    // 読み飛ばし、次の改行から本文を始める。このとき '\r' の手前の終端が残るが、
                    // この後に返すトークンはどれも終端を明示する (accept_token)。
                    lexer->mark_end(lexer);
                    skip(scanner, lexer);
                    if (lexer->lookahead == '\n') {
                        lexer->result_symbol = HEREDOC_BODY_START;
                        pending->started = true;
                        return true;
                    }
                } else {
                    skip(scanner, lexer);
                }
                break;
            case '\n':
                if (pending != NULL) {
                    lexer->mark_end(lexer);
                    lexer->result_symbol = HEREDOC_BODY_START;
                    pending->started = true;
                    return true;
                } else if (!valid_symbols[NO_LINE_BREAK] && valid_symbols[LINE_BREAK] && !crossed_newline) {
                    lexer->mark_end(lexer);
                    advance(lexer);
                    crossed_newline = true;
                    scanner->binary_operator_hint = false;
                } else {
                    skip(scanner, lexer);
                }
                break;
            case '\\':
                if (pending != NULL) {
                    // 行継続 (`\` + 改行) の行で開いた heredoc も、次の行から本文を読む。
                    // この段の最後の終端は終端行の改行まで含める (scan_heredoc_content)。
                    skip(scanner, lexer);
                    if (lexer->lookahead == '\r') {
                        lexer->mark_end(lexer);
                        skip(scanner, lexer);
                        if (lexer->lookahead != '\n') {
                            return false;
                        }
                    } else if (lexer->lookahead == '\n') {
                        lexer->mark_end(lexer);
                    } else if (iswspace(lexer->lookahead)) {
                        skip(scanner, lexer);
                        break;
                    } else {
                        return false;
                    }
                    lexer->result_symbol = HEREDOC_BODY_START;
                    pending->started = true;
                    pending->continued = true;
                    return true;
                }
                {
                    // 行継続 (`\` + 改行) は改行を消すだけなので、その前の改ページの手がかりを保つ
                    // (`count\f\` + 改行 + `+1` は `count + 1`)。
                    bool hint = scanner->binary_operator_hint;
                    advance(lexer);
                    if (lexer->lookahead == '\r') {
                        skip(scanner, lexer);
                    }
                    if (!iswspace(lexer->lookahead)) {
                        return false;
                    }
                    bool line_continuation = lexer->lookahead == '\n';
                    skip(scanner, lexer);
                    if (line_continuation) {
                        scanner->binary_operator_hint = hint;
                    }
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
                lexer->mark_end(lexer);
                return true;
            case '.':
            case '=':
                // scan_operator より先に処理しないと過剰に読み進めてしまう。
                // 例: scan_operator('.') は `..` を期待し、scan_operator('=')
                // は `==` または `=~` を期待する。
                advance(lexer);
                lexer->mark_end(lexer);
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

    // 終端は明示する (scan() が返すトークンの約束。accept_token を参照)。
    if (can_have_setter_suffix && lexer->lookahead == '=') {
        lexer->mark_end(lexer);
        advance(lexer);
        if (lexer->lookahead != '>') {
            lexer->mark_end(lexer);
        }
    } else {
        lexer->mark_end(lexer);
    }

    return true;
}

// 範囲演算子と return・break・next の後は、空白に依存せず引数の式が始まる。
static inline bool is_expression_start(const bool *valid_symbols) {
    return valid_symbols[RANGE_OPERAND] || valid_symbols[JUMP_ARGUMENT];
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
            // 範囲演算子と制御キーワードの直後は式の開始位置で、`/` は必ず正規表現の開始になる。
            // `_range_operand` / `_jump_argument` はマッチしないトークンで、その位置を
            // スキャナーに伝えるためだけに文法へ置いてある (`/a/../b/` が `(/a/../b/)`)。
            if (valid_symbols[FORWARD_SLASH] && !is_expression_start(valid_symbols)) {
                // ローカル変数の後の `/` は、空白の付き方によらず除算演算子。
                if (scanner->binary_operator_hint) {
                    return false;
                }
                // `//` と連続する場合は空の正規表現リテラル。
                // 除算演算子として読むと右辺が正規表現の開始になり、
                // 閉じない (`a // b` は Ruby でも構文エラー) ので、
                // 正しい Ruby では常に空の正規表現。
                if (lexer->lookahead == '/') {
                    return true;
                }
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
            // 引用文字列の連結だけを待つ位置では `%w[]` などの配列は有効でない。
            // この位置の `%` は、空白や型指定の有無によらず二項演算子になる。
            // `"%s"%[value]` や `"a"%q[x]` を後続の文字列として読まない。
            if (!valid_symbols[STRING_ARRAY_START]) {
                return false;
            }
            // ローカル変数の後の `%` は percent literal の開始ではなく剰余演算子。
            // `/` 演算子が有効な位置では `%` 演算子も有効になる。
            if (scanner->binary_operator_hint && valid_symbols[FORWARD_SLASH] && !is_expression_start(valid_symbols)) {
                return false;
            }
            advance(lexer);

            bool has_percent_type = true;
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
                    has_percent_type = false;
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

                case '\v':
                case '\f':
                    // VT/FF は scalar literal の区切りにもなる。配列では語の区切りとして
                    // 消費されて閉じられないため、開始として受理しない。
                    if (literal->type == STRING_ARRAY_START || literal->type == SYMBOL_ARRAY_START) {
                        return false;
                    }
                    // 型のない `%` と空白の組は式の開始位置だけでリテラルになる。
                    // `%Q` など型が明示されていればコマンド引数でもよい。
                    if (!has_percent_type && (valid_symbols[FORWARD_SLASH] || !valid_symbols[STRING_ARRAY_START])) {
                        return false;
                    }
                    literal->open_delimiter = literal->close_delimiter = lexer->lookahead;
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

// `[` の直後から、対応する `]` と、その後に続く代入の `=` を先読みする。
// `h [k] = v` のように空白を挟んだ添字代入を、コマンド呼び出しの配列引数
// (`h([k])`) と区別するために使う。`h([k]) = v` は Ruby では書けないので、
// `]` の直後に `=` が来ればその `[` は添字参照だと確定できる。
// 添字の中では改行やコメントを許し、走査文字数には上限を設ける。
static inline bool scan_index_assignment_ahead(TSLexer *lexer) {
    uint32_t depth = 1;
    uint32_t budget = 4096;

    while (depth > 0) {
        if (budget-- == 0 || lexer->eof(lexer)) {
            return false;
        }
        int32_t c = lexer->lookahead;
        if (c == '#') {
            // コメント内の `[` / `]` は添字の括弧として数えない。
            do {
                if (budget-- == 0) {
                    return false;
                }
                advance(lexer);
            } while (!lexer->eof(lexer) && lexer->lookahead != '\n' && lexer->lookahead != '\r');
            continue;
        }
        if (c == '\'' || c == '"') {
            // 文字列中の括弧を数えないよう読み飛ばす。
            advance(lexer);
            while (lexer->lookahead != c) {
                if (budget-- == 0 || lexer->eof(lexer)) {
                    return false;
                }
                if (lexer->lookahead == '\\') {
                    advance(lexer);
                    if (lexer->eof(lexer)) {
                        return false;
                    }
                }
                advance(lexer);
            }
            advance(lexer);
            continue;
        }
        if (c == '[') {
            depth++;
        } else if (c == ']') {
            depth--;
        }
        advance(lexer);
    }

    while (lexer->lookahead == ' ' || lexer->lookahead == '\t') {
        advance(lexer);
    }

    // 複合代入 (`+=` / `||=` / `<<=` など) の演算子部分を読み飛ばす。
    // `<=` / `>=` は比較演算子なので `<<` / `>>` の形だけを許す。
    int32_t op = lexer->lookahead;
    if (op == '+' || op == '-' || op == '*' || op == '/' || op == '%' || op == '|' || op == '&' || op == '^') {
        advance(lexer);
        if (lexer->lookahead == op && (op == '*' || op == '|' || op == '&')) {
            advance(lexer);
        }
    } else if (op == '<' || op == '>') {
        advance(lexer);
        if (lexer->lookahead != op) {
            return false;
        }
        advance(lexer);
    }

    if (lexer->lookahead != '=') {
        return false;
    }
    advance(lexer);
    // `==` / `=~` / `=>` は代入ではない。
    return lexer->lookahead != '=' && lexer->lookahead != '~' && lexer->lookahead != '>';
}

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
            // EOF の NUL も ASCII 外の文字も、特殊グローバル変数の
            // 1 文字目としては扱わない（判定は is_special_global_variable_char）。
            if (is_special_global_variable_char(lexer->lookahead)) {
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

static inline bool scan_heredoc_content(Scanner *scanner, TSLexer *lexer, const bool *valid_symbols) {
    uint32_t index;
    if (!find_current_heredoc(scanner, &index)) {
        return false;
    }
    Heredoc *heredoc = array_get(&scanner->open_heredocs, index);
    // この本文の行の補間で開いた heredoc は、行末の改行から外側の本文より先に読む。
    Heredoc *nested = NULL;
    if (valid_symbols[HEREDOC_BODY_START] && last_frame_head(scanner) > index) {
        nested = pending_heredoc(scanner);
    }
    size_t position_in_word = 0;
    bool look_for_heredoc_end = true;
    bool has_content = false;
    // interpolation・エスケープの直後は行途中なので終端語として扱わない。
    // 本文を返す前に見つけた終端行は、インデントの分だけ列が 0 でない
    // 場合もあるため、get_column() ではなく保存した状態で判定する。
    bool at_line_start = heredoc->end_line_pending;
    heredoc->end_line_pending = false;

    for (;;) {
        if (position_in_word == heredoc->word.size && at_line_start && look_for_heredoc_end) {
            if (!has_content) {
                lexer->mark_end(lexer);
            }
            // 空の終端語では、改行後の EOF だけを架空の空行とみなさない。
            bool at_line_end = lexer->lookahead == '\n' ||
                (lexer->eof(lexer) && (heredoc->word.size > 0 || lexer->get_column(lexer) > 0));
            if (lexer->lookahead == '\r') {
                // CRLF は行末だが、単独 CR や終端語の後の空白は本文に残す。
                advance(lexer);
                at_line_end = lexer->lookahead == '\n';
            }
            if (at_line_end) {
                if (has_content) {
                    heredoc->end_line_pending = true;
                    lexer->result_symbol = HEREDOC_CONTENT;
                } else {
                    // 行継続で終わる行で開いた段では、開いた行の改行が行継続で消えている。
                    // 段の最後の終端では、Ruby と同じく終端行の改行も heredoc 側に含め、
                    // コードの改行に戻さない (戻すと、行継続でつながる次の行との間に文の区切り
                    // ができる)。終端語の後に HEREDOC_LINE_END で終端行の改行を返す。
                    bool continued = close_heredoc(scanner, index);
                    lexer->result_symbol = continued && lexer->lookahead == '\n' && valid_symbols[HEREDOC_END_CONTINUED]
                                               ? HEREDOC_END_CONTINUED
                                               : HEREDOC_BODY_END;
                }
                return true;
            }
            has_content = true;
            position_in_word = 0;
            at_line_start = false;
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
            // 終端語の一部と一致した文字も、照合に失敗すれば本文になる。
            has_content = has_content || position_in_word > 0;
            position_in_word = 0;
            look_for_heredoc_end = false;

            if (heredoc->allows_interpolation && lexer->lookahead == '\\') {
                if (has_content) {
                    lexer->mark_end(lexer);
                    lexer->result_symbol = HEREDOC_CONTENT;
                    return true;
                }
                // 行末の '\' (行継続) は改行ごと escape_sequence になり、入れ子の本文を始める
                // 行末を飲み込む。Ruby は行継続の行でも次の行から入れ子の本文を読むので、
                // '\' だけを本文として返し、次の走査でその行末から入れ子の本文を始める。
                if (nested != NULL) {
                    advance(lexer);
                    lexer->mark_end(lexer);
                    if (lexer->lookahead == '\r') {
                        advance(lexer);
                    }
                    if (lexer->lookahead == '\n') {
                        lexer->result_symbol = HEREDOC_CONTENT;
                        return true;
                    }
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
                // 補間にならなかった '#' (と短縮補間に続かない '@' / '$') も本文に含める。
                has_content = true;
                lexer->mark_end(lexer);
            } else if (nested != NULL && (lexer->lookahead == '\n' || lexer->lookahead == '\r')) {
                // 入れ子の本文は、空白の経路と同じく行末 (CRLF は '\r') から始める。
                // 外側の本文はその手前で区切り、単独 CR は本文に残す。
                lexer->mark_end(lexer);
                if (lexer->lookahead == '\r') {
                    advance(lexer);
                    if (lexer->lookahead != '\n') {
                        has_content = true;
                        lexer->mark_end(lexer);
                        continue;
                    }
                }
                if (has_content) {
                    lexer->result_symbol = HEREDOC_CONTENT;
                } else {
                    nested->started = true;
                    lexer->result_symbol = HEREDOC_BODY_START;
                }
                return true;
            } else if (lexer->lookahead == '\n') {
                advance(lexer);
                has_content = true;
                look_for_heredoc_end = true;
                at_line_start = true;
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

static inline bool scan_literal_content(Scanner *scanner, TSLexer *lexer, const bool *valid_symbols) {
    Literal *literal = array_back(&scanner->literal_stack);
    bool has_content = false;
    bool stop_on_space = literal->type == SYMBOL_ARRAY_START || literal->type == STRING_ARRAY_START;
    // リテラルより前に同じ行で開いた heredoc は、リテラルの中の改行から本文を読む (Ruby と同じ順)。
    Heredoc *pending = valid_symbols[HEREDOC_BODY_START] ? pending_heredoc(scanner) : NULL;
    // 補間しない配列で、直前の `\` が改行をエスケープした。
    bool escaped_line_end = false;

    for (;;) {
        if (pending != NULL && stop_on_space && !has_content && iswspace(lexer->lookahead) &&
            lexer->lookahead != literal->close_delimiter) {
            // 配列の語の間の空白は、内部の字句解析が区切りとして読む。その中に本文を始める改行
            // (LF か CRLF) があるときだけ、手前の空白 (単独 CR を含む) を読み飛ばして改行から
            // 本文を始める。閉じ区切りや語に着いたら、区切りとして内部の字句解析に任せる。
            for (;;) {
                if (lexer->lookahead == literal->close_delimiter || !iswspace(lexer->lookahead)) {
                    return false;
                }
                if (lexer->lookahead == '\n') {
                    lexer->mark_end(lexer);
                    break;
                }
                if (lexer->lookahead == '\r') {
                    // CRLF なら '\r' の位置で幅 0 の開始になる (終端が先頭より前)。
                    lexer->mark_end(lexer);
                    skip(scanner, lexer);
                    if (lexer->lookahead == '\n') {
                        break;
                    }
                    continue;
                }
                skip(scanner, lexer);
            }
            pending->started = true;
            lexer->result_symbol = HEREDOC_BODY_START;
            return true;
        }
        if (pending != NULL && lexer->lookahead != literal->close_delimiter &&
            (lexer->lookahead == '\n' || lexer->lookahead == '\r')) {
            // 本文は LF なら '\n'、CRLF なら '\r' から始め、リテラルの内容はその手前で区切る。
            lexer->mark_end(lexer);
            if (lexer->lookahead == '\r') {
                advance(lexer);
            }
            if (lexer->lookahead == '\n') {
                if (has_content) {
                    if (escaped_line_end) {
                        pending->continued = true;
                    }
                    lexer->result_symbol = STRING_CONTENT;
                } else {
                    pending->started = true;
                    lexer->result_symbol = HEREDOC_BODY_START;
                }
                return true;
            }
            // 単独 CR は、文字列では内容、配列では語の区切りの空白になる。ただし直前の `\` で
            // エスケープした CR は、配列でも語の一部になる。
            if (stop_on_space && !escaped_line_end) {
                if (has_content) {
                    lexer->result_symbol = STRING_CONTENT;
                    return true;
                }
                return false;
            }
            escaped_line_end = false;
            has_content = true;
            continue;
        }
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
                        // `is_regex_option_char` は int32_t のまま比較するため、
                        // EOF（0）も ASCII 外の文字も自然に弾ける。strchr を使うと
                        // EOF が終端 NUL に一致して無限ループになり、さらに下位
                        // 8 bit の衝突で `ど`（U+3069）などが誤って消費される。
                        while (is_regex_option_char(lexer->lookahead)) {
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
                // 行末の `\` は改行ごと escape_sequence になり、heredoc の本文を始める改行を
                // 飲み込む。`\` だけを内容として返し、次の走査でその改行から本文を始める。
                // 改行はエスケープされている (文字列では行継続、配列では語の一部) ので、
                // 段の最後の終端行の改行も heredoc 側に含め、リテラルに戻さない。
                if (pending != NULL) {
                    advance(lexer);
                    lexer->mark_end(lexer);
                    if (lexer->lookahead == '\r') {
                        advance(lexer);
                    }
                    if (lexer->lookahead == '\n') {
                        pending->continued = true;
                        lexer->result_symbol = STRING_CONTENT;
                        return true;
                    }
                }
                return false;
            }
            advance(lexer);
            // 補間しないリテラルの `\` の後の改行は読み進めず、上の分岐で本文を始める。
            // 文字列では `\` と改行がそのまま残るが、配列では改行が語の一部になる。
            if (pending != NULL && (lexer->lookahead == '\n' || lexer->lookahead == '\r')) {
                escaped_line_end = stop_on_space;
            } else {
                advance(lexer);
            }

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

// トークンを現在位置で終える。scan() が返すトークンは、既定の終端 (返したときの位置) に
// 頼らず終端を明示する。scan_whitespace() が単独 CR を確かめるために '\r' の手前で呼んだ
// mark_end が残っていると、既定の終端はその位置になり、トークンが幅 0 になるため。
static inline bool accept_token(TSLexer *lexer, TokenType symbol) {
    lexer->mark_end(lexer);
    lexer->result_symbol = symbol;
    return true;
}

static inline bool scan(Scanner *scanner, TSLexer *lexer, const bool *valid_symbols) {
    scanner->has_leading_whitespace = false;
    scanner->binary_operator_hint = false;

    // 一部の閉じ区切り文字を除く任意文字に一致するリテラル内容を処理する。
    if (!valid_symbols[STRING_START]) {
        // 行継続の段の最後の終端語の後は、終端行の改行 (LF か CRLF) だけが続く。
        if (valid_symbols[HEREDOC_LINE_END]) {
            if (lexer->lookahead == '\r') {
                advance(lexer);
            }
            if (lexer->lookahead != '\n') {
                return false;
            }
            advance(lexer);
            return accept_token(lexer, HEREDOC_LINE_END);
        }
        if ((valid_symbols[STRING_CONTENT] || valid_symbols[STRING_END]) && scanner->literal_stack.size > 0) {
            return scan_literal_content(scanner, lexer, valid_symbols);
        }
        if ((valid_symbols[HEREDOC_CONTENT] || valid_symbols[HEREDOC_BODY_END]) && scanner->open_heredocs.size > 0) {
            return scan_heredoc_content(scanner, lexer, valid_symbols);
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
        case '{':
            // 括弧なし仮引数リストの直後の `{` は lambda の本体。Ruby も
            // `tLAMBEG` として区別しており、直前の呼び出しのブロックには
            // ならない (`-> a=f() { }` の `{` は f のブロックではない)。
            if (valid_symbols[LAMBDA_BODY_BRACE]) {
                advance(lexer);
                return accept_token(lexer, LAMBDA_BODY_BRACE);
            }
            // 括弧なしメソッド呼び出しの直後の `{` は Ruby では常にブロック。
            // ハッシュを唯一の引数にするには `foo({...})` と括弧が要るため、
            // この位置ではハッシュリテラルの開始として解釈してはならない。
            if (valid_symbols[COMMAND_BLOCK_BRACE]) {
                advance(lexer);
                return accept_token(lexer, COMMAND_BLOCK_BRACE);
            }
            break;

        case '&':
            if (valid_symbols[BLOCK_AMPERSAND] || valid_symbols[BINARY_AMPERSAND]) {
                advance(lexer);
                if (lexer->lookahead == '&' || lexer->lookahead == '.' || lexer->lookahead == '=') {
                    // `&&` / `&.` / `&=` は内部レキサに任せる。
                    return false;
                }
                // ローカル変数の後の `&` は、Ruby ではブロック引数にならない。
                if (scanner->binary_operator_hint && valid_symbols[BINARY_AMPERSAND]) {
                    return accept_token(lexer, BINARY_AMPERSAND);
                }
                // `&` の直後に空白があっても、二項 `&` が使えない位置
                // (`f(& blk)` のように直前に完結した式が無い位置) なら
                // Ruby はブロック引数の `&` として扱う。
                if (valid_symbols[BLOCK_AMPERSAND] &&
                    (!iswspace(lexer->lookahead) || !valid_symbols[BINARY_AMPERSAND])) {
                    return accept_token(lexer, BLOCK_AMPERSAND);
                }
                if (valid_symbols[BINARY_AMPERSAND]) {
                    return accept_token(lexer, BINARY_AMPERSAND);
                }
                return false;
            }
            break;

        case '<':
            if (valid_symbols[SINGLETON_CLASS_LEFT_ANGLE_LEFT_ANGLE]) {
                advance(lexer);
                if (lexer->lookahead == '<') {
                    advance(lexer);
                    return accept_token(lexer, SINGLETON_CLASS_LEFT_ANGLE_LEFT_ANGLE);
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

                // ローカル変数の後の `<<` は heredoc を開かない。
                if (valid_symbols[STRING_START] && scanner->has_leading_whitespace && !scanner->binary_operator_hint) {
                    Heredoc heredoc = {0};
                    if (lexer->lookahead == '-' || lexer->lookahead == '~') {
                        advance(lexer);
                        heredoc.end_word_indentation_allowed = true;
                    }
                    if (scan_heredoc_word(lexer, &heredoc)) {
                        if (can_serialize_with(scanner, &heredoc, 0)) {
                            lexer->mark_end(lexer);
                            open_heredoc(scanner, heredoc);
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
                        if (valid_symbols[BINARY_STAR_STAR] &&
                            (!scanner->has_leading_whitespace || scanner->binary_operator_hint)) {
                            return accept_token(lexer, BINARY_STAR_STAR);
                        }
                        if (valid_symbols[HASH_SPLAT_STAR_STAR] && !iswspace(lexer->lookahead)) {
                            return accept_token(lexer, HASH_SPLAT_STAR_STAR);
                        }
                        if (valid_symbols[BINARY_STAR_STAR]) {
                            return accept_token(lexer, BINARY_STAR_STAR);
                        }
                        if (valid_symbols[HASH_SPLAT_STAR_STAR]) {
                            return accept_token(lexer, HASH_SPLAT_STAR_STAR);
                        }
                        return false;
                    }
                    return false;
                }
                if (valid_symbols[BINARY_STAR] && (!scanner->has_leading_whitespace || scanner->binary_operator_hint)) {
                    return accept_token(lexer, BINARY_STAR);
                }
                if (valid_symbols[SPLAT_STAR] && !iswspace(lexer->lookahead)) {
                    return accept_token(lexer, SPLAT_STAR);
                }
                if (valid_symbols[BINARY_STAR]) {
                    return accept_token(lexer, BINARY_STAR);
                }
                if (valid_symbols[SPLAT_STAR]) {
                    return accept_token(lexer, SPLAT_STAR);
                }
                return false;
            }
            break;

        case '+':
            if (valid_symbols[UNARY_PLUS] || valid_symbols[UNARY_PLUS_NUM] || valid_symbols[BINARY_PLUS]) {
                advance(lexer);
                if (lexer->lookahead == '=') {
                    return false;
                }
                // ローカル変数の後の `+` は、空白の付き方によらず二項演算。
                if (scanner->binary_operator_hint && valid_symbols[BINARY_PLUS] && !is_expression_start(valid_symbols)) {
                    return accept_token(lexer, BINARY_PLUS);
                }
                // 数値に隣接する符号だけをリテラルに結び付ける。式の開始位置では二項演算にしない。
                if (valid_symbols[UNARY_PLUS_NUM] &&
                    (is_expression_start(valid_symbols) || !valid_symbols[BINARY_STAR] || scanner->has_leading_whitespace) &&
                    lexer->lookahead >= '0' && lexer->lookahead <= '9') {
                    return accept_token(lexer, UNARY_PLUS_NUM);
                }
                if (valid_symbols[UNARY_PLUS] &&
                    (is_expression_start(valid_symbols) ||
                     (scanner->has_leading_whitespace && !iswspace(lexer->lookahead)))) {
                    return accept_token(lexer, UNARY_PLUS);
                }
                return accept_token(lexer, valid_symbols[BINARY_PLUS] ? BINARY_PLUS : UNARY_PLUS);
            }
            break;

        case '-':
            if (valid_symbols[UNARY_MINUS] || valid_symbols[UNARY_MINUS_NUM] || valid_symbols[BINARY_MINUS]) {
                advance(lexer);
                if (lexer->lookahead != '=' && lexer->lookahead != '>') {
                    // ローカル変数の後の `-` は、空白の付き方によらず二項演算。
                    if (scanner->binary_operator_hint && valid_symbols[BINARY_MINUS] &&
                        !is_expression_start(valid_symbols)) {
                        return accept_token(lexer, BINARY_MINUS);
                    }
                    if (valid_symbols[UNARY_MINUS_NUM] &&
                        (is_expression_start(valid_symbols) || !valid_symbols[BINARY_STAR] || scanner->has_leading_whitespace) &&
                        iswdigit(lexer->lookahead)) {
                        return accept_token(lexer, UNARY_MINUS_NUM);
                    }
                    if (valid_symbols[UNARY_MINUS] &&
                        (is_expression_start(valid_symbols) ||
                         (scanner->has_leading_whitespace && !iswspace(lexer->lookahead)))) {
                        return accept_token(lexer, UNARY_MINUS);
                    }
                    return accept_token(lexer, valid_symbols[BINARY_MINUS] ? BINARY_MINUS : UNARY_MINUS);
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
                        if (!can_serialize_with(scanner, NULL, 1)) return false;
                        array_push(&scanner->literal_stack, literal);
                        return accept_token(lexer, SYMBOL_START);

                    case '\'':
                        advance(lexer);
                        literal.open_delimiter = '\'';
                        literal.close_delimiter = '\'';
                        literal.allows_interpolation = false;
                        if (!can_serialize_with(scanner, NULL, 1)) return false;
                        array_push(&scanner->literal_stack, literal);
                        return accept_token(lexer, SYMBOL_START);

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
            // * 直前の識別子がローカル変数だという手がかりがある
            // * 対応する `]` の直後に代入の `=` が続く (`h [k] = v`)
            if (valid_symbols[ELEMENT_REFERENCE_BRACKET]) {
                advance(lexer);
                lexer->mark_end(lexer);
                if (!scanner->has_leading_whitespace || !valid_symbols[STRING_START] || scanner->binary_operator_hint) {
                    lexer->result_symbol = ELEMENT_REFERENCE_BRACKET;
                    return true;
                }
                if (scan_index_assignment_ahead(lexer)) {
                    lexer->result_symbol = ELEMENT_REFERENCE_BRACKET;
                    return true;
                }
                return false;
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
                return accept_token(lexer, validIdentifierSymbol);
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
            if (!can_serialize_with(scanner, &heredoc, 0)) {
                array_delete(&heredoc.word);
                return false;
            }
            open_heredoc(scanner, heredoc);
            return accept_token(lexer, HEREDOC_START);
        }

        if (scan_open_delimiter(scanner, lexer, &literal, valid_symbols)) {
            // リテラルの追加でも、開いている heredoc と合わせた保存容量を確認する。
            if (!can_serialize_with(scanner, NULL, 1)) return false;
            array_push(&scanner->literal_stack, literal);
            return accept_token(lexer, literal.type);
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
