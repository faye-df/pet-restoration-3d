import bpy
import json
import math
import os
import time
from pathlib import Path
from mathutils import Quaternion, Vector


ROOT = Path("/Users/phoebedufei/Documents/ChatGPT/3D")
SOURCE_BLEND = Path(os.environ.get(
    "PET_SOURCE_BLEND",
    str(ROOT / "blender/round-08/pet_unity_canine_ik_walk.blend"),
))
OUT = Path(os.environ.get("PET_OUT", str(ROOT / "blender/round-09")))
REPAIR_CROSS_WEIGHTS = os.environ.get("PET_REPAIR_CROSS_WEIGHTS", "1") == "1"
REPAIR_ALL_LIMBS = os.environ.get("PET_REPAIR_ALL_LIMBS", "0") == "1"
ADD_POLE_TARGETS = os.environ.get("PET_ADD_POLE_TARGETS", "0") == "1"
PREVIEWS = OUT / "previews"
FRAMES = PREVIEWS / "frames"
BLEND = OUT / "pet_unity_canine_walk_fixed.blend"
FBX = OUT / "pet_unity_canine_walk_fixed.fbx"
REPORT = OUT / "rear_leg_fix_report.json"
GIF = PREVIEWS / "pet_walk_fixed.gif"
PREVIEWS.mkdir(parents=True, exist_ok=True)
FRAMES.mkdir(parents=True, exist_ok=True)


def bbox_world(obj):
    # Use undeformed source vertices. object.bound_box can reflect the current
    # evaluated pose, which makes semantic regions change with the frame.
    points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    lo = Vector(tuple(min(point[i] for point in points) for i in range(3)))
    hi = Vector(tuple(max(point[i] for point in points) for i in range(3)))
    return lo, hi


def evaluated_bbox(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
        lo = Vector(tuple(min(point[i] for point in points) for i in range(3)))
        hi = Vector(tuple(max(point[i] for point in points) for i in range(3)))
        return lo, hi
    finally:
        evaluated.to_mesh_clear()


def family_weight_audit(pet, lo, hi, family_name, x_min, x_max):
    dims = hi - lo
    mid_y = (lo.y + hi.y) * 0.5
    names = {group.index: group.name for group in pet.vertex_groups}
    audited_vertices = 0
    cross_vertices = 0
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
            if names[item.group].startswith(family_name + "_")
            and names[item.group].endswith("." + other)
        )
        audited_vertices += 1
        cross_sum += cross
        if cross > 0.05:
            cross_vertices += 1
    return {
        "audited_vertices": audited_vertices,
        "opposite_side_over_0_05": cross_vertices,
        "cross_percent": cross_vertices * 100.0 / max(1, audited_vertices),
        "mean_opposite_side_weight": cross_sum / max(1, audited_vertices),
    }


def full_weight_audit(pet, lo, hi):
    return {
        "front": family_weight_audit(pet, lo, hi, "Front", 0.54, 0.80),
        "rear": family_weight_audit(pet, lo, hi, "Rear", 0.20, 0.53),
    }


def repair_limb_weights(pet, rig, lo, hi, all_limbs):
    dims = hi - lo
    mid_y = (lo.y + hi.y) * 0.5
    names = {group.index: group.name for group in pet.vertex_groups}
    saved = []
    transferred_vertices = 0
    transferred_weight = 0.0
    for vertex in pet.data.vertices:
        point = pet.matrix_world @ vertex.co
        nx = (point.x - lo.x) / max(dims.x, 1e-9)
        nz = (point.z - lo.z) / max(dims.z, 1e-9)
        side = "L" if point.y >= mid_y else "R"
        other = "R" if side == "L" else "L"
        weights = {}
        moved = 0.0
        for item in vertex.groups:
            name = names[item.group]
            value = item.weight
            in_rear = 0.20 <= nx <= 0.53 and nz <= 0.62 and name.startswith("Rear_")
            in_front = 0.54 <= nx <= 0.80 and nz <= 0.62 and name.startswith("Front_")
            should_transfer = (in_rear or (all_limbs and in_front)) and name.endswith("." + other)
            if should_transfer:
                mirror = name[:-1] + side
                weights[mirror] = weights.get(mirror, 0.0) + value
                moved += value
            else:
                weights[name] = weights.get(name, 0.0) + value
        strongest = sorted(
            ((name, value) for name, value in weights.items() if value > 1e-8),
            key=lambda item: item[1],
            reverse=True,
        )[:4]
        total = sum(value for _, value in strongest)
        if total <= 1e-8:
            strongest = [("Pelvis", 1.0)]
            total = 1.0
        saved.append([(name, value / total) for name, value in strongest])
        if moved > 1e-8:
            transferred_vertices += 1
            transferred_weight += moved

    pet.vertex_groups.clear()
    for bone in rig.data.bones:
        if bone.use_deform:
            pet.vertex_groups.new(name=bone.name)
    for vertex_index, weights in enumerate(saved):
        for name, value in weights:
            group = pet.vertex_groups.get(name)
            if group:
                group.add([vertex_index], value, "REPLACE")
    return {
        "vertices_repaired": transferred_vertices,
        "total_weight_mirrored_to_correct_side": transferred_weight,
        "policy": (
            "front+rear opposite-side limb weights mirrored to the same anatomical bone; global top-4 renormalization"
            if all_limbs else
            "rear opposite-side weights mirrored to the same anatomical bone; global top-4 renormalization"
        ),
    }


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
scene.name = "Round09_RearLeg_And_Axis_Fix"
rig = bpy.data.objects["Pet_Unity_Canine_Rig"]
pet = bpy.data.objects["Pet_Unity_Mesh"]
lo, hi = bbox_world(pet)

