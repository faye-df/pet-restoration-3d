import bpy
import json
from pathlib import Path
from mathutils import Vector


ROOT = Path("/Users/phoebedufei/Documents/ChatGPT/3D")
CASES = {
    "voxel_then_rear_repair": ROOT / "blender/round-09/pet_unity_canine_walk_fixed.blend",
    "semantic_only_no_repair": ROOT / "blender/round-10/semantic-walk/pet_unity_canine_walk_fixed.blend",
    "round11_all_limbs_poles_v1": ROOT / "blender/round-11/pet_unity_canine_walk_fixed.blend",
    "round12_all_limbs_poles_planar": ROOT / "blender/round-12/pet_unity_canine_walk_fixed.blend",
    "round13_static_bounds_candidate": ROOT / "blender/round-13/pet_unity_canine_walk_fixed.blend",
}
OUT = ROOT / "blender/round-10/semantic_vs_voxel_ab_report.json"


def percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def evaluated_points(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        return [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def cross_audit(pet, family, x_min, x_max):
    points = [pet.matrix_world @ vertex.co for vertex in pet.data.vertices]
    lo = Vector(tuple(min(point[i] for point in points) for i in range(3)))
    hi = Vector(tuple(max(point[i] for point in points) for i in range(3)))
    dims = hi - lo
    mid_y = (lo.y + hi.y) * 0.5
    names = {group.index: group.name for group in pet.vertex_groups}
    audited = 0
    cross_005 = 0
    cross_sum = 0.0
    for vertex in pet.data.vertices:
        point = pet.matrix_world @ vertex.co
        nx = (point.x - lo.x) / max(dims.x, 1e-9)
        nz = (point.z - lo.z) / max(dims.z, 1e-9)
        if not (x_min <= nx <= x_max and nz <= 0.62):
            continue
        side = "L" if point.y >= mid_y else "R"
        other = "R" if side == "L" else "L"
        cross = sum(
            item.weight
            for item in vertex.groups
            if names[item.group].startswith(family + "_")
            and names[item.group].endswith("." + other)
        )
        audited += 1
        cross_sum += cross
        if cross > 0.05:
            cross_005 += 1
    return {
        "audited_vertices": audited,
        "opposite_side_over_0_05": cross_005,
        "cross_percent": cross_005 * 100.0 / max(1, audited),
        "mean_opposite_side_weight": cross_sum / max(1, audited),
    }


def audit_case(path):
    bpy.ops.wm.open_mainfile(filepath=str(path))
    scene = bpy.context.scene
    pet = bpy.data.objects["Pet_Unity_Mesh"]
    rig = bpy.data.objects["Pet_Unity_Canine_Rig"]
    rest_points = [pet.matrix_world @ vertex.co for vertex in pet.data.vertices]
    edges = [(edge.vertices[0], edge.vertices[1]) for edge in pet.data.edges]
    rest_lengths = [(rest_points[b] - rest_points[a]).length for a, b in edges]

    frame_stretch = []
    for frame in (1, 7, 13, 19, 24):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        posed = evaluated_points(pet)
        ratios = []
        for (a, b), rest_length in zip(edges, rest_lengths):
            if rest_length <= 1e-7:
                continue
            ratios.append((posed[b] - posed[a]).length / rest_length)
        frame_stretch.append({
            "frame": frame,
            "p99_ratio": percentile(ratios, 0.99),
            "p999_ratio": percentile(ratios, 0.999),
            "max_ratio": max(ratios),
            "edges_over_2x": sum(1 for ratio in ratios if ratio > 2.0),
            "edges_over_5x": sum(1 for ratio in ratios if ratio > 5.0),
        })

    weighted = 0
    max_influences = 0
    for vertex in pet.data.vertices:
        count = sum(1 for item in vertex.groups if item.weight > 1e-6)
        weighted += count > 0
        max_influences = max(max_influences, count)

    return {
        "file": str(path),
        "mesh": {
            "vertices": len(pet.data.vertices),
            "polygons": len(pet.data.polygons),
            "coverage_percent": weighted * 100.0 / max(1, len(pet.data.vertices)),
            "max_influences_per_vertex": max_influences,
        },
        "cross_weight_audit": {
            "front": cross_audit(pet, "Front", 0.54, 0.80),
            "rear": cross_audit(pet, "Rear", 0.20, 0.53),
        },
        "edge_stretch_audit": frame_stretch,
        "bones": {
            "total": len(rig.data.bones),
            "deform": sum(1 for bone in rig.data.bones if bone.use_deform),
        },
    }


report = {name: audit_case(path) for name, path in CASES.items()}
OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
