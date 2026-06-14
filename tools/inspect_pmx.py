# 检查 PMX 的嘴/牙几何与开口 morph：import → 列材质/morph/骨骼，找真正开口的 morph。
# 用法：Blender --background --python tools/inspect_pmx.py -- <PMX>
import bpy, addon_utils, sys
import numpy as np

PMX = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else \
    "/Users/bytedance/Downloads/Reika 18/Reika18_AC.pmx"
print("INSPECT:", PMX)

addon_utils.enable("mmd_tools", default_set=True)
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.mmd_tools.import_model(filepath=PMX, scale=0.08)

mesh = max((o for o in bpy.data.objects if o.type == "MESH"),
           key=lambda o: len(o.data.vertices))
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
print("MESH:", mesh.name, len(mesh.data.vertices), "verts")

# 材质：找牙/口/舌相关
print("\n=== MATERIALS ===")
for slot in mesh.material_slots:
    n = slot.material.name if slot.material else "(none)"
    flag = ""
    for kw in ("teeth", "tooth", "mouth", "tongue", "歯", "口", "舌", "牙", "gum", "oral", "inner"):
        if kw.lower() in n.lower():
            flag = "  <== MOUTH/TEETH?"
            break
    print(f"  {n}{flag}")

# 骨骼：找下颌/口
print("\n=== JAW/MOUTH BONES ===")
for b in arm.data.bones:
    for kw in ("顎", "あご", "jaw", "口", "mouth", "歯"):
        if kw.lower() in b.name.lower():
            print(f"  {b.name}")
            break

# morph slider 绑定后枚举形态 key，按最大位移排序，找开口的
root = mesh.parent
while root.parent is not None:
    root = root.parent
bpy.context.view_layer.objects.active = mesh
bpy.ops.mmd_tools.morph_slider_setup(type="BIND")
ph = None
for o in bpy.data.objects:
    if o.type == "MESH" and o.data.shape_keys and "あ" in o.data.shape_keys.key_blocks:
        ph = o
        break
keys = ph.data.shape_keys.key_blocks if ph else None
print("\nPLACEHOLDER:", ph.name if ph else None)

n = len(mesh.data.vertices)
dg = bpy.context.evaluated_depsgraph_get()

def capture():
    bpy.context.view_layer.update(); dg.update()
    ev = mesh.evaluated_get(dg); me = ev.to_mesh()
    a = np.empty(n * 3, dtype=np.float32); me.vertices.foreach_get("co", a)
    ev.to_mesh_clear(); return a.reshape(-1, 3).copy()

for k in keys:
    k.value = 0.0
basis = capture()
# 嘴部区域：下半脸前部（粗略，Blender 坐标 z-up，面朝 -Y）
zc = basis[:, 2]; yc = basis[:, 1]
mouth_region = (zc < np.percentile(zc, 35)) & (yc < np.percentile(yc, 20))

print("\n=== MORPHS (按嘴部最大下移排序，top 15) ===")
results = []
for k in keys:
    if k.name == "あ" or True:
        pass
    k.value = 1.0
    pos = capture()
    k.value = 0.0
    d = pos - basis
    mag = np.linalg.norm(d, axis=1)
    # 嘴区向下(z 减小)位移
    mouth_dz = d[mouth_region, 2]
    results.append((k.name, float(mag.max()), float(mouth_dz.min()) if mouth_region.sum() else 0.0,
                    int((mag > 1e-4).sum())))
results.sort(key=lambda r: r[2])  # 最负的下移在前
for name, mx, dz, cnt in results[:15]:
    print(f"  {name:16} maxΔ={mx*1000:6.1f}mm  嘴区下移={dz*1000:7.2f}mm  动点={cnt}")
print("\nDONE")
