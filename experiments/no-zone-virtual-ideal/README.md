# Virtual Collision-Free No-Zone

This experiment removes shuttle-to-shuttle collision constraints while
retaining direct movement, pick/place, exclusive readers, optical service, and
platter return. Same-side shuttles share pending work. Natural replay uses a
local-first benefit gate: an owner with local work stays local, while a helper
leaves its region only when its estimated read-time benefit exceeds the cost of
returning to its home anchor. Closed batch sees all tasks and selects the
minimum estimated completion candidate.

The result is a physically impossible collision-free virtual reference, not a
proof of globally optimal scheduling. It measures how much of Greedy
No-Zone's loss could disappear under perfect shuttle coordination.

```bash
.venv/bin/python scripts/run_virtual_nozone_study.py \
  --config experiments/no-zone-virtual-ideal/full.json \
  --workers 4
```
