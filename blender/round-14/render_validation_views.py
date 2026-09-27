import bpy
from pathlib import Path
from mathutils import Vector


ROOT = Path("/Users/phoebedufei/Documents/ChatGPT/3D")
BLEND = ROOT / "blender/round-14/pet_unity_canine_motion_bridge_fixed.blend"
OUT = ROOT / "blender/round-14/previews/validation"
OUT.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.open_mainfile(filepath=str(BLEND))
scene = bpy.context.scene
pet = bpy.data.objects["Pet_Unity_Mesh"]
camera = bpy.data.objects["Preview_Camera"]
camera.hide_viewport = False
camera.animation_data_clear()

points = [pet.matrix_world @ vertex.co for vertex in pet.data.vertices]
lo = Vector(tuple(min(point[i] for point in points) for i in range(3)))
hi = Vector(tuple(max(point[i] for point in points) for i in range(3)))
center = (lo + hi) * 0.5
scale = max(hi - lo)
target = center + Vector((0.0, 0.0, -0.02))

views = {
    "front_three_quarter": center + Vector((scale * 1.45, -scale * 1.65, scale * 0.35)),
    "front": center + Vector((scale * 2.25, 0.0, scale * 0.22)),
    "rear_three_quarter": center + Vector((-scale * 1.45, -scale * 1.65, scale * 0.35)),
}

scene.render.resolution_x = 720
scene.render.resolution_y = 540
scene.render.resolution_percentage = 100
for name, location in views.items():
    camera.location = location
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    for frame in (7, 19):
        scene.frame_set(frame)
        scene.render.filepath = str(OUT / f"{name}_{frame:02d}.png")
        bpy.ops.render.render(write_still=True)

print(f"validation_views={OUT}")