weights_before = full_weight_audit(pet, lo, hi)
if REPAIR_CROSS_WEIGHTS:
    weight_repair = repair_limb_weights(pet, rig, lo, hi, REPAIR_ALL_LIMBS)
else:
    weight_repair = {
        "vertices_repaired": 0,
        "total_weight_mirrored_to_correct_side": 0.0,
        "policy": "disabled; source weights kept unchanged for A/B evaluation",
    }
weights_after = full_weight_audit(pet, lo, hi)

# Round08 sources already contain these controls; a fresh semantic-only base
# contains only the deform skeleton. Create the four non-deforming targets and
# IK constraints on demand so the same animation path can evaluate both.
target_pairs = (
    ("Front_Paw.L", "IK_Front.L"),
    ("Front_Paw.R", "IK_Front.R"),
    ("Rear_Paw.L", "IK_Rear.L"),
    ("Rear_Paw.R", "IK_Rear.R"),
)
missing_targets = [target_name for _, target_name in target_pairs if target_name not in rig.data.bones]
pole_specs = (
    ("Front.L", "Front_Upper.L", -1.0),
    ("Front.R", "Front_Upper.R", -1.0),
    ("Rear.L", "Rear_Upper.L", 1.0),
    ("Rear.R", "Rear_Upper.R", 1.0),
)
missing_poles = [
    "Pole_" + limb_name
    for limb_name, _, _ in pole_specs
    if ADD_POLE_TARGETS and "Pole_" + limb_name not in rig.data.bones
]
if missing_targets or missing_poles:
    bpy.ops.object.select_all(action="DESELECT")
    rig.hide_viewport = False
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = rig.data.edit_bones
    for paw_name, target_name in target_pairs:
        if target_name in edit_bones:
            continue
        paw = edit_bones[paw_name]
        target = edit_bones.new(target_name)
        target.head = paw.tail.copy()
        target.tail = paw.tail + Vector((0.0, 0.0, 0.045))
        target.use_deform = False
        target.parent = None
    if ADD_POLE_TARGETS:
        pole_offset = (hi.x - lo.x) * 0.30
        for limb_name, upper_name, direction in pole_specs:
            pole_name = "Pole_" + limb_name
            if pole_name in edit_bones:
                continue
            upper = edit_bones[upper_name]
            pole = edit_bones.new(pole_name)
            pole.head = upper.tail + Vector((direction * pole_offset, 0.0, 0.0))
            pole.tail = pole.head + Vector((0.0, 0.0, 0.045))
            pole.use_deform = False
            pole.parent = edit_bones["Root"]
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.object.mode_set(mode="OBJECT")

# Create or update the IK constraints even when the source already had foot
# targets. Front chains include the scapula for enough reach; rear chains stop
# at the upper leg. Pole targets make the bend plane deterministic.
for paw_name, target_name in target_pairs:
    paw = rig.pose.bones[paw_name]
    constraint = next(
        (item for item in paw.constraints if item.type == "IK" and item.subtarget == target_name),
        None,
    )
    if constraint is None:
        constraint = paw.constraints.new("IK")
        constraint.name = "Grounded_Foot_IK"
        constraint.target = rig
        constraint.subtarget = target_name
    constraint.chain_count = 4 if paw_name.startswith("Front_") else 3
    constraint.use_stretch = False
    if ADD_POLE_TARGETS:
        limb_name = target_name.removeprefix("IK_")
        constraint.pole_target = rig
        constraint.pole_subtarget = "Pole_" + limb_name

