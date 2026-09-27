import bpy
import json
import math
import time
from pathlib import Path
from mathutils import Quaternion, Vector


ROOT = Path("/Users/phoebedufei/Documents/ChatGPT/3D")
SOURCE_BLEND = ROOT / "blender/round-07/pet_unity_canine_rig.blend"
ROUND07_REPORT = ROOT / "blender/round-07/unity_canine_rig_report.json"
OUT = ROOT / "blender/round-08"
PREVIEWS = OUT / "previews"
FRAMES = PREVIEWS / "frames"
BLEND = OUT / "pet_unity_canine_ik_walk.blend"
FBX = OUT / "pet_unity_canine_ik_walk.fbx"
REPORT = OUT / "ik_walk_report.json"
GIF = PREVIEWS / "pet_ik_walk_preview.gif"
PREVIEWS.mkdir(parents=True, exist_ok=True)
FRAMES.mkdir(parents=True, exist_ok=True)


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


def key_location(pose_bone, frame, location):
    pose_bone.location = Vector(location)
    pose_bone.keyframe_insert(data_path="location", frame=frame)


def key_world_axis_rotation(pose_bone, frame, degrees, world_axis):
    pose_bone.rotation_mode = "QUATERNION"
    rest_rotation = pose_bone.bone.matrix_local.to_quaternion()
    local_axis = rest_rotation.inverted() @ Vector(world_axis)
    pose_bone.rotation_quaternion = Quaternion(local_axis.normalized(), math.radians(degrees))
    pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)


started = time.time()
bpy.ops.wm.open_mainfile(filepath=str(SOURCE_BLEND))
scene = bpy.context.scene
scene.name = "Round08_Unity_Canine_IK"
rig = bpy.data.objects["Pet_Unity_Canine_Rig"]
pet = bpy.data.objects["Pet_Unity_Mesh"]

# Remove the previous direct-rotation action and return every pose bone to rest.
rig.animation_data_clear()
for pose_bone in rig.pose.bones:
    pose_bone.matrix_basis.identity()
    for constraint in list(pose_bone.constraints):
        pose_bone.constraints.remove(constraint)

# Four root-level, non-deforming targets. They are animation controls only and
# are excluded from the deform-only Unity FBX after constraints are baked.
bpy.ops.object.select_all(action="DESELECT")
rig.hide_viewport = False
rig.select_set(True)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode="EDIT")
edit_bones = rig.data.edit_bones
target_map = {}
for limb, paw_name in (
    ("Front.L", "Front_Paw.L"),
    ("Front.R", "Front_Paw.R"),
    ("Rear.L", "Rear_Paw.L"),
    ("Rear.R", "Rear_Paw.R"),
):
    target_name = "IK_" + limb
    old = edit_bones.get(target_name)
    if old:
        edit_bones.remove(old)
    paw = edit_bones[paw_name]
    target = edit_bones.new(target_name)
    target.head = paw.tail.copy()
    target.tail = paw.tail + Vector((0.0, 0.0, 0.045))
    target.use_deform = False
    target.parent = None
    target_map[paw_name] = target_name
bpy.ops.object.mode_set(mode="POSE")

for paw_name, target_name in target_map.items():
    constraint = rig.pose.bones[paw_name].constraints.new("IK")
    constraint.name = "Grounded_Foot_IK"
    constraint.target = rig
    constraint.subtarget = target_name
    constraint.chain_count = 3
    constraint.use_stretch = False
bpy.ops.object.mode_set(mode="OBJECT")

action = bpy.data.actions.new("Pet_IK_Walk_RootMotion_24f")
rig.animation_data_create()
rig.animation_data.action = action

# One one-second stride. Group A (front L + rear R) swings during the first
# half; group B swings during the second half. The root advances one stride,
# so planted targets remain stationary in world space instead of foot-sliding.
key_frames = [1, 7, 13, 19, 25]
stride = 0.16
lift = 0.045
group_a = ["IK_Front.L", "IK_Rear.R"]
group_b = ["IK_Front.R", "IK_Rear.L"]

for target_name in group_a + group_b:
    target = rig.pose.bones[target_name]
    target.rotation_mode = "QUATERNION"
    target.rotation_quaternion = Quaternion((1.0, 0.0, 0.0, 0.0))
    target.keyframe_insert(data_path="rotation_quaternion", frame=1)
    target.keyframe_insert(data_path="rotation_quaternion", frame=25)

for target_name in group_a:
    target = rig.pose.bones[target_name]
    for frame, x_offset, z_offset in (
        (1, -stride * 0.5, 0.0),
        (7, 0.0, lift),
        (13, stride * 0.5, 0.0),
        (19, stride * 0.5, 0.0),
        (25, stride * 0.5, 0.0),
    ):
        key_location(target, frame, (x_offset, 0.0, z_offset))

for target_name in group_b:
    target = rig.pose.bones[target_name]
    for frame, x_offset, z_offset in (
        (1, stride * 0.5, 0.0),
        (7, stride * 0.5, 0.0),
        (13, stride * 0.5, 0.0),
        (19, stride, lift),
        (25, stride * 1.5, 0.0),
    ):
        key_location(target, frame, (x_offset, 0.0, z_offset))

