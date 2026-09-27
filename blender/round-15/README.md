# Round 15 — rejected local residual-weight refinement

## Hypothesis

After Round 14 removed invalid cross-limb polygons, 33 vertices still belonged
to edges that stretched above 2x in at least one sampled gait frame. The test
asked whether a very local, topology-aware weight adjustment could reduce those
residuals without changing the mesh.

The experiment changed only the 33 motion-proven vertices. Each iteration mixed
the vertex's weights with its same-side one-ring neighbors, projected opposite-
side limb weights to the geometric side, kept the strongest four influences,
and normalized them.

## Result

All six variants were worse than Round 14. The Round 14 maximum sampled stretch
was 3.95x with at most 15 edges above 2x in one frame. The best tested Round 15
variant still reached 4.62x, and the projection-only variant reached 4.77x.

The affected vertices are not simple left/right mistakes. They sit around the
shoulder, abdomen, tail root, and front/rear transition, where legitimate torso
and limb influences overlap. One-ring averaging spreads those mixed influences;
hard side projection removes blending needed for the torso-to-limb transition.

## Decision

- Reject all Round 15 variants.
- Keep Round 14 as the current candidate.
- Do not apply generic Laplacian/neighbor weight smoothing to this asset.
- If deformation quality must improve further, use local manual retopology or a
  closed-volume remesh before binding, then recompute weights on that clean mesh.

The experiment generator remains in `refine_residual_weights.py` for auditing
and for possible future tests with a genuinely clean quadruped mesh. Individual
test `.blend` files remain local and are not promoted or uploaded.
