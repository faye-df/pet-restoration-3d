# Round 13 — Unity canine rig candidate

Status: **candidate**. Stable rollback: **Round 09**.

This version keeps voxel-derived smooth weights, mirrors opposite-side limb
weights back to the matching anatomical side for all four legs, creates four
non-deforming pole targets, and lets the front IK chain include the scapula.

Automated results:

- 21,229 vertices / 23,169 polygons.
- 36 deform bones; 45 Blender bones including Root, four foot IK targets, and
  four pole targets.
- 100% weight coverage; maximum four influences per vertex.
- Zero front and rear cross-weight violations after reopening the `.blend`.
- Maximum front-foot target error: approximately 0.006 mm.
- Rear swing clearance: approximately 4.8 cm.

Do not mark this version stable until its FBX has passed a Unity/PICO import and
runtime test. See `../VERSIONS.md` and `../version_manifest.json` for rollback and
checksum information.

The `.blend` and `.fbx` in this directory are stored in GitHub through Git LFS.
A normal clone with Git LFS installed retrieves both files automatically.