# Replace the Round08 action. The IK target and Root bones point along world Z,
# so their pose-local Y channel is vertical. Round08 incorrectly keyed local Z,
# which moved the feet/body sideways instead of upward.
rig.animation_data_clear()
for pose_bone in rig.pose.bones:
    pose_bone.matrix_basis.identity()

action = bpy.data.actions.new("Pet_IK_Walk_RootMotion_FixedAxes_24f")
rig.animation_data_create()
rig.animation_data.action = action

stride = 0.16
lift = 0.045
key_frames = [1, 7, 13, 19, 25]
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
        key_location(target, frame, (x_offset, z_offset, 0.0))

for target_name in group_b:
    target = rig.pose.bones[target_name]
    for frame, x_offset, z_offset in (
        (1, stride * 0.5, 0.0),
        (7, stride * 0.5, 0.0),
        (13, stride * 0.5, 0.0),
        (19, stride, lift),
        (25, stride * 1.5, 0.0),
    ):
        key_location(target, frame, (x_offset, z_offset, 0.0))

root = rig.pose.bones["Root"]
for frame, x_offset, z_offset in (
    (1, 0.0, 0.0),
    (7, stride * 0.25, 0.008),
    (13, stride * 0.50, 0.0),
    (19, stride * 0.75, 0.008),
    (25, stride, 0.0),
):
    key_location(root, frame, (x_offset, z_offset, 0.0))

for frame, phase in zip(key_frames, (-1.0, 0.0, 1.0, 0.0, -1.0)):
    key_world_axis_rotation(rig.pose.bones["Head"], frame, phase * 1.5, (0.0, 1.0, 0.0))
    key_world_axis_rotation(rig.pose.bones["Tail_01"], frame, phase * 5.0, (0.0, 0.0, 1.0))
    key_world_axis_rotation(rig.pose.bones["Tail_02"], frame, phase * 7.0, (0.0, 0.0, 1.0))

# Bone roll differs across imported rigs, so choose the pole angle from four
# deterministic candidates. The winning angle keeps front elbows behind the
# shoulder and rear knees in front of the hip while minimizing lateral drift.
pole_angle_results = []
if ADD_POLE_TARGETS:
    scene.frame_set(13)
    bpy.context.view_layer.update()
    pole_eval = (
        ("Front_Paw.L", "Front_Upper.L", -1.0),
        ("Front_Paw.R", "Front_Upper.R", -1.0),
        ("Rear_Paw.L", "Rear_Upper.L", 1.0),
        ("Rear_Paw.R", "Rear_Upper.R", 1.0),
    )
    for paw_name, upper_name, desired_sign in pole_eval:
        constraint = next(item for item in rig.pose.bones[paw_name].constraints if item.type == "IK")
        candidates = []
        for step in range(8):
            angle = -math.pi + step * (math.pi * 0.25)
            constraint.pole_angle = angle
            bpy.context.view_layer.update()
            upper = rig.pose.bones[upper_name]
            base = rig.matrix_world @ upper.head
            joint = rig.matrix_world @ upper.tail
            desired_bend = desired_sign * (joint.x - base.x)
            lateral_drift = abs(joint.y - base.y)
            candidates.append((angle, desired_bend, lateral_drift))
        # First require the anatomically correct forward/backward bend, then
        # minimize side drift. Desired bend magnitude is only a tie-breaker.
        valid = [item for item in candidates if item[1] > 0.001]
        pool = valid if valid else candidates
        best = min(pool, key=lambda item: (item[2], -item[1]))
        constraint.pole_angle = best[0]
        pole_angle_results.append({
            "paw": paw_name,
            "pole_angle_degrees": math.degrees(best[0]),
            "desired_bend_m_at_frame13": best[1],
            "lateral_drift_m_at_frame13": best[2],
        })
    bpy.context.view_layer.update()

scene.frame_start = 1
scene.frame_end = 24
scene.render.fps = 24
scene.render.image_settings.file_format = "PNG"

