import bpy
import bmesh
import json
import time
from collections import defaultdict
from pathlib import Path
from mathutils import Vector


ROOT = Path("/Users/phoebedufei/Documents/ChatGPT/3D")
SOURCE = ROOT / "blender/round-13/pet_unity_canine_walk_fixed.blend"
OUT = ROOT / "blender/round-14"
PREVIEWS = OUT / "previews"
FRAMES = PREVIEWS / "frames"
BLEND = OUT / "pet_unity_canine_motion_bridge_fixed.blend"
FBX = OUT / "pet_unity_canine_motion_bridge_fixed.fbx"
REPORT = OUT / "motion_bridge_fix_report.json"
OUT.mkdir(parents=True, exist_ok=True)
PREVIEWS.mkdir(parents=True, exist_ok=True)
FRAMES.mkdir(parents=True, exist_ok=True)

SAMPLE_FRAMES = (1, 7, 13, 19, 24)
STRETCH_THRESHOLD = 2.0
MIN_LIMB_CONFIDENCE = 0.50


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


def dominant_limb(vertex, group_names):
    totals = defaultdict(float)
    for item in vertex.groups:
        name = group_names[item.group]
        for family in ("Front", "Rear"):
            for side in ("L", "R"):
                if name.startswith(family + "_") and name.endswith("." + side):
                    totals[(family, side)] += item.weight
    if not totals:
        return None
    key, weight = max(totals.items(), key=lambda item: item[1])
    if weight < MIN_LIMB_CONFIDENCE:
        return None
    return key[0], key[1], weight


def edge_stretch_audit(scene, pet):
    rest_points = [pet.matrix_world @ vertex.co for vertex in pet.data.vertices]
    edges = [(edge.vertices[0], edge.vertices[1]) for edge in pet.data.edges]
    rest_lengths = [(rest_points[b] - rest_points[a]).length for a, b in edges]
    result = []
    for frame in SAMPLE_FRAMES:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        posed = evaluated_points(pet)
        ratios = [
            (posed[b] - posed[a]).length / rest_length
            for (a, b), rest_length in zip(edges, rest_lengths)
            if rest_length > 1e-7
        ]
        result.append({
            "frame": frame,
            "p99_ratio": percentile(ratios, 0.99),
            "p999_ratio": percentile(ratios, 0.999),
            "max_ratio": max(ratios, default=0.0),
            "edges_over_2x": sum(ratio > 2.0 for ratio in ratios),
            "edges_over_5x": sum(ratio > 5.0 for ratio in ratios),
        })
    return result


started = time.time()
bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
scene = bpy.context.scene
scene.name = "Round14_Motion_Bridge_Repair"
pet = bpy.data.objects["Pet_Unity_Mesh"]
rig = bpy.data.objects["Pet_Unity_Canine_Rig"]
scene.frame_set(1)
bpy.context.view_layer.update()

before = edge_stretch_audit(scene, pet)
rest_points = [pet.matrix_world @ vertex.co for vertex in pet.data.vertices]
edges = [(edge.vertices[0], edge.vertices[1]) for edge in pet.data.edges]
rest_lengths = [(rest_points[b] - rest_points[a]).length for a, b in edges]
group_names = {group.index: group.name for group in pet.vertex_groups}
dominant = [dominant_limb(vertex, group_names) for vertex in pet.data.vertices]

lo = Vector(tuple(min(point[axis] for point in rest_points) for axis in range(3)))
hi = Vector(tuple(max(point[axis] for point in rest_points) for axis in range(3)))
dims = hi - lo

max_ratios = [1.0] * len(edges)
for frame in SAMPLE_FRAMES:
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    posed = evaluated_points(pet)
    for index, ((a, b), rest_length) in enumerate(zip(edges, rest_lengths)):
        if rest_length > 1e-7:
            max_ratios[index] = max(
                max_ratios[index],
                (posed[b] - posed[a]).length / rest_length,
            )

candidate_edges = set()
candidate_details = []
for edge_index, ((a, b), max_ratio) in enumerate(zip(edges, max_ratios)):
    limb_a = dominant[a]
    limb_b = dominant[b]
    if limb_a is None or limb_b is None:
        continue
    family_a, side_a, confidence_a = limb_a
    family_b, side_b, confidence_b = limb_b
    if family_a != family_b or side_a == side_b:
        continue
    midpoint = (rest_points[a] + rest_points[b]) * 0.5
    nx = (midpoint.x - lo.x) / max(dims.x, 1e-9)
    nz = (midpoint.z - lo.z) / max(dims.z, 1e-9)
    in_family_region = (
        (family_a == "Front" and 0.54 <= nx <= 0.85)
        or (family_a == "Rear" and 0.15 <= nx <= 0.55)
    )
    if not in_family_region or nz > 0.62 or max_ratio <= STRETCH_THRESHOLD:
        continue
    candidate_edges.add(frozenset((a, b)))
    candidate_details.append({
        "edge_index": edge_index,
        "vertices": [a, b],
        "family": family_a,
        "max_ratio": max_ratio,
        "rest_length_m": rest_lengths[edge_index],
        "normalized_midpoint": [nx, (midpoint.y - lo.y) / max(dims.y, 1e-9), nz],
        "endpoint_confidence": [confidence_a, confidence_b],
    })

