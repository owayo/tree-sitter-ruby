# Constant definitions
MAX_RETRIES = 3
# ^ definition.constant

# Documented constant
TIMEOUT_SECONDS = 30
# ^ definition.constant

# Constant with scope resolution
Module::NESTED_CONST = "value"
#        ^ definition.constant

class MyClass
  # Class-level constant
  DEFAULT_VALUE = 100
  # ^ definition.constant

  ITEMS_PER_PAGE = 20
  # ^ definition.constant
end
