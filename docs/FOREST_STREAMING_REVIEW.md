# Dense Forest streaming review — 23 October 2026

Branch: `codex/street-assets-experiments`. These changes apply to both trees and
street props; the experimental placement work remains separate from master.

## Confirmed defects and changes

- `getItemsBox` returns intersecting model bounds, including anchors in adjacent
  tiles. On the installed BeamNG 0.40.3, a query ending at x=499.99 returned bench
  anchors at 499, 499.995, 500 and 500.005. Retirement now filters on the same
  half-open anchor rectangle as generation. The query itself uses full tile bounds.
- Near/far rebuilds can request removal of the same item before its queue drains.
  Pending removals are deduplicated by the engine item key. A deliberately repeated
  removal diagnostic crashed the isolated game; `pcall` cannot catch C++ failures.
  That diagnostic is not a normal-route crash or a performance result.
- Removal used to drain an entire kind in one frame. Adds and removals now share
  the existing per-kind budget (600 solid props, 2500 trees), with removals first.
- Draining additions used to copy the entire pending tail every batch. A FIFO
  releases consumed references without copying the remaining entries. A LuaJIT
  microbenchmark draining 100,000 entries in batches of 600 took approximately
  160 ms with tail copying versus 2 ms with FIFO. This is not an FPS measurement.
- Diagnostic results include pending add/remove counts, so queue drain can be
  distinguished from total spawned items.

## Validation

Four LuaJIT-backed regressions cover interleaved FIFO order, garbage collection of
consumed tile references, boundary ownership (including negative tiles), duplicate
retirement, combined batch limits, and skipping stale generations. They invoke the
actual world scheduler with an engine stand-in. Existing widget checks also compile
the full Lua module, guarding LuaJIT's 200-local limit.

Live evidence is under the managed worktree's `out/runtime-review/`. The first
manual run was diagnostic only. The fresh runtime-only Kyiv route drove 1782 m;
subsequent Potato/OASIS changes preserved the road and did not crash. Queues drained
to zero during the hold; a later count of all actual Forest items matched the
reported count exactly (52,472). This run uses the pre-placement-fix generator.

The performance gate failed: the initial 120-second route measured 26.81 ms mean,
81 ms p99, 17 frames over 100 ms. Offline tests/Claude work overlapped this run and
the installed game is now 0.40.3, so it is not comparable to the earlier 0.40.2 table.
The subsequent manual hold keeps accumulating `driveFrames`; the initial route
snapshot is saved separately as `route-fixed-evidence.json`. No frame-time gain is
claimed from this run or from the FIFO microbenchmark. Integrated Python/Lua suite:
277 tests run: 274 passed, 3 skipped (local cache fixtures unavailable).

Retirement diagnostics also record the largest spatial-query batch and its elapsed
time; the slowest commit records its shape and add/remove counts. These help
separate spatial lookup cost from engine mutation cost in follow-up measurements.
