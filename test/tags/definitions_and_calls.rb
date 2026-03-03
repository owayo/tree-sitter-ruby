# Module definition with namespace path
module MyApp::Feature
#             ^ definition.module

  class Core::Worker
  #           ^ definition.class

    STATUS = "ok"
    # ^ definition.constant
    LIMIT = 10
    # ^ definition.constant

    def run
    #   ^ definition.method
      helper
      # ^ reference.call
      puts STATUS
      # ^ reference.call
      #    ^ reference.call
    end

    def self.build
    #        ^ definition.method
      helper
      # ^ reference.call
    end

    def mutate
    #   ^ definition.method
      STATUS ||= "warm"
      # ^ reference.call
      LIMIT += 1
      # ^ reference.call
    end
  end
end

def boot_require
#   ^ definition.method
  require "json"
  require_relative "lib/helper"
  load "seed.rb"
  lambda { helper }
  #        ^ reference.call
end

class << Service
#        ^ definition.class
  def boot
  #   ^ definition.method
    run
    # ^ reference.call
  end
end

alias old_name new_name
#     ^ definition.method
