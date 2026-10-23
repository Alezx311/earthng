# EarthNG overnight work — 2026-10-22 / 23

Deadline: 2026-10-23 08:00 Europe/Kiev (05:00 UTC).
Requested order: fix GitHub #4 MapBuilder, fix #2 bridges, then experiment with
thousands of street assets per tile on a separate branch, with measured performance.

## Coordination and recovery

- Main checkout: `C:\js\EarthNG`; original clean branch `master`.
- Fix branch: `codex/overnight-fixes`.
- Experiment branch to create AFTER verified fixes: `codex/street-assets-experiments`.
- Heartbeat automation: `earthng-2`, every 30 minutes in this chat; stop at deadline.
- Claude Code is installed and signed in through Claude Pro. Check its running
  process and `out/overnight/claude-mapbuilder.*` before launching another worker.
- Claude owns MapBuilder.bat, Setup.bat, Country.bat, launcher helper/tests and
  release-packaging fixes necessary for issue #4. Do not concurrently edit these.
- Codex owns bridge generation/profile fixes and their tests; then game verification.
- Neither worker may revert the other's work. Claude must not switch branches,
  publish, push, or commit shared work. Codex integrates and commits reviewed changes.
- Store checkpoints after each milestone, including failures and commands. Never
  call an issue fixed solely on inspection; distinguish automated and real-game tests.
- If a service hits limits, retain edits/logs and resume at the next permitted run;
  no paid fallback or changes to account settings.

## Initial evidence

- Issue #4: Python dependencies install, second MapBuilder.bat invocation silently
  closes, no GUI. Launcher currently detaches pythonw without startup diagnostics.
- Issue #2: Bratislava bridge too low to drive underneath, missing realistic sides.
- Existing performance research: docs/PERFORMANCE.md; Forest instancing is working
  for trees, DynamicShapeBatch was not visible in past experiments. Reuse evidence.
- Game: `C:/Program Files (x86)/Steam/steamapps/common/BeamNG.drive`, native Lua mod.
- Use isolated profiles under out/. Existing test_world.py and probe.py provide
  game automation without controlling the user's keyboard. Do not alter personal saves.
- Stock assets must remain references to the installed game, never redistributed.

## Next actions

1. Run Claude's MapBuilder task and inspect its results.
2. Trace bridge height pipeline, stock bridge assets, and existing deck generation.
3. Add regression coverage; build and inspect representative bridges in game.
4. Commit fixes; create experiments branch; benchmark baseline and detail tiers.

## Checkpoint — 23:58 Kyiv

- Claude CLI running as PID 6480, exec session 23843; report in
  out/overnight/mapbuilder-report.md. It reproduced a silent pythonw Tk startup
  failure, found the clean release's imports complete, and is implementing a
  launcher with preflight/diagnostics. Review when finished, especially embedded
  python versus venv repair and any automatic venv recreation.
- Existing master already includes bridge parapets/soffit + ordinary crossing
  clearance from merged PR #5. Do not attribute those changes to this session.
- Codex changed fast_profile.py: clearance also applies between bridges on
  different layers; invalid nonfinite layer tags no longer poison the solver.
  Fast source cache bumped to fast-12. Short stacked spans reproduced separation
  of 0 / 0.397 / 0.829 m for spans 14 / 30 / 50 m before the fix; new tests pass.
- Test run before Claude's launcher edits: all 249 tests passed in 19.2 s,
  out/overnight/tests-initial.log. Rerun affected/full suite after integration.
- Built 104-cell Bratislava test pack from cached OSM with new heights:
  out/overnight/packs/earthng_bratislava-bridges.zip. Build helper and clearance
  audit under out/overnight/. 99,219 stations / 292 solver crossings / no reported
  shortfalls; independent exact-line audit: 235 crossings, 0 below 4 m versus
  127 in the old fast-9 data. Minimum new audited headroom about 4.307 m.
  Much of that improvement comes from the existing PR #5 clearance solve.
- Stock assets inspected in-place: assets/meshes.zip contains
  /assets/meshes/props/assembly_kit/ak_guardrail_001/ak_bridge_guardrail_001.dae;
  East Coast USA has eca_guardrail1/2/post/endcap and several bridge models;
  assembly kit is metre scale, Z_UP, approximately 2 m guardrail section.
  Do not copy stock art into the repository or release.
- First real game run out/overnight/bridge-baseline used old Slovakia pack +
  current source planet; manual run, not an automated pass. Game shut down cleanly.
  Screenshot screenshots/e2r-bridge-old.png shows bridge sides exist with current
  planet even on old pack, but low decks remain because heights live in country.
- Second game now running: exec session 79973, profile
  out/overnight/bridge-fixed/user, new test pack, landing 48.17075,17.1861
  (Ivanska cesta crossing), 1200 s timeout. Use probe.py for camera/ray tests,
  then shut down before starting any other game. Existing test planet reusable:
  out/overnight/bridge-baseline/mod/earthng_planet.zip.