# Remove the thin polygons that physically connect an independently animated
# left limb to its right counterpart. This is deliberately motion driven: a
# legitimate belly seam is not touched unless it stretches during the gait and
# both endpoints are confidently controlled by opposite sides of one limb pair.
faces_to_delete = set()
for polygon in pet.data.polygons:
    vertices = list(polygon.vertices)
    polygon_edges = {
        frozenset((vertices[index], vertices[(index + 1) % len(vertices)]))
        for index in range(len(vertices))
    }
    if polygon_edges & candidate_edges:
        faces_to_delete.add(polygon.index)

original_counts = {
    "vertices": len(pet.data.vertices),
    "edges": len(pet.data.edges),
    "polygons": len(pet.data.polygons),
}

# Do not use Blender's edit-mode selection here: a saved .blend can carry
# selected vertices from a previous interactive session, and selection flush
# may expand a face deletion unexpectedly. BMesh addresses exactly the indexed
# faces and keeps vertex-group, UV, color, and material custom data intact.
bm = bmesh.new()
bm.from_mesh(pet.data)
bm.faces.ensure_lookup_table()
bm.edges.ensure_lookup_table()
indexed_faces = [bm.faces[index] for index in sorted(faces_to_delete)]
bmesh.ops.delete(bm, geom=indexed_faces, context="FACES_ONLY")
bm.edges.ensure_lookup_table()
loose_edges = [edge for edge in bm.edges if not edge.link_faces]
loose_edges_removed = len(loose_edges)
if loose_edges:
    bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")
bm.to_mesh(pet.data)
bm.free()
pet.data.update()

after_counts = {
    "vertices": len(pet.data.vertices),
    "edges": len(pet.data.edges),
    "polygons": len(pet.data.polygons),
}
if after_counts["vertices"] != original_counts["vertices"]:
    raise RuntimeError(
        "Safety check failed: topology repair must not delete vertices "
        f"({original_counts['vertices']} -> {after_counts['vertices']})"
    )
if after_counts["polygons"] != original_counts["polygons"] - len(faces_to_delete):
    raise RuntimeError(
        "Safety check failed: deleted polygon count does not match the planned cut "
        f"({original_counts['polygons']} -> {after_counts['polygons']}; planned {len(faces_to_delete)})"
    )
after = edge_stretch_audit(scene, pet)

# Count open boundary edges after the surgical cut. Open edges are acceptable
# on the hidden inner legs for this test, but the number is reported rather
# than concealed so a later retopology pass can close them if necessary.
edge_face_counts = defaultdict(int)
for polygon in pet.data.polygons:
    vertices = list(polygon.vertices)
    for index in range(len(vertices)):
        edge_face_counts[frozenset((vertices[index], vertices[(index + 1) % len(vertices)]))] += 1
boundary_edges = sum(count == 1 for count in edge_face_counts.values())
nonmanifold_edges = sum(count != 2 for count in edge_face_counts.values())

scene.render.image_settings.file_format = "PNG"
for frame in (1, 7, 13, 19):
    scene.frame_set(frame)
    scene.render.filepath = str(PREVIEWS / f"walk_fixed_{frame:02d}.png")
    bpy.ops.render.render(write_still=True)

scene.render.filepath = str(FRAMES / "walk_")
bpy.ops.render.render(animation=True)

scene.frame_set(1)
for obj in scene.objects:
    if obj.type in {"CAMERA", "LIGHT"} or obj.name == "Preview_Ground" or obj.name.startswith("DBG_"):
        obj.hide_viewport = True
pet.hide_viewport = False
rig.hide_viewport = False
rig.show_in_front = True
bpy.ops.object.select_all(action="DESELECT")
rig.select_set(True)
bpy.context.view_layer.objects.active = rig
bpy.ops.wm.save_as_mainfile(filepath=str(BLEND))

bpy.ops.object.select_all(action="DESELECT")
pet.select_set(True)
rig.select_set(True)
bpy.context.view_layer.objects.active = rig
bpy.ops.export_scene.fbx(
    filepath=str(FBX),
    use_selection=True,
    object_types={"ARMATURE", "MESH"},
    apply_unit_scale=True,
    apply_scale_options="FBX_SCALE_UNITS",
    add_leaf_bones=False,
    use_armature_deform_only=True,
    bake_anim=True,
    bake_anim_use_all_actions=False,
    bake_anim_simplify_factor=0.0,
    path_mode="COPY",
    embed_textures=True,
)

report = {
    "source": str(SOURCE),
    "method": {
        "name": "motion-driven opposite-limb bridge removal",
        "sample_frames": list(SAMPLE_FRAMES),
        "stretch_threshold": STRETCH_THRESHOLD,
        "minimum_limb_confidence": MIN_LIMB_CONFIDENCE,
        "description": (
            "Delete only polygons incident to an edge whose endpoints are confidently driven by opposite sides "
            "of the same limb family and whose edge stretches during the gait. Skeleton and weights are unchanged."
        ),
    },
    "topology": {
        "before": original_counts,
        "after": after_counts,
        "candidate_bridge_edges": len(candidate_edges),
        "deleted_polygons": len(faces_to_delete),
        "loose_edges_removed": loose_edges_removed,
        "boundary_edges_after": boundary_edges,
        "nonmanifold_edges_after": nonmanifold_edges,
        "candidate_details": sorted(candidate_details, key=lambda item: item["max_ratio"], reverse=True),
    },
    "edge_stretch_before": before,
    "edge_stretch_after": after,
    "outputs": {
        "blend": str(BLEND),
        "fbx": str(FBX),
        "previews": str(PREVIEWS),
    },
    "elapsed_seconds": round(time.time() - started, 3),
}
REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
