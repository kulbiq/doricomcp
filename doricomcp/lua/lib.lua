-- doricomcp Lua library. Prepended by bridge.py with `local REQ` and `local OUT, DONE`.
-- Hard rules (each broke something when ignored):
--   never tostring(Instrument), Instrument.name, FlowInstrument.name (throw "Not implemented");
--   never delete events by element id guesses; probes clean up by undo right after (bridge side) or inverse edits.

OPS = {}
RL, P = DoCore.RhythmicLength, DoCore.MIDIPitchWithSpelling
CTX = DoCore.PropertyContext()

---------------------------------------------------------------- JSON
local function jstr(s)
  return '"' .. s:gsub('[%c"\\]', function(c)
    local m = {['"'] = '\\"', ['\\'] = '\\\\', ['\n'] = '\\n', ['\t'] = '\\t', ['\r'] = '\\r'}
    return m[c] or string.format("\\u%04x", c:byte())
  end) .. '"'
end
local function json(v)
  local t = type(v)
  if v == nil then return "null" end
  if t == "boolean" then return tostring(v) end
  if t == "number" then
    if v ~= v or v == math.huge or v == -math.huge then return "null" end
    if v == math.floor(v) and math.abs(v) < 2^53 then return string.format("%d", v) end
    return string.format("%.17g", v)
  end
  if t == "string" then return jstr(v) end
  if t == "table" then
    local n = #v
    if n > 0 and next(v, n) == nil or (n == 0 and next(v) == nil) then
      local parts = {}
      for i = 1, n do parts[i] = json(v[i]) end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    local parts = {}
    for k, x in pairs(v) do parts[#parts + 1] = jstr(tostring(k)) .. ":" .. json(x) end
    return "{" .. table.concat(parts, ",") .. "}"
  end
  return jstr(tostring(v))
end

---------------------------------------------------------------- helpers
function S(x) local ok, r = pcall(tostring, x) return ok and r or nil end
function TRY(f, ...) local ok, r = pcall(f, ...) if ok then return r end return nil end

-- RhythmicLength -> "n/d" (or "n"), exact
function RAT(r)
  if r == nil then return nil end
  local n, d = TRY(function() return r.numerator end), TRY(function() return r.denominator end)
  if n and d then
    if d == 1 then return string.format("%d", n) end
    return string.format("%d/%d", n, d)
  end
  local s = S(r) or ""
  return s:match("^(%-?%d+/%d+)") or s:match("^(%-?%d+)")
end
-- "n/d" | "n" | number -> RhythmicLength
function LEN(x)
  local n, d = tostring(x):match("^(%-?%d+)/(%d+)$")
  if n then return RL(tonumber(n), tonumber(d)) end
  return RL(tonumber(x))
end
function NUM(x) -- "n/d" -> number, for comparisons only
  local n, d = tostring(x):match("^(%-?%d+)/(%d+)$")
  if n then return tonumber(n) / tonumber(d) end
  return tonumber(x)
end

function EVTYPE(e) return (S(e) or ""):match("^(k%w+)") end

-- DoApp's current score is the active open score. ScriptHost().currentScore can be an empty placeholder
-- (openScoreID -1, 0 flows) after a project was closed and reopened.
function SCORE()
  local sc = DoApp.DoApp().currentScore
  if sc and (TRY(function() return sc.openScoreID end) or -1) >= 0 then return sc end
  sc = DoCore.ScriptHost().currentScore
  assert(sc and (TRY(function() return sc.openScoreID end) or -1) >= 0, "no score is open in Dorico")
  return sc
end
function FLOW(id) -- by Dorico FlowID (what commands take as FlowID=)
  id = id or 0
  for _, f in pairs(SCORE().flows) do if f.id == id then return f end end
  error("no flow with FlowID " .. tostring(id))
end
function STREAM(flow, id)
  for _, st in pairs(flow.allStreams) do if st.id == id then return st end end
  error("no stream " .. tostring(id))
end

-- Variant -> Lua value; nil if unset, {list=true} for sealed list Variants (type 4)
function VAL(v)
  if v == nil or not v.valid then return nil end
  local t = v.type
  if t == 4 then return {sealed = true} end
  if t == 5 then return v:toBool() end
  if t == 1 then return v:toDouble() end
  if t == 0 then return TRY(function() return v:toInt() end) end
  return TRY(function() return v:toString() end)
end
function PROP(obj, name) return VAL(TRY(function() return obj.propertyTable:get(name, CTX) end)) end
function PROPS(obj)
  local out = {}
  local names = TRY(function() return obj.propertyTable:getPropertyNames() end) or {}
  for _, n in pairs(names) do
    local v = PROP(obj, n)
    if v ~= nil then out[n] = v end
  end
  return out
end

---------------------------------------------------------------- ops
OPS.ping = function()
  local app = DoApp.DoApp()
  local score = SCORE()
  return {version = S(app.versionString), layout = app.currentLayoutID, title = S(score.title),
          flows = #score.flows}
end

-- dev only: run REQ.code (a Lua chunk body returning a value) with the library in scope
OPS.eval = function(req) return assert(load(req.code, "eval", "t", _ENV))() end

-- st.events throws "Not implemented" for some stream kinds (seen after NoteInput.CreateTempo); such
-- streams are still covered by st:dump()
function EVENTS(st)
  local ok, evs = pcall(function() return st.events end)
  return ok and evs or {}
end

local function count(t) local n = 0 for _ in pairs(t) do n = n + 1 end return n end

-- block id of the stream's block instance holding event `id` (EventEdit.Select / ChangeProperty need the
-- EventBlock id, not the instance id; a wrong one returns kOK and silently acts on the old selection)
function BLOCKOF(st, id)
  local first
  for _, bi in pairs(st.blockInstances) do
    local b = bi.block
    first = first or b.id
    -- enumerating block events throws when the block holds an unwrappable event (trill, tempo...)
    local hit = id and TRY(function() for _, e in pairs(b.events) do if e.id == id then return true end end end)
    if hit then return b.id end
  end
  return first
end

-- find an event object (only events exposed in .events; slurs etc. are dump-only)
function EVENT(flow, id)
  for _, st in pairs(flow.allStreams) do
    for _, e in pairs(EVENTS(st)) do if e.id == id then return e, st end end
  end
  return nil
end

local function event_row(e, st)
  local d = S(e) or ""
  local row = {id = e.id, type = EVTYPE(e), pos = RAT(e.position), dur = RAT(e.duration), desc = d,
               props = PROPS(e)}
  local ty = row.type
  if ty == "kTextEvent" then row.text = TRY(function() return e.text end) end
  if ty == "kGraceNoteEvent" then row.secondary = RAT(TRY(function() return e.secondaryPosition end)) end
  if ty == "kTupletEvent" then
    local td = TRY(function() return e.tupletDef end)
    if td then row.tuplet = {left = TRY(function() return td.left end), right = TRY(function() return td.right end)} end
  end
  if ty == "kOttavaLineEvent" then row.ottava = TRY(function() return e.ottavaLineDefinitionID end) end
  if ty == "kBreakEvent" then
    row.layout = TRY(function() return e.layoutID end)
    row.frame = TRY(function() return e.isFrameBreak end)
  end
  return row
end

---------------------------------------------------------------- read ops
OPS.overview = function()
  local score = SCORE()
  local out = {title = S(score.title), players = {}, instruments = {}, layouts = {}, flows = {},
               layout = DoApp.DoApp().currentLayoutID}
  for _, p in pairs(score.players) do
    local ins = {}
    for _, x in pairs(p.instruments) do ins[#ins + 1] = x.id end
    out.players[#out.players + 1] = {name = S(p), instruments = ins}
  end
  for _, x in pairs(score.instruments) do out.instruments[#out.instruments + 1] = x.id end
  for _, l in pairs(score.layouts) do out.layouts[#out.layouts + 1] = {id = l.id, desc = S(l)} end
  for _, f in pairs(score.flows) do
    local fl = {id = f.id, streams = {}, instruments = {}, players = {}}
    local seen = {}
    for _, fi in pairs(f.instruments) do -- the table repeats entries; dedupe by id
      if not seen[fi.id] then
        seen[fi.id] = true
        local sts = {}
        for _, st in pairs(fi.streams) do sts[#sts + 1] = st.id end
        fl.instruments[#fl.instruments + 1] = {id = fi.id, voices = sts}
      end
    end
    for _, p in pairs(f.players) do fl.players[#fl.players + 1] = S(p) end
    for _, st in pairs(f.allStreams) do
      local d = S(st) or ""
      fl.streams[#fl.streams + 1] = {id = st.id, kind = d:match("(k%a+Stream)"), block = BLOCKOF(st),
                                     events = tonumber(d:match("(%d+) events"))}
    end
    out.flows[#out.flows + 1] = fl
  end
  return out
end

-- REQ: flow, streams (optional list of ids), from/to (optional "n/d"; events overlapping [from, to))
OPS.read = function(req)
  local flow = FLOW(req.flow)
  local want
  if req.streams then want = {} for _, id in ipairs(req.streams) do want[id] = true end end
  local lo, hi = req.from and NUM(req.from), req.to and NUM(req.to)
  local out = {}
  for _, st in pairs(flow.allStreams) do
    if not want or want[st.id] then
      local evs = {}
      for _, e in pairs(EVENTS(st)) do
        local p, en = NUM(RAT(e.position)), NUM(RAT(e.endPosition))
        if (not lo or en > lo or (en == p and p >= lo)) and (not hi or p < hi) then
          local row = event_row(e, st)
          row.block = BLOCKOF(st, e.id)
          evs[#evs + 1] = row
        end
      end
      local blocks = {}
      for _, bi in pairs(st.blockInstances) do blocks[#blocks + 1] = {instance = bi.id, block = bi.block.id, pos = RAT(bi.position)} end
      local okev = pcall(function() return st.events end)
      out[#out + 1] = {id = st.id, kind = (S(st) or ""):match("(k%a+Stream)"), events = evs, events_readable = okev,
                       blocks = blocks, dump = TRY(function() return st:dump() end)}
    end
  end
  return out
end

OPS.elements = function(req)
  local flow = FLOW(req.flow)
  local out = {dynamics = {}, bardivs = {}}
  for _, g in pairs(flow.elementTables.dynamics.elements) do
    local subs = {}
    for _, s in pairs(g.subElements) do subs[#subs + 1] = {id = s.id, props = PROPS(s)} end
    out.dynamics[#out.dynamics + 1] = {id = g.id, props = PROPS(g), subs = subs}
  end
  for _, el in pairs(flow.elementTables.barDivisions.elements) do
    out.bardivs[#out.bardivs + 1] = {id = el.id, props = PROPS(el)}
  end
  return out
end

---------------------------------------------------------------- sealed-value probe (equality method)
-- Creates candidate elements (orphans: no stream event, no delete binding). The caller MUST issue Edit.Undo
-- immediately after this script, with no selection in between, and verify the element counts are back.
-- REQ: flow, bardivs (element ids), dynamics ({group, sub} pairs)
OPS.probe_sealed = function(req)
  local flow = FLOW(req.flow)
  local bt, dt = flow.elementTables.barDivisions, flow.elementTables.dynamics
  local out = {before = {bardivs = count(bt.elements), dynamics = count(dt.elements)}, timesigs = {}, dynamics = {}, created = 0}
  local function get(o, n) return o.propertyTable:get(n, CTX) end
  local byBd = {}
  for _, el in pairs(bt.elements) do byBd[el.id] = el end
  local tsCand = {}
  local function tsCandidate(n, d)
    local k = n .. "/" .. d
    if not tsCand[k] then
      tsCand[k] = get(bt:createBarDivisionElement(DoCore.BarDivisionData.createForSingleTimeSignature(n, d)), "kBarDivisionTimeSignatures")
      out.created = out.created + 1
    end
    return tsCand[k]
  end
  local ORDER = {{4, 4}, {3, 4}, {2, 4}, {6, 8}, {2, 2}, {3, 8}, {12, 8}, {9, 8}, {5, 4}, {6, 4}, {3, 2}, {7, 8}, {5, 8}}
  for _, id in ipairs(req.bardivs or {}) do
    local el = byBd[id]
    local res
    if not el then res = "missing"
    elseif PROP(el, "kBarDivisionCommonTimeSig") then res = "C"
    elseif PROP(el, "kBarDivisionGroupCutTimeLikeCommonTime") then res = "cut"
    else
      local v = get(el, "kBarDivisionTimeSignatures")
      for _, c in ipairs(ORDER) do if v == tsCandidate(c[1], c[2]) then res = c[1] .. "/" .. c[2] break end end
      if not res then
        for _, d in ipairs({4, 8, 2, 16, 1, 32}) do
          for n = 1, 32 do if v == tsCandidate(n, d) then res = n .. "/" .. d break end end
          if res then break end
        end
      end
      res = res or "complex"
    end
    out.timesigs[#out.timesigs + 1] = {id = id, value = res}
  end
  local byDyn = {}
  for _, g in pairs(dt.elements) do byDyn[g.id] = g end
  local DI = DoCore.DynamicIntensity
  local dyCand = {}
  local function dyCandidate(kind, n)
    local k = kind .. n
    if not dyCand[k] then
      local sub = dt:createDynamicGroup():createImmediateChange(RL(0), DI.create(kind == "p" and DI.kP or DI.kF, n))
      dyCand[k] = get(sub, "kDynamicImmediateChangeIntensity")
      out.created = out.created + 1
    end
    return dyCand[k]
  end
  for _, ref in ipairs(req.dynamics or {}) do
    local g, res, sub = byDyn[ref[1]], nil, nil
    if g then for _, s in pairs(g.subElements) do if s.id == ref[2] then sub = s end end end
    if not sub then res = "missing"
    else
      local v = get(sub, "kDynamicImmediateChangeIntensity")
      if not v.valid or v.type ~= 4 then res = "none"
      elseif PROP(sub, "kDynamicImmediateChangeIsMezzo") then
        res = (PROP(sub, "kDynamicImmediateChangeBasicType") == 1) and "mp" or "mf"
      else
        local basic = PROP(sub, "kDynamicImmediateChangeBasicType") == 1 and "p" or "f"
        for n = 1, 6 do if v == dyCandidate(basic, n) then res = string.rep(basic, n) break end end
        res = res or "unknown"
      end
    end
    out.dynamics[#out.dynamics + 1] = {group = ref[1], sub = ref[2], value = res}
  end
  return out
end

OPS.element_counts = function(req)
  local flow = FLOW(req.flow)
  return {bardivs = count(flow.elementTables.barDivisions.elements), dynamics = count(flow.elementTables.dynamics.elements)}
end

-- Key-signature probe: letters A..G entered by note input into an empty span of a voice,
-- read back Dorico's key-aware spelling, then delete them in the same script. REQ: flow, stream, pos, end (= pos + 7)
OPS.probe_key = function(req)
  local flow = FLOW(req.flow)
  local st = STREAM(flow, req.stream)
  local app = DoApp.DoApp()
  local start, stop = NUM(req.pos), NUM(req["end"])
  -- read through dump(): .events throws for streams holding trills/ornaments/techniques
  local function inspan()
    local out = {}
    for line in (st:dump() or ""):gmatch("[^\n]+") do
      local ty, p = line:match(": (k%w+) %(id:%d+%) at ([%d/]+)")
      if ty and NUM(p) >= start and NUM(p) < stop then out[#out + 1] = {type = ty, line = line} end
    end
    return out
  end
  assert(#inspan() == 0, "probe span is not empty")
  local rest = st:createRest(LEN(req.pos), RL(1))
  app:doCommand(("EventEdit.Select?FlowID=%d&EventID=%d&EventBlockID=%d"):format(flow.id, rest.id, BLOCKOF(st, rest.id)))
  app:doCommand("NoteInput.Enter?Set=true")
  app:doCommand("NoteInput.NoteValue?LogDuration=kCrotchet")
  for _, L in ipairs({"A", "B", "C", "D", "E", "F", "G"}) do app:doCommand("NoteInput.Pitch?Pitch=" .. L) end
  app:doCommand("NoteInput.Exit")
  app:doCommand("Edit.SelectNone")
  local spelled = {}
  for _, e in ipairs(inspan()) do
    if e.type == "kNoteEvent" then spelled[#spelled + 1] = e.line:match("%s(%u[#bx]*%-?%d+) %(ends") end
  end
  st:deleteEventsInRange(LEN(req.pos), LEN(req["end"]))  -- exactly the probed span (pos + 7 crotchets)
  return {spelled = spelled, left = #inspan()}
end

---------------------------------------------------------------- write transaction
-- REQ.flow, REQ.steps: list of steps run in order inside ONE script (= one undo step):
--   {"note", stream, pos, dur, pitch}      {"rest", stream, pos, dur}        {"grace", stream, pos, secpos, dur, pitch}
--   {"delete", stream, from, to}           {"delete_event", stream, id}
--   {"delete_ids", stream, {ids}}          (Event:delete each; slurs/text elsewhere in the stream stay)
--   {"select", stream, id}                 {"cmd", "Namespace.Command?..."}  {"selectnone"}
--   {"mark", type, {streams}}  {"delete_new", type, keep_stream}  (delete events of `type` the steps since the
--                                          mark created in those streams, except in keep_stream)
--   {"select_created", stream, step_index} (select what an earlier step of this script created; -1 = the step before)
--   {"prop", stream, id, name, value|nil}  (EventEdit.ChangeProperty; nil value resets)
--   {"luaprop", id, name, kind, value}     (propertyTable:set; kind int|double|string|bool)
--   {"duration", id, dur}  {"repitch", stream, id, spelling} (the selected note)
--   {"text", stream, pos, dur, text}       {"clef", stream, pos, clef_entity_id}
--   {"timesig", pos, num, den}             {"dynamic", stream, pos, kind(p|f), count}
--   {"ottava", stream, pos, dur, definition_id}  {"tuplet", stream, pos, left, right, unit_dur}
--   {"break", stream, layout, pos, frame(bool)}
--   {"copy"|"move"|"copylinked", stream, from, to, dest_stream, dest_pos}
-- Returns {created = {step index -> event id}}.
OPS.tx = function(req)
  local flow = FLOW(req.flow)
  local app = DoApp.DoApp()
  local created, log = {}, {}
  local function sel(st, id)
    app:doCommand(("EventEdit.Select?FlowID=%d&EventID=%d&EventBlockID=%d"):format(flow.id, id, BLOCKOF(st, id)))
  end
  local marked  -- {type, streams, ids seen at the mark}
  local function dumped(ty, streams)  -- id -> {stream, block} of `ty` events in streams, from their dumps
    local out = {}
    for _, sid in ipairs(streams) do
      local st, inst, cur = STREAM(flow, sid), {}, nil
      for _, bi in pairs(st.blockInstances) do inst[bi.id] = bi.block.id end
      for line in (TRY(function() return st:dump() end) or ""):gmatch("[^\n]+") do
        local b = line:match("^Start block id: (%d+)")
        if b then cur = inst[tonumber(b)] end
        local t, id = line:match(": (k%w+) %(id:(%d+)%)")
        if t == ty then out[tonumber(id)] = {stream = sid, block = cur} end
      end
    end
    return out
  end
  for i, s in ipairs(req.steps) do
    local k = s[1]
    local ev
    if k == "note" then ev = STREAM(flow, s[2]):createNote(LEN(s[3]), LEN(s[4]), P.fromString(s[5]))
    elseif k == "rest" then ev = STREAM(flow, s[2]):createRest(LEN(s[3]), LEN(s[4]))
    elseif k == "grace" then ev = STREAM(flow, s[2]):createGraceNote(LEN(s[3]), LEN(s[4]), LEN(s[5]), P.fromString(s[6]))
    elseif k == "delete" then STREAM(flow, s[2]):deleteEventsInRange(LEN(s[3]), LEN(s[4]))
    elseif k == "delete_event" then
      local e = assert(EVENT(flow, s[3]), "no event " .. tostring(s[3]))
      assert(STREAM(flow, s[2]):delete(e), "delete failed for event " .. tostring(s[3]))
    elseif k == "delete_ids" then
      local st, want, doomed = STREAM(flow, s[2]), {}, {}
      for _, id in ipairs(s[3]) do want[id] = true end
      for _, e in pairs(EVENTS(st)) do if want[e.id] then doomed[#doomed + 1] = e end end
      -- tuplets last: deleting a tuplet may take its notes with it (the caller reads the range back)
      table.sort(doomed, function(x, y) return (EVTYPE(x) == "kTupletEvent" and 1 or 0) < (EVTYPE(y) == "kTupletEvent" and 1 or 0) end)
      for _, e in ipairs(doomed) do TRY(function() return st:delete(e) end) end
    elseif k == "select" then sel(STREAM(flow, s[2]), s[3])
    elseif k == "mark" then marked = {s[2], s[3], dumped(s[2], s[3])}
    elseif k == "delete_new" then
      assert(marked and marked[1] == s[2], "delete_new without a mark for " .. tostring(s[2]))
      for id, at in pairs(dumped(s[2], marked[2])) do
        if not marked[3][id] and at.stream ~= s[3] then
          app:doCommand(("EventEdit.Delete?FlowID=%d&EventID=%d&EventBlockID=%d"):format(flow.id, id, at.block))
        end
      end
    elseif k == "select_created" then  -- {"select_created", stream, step index whose event to select; < 0: relative}
      local at = s[3] < 0 and i + s[3] or s[3]
      local id = assert(created[tostring(at)], "step " .. tostring(at) .. " created nothing to select")
      sel(STREAM(flow, s[2]), id)
    elseif k == "selectnone" then app:doCommand("Edit.SelectNone")
    elseif k == "cmd" then app:doCommand(s[2])
    elseif k == "prop" then
      local st = STREAM(flow, s[2])
      local c = ("EventEdit.ChangeProperty?FlowID=%d&EventID=%d&EventBlockID=%d&Type=%s"):format(flow.id, s[3], BLOCKOF(st, s[3]), s[4])
      if s[5] ~= nil then c = c .. "&Value=" .. tostring(s[5]) end
      app:doCommand(c)
    elseif k == "prop_created" then  -- {"prop_created", stream, step index, name, value}
      local st = STREAM(flow, s[2])
      local id = assert(created[tostring(s[3])], "step " .. tostring(s[3]) .. " created nothing")
      app:doCommand(("EventEdit.ChangeProperty?FlowID=%d&EventID=%d&EventBlockID=%d&Type=%s&Value=%s"):format(flow.id, id, BLOCKOF(st, id), s[4], tostring(s[5])))
    elseif k == "luaprop" then
      local e = assert(EVENT(flow, s[2]), "no event " .. tostring(s[2]))
      local V = DoCore.Variant
      local v = ({int = V.createInt, double = V.createDouble, string = V.createString, bool = V.createBool})[s[4]](s[5])
      assert(e.propertyTable:set(s[3], v, CTX), "propertyTable:set refused " .. s[3])
    elseif k == "subprop" then  -- {"subprop", dynamic group element id, sub-element id, name, value}
      local g, sub
      for _, x in pairs(flow.elementTables.dynamics.elements) do if x.id == s[2] then g = x end end
      assert(g, "no dynamic group element " .. tostring(s[2]))
      for _, x in pairs(g.subElements) do if x.id == s[3] then sub = x end end
      assert(sub, "no sub-element " .. tostring(s[3]) .. " in dynamic group " .. tostring(s[2]))
      assert(sub.propertyTable:set(s[4], DoCore.Variant.createString(s[5]), CTX), "propertyTable:set refused " .. s[4])
    elseif k == "duration" then
      local e = assert(EVENT(flow, s[2]), "no event " .. tostring(s[2]))
      e.duration = LEN(s[3])
    elseif k == "repitch" then  -- {"repitch", stream, id, spelling}: move the selected note until it reads `spelling`
      local st = STREAM(flow, s[2])
      local function cur() return (st:dump() or ""):match("%(id:" .. s[3] .. "%)[^\n]-%s(%u[#bx]*%-?%d+) %(ends") end
      local function step(sp) return ("CDEFGAB"):find(sp:sub(1, 1)) + 7 * tonumber(sp:match("%-?%d+$")) end
      local function midi(sp)
        local acc = sp:match("^%u([#bx]*)")
        local alter = select(2, acc:gsub("#", "")) - select(2, acc:gsub("b", "")) + 2 * select(2, acc:gsub("x", ""))
        return ({0, 2, 4, 5, 7, 9, 11})[("CDEFGAB"):find(sp:sub(1, 1))] + alter + 12 * (tonumber(sp:match("%-?%d+$")) + 1)
      end
      -- one semitone per command: PitchDownChromatic?count=2 moved C5 up to D5
      for _ = 1, 140 do
        local now = cur()
        if now == nil or now == s[4] then break end
        local d = midi(s[4]) - midi(now)
        if d ~= 0 then app:doCommand(d > 0 and "NoteEdit.PitchUpChromatic" or "NoteEdit.PitchDownChromatic")
        else app:doCommand(step(s[4]) > step(now) and "NoteEdit.RespellUsingNoteNameAbove" or "NoteEdit.RespellUsingNoteNameBelow") end
      end
    elseif k == "text" then ev = STREAM(flow, s[2]):createText(LEN(s[3]), LEN(s[4]), s[5])
    elseif k == "clef" then
      -- the score's own library holds only clefs already used; fall back to Dorico's default/user libraries
      local entity
      for _, lib in ipairs({function() return SCORE().libraries end, function() return DoCore.ScriptHost().engine.defaultLibrary end,
                            function() return DoCore.ScriptHost().engine.userLibrary end}) do
        entity = entity or TRY(function() return lib().clefs:find(s[4]) end)
      end
      assert(entity, "no clef " .. tostring(s[4]) .. " in the score, default or user library")
      ev = STREAM(flow, s[2]):createClef(LEN(s[3]), RL(0), false, entity)
    elseif k == "timesig" then
      local tbl = flow.elementTables.barDivisions
      local el = tbl:createBarDivisionElement(DoCore.BarDivisionData.createForSingleTimeSignature(s[3], s[4]))
      ev = flow.timebaseStreams[1]:createBarDivision(LEN(s[2]), el)
    elseif k == "dynamic" then
      local DI = DoCore.DynamicIntensity
      local g = flow.elementTables.dynamics:createDynamicGroup()
      g:createImmediateChange(RL(0), DI.create(s[4] == "p" and DI.kP or DI.kF, s[5]))
      ev = g:createEvent(LEN(s[3]), STREAM(flow, s[2]))
    elseif k == "ottava" then ev = STREAM(flow, s[2]):createOttavaLine(LEN(s[3]), LEN(s[4]), RL(0), RL(0), s[5])
    elseif k == "tuplet" then
      ev = STREAM(flow, s[2]):createTuplet(LEN(s[3]), DoCore.TupletDefinition(s[4], s[5], LEN(s[6])))
    elseif k == "break" then
      local st = STREAM(flow, s[2])
      if s[5] then ev = st:createFrameBreak(s[3], LEN(s[4])) else ev = st:createSystemBreak(s[3], LEN(s[4])) end
    elseif k == "copy" or k == "move" or k == "copylinked" then
      local st = STREAM(flow, s[2])
      local fn = ({copy = st.copyRange, move = st.moveRange, copylinked = st.copyRangeLinked})[k]
      fn(st, LEN(s[3]), LEN(s[4]), STREAM(flow, s[5]), LEN(s[6]), 0)
    else error("unknown step " .. tostring(k)) end
    if ev ~= nil then created[tostring(i)] = TRY(function() return ev.id end) or -1 end
  end
  return {created = created}
end

---------------------------------------------------------------- dispatcher
function RUN()
  local ok, res = xpcall(function()
    local op = OPS[REQ.op]
    assert(op, "unknown op " .. tostring(REQ.op))
    return op(REQ)
  end, debug.traceback)
  local f = assert(io.open(OUT, "w"))
  if ok then f:write(json({ok = true, result = res})) else f:write(json({ok = false, error = S(res)})) end
  f:close()
  local d = assert(io.open(DONE, "w")) d:write("1") d:close()
end