- Useful crossings: Ivanska 48.1707504,17.1859580 (new headroom 4.497 m vs 1.072 m);
  stacked Panonska 48.1290392,17.1050696 (4.307 m vs 2.442 m).

## Checkpoint — 01:20 Kyiv (Claude Code took over after Codex hit its limit)

- #4 MapBuilder: reviewed Claude worker's launcher, fixed the retry after Setup.bat to use
  .venv even when python\ exists, README troubleshooting line. Full suite 263 OK; real
  `MapBuilder.bat` start from this checkout: window shown in ~1 s, startup.log written.
  Committed 839a6f0. Reporter's exact trigger still unknown (their startup.log will say).
- #2 bridges, real game: `out/overnight/bridge-drive` (autopilot under Ivanska crossing,
  Bratislava test pack) drove 197 m at a steady 9.6-9.7 m/s through the bridge point with no
  height change: functional pass. Its frame >100 ms failure is the spawn phase. The separate
  `drive_under_bridge.lua` probe never moved the car (inputs, not the bridge).
  Stacked Panonska views `out/overnight/bridge-stack*/e2r-v-*.png`: two decks at different
  heights, parapets on both; the bare concrete band seen from above is the median between
  the parallel carriageways. No defect found; not a drive test.
- Street props experiment on `codex/street-assets-experiments` (a8e624f), report
  `docs/STREET_PROPS.md` there: Forest with collidable kinds beats TSStatic (spawn 8-12x,
  collision rebuild +0.8 ms vs +22 ms per 6000). Kyiv route: 37-72k props cost +0.5-0.7 ms
  mean frame, +1.5-3 ms p99, no extra >100 ms frames. Not merged, not pushed.

## Checkpoint — 05:04 Kyiv (Codex resumed)

- Main master is owned by the existing Claude desktop session; leave its changes alone.
- Codex now works in the attached managed worktree:
  C:/Users/Alezx311/.codex/worktrees/street-assets-night/EarthNG
  branch codex/street-assets-experiments, merged master ad58753 into it.
- Claude CLI placement implementation running (exec session 71789), report target
  out/overnight/claude-prop-placement-fix.md in this main checkout. Do not duplicate it.
  It owns generator.lua, test_generator.py and STREET_PROPS.md in the worktree.
- Codex owns world.lua/FIFO lifecycle there: bounded removal batches, no queue-tail
  copying, half-open anchor ownership, deduplicated pending removals. Four regressions pass.
- Real BeamNG getItemsBox returned neighbouring bench anchors x=500 and 500.005 for
  a box ending x=499.99: bounds overlap is confirmed; inset alone is not ownership.
  A subsequent deliberately repeated-remove probe crashed the isolated test game.
  Crash reporter closed by exact PID, no personal profile touched. Need validate fixed
  runtime in a fresh game. Do not count this diagnostic run as a performance pass.
- New real route + quality-cycle run: worktree/out/runtime-review/fixed. Runtime-only
  planet isolates Codex edits from Claude's in-progress generator changes. Check processes
  and report before any new launch. Tests use main C:/js/EarthNG/.venv/Scripts/python.exe.
- Continue until 08:00 Kyiv, then stop new work and disable earthng-2. No releases.

### 05:13 Kyiv follow-up (Codex)

- Runtime fixes committed in experiment worktree: 7df5742, 6f183d4; placement fixes
  from CLI Claude reviewed and committed 5acfbdc. Full suite: 277 run, 274 pass,
  3 cache-fixture skips. Runtime documentation: docs/FOREST_STREAMING_REVIEW.md.
- Runtime-only route drove 1782 m, Potato/OASIS preserved the road; pending queues
  drained and actual Forest count equalled recorded count (52472). Performance
  gate FAILED (26.81 ms mean, p99 81, 17 >100 ms during initial 120 s). This run
  overlapped offline work and installed game reports 0.40.3, so do not compare it
  with previous 0.40.2 numbers. Game stopped cleanly; own harness session 12334 ended.
- CLI Claude now implements full prop footprint clearance in generator/tests/docs,
  exec session 69548, PID 29896; report out/overnight/claude-prop-footprint-fix.md.
  Do not launch duplicate. It may leave uncommitted edits in the managed worktree.
- Asset measurement found bike rack length 4.16 m (local X), bench 2 m, not the
  guessed 1.8 m. Numeric bounds only in worktree/out/runtime-review/asset-bounds.jsonl.
- Another Claude desktop session is now running main's release/game-ua-beresteiska
  test, game PID 30820 at this checkpoint. Do not stop it or start another game
  while it runs. Wait for a free game slot before clean baseline/props comparisons.
- Next: review Claude footprint result, targeted/full tests, commit. Then compare
  identical final planet at prop spacing 0/6/3 with no parallel heavy work, inspect
  screenshots, update measurements and checkpoint. No publish from this task.
