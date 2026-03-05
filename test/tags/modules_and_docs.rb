# ドキュメント付きメソッド定義
# @definition.method
class MyApp
# ^ definition.class

  module Services
  #      ^ definition.module

    # ユーザーを検索する
    def find_user(id)
    #   ^ definition.method
    end

    # シングルトンメソッド
    def self.create(attrs)
    #        ^ definition.method
    end

    alias find find_user
    #     ^ definition.method
  end
end

# ネストされたスコープの定数定義
module Outer
#      ^ definition.module

  Inner::TIMEOUT = 30
  #      ^ definition.constant

  API_VERSION = "v2"
  # ^ definition.constant
end

# ドキュメントコメント付きモジュール定義
# アプリケーション全体の設定を管理する
module Configuration
#      ^ definition.module
end

# ドキュメントコメント付きスコープ解決モジュール
# ネットワーク関連のユーティリティ
module Utils::Network
#            ^ definition.module
end

# メソッド呼び出し参照
obj.process
#   ^ reference.call

validate(input)
# ^ reference.call
