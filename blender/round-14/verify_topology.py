import bpy
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path("/Users/phoebedufei/Documents/ChatGPT/3D")
CASES = {
    "round13": ROOT / "blender/round-13/pet_unity_canine_walk_fixed.blend",
    "round14": ROOT / "blender/round-14/pet_unity_canine_motion_bridge_fixed.blend",
}
OUT = ROOT / "blender/round-14/topology_integrity_report.json"


def topology_counts(mesh):
    face_counts = defaultdict(int)
    for polygon in mesh.polygons:
        vertices = list(polygon.vertices)
        for index in range(len(vertices)):
            edge = tuple(sorted((vertices[index], vertices[(index + 1) % len(vertices)])))
            face_counts[edge] += 1
    return {
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "polygons": len(mesh.polygons),
        "boundary_edges": sum(count == 1 for count in face_counts.values()),
        "edges_with_more_than_two_faces": sum(count > 2 for count in face_counts.values()),
        "loose_edges": sum(
            tuple(sorted(edge.vertices)) not in face_counts
            for edge in mesh.edges
        ),
    }


report = {}
for name, path in CASES.items():
    bpy.ops.wm.open_mainfile(filepath=str(path))
    pet = bpy.data.objects["Pet_Unity_Mesh"]
    rig = bpy.data.objects["Pet_Unity_Canine_Rig"]
    weighted = sum(any(item.weight > 1e-6 for item in vertex.groups) for vertex in pet.data.vertices)
    report[name] = {
        "file": str(path),
        "topology": topology_counts(pet.data),
        "materials": len(pet.data.materials),
        "images": len(bpy.data.images),
        "coverage_percent": weighted * 100.0 / max(1, len(pet.data.vertices)),
        "armature_modifier": any(
            modifier.type == "ARMATURE" and modifier.object == rig
            for modifier in pet.modifiers
        ),
        "bones_total": len(rig.data.bones),
        "bones_deform": sum(bone.use_deform for bone in rig.data.bones),
        "ik_constraints": sum(
            constraint.type == "IK"
            for pose_bone in rig.pose.bones
            for constraint in pose_bone.constraints
        ),
        "action": rig.animation_data.action.name if rig.animation_data and rig.animation_data.action else None,
    }

OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
