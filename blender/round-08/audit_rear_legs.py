import bpy
import json
import math
from pathlib import Path
from mathutils import Vector


ROOT = Path("/Users/phoebedufei/Documents/ChatGPT/3D")
BLEND = ROOT / "blender/round-08/pet_unity_canine_ik_walk.blend"
OUT = ROOT / "blender/round-08/rear_leg_audit.json"

bpy.ops.wm.open_mainfile(filepath=str(BLEND))
scene = bpy.context.scene
pet = bpy.data.objects["Pet_Unity_Mesh"]
rig = bpy.data.objects["Pet_Unity_Canine_Rig"]

points = [pet.matrix_world @ Vector(corner) for corner in pet.bound_box]
lo = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
hi = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
dims = hi - lo
mid_y = (lo.y + hi.y) * 0.5

group_names = {group.index: group.name for group in pet.vertex_groups}
rear_vertices = 0
cross_vertices = 0
cross_weight_sum = 0.0
same_weight_sum = 0.0
side_stats = {"L": {"vertices": 0, "cross": 0}, "R": {"vertices": 0, "cross": 0}}
height_bands = {
    "paw_0_30": {"vertices": 0, "cross": 0},
    "lower_30_48": {"vertices": 0, "cross": 0},
    "upper_48_62": {"vertices": 0, "cross": 0},
}
cross_weight_by_group = {}

for vertex in pet.data.vertices:
    point = pet.matrix_world @ vertex.co
    nx = (point.x - lo.x) / max(dims.x, 1e-9)
    nz = (point.z - lo.z) / max(dims.z, 1e-9)
    if not (0.20 <= nx <= 0.53 and nz <= 0.62):
        continue
    side = "L" if point.y >= mid_y else "R"
    other = "R" if side == "L" else "L"
    same = 0.0
    cross = 0.0
    for item in vertex.groups:
        name = group_names[item.group]
        if not name.startswith("Rear_"):
            continue
        if name.endswith("." + side):
            same += item.weight
        elif name.endswith("." + other):
            cross += item.weight
    rear_vertices += 1
    side_stats[side]["vertices"] += 1
    same_weight_sum += same
    cross_weight_sum += cross
    if nz < 0.30:
        band = "paw_0_30"
    elif nz < 0.48:
        band = "lower_30_48"
    else:
        band = "upper_48_62"
    height_bands[band]["vertices"] += 1
    if cross > 0.05:
        cross_vertices += 1
        side_stats[side]["cross"] += 1
        height_bands[band]["cross"] += 1
        for item in vertex.groups:
            name = group_names[item.group]
            if name.startswith("Rear_") and name.endswith("." + other):
                cross_weight_by_group[name] = cross_weight_by_group.get(name, 0.0) + item.weight


def angle_degrees(a, b):
    if a.length < 1e-9 or b.length < 1e-9:
        return None
    return math.degrees(a.angle(b))


poses = []
for frame in (1, 7, 13, 19, 24):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    entry = {"frame": frame, "sides": {}}
    for side in ("L", "R"):
        upper = rig.pose.bones[f"Rear_Upper.{side}"]
        lower = rig.pose.bones[f"Rear_Lower.{side}"]
        paw = rig.pose.bones[f"Rear_Paw.{side}"]
        hip = rig.matrix_world @ upper.head
        knee = rig.matrix_world @ upper.tail
        hock = rig.matrix_world @ lower.tail
        paw_tail = rig.matrix_world @ paw.tail
        entry["sides"][side] = {
            "hip": list(hip),
            "knee": list(knee),
            "hock": list(hock),
            "paw_tail": list(paw_tail),
            "knee_bend_degrees": angle_degrees(hip - knee, hock - knee),
            "hock_bend_degrees": angle_degrees(knee - hock, paw_tail - hock),
            "lateral_knee_offset_m": knee.y - mid_y,
            "lateral_hock_offset_m": hock.y - mid_y,
        }
    poses.append(entry)

report = {
    "rear_region_vertices": rear_vertices,
    "vertices_with_opposite_side_rear_weight_over_0_05": cross_vertices,
    "cross_vertex_percent": cross_vertices * 100.0 / max(1, rear_vertices),
    "mean_same_side_rear_weight": same_weight_sum / max(1, rear_vertices),
    "mean_opposite_side_rear_weight": cross_weight_sum / max(1, rear_vertices),
    "side_stats": side_stats,
    "height_bands": height_bands,
    "cross_weight_by_group": cross_weight_by_group,
    "pose_joint_audit": poses,
}
OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
