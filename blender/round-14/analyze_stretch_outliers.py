import bpy
import json
import os
from collections import Counter, defaultdict, deque
from pathlib import Path


ROOT = Path("/Users/phoebedufei/Documents/ChatGPT/3D")
SOURCE = Path(os.environ.get(
    "PET_SOURCE_BLEND",
    str(ROOT / "blender/round-13/pet_unity_canine_walk_fixed.blend"),
))
OUT = Path(os.environ.get(
    "PET_ANALYSIS_OUT",
    str(ROOT / "blender/round-14/stretch_outlier_analysis.json"),
))
OUT.parent.mkdir(parents=True, exist_ok=True)


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


def vertex_weights(obj, vertex_index, names):
    return sorted(
        (
            {"bone": names[item.group], "weight": item.weight}
            for item in obj.data.vertices[vertex_index].groups
            if item.weight > 1e-6
        ),
        key=lambda item: item["weight"],
        reverse=True,
    )


def connected_components(vertex_count, edges):
    adjacency = [[] for _ in range(vertex_count)]
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)
    labels = [-1] * vertex_count
    sizes = []
    for start in range(vertex_count):
        if labels[start] >= 0:
            continue
        label = len(sizes)
        queue = deque([start])
        labels[start] = label
        size = 0
        while queue:
            vertex = queue.popleft()
            size += 1
            for neighbor in adjacency[vertex]:
                if labels[neighbor] < 0:
                    labels[neighbor] = label
                    queue.append(neighbor)
        sizes.append(size)
    return labels, sizes


bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
scene = bpy.context.scene
pet = bpy.data.objects["Pet_Unity_Mesh"]
names = {group.index: group.name for group in pet.vertex_groups}
rest_points = [pet.matrix_world @ vertex.co for vertex in pet.data.vertices]
edges = [(edge.vertices[0], edge.vertices[1]) for edge in pet.data.edges]
rest_lengths = [(rest_points[b] - rest_points[a]).length for a, b in edges]
labels, component_sizes = connected_components(len(pet.data.vertices), edges)

lo = [min(point[axis] for point in rest_points) for axis in range(3)]
hi = [max(point[axis] for point in rest_points) for axis in range(3)]
dims = [max(hi[axis] - lo[axis], 1e-9) for axis in range(3)]

length_bins = {
    "under_0_1mm": sum(length < 0.0001 for length in rest_lengths),
    "0_1_to_0_5mm": sum(0.0001 <= length < 0.0005 for length in rest_lengths),
    "0_5_to_1mm": sum(0.0005 <= length < 0.001 for length in rest_lengths),
    "1_to_5mm": sum(0.001 <= length < 0.005 for length in rest_lengths),
    "over_5mm": sum(length >= 0.005 for length in rest_lengths),
}

frames = []
outlier_vertex_counts = Counter()
for frame in (1, 7, 13, 19, 24):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    posed = evaluated_points(pet)
    records = []
    for edge_index, ((a, b), rest_length) in enumerate(zip(edges, rest_lengths)):
        if rest_length <= 1e-7:
            continue
        posed_length = (posed[b] - posed[a]).length
        ratio = posed_length / rest_length
        if ratio <= 2.0:
            continue
        records.append((ratio, edge_index, a, b, rest_length, posed_length))
        if ratio > 5.0:
            outlier_vertex_counts[a] += 1
            outlier_vertex_counts[b] += 1
    records.sort(reverse=True)
    top = []
    for ratio, edge_index, a, b, rest_length, posed_length in records[:30]:
        midpoint = (rest_points[a] + rest_points[b]) * 0.5
        normalized = [(midpoint[axis] - lo[axis]) / dims[axis] for axis in range(3)]
        top.append({
            "edge_index": edge_index,
            "vertices": [a, b],
            "ratio": ratio,
            "rest_length_m": rest_length,
            "posed_length_m": posed_length,
            "rest_midpoint_m": list(midpoint),
            "normalized_midpoint": normalized,
            "component_ids": [labels[a], labels[b]],
            "component_sizes": [component_sizes[labels[a]], component_sizes[labels[b]]],
            "endpoint_weights": [vertex_weights(pet, a, names), vertex_weights(pet, b, names)],
        })
    frames.append({
        "frame": frame,
        "edges_over_2x": len(records),
        "edges_over_5x": sum(item[0] > 5.0 for item in records),
        "top_outliers": top,
    })

report = {
    "source": str(SOURCE),
    "mesh": {
        "vertices": len(pet.data.vertices),
        "edges": len(edges),
        "polygons": len(pet.data.polygons),
        "connected_components": len(component_sizes),
        "largest_component_sizes": sorted(component_sizes, reverse=True)[:20],
    },
    "rest_edge_lengths_m": {
        "min": min(rest_lengths),
        "p01": percentile(rest_lengths, 0.01),
        "p50": percentile(rest_lengths, 0.50),
        "p99": percentile(rest_lengths, 0.99),
        "max": max(rest_lengths),
        "bins": length_bins,
    },
    "frames": frames,
    "most_frequent_outlier_vertices": [
        {
            "vertex": vertex,
            "occurrences": count,
            "component": labels[vertex],
            "component_size": component_sizes[labels[vertex]],
            "rest_position_m": list(rest_points[vertex]),
            "weights": vertex_weights(pet, vertex, names),
        }
        for vertex, count in outlier_vertex_counts.most_common(50)
    ],
}
OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