root = rig.pose.bones["Root"]
for frame, x_offset, z_offset in (
    (1, 0.0, 0.0),
    (7, stride * 0.25, 0.008),
    (13, stride * 0.50, 0.0),
    (19, stride * 0.75, 0.008),
    (25, stride, 0.0),
):
    key_location(root, frame, (x_offset, 0.0, z_offset))

for frame, phase in zip(key_frames, (-1.0, 0.0, 1.0, 0.0, -1.0)):
    key_world_axis_rotation(rig.pose.bones["Head"], frame, phase * 1.5, (0.0, 1.0, 0.0))
    key_world_axis_rotation(rig.pose.bones["Tail_01"], frame, phase * 5.0, (0.0, 0.0, 1.0))
    key_world_axis_rotation(rig.pose.bones["Tail_02"], frame, phase * 7.0, (0.0, 0.0, 1.0))

scene.frame_start = 1
scene.frame_end = 24
scene.render.fps = 24
scene.render.image_settings.file_format = "PNG"

# Follow the exported root motion in previews so the dog stays centered. The
# camera is preview-only and hidden before saving/exporting.
camera = bpy.data.objects.get("Preview_Camera")
if camera:
    camera.data.lens = 58
    camera_base = camera.location.copy()
    for frame, x_offset in (
        (1, 0.0),
        (7, stride * 0.25),
        (13, stride * 0.50),
        (19, stride * 0.75),
        (25, stride),
    ):
        camera.location = camera_base + Vector((x_offset, 0.0, 0.0))
        camera.keyframe_insert(data_path="location", frame=frame)

# Objective metrics and still previews.
rest_lo, rest_hi = evaluated_bbox(pet)
rest_dims = rest_hi - rest_lo
pose_bounds = []
foot_errors = []
for frame in (1, 7, 13, 19, 24):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    pose_lo, pose_hi = evaluated_bbox(pet)
    pose_dims = pose_hi - pose_lo
    pose_bounds.append({
        "frame": frame,
        "dimensions_m": list(pose_dims),
        "max_dimension_ratio_vs_reference": max(
            pose_dims.x / rest_dims.x,
            pose_dims.y / rest_dims.y,
            pose_dims.z / rest_dims.z,
        ),
    })
    for paw_name, target_name in target_map.items():
        paw_tail = rig.matrix_world @ rig.pose.bones[paw_name].tail
        target_head = rig.matrix_world @ rig.pose.bones[target_name].head
        foot_errors.append({
            "frame": frame,
            "paw": paw_name,
            "target": target_name,
            "error_m": (paw_tail - target_head).length,
            "height_m": paw_tail.z,
        })

for frame in (1, 7, 13, 19):
    scene.frame_set(frame)
    scene.render.filepath = str(PREVIEWS / f"ik_walk_{frame:02d}.png")
    bpy.ops.render.render(write_still=True)

# Full 24-frame loop for the GIF helper.
scene.render.filepath = str(FRAMES / "walk_")
bpy.ops.render.render(animation=True)

# Weight audit remains mandatory after adding non-deforming IK controls.
weighted = 0
max_influences = 0
for vertex in pet.data.vertices:
    positive = [item for item in vertex.groups if item.weight > 1e-6]
    if positive:
        weighted += 1
    max_influences = max(max_influences, len(positive))

# Clean beginner viewport: hide preview-only camera/light/ground and debug
# cylinders, leave only the textured mesh and readable armature visible.
for obj in scene.objects:
    if obj.type in {"CAMERA", "LIGHT"} or obj.name == "Preview_Ground" or obj.name.startswith("DBG_"):
        obj.hide_viewport = True
pet.hide_viewport = False
rig.hide_viewport = False
rig.show_in_front = True
scene.frame_set(1)
bpy.ops.object.select_all(action="DESELECT")
rig.select_set(True)
bpy.context.view_layer.objects.active = rig

bpy.ops.wm.save_as_mainfile(filepath=str(BLEND))

# FBX exporter evaluates and bakes IK constraints to the deform skeleton.
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

previous = json.loads(ROUND07_REPORT.read_text(encoding="utf-8"))
report = {
    "source_round": 7,
    "method": "Round07 custom canine deform rig -> four grounded IK targets -> one-stride root-motion walk -> baked deform-only Unity FBX",
    "mesh": previous["mesh"],
    "skeleton": {
        "total_blender_bones": len(rig.data.bones),
        "deform_bones": sum(1 for bone in rig.data.bones if bone.use_deform),
        "non_deform_ik_controls": len(target_map),
        "export_mode": "deform_only_with_required_parent_root",
    },
    "weights": {
        "weighted_vertices": weighted,
        "unweighted_vertices": len(pet.data.vertices) - weighted,
        "coverage_percent": weighted * 100.0 / max(1, len(pet.data.vertices)),
        "max_influences_per_vertex": max_influences,
    },
    "animation": {
        "action": action.name,
        "fps": 24,
        "frames": [1, 25],
        "stride_m": stride,
        "foot_lift_m": lift,
        "root_motion_m": stride,
        "pose_bounds": pose_bounds,
        "foot_target_errors": foot_errors,
        "max_foot_target_error_m": max(item["error_m"] for item in foot_errors),
    },
    "outputs": {
        "blend": str(BLEND),
        "fbx": str(FBX),
        "report": str(REPORT),
        "previews": str(PREVIEWS),
        "walk_gif": str(GIF),
    },
    "elapsed_seconds": round(time.time() - started, 3),
}
REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
