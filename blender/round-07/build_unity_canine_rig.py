import bpy
import json
import math
import os
import time
from pathlib import Path
from mathutils import Quaternion, Vector


ROOT = Path("/Users/phoebedufei/Documents/ChatGPT/3D")
SOURCE = Path(os.environ.get(
    "PET_SOURCE",
    str(ROOT / "outputs/tripo-out/pet-gptimage-v2-p2-20k-quad/tripo-out/pet-gptimage-v2-p2-20k-quad-50ebb73b/model.fbx"),
))
OUT = Path(os.environ.get("PET_OUT", str(ROOT / "blender/round-07")))
# The semantic path is deterministic and side-safe, but the Round10 A/B test
# showed severe discontinuities at hard region borders. Keep voxel as the safe
# default until semantic weights gain a topology-aware smoothing pass.
WEIGHT_MODE = os.environ.get("PET_WEIGHT_MODE", "voxel").lower()
if WEIGHT_MODE not in {"semantic", "voxel"}:
    raise ValueError("PET_WEIGHT_MODE must be 'semantic' or 'voxel'")
PREVIEWS = OUT / "previews"
BLEND = OUT / "pet_unity_canine_rig.blend"
FBX = OUT / "pet_unity_canine_rig.fbx"
REPORT = OUT / "unity_canine_rig_report.json"
VIDEO = PREVIEWS / "pet_walk_preview.mp4"
ANIM_FRAMES = PREVIEWS / "frames"
ANIM_FRAMES.mkdir(parents=True, exist_ok=True)
PREVIEWS.mkdir(parents=True, exist_ok=True)


def bbox_world(obj):
    points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    lo = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    hi = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    return lo, hi


