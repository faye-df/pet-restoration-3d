# Round 14 — motion-driven mesh bridge repair

## Outcome

Round 13's remaining large edge-stretch outliers were not primarily a skinning
weight problem. The Tripo mesh contains topology edges that physically connect
the left and right front/rear legs across the centerline. After side-safe weights
made the limbs move independently, those cross-limb edges stretched by as much
as 10.97x.

Round 14 keeps the Round 13 36-deform-bone skeleton, four IK targets, four pole
targets, animation, textures, and weights. It detects and cuts only topology
bridges that are proven invalid by the walk motion.

## Algorithm

1. Sample frames 1, 7, 13, 19, and 24.
2. Compute the maximum posed/rest length ratio for every mesh edge.
3. Sum each endpoint's weights by limb family and side.
4. Select an edge only when:
   - both endpoints have at least 50% limb-side confidence;
   - both belong to the same front/rear family but opposite sides;
   - the midpoint lies in that limb's lower semantic region; and
   - the edge stretches above 2x in a sampled frame.
5. Delete only polygons incident to selected edges, then remove loose edges.
6. Save a new Blender/FBX version and independently reload it for audit.

This is motion-aware mesh cleanup, not conventional weight smoothing. Weight
smoothing cannot solve a polygon that should not connect two independently
moving legs; it can only turn the bridge into a visible rubber membrane.

## Results

| Metric | Round 13 | Round 14 |
| --- | ---: | ---: |
| Vertices | 21,229 | 21,229 |
| Polygons | 23,169 | 23,138 |
| Deform bones | 36 | 36 |
| Weight coverage | 100% | 100% |
| Max influences | 4 | 4 |
| Front/rear cross-weight violations | 0 / 0 | 0 / 0 |
| Maximum sampled edge stretch | 10.97x | 3.95x |
| Worst edges above 5x per frame | 15 | 0 |
| Boundary edges | 457 | 518 |
| Loose edges | 0 | 0 |

The extra 61 boundary edges form hidden cuts on the inner legs. Multi-angle
renders did not reveal a visible hole, but the underside must still be checked
inside Unity/PICO at close range.

## Why this route

- Blender automatic weights use a bone-heat method based on distance to bones;
  it does not repair incorrect source topology.
- Pinocchio fits a known skeleton into a character volume and was an important
  automatic-rigging baseline, but our skeleton is already placed and tested.
- Bounded biharmonic weights offer smooth, non-negative weights, but generally
  assume a suitable deformation domain; they do not make a fused pair of legs
  topologically separate.
- RigNet predicts skeleton and skinning from a mesh, but replacing the verified
  canine skeleton with a learned generic rig would add a new source of error.

For this asset, the shortest reliable route is: retain the verified skeleton and
weights, detect deformation failures with motion, then repair the bad topology.

## Files

- `repair_motion_bridges.py`: reproducible generator.
- `analyze_stretch_outliers.py`: detailed endpoint/weight diagnosis.
- `verify_topology.py`: independent reload integrity check.
- `render_validation_views.py`: front and three-quarter renders.
- `motion_bridge_fix_report.json`: complete cut and stretch metrics.
- `topology_integrity_report.json`: topology/material/rig integrity comparison.
- `pet_unity_canine_motion_bridge_fixed.blend`: editable candidate.
- `pet_unity_canine_motion_bridge_fixed.fbx`: Unity import candidate.

## References

- Blender Manual, Armature Deform Parent / Automatic Weights:
  <https://docs.blender.org/manual/en/latest/animation/armatures/skinning/parenting.html>
- Baran and Popovic, Automatic Rigging and Animation of 3D Characters (2007):
  <https://dspace.mit.edu/entities/publication/02216671-1424-4552-a2d3-74cec29e2062>
- Jacobson et al., Bounded Biharmonic Weights for Real-Time Deformation (2011):
  <https://homes.cs.washington.edu/~jovan/papers/jacobson-2011-bbw.pdf>
- Xu et al., RigNet: Neural Rigging for Articulated Characters (2020):
  <https://arxiv.org/abs/2005.00559>
