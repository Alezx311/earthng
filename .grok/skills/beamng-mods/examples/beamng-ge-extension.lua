local M = {}

M.onExtensionLoaded = function()
  log("I", "myMod", "GE extension loaded")
end

M.onUpdate = function(dtReal, dtSim, dtRaw)
  -- Keep lightweight; runs every frame.
end

return M
