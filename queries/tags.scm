; メソッド定義

(
  (comment)* @doc
  .
  [
    (method
      name: (_) @name) @definition.method
    (singleton_method
      name: (_) @name) @definition.method
  ]
  (#strip! @doc "^#\\s*")
  (#select-adjacent! @doc @definition.method)
)

(alias
  name: (_) @name) @definition.method

(setter
  (identifier) @ignore)

; クラス定義

(
  (comment)* @doc
  .
  [
    (class
      name: [
        (constant) @name
        (scope_resolution
          name: (_) @name)
      ]) @definition.class
    (singleton_class
      value: [
        (constant) @name
        (scope_resolution
          name: (_) @name)
      ]) @definition.class
  ]
  (#strip! @doc "^#\\s*")
  (#select-adjacent! @doc @definition.class)
)

; モジュール定義

(
  (comment)* @doc
  .
  (module
    name: [
      (constant) @name
      (scope_resolution
        name: (_) @name)
    ]) @definition.module
  (#strip! @doc "^#\\s*")
  (#select-adjacent! @doc @definition.module)
)

; 定数定義

(
  (comment)* @doc
  .
  (assignment
    left: [
      (constant) @name
      (scope_resolution
        name: (constant) @name)
    ]) @definition.constant
  (#strip! @doc "^#\\s*")
  (#select-adjacent! @doc @definition.constant)
)

; 呼び出し

(
  (call method: (identifier) @name) @reference.call
  ; 組み込みの擬似メソッドはタグ参照としては扱わない。
  (#not-match? @name "^(lambda|load|require|require_relative|__FILE__|__LINE__)$")
)

(
  [(identifier) (constant)] @name @reference.call
  (#is-not? local)
  (#not-match? @name "^(lambda|load|require|require_relative|__FILE__|__LINE__)$")
)