def evaluated_bbox(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
        lo = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
        hi = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
        return lo, hi
    finally:
        evaluated.to_mesh_clear()


def point_segment_distance(point, start, end):
    segment = end - start
    length_squared = segment.length_squared
    if length_squared < 1e-12:
        return (point - start).length
    t = max(0.0, min(1.0, (point - start).dot(segment) / length_squared))
    return (point - (start + segment * t)).length


def add_bone(edit_bones, name, head, tail, parent=None, deform=True):
    bone = edit_bones.new(name)
    bone.head = Vector(head)
    bone.tail = Vector(tail)
    bone.use_deform = deform
    if parent:
        bone.parent = edit_bones[parent]
    return bone


def add_area(scene, name, location, target, energy, size):
    data = bpy.data.lights.new(name, type="AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()
    return obj


def add_bone_marker(collection, start, end, radius, material, name):
    start = Vector(start)
    end = Vector(end)
    delta = end - start
    length = delta.length
    if length < 1e-6:
        return None
    bpy.ops.mesh.primitive_cylinder_add(vertices=10, radius=radius, depth=length, location=(start + end) * 0.5)
    marker = bpy.context.object
    marker.name = "DBG_" + name
    marker.rotation_euler = delta.to_track_quat("Z", "Y").to_euler()
    marker.data.materials.append(material)
    for old_collection in list(marker.users_collection):
        old_collection.objects.unlink(marker)
    collection.objects.link(marker)
    return marker


started = time.time()

# Isolated scene and source import.
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.name = "Round07_Unity_Canine"
bpy.ops.import_scene.fbx(filepath=str(SOURCE), use_anim=False)
meshes = [obj for obj in scene.objects if obj.type == "MESH"]
if len(meshes) != 1:
    raise RuntimeError(f"Expected one pet mesh, found {len(meshes)}")
pet = meshes[0]
pet.name = "Pet_Unity_Mesh"
pet.data.name = "Pet_Unity_MeshData"
for polygon in pet.data.polygons:
    polygon.use_smooth = True
bpy.context.view_layer.objects.active = pet
pet.select_set(True)
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

lo, hi = bbox_world(pet)
dims = hi - lo
length, width, height = dims.x, dims.y, dims.z
mid_y = (lo.y + hi.y) * 0.5
floor_z = lo.z + height * 0.025
back_z = lo.z + height * 0.67

# Anatomical landmarks expressed as proportions of the neutral dog bounds.
def P(x, y, z):
    return Vector((lo.x + length * x, mid_y + width * y, lo.z + height * z))


arm_data = bpy.data.armatures.new("Pet_Unity_Canine_Skeleton")
rig = bpy.data.objects.new("Pet_Unity_Canine_Rig", arm_data)
scene.collection.objects.link(rig)
rig.show_in_front = True
rig.data.display_type = "OCTAHEDRAL"
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
eb = arm_data.edit_bones

# One non-deforming scene root plus 36 deform bones. X is forward, Z is up.
add_bone(eb, "Root", P(0.43, 0.0, 0.48), P(0.43, 0.0, 0.60), deform=False)
add_bone(eb, "Pelvis", P(0.31, 0.0, 0.59), P(0.39, 0.0, 0.64), "Root")
add_bone(eb, "Spine_01", P(0.39, 0.0, 0.64), P(0.49, 0.0, 0.67), "Pelvis")
add_bone(eb, "Spine_02", P(0.49, 0.0, 0.67), P(0.59, 0.0, 0.69), "Spine_01")
add_bone(eb, "Chest", P(0.59, 0.0, 0.69), P(0.68, 0.0, 0.71), "Spine_02")
add_bone(eb, "Neck_01", P(0.68, 0.0, 0.71), P(0.74, 0.0, 0.77), "Chest")
add_bone(eb, "Neck_02", P(0.74, 0.0, 0.77), P(0.80, 0.0, 0.80), "Neck_01")
add_bone(eb, "Head", P(0.80, 0.0, 0.80), P(0.91, 0.0, 0.76), "Neck_02")
add_bone(eb, "Jaw", P(0.81, 0.0, 0.73), P(0.93, 0.0, 0.70), "Head")
add_bone(eb, "Ear.L", P(0.79, 0.13, 0.82), P(0.76, 0.17, 0.96), "Head")
add_bone(eb, "Ear.R", P(0.79, -0.13, 0.82), P(0.76, -0.17, 0.96), "Head")

tail_points = [
    P(0.31, 0.0, 0.60), P(0.25, 0.0, 0.57), P(0.19, 0.0, 0.51),
    P(0.13, 0.0, 0.43), P(0.08, 0.0, 0.33), P(0.04, 0.0, 0.23),
    P(0.01, 0.0, 0.14),
]
tail_parent = "Pelvis"
for index in range(6):
    name = f"Tail_{index + 1:02d}"
    add_bone(eb, name, tail_points[index], tail_points[index + 1], tail_parent)
    tail_parent = name

for suffix, side in (("L", 1.0), ("R", -1.0)):
    fy = 0.18 * side
    ry = 0.20 * side

    add_bone(eb, f"Front_Scapula.{suffix}", P(0.64, 0.05 * side, 0.70), P(0.69, fy, 0.61), "Chest")
    add_bone(eb, f"Front_Upper.{suffix}", P(0.69, fy, 0.61), P(0.67, fy, 0.40), f"Front_Scapula.{suffix}")
    add_bone(eb, f"Front_Lower.{suffix}", P(0.67, fy, 0.40), P(0.69, fy, 0.15), f"Front_Upper.{suffix}")
    add_bone(eb, f"Front_Paw.{suffix}", P(0.69, fy, 0.15), P(0.70, fy, 0.045), f"Front_Lower.{suffix}")
    add_bone(eb, f"Front_Toe.{suffix}", P(0.70, fy, 0.045), P(0.76, fy, 0.03), f"Front_Paw.{suffix}")

    add_bone(eb, f"Rear_Hip.{suffix}", P(0.34, 0.04 * side, 0.64), P(0.33, ry, 0.59), "Pelvis")
    add_bone(eb, f"Rear_Upper.{suffix}", P(0.33, ry, 0.59), P(0.41, ry, 0.40), f"Rear_Hip.{suffix}")
    add_bone(eb, f"Rear_Lower.{suffix}", P(0.41, ry, 0.40), P(0.29, ry, 0.20), f"Rear_Upper.{suffix}")
    add_bone(eb, f"Rear_Paw.{suffix}", P(0.29, ry, 0.20), P(0.33, ry, 0.05), f"Rear_Lower.{suffix}")
    add_bone(eb, f"Rear_Toe.{suffix}", P(0.33, ry, 0.05), P(0.40, ry, 0.03), f"Rear_Paw.{suffix}")

bpy.ops.object.mode_set(mode="OBJECT")

# Deterministic smooth-distance weights. Semantic penalties keep belly vertices
# out of the legs and keep the left/right legs separated. Four influences are
# retained from the beginning, matching Unity/PICO mobile skinning limits.
deform_bones = [bone for bone in rig.data.bones if bone.use_deform]
for bone in deform_bones:
    pet.vertex_groups.new(name=bone.name)

segments = {
    bone.name: (rig.matrix_world @ bone.head_local, rig.matrix_world @ bone.tail_local)
    for bone in deform_bones
}
sigma = max(dims) * 0.075
body_cut = lo.z + height * 0.43


def family(name):
    if name.startswith("Front_"):
        return "front"
    if name.startswith("Rear_"):
        return "rear"
    if name.startswith("Tail_"):
        return "tail"
    if name.startswith("Ear") or name in {"Head", "Jaw", "Neck_01", "Neck_02"}:
        return "head"
    return "body"


for vertex in pet.data.vertices:
    point = pet.matrix_world @ vertex.co
    nx = (point.x - lo.x) / max(length, 1e-6)
    nz = (point.z - lo.z) / max(height, 1e-6)
    side = "L" if point.y >= mid_y else "R"
    candidates = []
    for bone in deform_bones:
        name = bone.name
        start, end = segments[name]
        group = family(name)

        # Hard semantic partitions prevent belly/back vertices from receiving
        # weights from paws and stop opposite-side legs sharing vertices. The
        # narrow transition bands still blend into the chest and pelvis.
        same_side = not name.endswith((".L", ".R")) or name.endswith("." + side)
        allowed = False
        if nx < 0.22:
            allowed = group == "tail" or name in {"Pelvis", "Spine_01"}
        elif nx > 0.74:
            allowed = group == "head" or name in {"Chest", "Neck_01", "Neck_02"}
        elif nz >= 0.50:
            allowed = group == "body"
            allowed = allowed or (group == "head" and nx > 0.62)
            allowed = allowed or (group == "tail" and nx < 0.36)
        elif nx >= 0.54:
            allowed = group == "front" and same_side
            allowed = allowed or (nz > 0.42 and name in {"Chest", "Spine_02"})
        elif nx <= 0.50:
            allowed = group == "rear" and same_side
            allowed = allowed or (nx < 0.28 and group == "tail")
            allowed = allowed or (nz > 0.42 and name in {"Pelvis", "Spine_01"})
        else:
            allowed = (group in {"front", "rear"} and same_side) or group == "body"
        if not allowed:
            continue

        score = point_segment_distance(point, start, end)

        if name.endswith(".L") and side == "R":
            score += width * 0.55
        elif name.endswith(".R") and side == "L":
            score += width * 0.55

        if nz < 0.43:
            if nx > 0.54 and group == "rear":
                score += length * 0.28
            if nx < 0.50 and group == "front":
                score += length * 0.28
            if group == "body":
                score += height * 0.20
        else:
            if group in {"front", "rear"}:
                score += height * 0.16

        if nx > 0.72 and group in {"tail", "rear"}:
            score += length * 0.35
        if nx < 0.24 and group in {"head", "front"}:
            score += length * 0.35
        if nx > 0.58 and group == "tail":
            score += length * 0.45
        if nx < 0.23 and group not in {"tail", "body"}:
            score += length * 0.30

        weight = math.exp(-((score / max(sigma, 1e-6)) ** 2))
        candidates.append((weight, name))

    strongest = sorted(candidates, reverse=True)[:4]
    total = sum(value for value, _ in strongest)
    if total <= 1e-12:
        strongest = [(1.0, "Spine_01")]
        total = 1.0
    for value, name in strongest:
        if value / total > 1e-5:
            pet.vertex_groups[name].add([vertex.index], value / total, "REPLACE")

# Semantic distance weights are the deterministic primary path. The old voxel
# proxy remains available only as an explicit A/B fallback because voxel remesh
# can bridge the narrow gap between left/right legs and transfer cross-weights.
weight_method = "semantic_distance_gaussian_top4"
proxy_status = {
    "requested": WEIGHT_MODE == "voxel",
    "attempted": False,
    "vertices": 0,
    "polygons": 0,
    "coverage_percent": 0.0,
    "transfer_applied": False,
}
if WEIGHT_MODE == "voxel":
    proxy_status["attempted"] = True
    proxy = pet.copy()
    proxy.data = pet.data.copy()
    proxy.name = "Pet_Closed_Weight_Proxy"
    proxy.data.name = "Pet_Closed_Weight_Proxy_Mesh"
    scene.collection.objects.link(proxy)
    proxy.parent = None
    proxy.matrix_world = pet.matrix_world.copy()
    proxy.vertex_groups.clear()
    for modifier in list(proxy.modifiers):
        proxy.modifiers.remove(modifier)

    bpy.ops.object.select_all(action="DESELECT")
    proxy.select_set(True)
    bpy.context.view_layer.objects.active = proxy
    proxy.data.remesh_voxel_size = max(dims) * 0.010
    proxy.data.remesh_voxel_adaptivity = 0.0
    bpy.ops.object.voxel_remesh()
    proxy_status["vertices"] = len(proxy.data.vertices)
    proxy_status["polygons"] = len(proxy.data.polygons)

    bpy.ops.object.select_all(action="DESELECT")
    proxy.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    try:
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    except Exception as exc:
        proxy_status["bind_exception"] = f"{type(exc).__name__}: {exc}"

    proxy_weighted = sum(
        1 for vertex in proxy.data.vertices
        if any(item.weight > 1e-6 for item in vertex.groups)
    )
    proxy_coverage = proxy_weighted * 100.0 / max(1, len(proxy.data.vertices))
    proxy_status["coverage_percent"] = proxy_coverage

    if proxy_coverage >= 95.0:
        pet.vertex_groups.clear()
        for group in proxy.vertex_groups:
            if group.name in segments:
                pet.vertex_groups.new(name=group.name)
        transfer = pet.modifiers.new("ClosedProxyWeightTransfer", "DATA_TRANSFER")
        transfer.object = proxy
        transfer.use_vert_data = True
        transfer.data_types_verts = {"VGROUP_WEIGHTS"}
        transfer.vert_mapping = "POLYINTERP_NEAREST"
        transfer.layers_vgroup_select_src = "ALL"
        transfer.layers_vgroup_select_dst = "NAME"
        bpy.ops.object.select_all(action="DESELECT")
        pet.select_set(True)
        bpy.context.view_layer.objects.active = pet
        bpy.ops.object.modifier_apply(modifier=transfer.name)
        proxy_status["transfer_applied"] = True
        weight_method = "voxel_proxy_bone_heat_transfer_top4"

        pruned_vertex_weights = []
        for vertex in pet.data.vertices:
            current = [
                (pet.vertex_groups[item.group].name, item.weight)
                for item in vertex.groups
                if item.weight > 1e-8 and pet.vertex_groups[item.group].name in segments
            ]
            if not current:
                point = pet.matrix_world @ vertex.co
                nearest = min(segments, key=lambda name: point_segment_distance(point, *segments[name]))
                current = [(nearest, 1.0)]
            strongest = sorted(current, key=lambda item: item[1], reverse=True)[:4]
            total = sum(value for _, value in strongest)
            pruned_vertex_weights.append([(name, value / total) for name, value in strongest])

        pet.vertex_groups.clear()
        for bone in deform_bones:
            pet.vertex_groups.new(name=bone.name)
        for vertex_index, weights in enumerate(pruned_vertex_weights):
            for name, value in weights:
                pet.vertex_groups[name].add([vertex_index], value, "REPLACE")

    bpy.data.objects.remove(proxy, do_unlink=True)

armature_modifier = pet.modifiers.new("Pet_Unity_Armature", "ARMATURE")
armature_modifier.object = rig
pet.parent = rig

# Weight audit.
weighted_vertices = 0
max_influences = 0
influence_histogram = {}
for vertex in pet.data.vertices:
    positive = [item for item in vertex.groups if item.weight > 1e-6]
    count = len(positive)
    influence_histogram[str(count)] = influence_histogram.get(str(count), 0) + 1
    if count:
        weighted_vertices += 1
    max_influences = max(max_influences, count)

# Direct deform-bone animation: no Rigify widgets or control bones are exported.
action = bpy.data.actions.new("Pet_Walk_24f")
rig.animation_data_create()
rig.animation_data.action = action
frames = [1, 7, 13, 19, 25]
phases = [-1.0, 0.0, 1.0, 0.0, -1.0]


def key_world_axis_rotation(name, frame, degrees, world_axis=(0.0, 1.0, 0.0)):
    pose_bone = rig.pose.bones[name]
    pose_bone.rotation_mode = "QUATERNION"
    rest_rotation = pose_bone.bone.matrix_local.to_quaternion()
    local_axis = rest_rotation.inverted() @ Vector(world_axis)
    pose_bone.rotation_quaternion = Quaternion(local_axis.normalized(), math.radians(degrees))
    pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)


for frame, phase in zip(frames, phases):
    for suffix, sign in (("L", 1.0), ("R", -1.0)):
        front_phase = phase * sign
        rear_phase = -phase * sign
        key_world_axis_rotation(f"Front_Upper.{suffix}", frame, front_phase * 11.0)
        key_world_axis_rotation(f"Front_Lower.{suffix}", frame, max(0.0, front_phase) * 14.0 - 3.0)
        key_world_axis_rotation(f"Front_Paw.{suffix}", frame, -front_phase * 5.0)
        key_world_axis_rotation(f"Rear_Upper.{suffix}", frame, rear_phase * 10.0)
        key_world_axis_rotation(f"Rear_Lower.{suffix}", frame, max(0.0, rear_phase) * 16.0 - 4.0)
        key_world_axis_rotation(f"Rear_Paw.{suffix}", frame, -rear_phase * 5.0)

    root = rig.pose.bones["Root"]
    # Root bone points along world Z, so pose-local Y is the vertical channel.
    root.location = Vector((0.0, 0.007 if phase == 0.0 else 0.0, 0.0))
    root.keyframe_insert(data_path="location", frame=frame)
    key_world_axis_rotation("Head", frame, phase * 1.8)
    key_world_axis_rotation("Tail_01", frame, phase * 5.0, world_axis=(0.0, 0.0, 1.0))
    key_world_axis_rotation("Tail_02", frame, phase * 7.0, world_axis=(0.0, 0.0, 1.0))

# Blender 5.2 stores newly created animation curves in layered action slots;
# default interpolation is already Bezier, so no legacy action.fcurves pass is
# needed here (and that attribute is no longer exposed on layered actions).

scene.frame_start = 1
scene.frame_end = 25

# Studio lighting and camera.
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 720
scene.render.resolution_y = 540
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.world.color = (0.018, 0.018, 0.018)
try:
    scene.view_settings.look = "AgX - Medium High Contrast"
except Exception:
    pass

bpy.ops.mesh.primitive_plane_add(size=max(dims.x, dims.y) * 5.0, location=(lo.x + length * 0.5, mid_y, floor_z - 0.006))
ground = bpy.context.object
ground.name = "Preview_Ground"
ground_mat = bpy.data.materials.new("Preview_Ground_Material")
ground_mat.diffuse_color = (0.10, 0.10, 0.10, 1.0)
ground.data.materials.append(ground_mat)

center = (lo + hi) * 0.5
scale = max(dims)
add_area(scene, "Preview_Key", center + Vector((scale * 1.2, -scale * 1.8, scale * 2.0)), center, 420, scale * 1.7)
add_area(scene, "Preview_Fill", center + Vector((-scale * 1.3, -scale * 1.1, scale * 1.2)), center, 180, scale * 1.5)
add_area(scene, "Preview_Rim", center + Vector((0, scale * 1.8, scale * 1.5)), center, 260, scale * 1.3)

camera_data = bpy.data.cameras.new("Preview_Camera")
camera = bpy.data.objects.new("Preview_Camera", camera_data)
scene.collection.objects.link(camera)
scene.camera = camera
camera_data.lens = 65
camera.location = center + Vector((0, -scale * 2.3, height * 0.12))
camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()

# Render a clean skeleton overlay using temporary cylinders. These markers are
# excluded from the Unity FBX and hidden after the diagnostic frame.
debug_collection = bpy.data.collections.new("Debug_Skeleton_Only")
scene.collection.children.link(debug_collection)
debug_material = bpy.data.materials.new("Debug_Bone_Material")
debug_material.diffuse_color = (0.04, 0.55, 1.0, 1.0)
debug_material.metallic = 0.0
debug_material.roughness = 0.35
for bone in deform_bones:
    add_bone_marker(debug_collection, *segments[bone.name], scale * 0.007, debug_material, bone.name)

scene.frame_set(1)
scene.render.filepath = str(PREVIEWS / "skeleton_overlay.png")
bpy.ops.render.render(write_still=True)
debug_collection.hide_render = True
debug_collection.hide_viewport = True

pose_bounds = []
scene.frame_set(7)
scene.render.filepath = str(PREVIEWS / "rest.png")
bpy.ops.render.render(write_still=True)
for frame in (1, 7, 13, 19):
    scene.frame_set(frame)
    pose_lo, pose_hi = evaluated_bbox(pet)
    pose_dims = pose_hi - pose_lo
    pose_bounds.append({
        "frame": frame,
        "dimensions_m": list(pose_dims),
        "max_dimension_ratio_vs_rest": max(
            pose_dims.x / dims.x, pose_dims.y / dims.y, pose_dims.z / dims.z
        ),
    })
    scene.render.filepath = str(PREVIEWS / f"walk_{frame:02d}.png")
    bpy.ops.render.render(write_still=True)

# Beginner-friendly frame sequence. Frame 25 repeats frame 1, so the sequence
# ends at frame 24 for a seamless 1-second loop at 24 fps. A native macOS
# ImageIO helper assembles these PNG files into a GIF after Blender exits.
scene.frame_start = 1
scene.frame_end = 24
scene.render.filepath = str(ANIM_FRAMES / "walk_")
scene.render.image_settings.file_format = "PNG"
bpy.ops.render.render(animation=True)

# Save the editable master first.
scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(BLEND))

