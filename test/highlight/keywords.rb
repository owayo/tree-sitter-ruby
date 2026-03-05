module Helpers
# <- keyword
#      ^ constructor

  begin
  # <- keyword
    retry
    # <- keyword
  rescue StandardError
  # <- keyword
  ensure
  # <- keyword
  end
  # <- keyword

  for x in [1, 2]
  # <- keyword
  #     ^ keyword
  end

  unless condition
  # <- keyword
  end

  until done
  # <- keyword
  end

  while running
  # <- keyword
  end

  case value
  # <- keyword
    when 1
    # <- keyword
      then
      # <- keyword
    else
    # <- keyword
  end

  if true
  # <- keyword
  elsif false
  # <- keyword
  end

  alias old_name new_name
  # <- keyword

  1 and 2
  # ^ keyword
  1 or 2
  # ^ keyword
end
