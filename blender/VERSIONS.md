# Pet rig pipeline versions

The numbered `round-*` folders are immutable experiment/output versions. A new
test writes a new round instead of overwriting the previous Blender or FBX file.
Large binary artifacts stay on this machine and are identified by SHA-256 in
`version_manifest.json`; scripts, JSON reports, and this decision log are tracked
in Git.

## Status vocabulary

- `stable`: recommended rollback point.
- `candidate`: passed automated checks but still needs an engine test.
- `rejected`: retained as evidence; do not import into Unity.
- `superseded`: useful history, replaced by a later round.

## Version history

### Round 09 — stable baseline

- Corrected pose-local animation axes.
- Repaired most rear-leg cross weights.
- No pole targets; front IK maximum error was about 8.46 mm.
- Kept as the known-good visual rollback point.

### Round 10 — rejected

- A/B test of deterministic semantic-distance weights without voxel transfer.
- Left/right cross weights were zero, but hard semantic borders caused severe
  mesh tearing: 185–250 edges per sampled frame exceeded 5x their rest length;
  worst observed ratio was about 117x.
- Evidence that side-safe weights also need topology-aware smoothing.

### Round 11 — rejected

- Added four-limb side cleanup, four pole targets, and a four-bone front IK chain.
- IK error improved to about 0.006 mm, but pole-angle scoring allowed roughly
  4.4 cm rear-knee lateral drift.

### Round 12 — superseded

- Changed pole-angle selection to prioritize planar motion.
- Generator self-audit reported zero cross weights, but independent reload audit
  exposed a pose-dependent bounding-box bug in the semantic region calculation.

### Round 13 — candidate (current)

- Semantic regions use undeformed source vertices, independent of animation frame.
- Independent reload audit: zero front and rear cross-weight violations.
- 21,229 vertices, 23,169 polygons, 36 deform bones, 4 pole/IK controls plus root,
  100% weighted vertices, maximum 4 influences per vertex.
- Front IK error reduced from 8.46 mm to about 0.006 mm.
- Rear foot clearance is about 4.8 cm.
- Side, front, and three-quarter previews show no visible leg crossing, gross
  splaying, or mesh tearing.
- Still requires Unity/PICO import, scale, animation-loop, and runtime performance
  checks before promotion to `stable`.

## Reproduction

The current generator is parameterized rather than tied to one output folder:

```sh
env PET_OUT=<new-round-directory> \
  PET_REPAIR_CROSS_WEIGHTS=1 \
  PET_REPAIR_ALL_LIMBS=1 \
  PET_ADD_POLE_TARGETS=1 \
  /Applications/Blender.app/Contents/MacOS/Blender \
  --background --factory-startup \
  --python blender/round-09/fix_rear_legs_and_axes.py
```

Run `blender/round-10/audit_ab.py` after saving and reloading the result. A version
must not be promoted based only on the in-process generator report.

