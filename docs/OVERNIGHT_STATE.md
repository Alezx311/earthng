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
