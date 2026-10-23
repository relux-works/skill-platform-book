-- Pandoc filter for the platform book.
--
-- 1. Status markers. The chapters write a status as ⟦решено⟧, which reads
--    cleanly on GitHub; in the book it becomes a coloured badge
--    <span class="status dec">решено</span>. A marker may span several words
--    (⟦работает сегодня⟧) and may carry punctuation before or after it.
-- 2. Diagram sizes. Tall diagrams get the class "tall" so that the
--    stylesheet lets them use the full page height.
-- 3. Landscape figures, see below.

local status_class = {
  ["working today"] = "now",
  ["decided"] = "dec",
  ["proposed"] = "prop",
  ["specification"] = "spec",
  ["open"] = "open",
  ["работает сегодня"] = "now",
  ["решено"] = "dec",
  ["предложено"] = "prop",
  ["спецификация"] = "spec",
  ["открыто"] = "open",
}

local open_mark, close_mark = "⟦", "⟧"

local function badge(label)
  local class = status_class[label]
  if not class then
    error("unknown status marker: " .. label)
  end
  return pandoc.Span({ pandoc.Str(label) }, { class = "status " .. class })
end

-- Rewrite one run of inlines that starts with a Str containing the opening
-- mark. Returns the replacement inlines and the index after the run, or nil
-- when the run is not a complete marker.
local function take_marker(inlines, i)
  local parts = {}
  local j = i
  while j <= #inlines do
    local el = inlines[j]
    if el.t == "Str" then
      parts[#parts + 1] = el.text
      if el.text:find(close_mark, 1, true) then
        local s = table.concat(parts)
        local pre, label, post = s:match("^(.-)" .. open_mark .. "(.-)" .. close_mark .. "(.*)$")
        if not label then
          return nil
        end
        local out = pandoc.List()
        if pre ~= "" then out:insert(pandoc.Str(pre)) end
        out:insert(badge(label))
        if post ~= "" then out:insert(pandoc.Str(post)) end
        return out, j + 1
      end
    elseif el.t == "Space" or el.t == "SoftBreak" then
      parts[#parts + 1] = " "
    else
      return nil
    end
    j = j + 1
  end
  return nil
end

-- Give every opening marker its own Str boundary. Otherwise take_marker's
-- trailing text can hide a second marker, including one spanning later words.
local function split_marker_starts(inlines)
  local out = pandoc.List()
  for _, el in ipairs(inlines) do
    if el.t == "Str" then
      local start = 1
      local marker = el.text:find(open_mark, start, true)
      while marker do
        if marker > start then
          out:insert(pandoc.Str(el.text:sub(start, marker - 1)))
        end
        start = marker
        marker = el.text:find(open_mark, marker + #open_mark, true)
      end
      out:insert(pandoc.Str(el.text:sub(start)))
    else
      out:insert(el)
    end
  end
  return out
end

-- 4. Russian typesetting: a short preposition, conjunction or particle is
--    bound to the next word, and an em dash to the word before it, so that
--    neither is left hanging at the end or start of a line.
local nbsp = "\u{00A0}"
local bind_next = {}
for w in ("в во с со к ко о об обо у и а но на по за из от до не ни ли же бы при для без над под про что как или") :gmatch("%S+") do
  bind_next[w] = true
end

local function bind_spaces(inlines)
  local out = pandoc.List()
  local n = #inlines
  for i = 1, n do
    local el = inlines[i]
    local prev, nxt = inlines[i - 1], inlines[i + 1]
    if el.t == "Space" and prev and nxt and prev.t == "Str" and nxt.t == "Str" then
      local word = pandoc.text.lower(prev.text):gsub("^[«(%[]+", "")
      if bind_next[word] and not prev.text:find("[%.,;:!?»)]$") then
        out:insert(pandoc.Str(nbsp))
      elseif nxt.text:sub(1, 3) == "\u{2014}" then
        out:insert(pandoc.Str(nbsp))
      else
        out:insert(el)
      end
    else
      out:insert(el)
    end
  end
  return out
end

function Inlines(inlines)
  inlines = split_marker_starts(inlines)
  local out = pandoc.List()
  local i = 1
  while i <= #inlines do
    local el = inlines[i]
    local replaced, next_i = nil, nil
    if el.t == "Str" and el.text:find(open_mark, 1, true) then
      replaced, next_i = take_marker(inlines, i)
    end
    if replaced then
      out:extend(replaced)
      i = next_i
    else
      out:insert(el)
      i = i + 1
    end
  end
  return bind_spaces(out)
end

-- Set {.tall} or {.landscape} on the image explicitly; no filename heuristics.

-- 3. Landscape figures. An image marked {.landscape} puts its whole figure
--    on a landscape page (the stylesheet selects the page by the class).
function Figure(fig)
  local landscape = false
  fig:walk({ Image = function(img)
    if img.classes:includes("landscape") then landscape = true end
  end })
  if landscape then
    fig.classes:insert("landscape")
  end
  return fig
end

-- Set the running book title at each chapter boundary, preserving first-except
-- headers on chapter opening pages. Pandoc moves heading attributes to sections.
function Pandoc(doc)
  local title = pandoc.utils.stringify(doc.meta.title or "")
  return doc:walk({ Header = function(header)
    if header.level == 1 then header.attributes["data-book-title"] = title end
    return header
  end })
end
