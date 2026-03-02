# frozen_string_literal: true

# Real-world Ruby patterns derived from Rails and RuboCop sources
# Used to validate tree-sitter-ruby parser correctness

# --- Pattern 1: Complex rescue/ensure with multiple exception types ---
def safe_execute
  perform_action
rescue ArgumentError, TypeError => e
  warn "Type error: #{e.message}"
  STATUS_ERROR
rescue RuntimeError => e
  warn "Runtime: #{e.message}"
  STATUS_FAILURE
rescue Interrupt
  warn "Interrupted"
  STATUS_INTERRUPTED
ensure
  elapsed = Process.clock_gettime(Process::CLOCK_MONOTONIC)
end

# --- Pattern 2: Heredoc with method chain ---
def warning_message
  <<~MSG.strip.freeze
    Configuration error detected.
    Please check your settings file.
  MSG
end

# --- Pattern 3: Safe navigation operator chains ---
def fetch_timeout(params)
  params[:timeout]&.to_i&.clamp(1, 30) || 10
end

# --- Pattern 4: class_eval with heredoc interpolation ---
def self.define_handler(event_name)
  class_eval(<<~RUBY, __FILE__, __LINE__ + 1)
    def on_#{event_name}(node)
      process_event(:on_#{event_name}, node)
    end
  RUBY
end

# --- Pattern 5: Lambda/Proc variations ---
double = ->(x) { x * 2 }
greet = lambda { |name| "Hello, #{name}!" }
validator = proc { |val| val.is_a?(String) && val.length > 0 }
noop = -> {}

# --- Pattern 6: Multiple assignment and destructuring ---
first, *rest = [1, 2, 3, 4, 5]
a, (b, c) = [1, [2, 3]]
x, = *[10, 20]

# --- Pattern 7: Complex block parameters with destructuring ---
pairs = { name: "Alice", age: 30 }
pairs.each_with_object([]) do |(key, value), result|
  result << "#{key}: #{value}"
end

# --- Pattern 8: Ternary with method calls ---
def format_value(env)
  env.key?(:format) ? env.delete(:format).to_s : "default"
end

# --- Pattern 9: Symbol-to-proc and block passing ---
names = ["alice", "bob", "carol"]
upper = names.map(&:upcase)
lengths = names.map(&:length).sort
handler = method(:puts)
names.each(&handler)

# --- Pattern 10: Percent notation literals ---
WORDS = %w[foo bar baz]
SYMBOLS = %i[read write execute]
PATTERN = %r{/users/(\d+)/posts}
COMMAND = %x(echo hello)

# --- Pattern 11: Complex string interpolation ---
def build_query(table, columns, conditions)
  "SELECT #{columns.join(', ')} FROM #{table} WHERE #{conditions.map { |k, v| "#{k} = '#{v}'" }.join(' AND ')}"
end

# --- Pattern 12: Nested hash with symbol keys ---
def serialize_record(record)
  {
    severity: record.severity.to_s,
    location: {
      begin_pos: record.location.begin_pos,
      end_pos: record.location.end_pos
    },
    message: record.message,
    status: record.status || :pending
  }
end

# --- Pattern 13: Multi-line method chain (dot at start) ---
def filtered_params(params)
  ActionController::Parameters.new(person: { name: "Test", city: "Tokyo" })
    .require(:person)
    .permit(:name, :city)
end

# --- Pattern 14: Complex case/when ---
def classify(value)
  case value
  when Integer then "number"
  when String then "text"
  when Array then "list"
  when ->(v) { v.respond_to?(:each) } then "iterable"
  when nil then "empty"
  else "unknown"
  end
end

# --- Pattern 15: Regex with interpolation ---
def match_route(prefix, id_pattern)
  route = %r{^/#{Regexp.escape(prefix)}/#{id_pattern}$}
  route.match("/users/42")
end

# --- Pattern 16: Inject with destructured tuple ---
def build_table(transitions)
  transitions.inject([0, nil]) { |state, (expected, symbol)|
    new_state = move(state, symbol)
    [new_state, expected]
  }
end

# --- Pattern 17: define_method with block ---
%i[get post put delete].each do |http_method|
  define_method(:"test_#{http_method}") do |path, **options|
    send(http_method, path, **options)
  end
end

# --- Pattern 18: Proc.new with modifier ---
setup_handler = Proc.new do |request|
  :strict unless request.user_agent == "unknown"
end

# --- Pattern 19: Conditional assignment and or-equals ---
class Cache
  def fetch(key)
    @store ||= {}
    @store[key] ||= compute(key)
  end

  def clear
    @store&.clear
  end
end

# --- Pattern 20: Ruby 4.0 - Leading logical operators for line continuation ---
def complex_condition?(a, b, c)
  a.valid?
  && b.present?
  && c.enabled?
end

def alternative_check(x, y)
  x.nil?
  || y.empty?
end

def keyword_continuation(val1, val2)
  val1.positive?
  and val2.positive?
end

def keyword_or_check(result, fallback)
  result
  or fallback
end

# --- Pattern 21: it as implicit block parameter (Ruby 3.4+) ---
squared = [1, 2, 3].map { it ** 2 }
evens = (1..10).select { it.even? }
