import bpy
import json
import os
import time
from collections import defaultdict
from pathlib import Path
from mathutils import Vector


ROOT = Path("/Users/phoebedufei/Documents/ChatGPT/3D")
SOURCE = Path(os.environ.get(
    "PET_SOURCE_BLEND",
    str(ROOT / "blender/round-14/pet_unity_canine_motion_bridge_fixed.blend"),
))
OUT = Path(os.environ.get("PET_OUT", str(ROOT / "blender/round-15")))
ALPHA = float(os.environ.get("PET_SMOOTH_ALPHA", "0.5"))
ITERATIONS = int(os.environ.get("PET_SMOOTH_ITERATIONS", "3"))
STRETCH_THRESHOLD = float(os.environ.get("PET_STRETCH_THRESHOLD", "2.0"))
SAMPLE_FRAMES = (1, 7, 13, 19, 24)
BLEND = OUT / "pet_unity_canine_residual_weights.blend"
REPORT = OUT / "residual_weight_report.json"
OUT.mkdir(parents=True, exist_ok=True)


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


def read_weights(obj, group_names):
    return [
        {
            group_names[item.group]: item.weight
            for item in vertex.groups
            if item.weight > 1e-8
        }
        for vertex in obj.data.vertices
    ]


def normalize_top4(weights):
    strongest = sorted(
        ((name, value) for name, value in weights.items() if value > 1e-8),
        key=lambda item: item[1],
        reverse=True,
    )[:4]
    total = sum(value for _, value in strongest)
    if total <= 1e-8:
        return {"Pelvis": 1.0}
    return {name: value / total for name, value in strongest}


def mirror_to_geometry_side(weights, side):
    opposite = "R" if side == "L" else "L"
    projected = defaultdict(float)
    for name, value in weights.items():
        if (
            (name.startswith("Front_") or name.startswith("Rear_"))
            and name.endswith("." + opposite)
        ):
            projected[name[:-1] + side] += value
        else:
            projected[name] += value
    return dict(projected)


def stretch_audit(scene, obj):
    rest = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    edges = [(edge.vertices[0], edge.vertices[1]) for edge in obj.data.edges]
    lengths = [(rest[b] - rest[a]).length for a, b in edges]
    max_ratios = [1.0] * len(edges)
    frames = []
    for frame in SAMPLE_FRAMES:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        posed = evaluated_points(obj)
        ratios = []
        for index, ((a, b), length) in enumerate(zip(edges, lengths)):
            if length <= 1e-7:
                continue
            ratio = (posed[b] - posed[a]).length / length
            ratios.append(ratio)
            max_ratios[index] = max(max_ratios[index], ratio)
        frames.append({
            "frame": frame,
            "p99_ratio": percentile(ratios, 0.99),
            "p999_ratio": percentile(ratios, 0.999),
            "max_ratio": max(ratios, default=0.0),
            "edges_over_2x": sum(ratio > 2.0 for ratio in ratios),
            "edges_over_5x": sum(ratio > 5.0 for ratio in ratios),
        })
    return edges, max_ratios, frames


started = time.time()
bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
scene = bpy.context.scene
pet = bpy.data.objects["Pet_Unity_Mesh"]
rig = bpy.data.objects["Pet_Unity_Canine_Rig"]
scene.frame_set(1)
bpy.context.view_layer.update()

edges, max_ratios, before = stretch_audit(scene, pet)
active_vertices = set()
for (a, b), ratio in zip(edges, max_ratios):
    if ratio > STRETCH_THRESHOLD:
        active_vertices.add(a)
        active_vertices.add(b)

adjacency = [[] for _ in pet.data.vertices]
for a, b in edges:
    adjacency[a].append(b)
    adjacency[b].append(a)

points = [pet.matrix_world @ vertex.co for vertex in pet.data.vertices]
mid_y = (min(point.y for point in points) + max(point.y for point in points)) * 0.5
sides = ["L" if point.y >= mid_y else "R" for point in points]
group_names = {group.index: group.name for group in pet.vertex_groups}
weights = read_weights(pet, group_names)
weights_before = {str(index): weights[index] for index in sorted(active_vertices)}

for _ in range(ITERATIONS):
    updated = list(weights)
    for vertex_index in active_vertices:
        same_side_neighbors = [
            neighbor for neighbor in adjacency[vertex_index]
            if sides[neighbor] == sides[vertex_index]
        ]
        if not same_side_neighbors:
            continue
        neighbor_average = defaultdict(float)
        for neighbor in same_side_neighbors:
            for name, value in weights[neighbor].items():
                neighbor_average[name] += value / len(same_side_neighbors)
        blended = defaultdict(float)
        for name, value in weights[vertex_index].items():
            blended[name] += (1.0 - ALPHA) * value
        for name, value in neighbor_average.items():
            blended[name] += ALPHA * value
        updated[vertex_index] = normalize_top4(
            mirror_to_geometry_side(dict(blended), sides[vertex_index])
        )
    weights = updated

# Rewrite only the motion-proven outlier vertices. All other skin weights remain
# byte-for-byte equivalent at the Blender data level.
for group in pet.vertex_groups:
    group.remove(sorted(active_vertices))
for vertex_index in sorted(active_vertices):
    for name, value in weights[vertex_index].items():
        group = pet.vertex_groups.get(name)
        if group is None:
            group = pet.vertex_groups.new(name=name)
        group.add([vertex_index], value, "REPLACE")

bpy.context.view_layer.update()
_, _, after = stretch_audit(scene, pet)
weights_after = {str(index): weights[index] for index in sorted(active_vertices)}

scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(BLEND))
report = {
    "source": str(SOURCE),
    "parameters": {
        "alpha": ALPHA,
        "iterations": ITERATIONS,
        "stretch_threshold": STRETCH_THRESHOLD,
        "sample_frames": list(SAMPLE_FRAMES),
    },
    "method": (
        "Motion-proven outlier vertices only; same-side one-ring graph diffusion, "
        "opposite-side limb projection, top-4 normalization."
    ),
    "active_vertex_count": len(active_vertices),
    "active_vertices": sorted(active_vertices),
    "weights_before": weights_before,
    "weights_after": weights_after,
    "edge_stretch_before": before,
    "edge_stretch_after": after,
    "output_blend": str(BLEND),
    "elapsed_seconds": round(time.time() - started, 3),
}
REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps({
    "parameters": report["parameters"],
    "active_vertex_count": report["active_vertex_count"],
    "edge_stretch_before": before,
    "edge_stretch_after": after,
    "output_blend": str(BLEND),
}, indent=2))