# Quantitative validation: real vertical foot clearance, minimal side drift,
# stable knee direction, complete weights, and bounded deformation.
rest_lo, rest_hi = evaluated_bbox(pet)
rest_dims = rest_hi - rest_lo
pose_checks = []
foot_checks = []
joint_checks = []
front_joint_checks = []
for frame in (1, 7, 13, 19, 24):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    pose_lo, pose_hi = evaluated_bbox(pet)
    pose_dims = pose_hi - pose_lo
    pose_checks.append({
        "frame": frame,
        "dimensions_m": list(pose_dims),
        "max_dimension_ratio_vs_frame1": max(
            pose_dims.x / max(rest_dims.x, 1e-9),
            pose_dims.y / max(rest_dims.y, 1e-9),
            pose_dims.z / max(rest_dims.z, 1e-9),
        ),
    })
    for paw_name, target_name in (
        ("Front_Paw.L", "IK_Front.L"),
        ("Front_Paw.R", "IK_Front.R"),
        ("Rear_Paw.L", "IK_Rear.L"),
        ("Rear_Paw.R", "IK_Rear.R"),
    ):
        paw_tail = rig.matrix_world @ rig.pose.bones[paw_name].tail
        target_head = rig.matrix_world @ rig.pose.bones[target_name].head
        foot_checks.append({
            "frame": frame,
            "paw": paw_name,
            "error_m": (paw_tail - target_head).length,
            "x_m": paw_tail.x,
            "y_m": paw_tail.y,
            "height_m": paw_tail.z,
        })
    for side in ("L", "R"):
        front_upper = rig.pose.bones[f"Front_Upper.{side}"]
        front_lower = rig.pose.bones[f"Front_Lower.{side}"]
        shoulder = rig.matrix_world @ front_upper.head
        elbow = rig.matrix_world @ front_upper.tail
        wrist = rig.matrix_world @ front_lower.tail
        elbow_angle = math.degrees((shoulder - elbow).angle(wrist - elbow))
        front_joint_checks.append({
            "frame": frame,
            "side": side,
            "elbow_bend_degrees": elbow_angle,
            "elbow_behind_shoulder_m": shoulder.x - elbow.x,
            "wrist_ahead_of_elbow_m": wrist.x - elbow.x,
            "lateral_elbow_drift_m": elbow.y - shoulder.y,
        })
        upper = rig.pose.bones[f"Rear_Upper.{side}"]
        lower = rig.pose.bones[f"Rear_Lower.{side}"]
        hip = rig.matrix_world @ upper.head
        knee = rig.matrix_world @ upper.tail
        hock = rig.matrix_world @ lower.tail
        knee_angle = math.degrees((hip - knee).angle(hock - knee))
        joint_checks.append({
            "frame": frame,
            "side": side,
            "knee_bend_degrees": knee_angle,
            "knee_forward_of_hip_m": knee.x - hip.x,
            "hock_behind_knee_m": knee.x - hock.x,
        })

for frame in (1, 7, 13, 19):
    scene.frame_set(frame)
    scene.render.filepath = str(PREVIEWS / f"walk_fixed_{frame:02d}.png")
    bpy.ops.render.render(write_still=True)

scene.render.filepath = str(FRAMES / "walk_")
bpy.ops.render.render(animation=True)

weighted = 0
max_influences = 0
for vertex in pet.data.vertices:
    positive = [item for item in vertex.groups if item.weight > 1e-6]
    if positive:
        weighted += 1
    max_influences = max(max_influences, len(positive))

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

ground_heights = [item["height_m"] for item in foot_checks if item["frame"] in (1, 13, 24)]
swing_rear = [
    item for item in foot_checks
    if (item["frame"], item["paw"]) in ((7, "Rear_Paw.R"), (19, "Rear_Paw.L"))
]
report = {
    "source_round": 8,
    "diagnosis": {
        "animation_axis_bug": "foot lift and body bob were keyed on pose-local Z, which maps sideways for these vertical control bones",
        "weight_bug": "opposite-side rear upper/lower groups affected the inner rear legs",
        "ik_chain_orientation": (
            "deterministic front/rear pole targets enabled; front chain includes scapula"
            if ADD_POLE_TARGETS else
            "joint order remained stable; pole targets disabled"
        ),
    },
    "weight_audit_before": weights_before,
    "weight_repair": weight_repair,
    "weight_audit_after": weights_after,
    "mesh": {
        "vertices": len(pet.data.vertices),
        "polygons": len(pet.data.polygons),
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
        "intended_foot_lift_m": lift,
        "measured_rear_swing_clearance_m": [item["height_m"] - min(ground_heights) for item in swing_rear],
        "max_foot_target_error_m": max(item["error_m"] for item in foot_checks),
        "max_front_foot_target_error_m": max(
            item["error_m"] for item in foot_checks if item["paw"].startswith("Front_")
        ),
        "max_rear_foot_target_error_m": max(
            item["error_m"] for item in foot_checks if item["paw"].startswith("Rear_")
        ),
        "pose_checks": pose_checks,
        "foot_checks": foot_checks,
        "front_joint_checks": front_joint_checks,
        "rear_joint_checks": joint_checks,
        "pole_targets": pole_angle_results,
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