# Unity export: only the mesh and deform armature, no lights, ground, cameras,
# debug markers, Rigify widgets, or leaf bones.
bpy.ops.object.select_all(action="DESELECT")
pet.hide_viewport = False
rig.hide_viewport = False
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
    "method": f"Tripo neutral mesh -> custom 36-deform-bone canine skeleton -> {weight_method} -> direct 24-frame walk -> Unity FBX",
    "mesh": {
        "vertices": len(pet.data.vertices),
        "polygons": len(pet.data.polygons),
        "dimensions_m": list(dims),
        "head_direction": "+X",
    },
    "skeleton": {
        "total_bones": len(rig.data.bones),
        "deform_bones": len(deform_bones),
        "control_widgets": 0,
        "rigify_used": False,
    },
    "weights": {
        "method": weight_method,
        "weighted_vertices": weighted_vertices,
        "unweighted_vertices": len(pet.data.vertices) - weighted_vertices,
        "coverage_percent": weighted_vertices * 100.0 / max(1, len(pet.data.vertices)),
        "max_influences_per_vertex": max_influences,
        "influence_histogram": influence_histogram,
        "voxel_proxy": proxy_status,
    },
    "animation": {
        "action": action.name,
        "frames": frames,
        "fps": scene.render.fps,
        "pose_bounds": pose_bounds,
    },
    "unity_export": {
        "fbx": str(FBX),
        "deform_only": True,
        "leaf_bones": False,
        "embedded_textures": True,
    },
    "outputs": {
        "blend": str(BLEND),
        "report": str(REPORT),
        "previews": str(PREVIEWS),
        "walk_frames": str(ANIM_FRAMES),
        "walk_gif": str(PREVIEWS / "pet_walk_preview.gif"),
    },
    "elapsed_seconds": round(time.time() - started, 3),
}
REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
