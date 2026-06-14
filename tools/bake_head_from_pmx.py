# 在 Blender 3.6 中运行：导入 PMX，烘焙骨骼 morph 为顶点差量，
# 裁出头部，导出为 FCH (FaceCap Head) 自定义格式 + 纹理。
import bpy, addon_utils, json, struct, os, shutil, sys
import numpy as np

# 可被命令行覆盖：Blender --background --python bake_head_from_pmx.py -- <PMX> <OUT_DIR>
PMX = "/Users/bytedance/Downloads/Reika 18/Reika18_Children.pmx"
OUT_DIR = "/Users/bytedance/work/mytest/facecap_ios/Resources/heads/Children"
if "--" in sys.argv:
    _extra = sys.argv[sys.argv.index("--") + 1:]
    if len(_extra) >= 1 and _extra[0]:
        PMX = _extra[0]
    if len(_extra) >= 2 and _extra[1]:
        OUT_DIR = _extra[1]
print("PMX:", PMX)
print("OUT_DIR:", OUT_DIR)
NECK_Z = None  # 自动取 首 骨骼高度

addon_utils.enable("mmd_tools", default_set=True)
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.mmd_tools.import_model(filepath=PMX, scale=0.08)

# ---- 定位主网格 / 骨架 ----
mesh_obj = max((o for o in bpy.data.objects if o.type == "MESH"),
               key=lambda o: len(o.data.vertices))
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
print("MAIN MESH:", mesh_obj.name, len(mesh_obj.data.vertices))

def find_bone(*names):
    for n in names:
        b = arm.data.bones.get(n)
        if b:
            return b
    return None

eye_l_bone = find_bone("左目", "目.L")
eye_r_bone = find_bone("右目", "目.R")
neck_bone = find_bone("首")
assert eye_l_bone and eye_r_bone and neck_bone
eyeL_w = arm.matrix_world @ eye_l_bone.head_local
eyeR_w = arm.matrix_world @ eye_r_bone.head_local
NECK_Z = (arm.matrix_world @ neck_bone.head_local).z
print("EYE_L:", tuple(eyeL_w), "EYE_R:", tuple(eyeR_w), "NECK_Z:", NECK_Z)
CHAR_LEFT_SIGN = 1.0 if eyeL_w.x > 0 else -1.0
print("CHAR_LEFT_SIGN:", CHAR_LEFT_SIGN)

# ---- 绑定 morph 滑条（placeholder 带 shape key 驱动骨骼）----
root = mesh_obj.parent
while root.parent is not None:
    root = root.parent
bpy.context.view_layer.objects.active = mesh_obj
try:
    bpy.ops.mmd_tools.morph_slider_setup(type="BIND")
except Exception as e:
    print("BIND FAILED:", e)
    print([op for op in dir(bpy.ops.mmd_tools)])
    raise

placeholder = None
for o in bpy.data.objects:
    if o.type == "MESH" and o.data.shape_keys and "あ" in o.data.shape_keys.key_blocks:
        placeholder = o
        break
assert placeholder, "placeholder not found"
keys = placeholder.data.shape_keys.key_blocks
print("PLACEHOLDER:", placeholder.name, "keys:", [k.name for k in keys])

# ---- 烘焙工具 ----
n_verts = len(mesh_obj.data.vertices)
dg = bpy.context.evaluated_depsgraph_get()

def zero_all():
    for k in keys:
        k.value = 0.0

def capture():
    bpy.context.view_layer.update()
    dg.update()
    ev = mesh_obj.evaluated_get(dg)
    me = ev.to_mesh()
    arr = np.empty(n_verts * 3, dtype=np.float32)
    me.vertices.foreach_get("co", arr)
    pos = arr.reshape(-1, 3).copy()
    ev.to_mesh_clear()
    return pos

zero_all()
basis = capture()

normals = np.empty(n_verts * 3, dtype=np.float32)
mesh_obj.data.vertices.foreach_get("normal", normals)
normals = normals.reshape(-1, 3).copy()

# 每顶点 UV（PMX 顶点自带 UV，取第一个 loop 的值）
me0 = mesh_obj.data
uvs = np.zeros((n_verts, 2), dtype=np.float32)
uv_layer = me0.uv_layers.active.data
loops_vi = np.empty(len(me0.loops), dtype=np.int64)
me0.loops.foreach_get("vertex_index", loops_vi)
uv_arr = np.empty(len(me0.loops) * 2, dtype=np.float32)
uv_layer.foreach_get("uv", uv_arr)
uv_arr = uv_arr.reshape(-1, 2)
uvs[loops_vi] = uv_arr  # 同顶点多次写入，留最后一个

def bake(name):
    zero_all()
    if name not in keys:
        return None
    keys[name].value = 1.0
    pos = capture()
    zero_all()
    return pos - basis

# ---- MMD 表情 → ARKit 通道映射 ----
# (arkit名, 源morph, 模式) 模式: full / L / R（L/R=按角色左右半边拆分）
# 注意：通道名必须用 ARKit BlendShapeLocation 的原始键名（下划线风格，
# 如 eyeBlink_L），App 端按 rawValue 匹配。
MAPPING = [
    ("jawOpen", "あ", "full"),
    ("mouthFunnel", "お", "full"),
    ("mouthPucker", "う", "full"),
    ("mouthStretch_L", "い", "L"), ("mouthStretch_R", "い", "R"),
    ("mouthSmile_L", "にやり", "L"), ("mouthSmile_R", "にやり", "R"),
    # mouthFrown 不再映射「激怒」（那是横向运动、嘴角不下垂）；改由 synth_morphs 合成
    ("mouthLowerDown_L", "え", "L"), ("mouthLowerDown_R", "え", "R"),
    ("eyeSquint_L", "笑い", "L"), ("eyeSquint_R", "笑い", "R"),
    ("eyeWide_L", "びっくり", "L"), ("eyeWide_R", "びっくり", "R"),
    ("browInnerUp", "困る", "full"),
    ("browDown_L", "怒り", "L"), ("browDown_R", "怒り", "R"),
    ("browOuterUp_L", "上", "L"), ("browOuterUp_R", "上", "R"),
]

deltas_cache = {}
for _, src, _ in MAPPING:
    if src not in deltas_cache:
        deltas_cache[src] = bake(src)
        d = deltas_cache[src]
        print("BAKED", src, "max-delta:", 0 if d is None else float(np.abs(d).max()))

# 眨眼：优先用 まばたき（标准双眼眨）按左右拆分；缺失时用 ウィンク 兜底
morphs_out = {}  # arkit name -> (n_verts,3) delta
d_blink = bake("まばたき")
if d_blink is not None and np.abs(d_blink).max() > 1e-6:
    for side, key in (("L", "eyeBlink_L"), ("R", "eyeBlink_R")):
        sign = CHAR_LEFT_SIGN if side == "L" else -CHAR_LEFT_SIGN
        w = np.clip(0.5 + basis[:, 0] * sign / 0.02, 0, 1)[:, None]
        morphs_out[key] = d_blink * w
        print("BLINK SPLIT ->", key, "max:", float(np.abs(morphs_out[key]).max()))
else:
    for wname in ("ウィンク", "ウィンク右"):
        d = bake(wname)
        if d is None:
            continue
        mag = np.linalg.norm(d, axis=1)
        if mag.max() < 1e-6:
            continue
        cx = float((basis[:, 0] * mag).sum() / mag.sum())
        key = "eyeBlink_L" if cx * CHAR_LEFT_SIGN > 0 else "eyeBlink_R"
        if key not in morphs_out:
            morphs_out[key] = d
            print("WINK", wname, "->", key, "cx:", cx)

FALLOFF = 0.012  # 中线过渡带（米）
for arkit, src, mode in MAPPING:
    d = deltas_cache.get(src)
    if d is None:
        continue
    if mode == "full":
        morphs_out[arkit] = d
    else:
        sign = CHAR_LEFT_SIGN if mode == "L" else -CHAR_LEFT_SIGN
        w = np.clip(0.5 + basis[:, 0] * sign / (2 * FALLOFF), 0, 1)[:, None]
        morphs_out[arkit] = d * w

# ---- jawOpen：通用张嘴生成（逻辑见 tools/jaw_open.py，问题综述见 tools/JAW_OPEN.md）----
# 自动判定元音「あ」是否自带开颌；不足（骨骼驱动型如 AC/inase）则转模型下颌骨复用其
# 口腔/牙齿，并补下唇内缘的权重缺口。新模型无需改这里，参数都在 jaw_open 里。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jaw_open
_jaw_delta, _jaw_info = jaw_open.build_jaw_open(
    arm=arm, mesh=mesh_obj, basis=basis, capture=capture, zero_all=zero_all,
    eye_z=float(eyeL_w.z), neck_z=NECK_Z, vowel_delta=morphs_out.get("jawOpen"))
print("JAW:", _jaw_info)
if _jaw_delta is not None:
    morphs_out["jawOpen"] = _jaw_delta

# tongueOut：模型自带真舌头（Tongue 1~4 舌骨）。按舌骨顶点权重让舌头前伸下垂，
# 权重渐变天然实现舌根固定、舌尖伸出最多。Blender 坐标：前伸=-Y、下垂=-Z。
tong_groups = {}
for g in mesh_obj.vertex_groups:
    if "tong" in g.name.lower() or "舌" in g.name:
        num = next((int(ch) for ch in reversed(g.name) if ch.isdigit()), 2)
        tong_groups[g.index] = num  # 1=舌根 … 4=舌尖
if tong_groups:
    tdir = np.array([0.0, -0.045, -0.006])  # Blender 前伸(-Y)+略下垂(-Z)；近水平从唇缝伸出，少穿下唇
    tdelta = np.zeros((n_verts, 3))
    for v in mesh_obj.data.vertices:
        f = 0.0
        for gv in v.groups:
            if gv.group in tong_groups:
                num = tong_groups[gv.group]
                f += gv.weight * (0.15 + 0.85 * (num - 1) / 3.0)  # 舌尖伸更多
        if f > 0.01:
            tdelta[v.index] = min(f, 1.0) * tdir
    morphs_out["tongueOut"] = tdelta
    print("TONGUE groups:", sorted(tong_groups.items()),
          "verts:", int((np.linalg.norm(tdelta, axis=1) > 1e-6).sum()))
else:
    print("TONGUE: no tongue vertex groups found")

print("MORPH CHANNELS:", sorted(morphs_out.keys()))

# ---- 选择头部顶点（材质过滤 + 高度过滤）----
mats = [s.material.name if s.material else "" for s in mesh_obj.material_slots]
EXCLUDE_KW = ("Suit", "Boots", "Gloves", "Panties", "Pubes", "GenS",
              "Chest", "Arms", "Legs", "Inners")
def mat_ok(name):
    if name.startswith("-"):
        return False
    return not any(k in name for k in EXCLUDE_KW)

# 材质→纹理文件
mat_tex = {}
for slot in mesh_obj.material_slots:
    m = slot.material
    tex = None
    if m and m.use_nodes:
        for node in m.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image and node.image.filepath:
                p = bpy.path.abspath(node.image.filepath)
                if os.path.exists(p):
                    tex = p
                    break
    mat_tex[m.name if m else ""] = tex
for k, v in mat_tex.items():
    print("MATTEX", repr(k), "->", v and os.path.basename(v))

me = mesh_obj.data
n_tris_loops = len(me.loop_triangles) or 0
me.calc_loop_triangles()
tri_v = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
me.loop_triangles.foreach_get("vertices", tri_v)
tri_v = tri_v.reshape(-1, 3)
tri_mat = np.empty(len(me.loop_triangles), dtype=np.int64)
me.loop_triangles.foreach_get("material_index", tri_mat)

z = basis[:, 2]
Z_MIN = NECK_Z - 0.02
vert_high = z >= Z_MIN

eye_mat_ids = {i for i, n in enumerate(mats) if n == "Eyes"}
head_mat_ids = {i for i, n in enumerate(mats) if mat_ok(n) and n != "Eyes"}

tri_keep_head = np.isin(tri_mat, list(head_mat_ids)) & vert_high[tri_v].all(axis=1)
tri_keep_eyes = np.isin(tri_mat, list(eye_mat_ids))
print("HEAD TRIS:", int(tri_keep_head.sum()), "EYE TRIS:", int(tri_keep_eyes.sum()))

# ---- 坐标转换 Blender(z-up, 面朝-Y) -> SceneKit(y-up, 面朝+Z) ----
def conv(p):  # (n,3)
    return np.stack([p[:, 0], p[:, 2], -p[:, 1]], axis=1)

mid_eye = (np.array(eyeL_w) + np.array(eyeR_w)) / 2
origin_b = np.array([0.0, mid_eye[1] + 0.06, mid_eye[2] - 0.01])  # 面部中心略靠后
origin_s = conv(origin_b[None])[0]

# 法线贴图：MMD 材质常没把法线接进节点，按 _D→_N 命名约定找（Face_D→Face_N）；脸皮子网格
# 的漫反射常被换成怪名贴图（AO/-C/Tifa_Head），但这些都是 Genesis 8 脸、UV 标准，直接用
# 源里的 G8 标准脸法线 Face_N 即可对齐（已离线渲染验证）。
PMX_DIR = os.path.dirname(PMX)
normal_paths = {}  # basename -> 绝对路径，末尾统一拷贝到 OUT_DIR
def _register(cand):
    bn = os.path.basename(cand)
    normal_paths[bn] = cand
    return bn
def find_normal(tex_path, mat_name=""):
    # 1) 常规 _D→_N（同目录）
    if tex_path:
        base, ext = os.path.splitext(tex_path)
        if base.endswith("_D"):
            for e in (ext, ".jpg", ".png", ".jpeg"):
                cand = base[:-2] + "_N" + e
                if os.path.exists(cand):
                    return _register(cand)
    # 2) 脸皮兜底：名字含 face/head（排除 hair/eye/lash/brow/ear）→ G8 标准脸法线 Face_N
    n = mat_name.lower()
    if ("face" in n or "head" in n) and not any(k in n for k in
            ("hair", "eye", "lash", "brow", "ear")):
        for e in (".jpg", ".png", ".jpeg"):
            cand = os.path.join(PMX_DIR, "Face_N" + e)
            if os.path.exists(cand):
                return _register(cand)
    return None

def build_object(tri_mask, name, pivot_b, with_morphs, vert_extra_mask=None):
    tris = tri_v[tri_mask]
    tmats = tri_mat[tri_mask]
    if vert_extra_mask is not None:
        keep = vert_extra_mask[tris].all(axis=1)
        tris, tmats = tris[keep], tmats[keep]
    used = np.unique(tris)
    remap = np.full(n_verts, -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    pivot_s = conv(np.array(pivot_b, dtype=np.float64)[None])[0]
    pos = conv(basis[used]) - pivot_s
    nor = conv(normals[used])
    obj = {
        "name": name,
        "position": [float(x) for x in (pivot_s - origin_s)] if name != "Head" else [0, 0, 0],
        "vertexCount": int(len(used)),
        "_pos": pos.astype(np.float32),
        "_nor": nor.astype(np.float32),
        "_uv": uvs[used].astype(np.float32),
        "submeshes": [],
        "morphs": [],
    }
    new_tris = remap[tris]
    # 翻转三角形绕序（镜像变换 x,z,-y 行列式为正，但 Blender->SceneKit 朝向检查后再定）
    for mi in sorted(set(tmats.tolist())):
        sel = new_tris[tmats == mi]
        tex = mat_tex.get(mats[mi])
        obj["submeshes"].append({
            "name": mats[mi],
            "texture": os.path.basename(tex) if tex else None,
            "normal": find_normal(tex, mats[mi]),
            "transparent": bool(tex and tex.lower().endswith(".png")),
            "_idx": sel.astype(np.uint32).ravel(),
        })
    if with_morphs:
        for mname, delta in sorted(morphs_out.items()):
            dsub = delta[used]
            mag = np.linalg.norm(dsub, axis=1)
            nz = np.where(mag > 1e-5)[0]
            if len(nz) == 0:
                continue
            obj["morphs"].append({
                "name": mname,
                "_idx": nz.astype(np.uint32),
                "_delta": conv(dsub[nz]).astype(np.float32),
            })
    return obj

head = build_object(tri_keep_head, "Head", origin_b, True)
eyeL = build_object(tri_keep_eyes, "EyeLeft", np.array(eyeL_w), False,
                    vert_extra_mask=(basis[:, 0] * CHAR_LEFT_SIGN > 0))
eyeR = build_object(tri_keep_eyes, "EyeRight", np.array(eyeR_w), False,
                    vert_extra_mask=(basis[:, 0] * CHAR_LEFT_SIGN <= 0))
objects = [head, eyeL, eyeR]
for o in objects:
    print("OBJ", o["name"], "verts:", o["vertexCount"],
          "submeshes:", [(s["name"], len(s["_idx"]) // 3) for s in o["submeshes"]],
          "morphs:", len(o["morphs"]))

# ---- 写 FCH 文件 ----
blob = bytearray()
def put(arr):
    off = len(blob)
    blob.extend(arr.tobytes())
    return {"offset": off, "count": int(arr.size)}

meta = {"version": 1, "objects": []}
for o in objects:
    jo = {
        "name": o["name"], "position": o["position"],
        "vertexCount": o["vertexCount"],
        "positions": put(o["_pos"]), "normals": put(o["_nor"]), "uvs": put(o["_uv"]),
        "submeshes": [], "morphs": [],
    }
    for s in o["submeshes"]:
        jo["submeshes"].append({
            "name": s["name"], "texture": s["texture"], "normal": s.get("normal"),
            "transparent": s["transparent"], "indices": put(s["_idx"]),
        })
    for m in o["morphs"]:
        jo["morphs"].append({
            "name": m["name"],
            "vertexIndices": put(m["_idx"]), "deltas": put(m["_delta"]),
        })
    meta["objects"].append(jo)

os.makedirs(OUT_DIR, exist_ok=True)
js = json.dumps(meta).encode("utf-8")
with open(os.path.join(OUT_DIR, "head.fch"), "wb") as f:
    f.write(b"FCH1")
    f.write(struct.pack("<I", len(js)))
    f.write(js)
    f.write(bytes(blob))
print("FCH SIZE:", os.path.getsize(os.path.join(OUT_DIR, "head.fch")))

# 过程化补齐 PMX 缺失/错误的 ARKit 形态 key（颧骨、上唇、鼻翼、撇嘴、下巴侧移……）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synth_morphs
print("SYNTH MORPHS:")
synth_morphs.synth_into_fch(os.path.join(OUT_DIR, "head.fch"))

# 拷贝用到的纹理
used_tex = {s["texture"] for o in objects for s in o["submeshes"] if s["texture"]}
for slot_name, p in mat_tex.items():
    if p and os.path.basename(p) in used_tex:
        shutil.copy(p, os.path.join(OUT_DIR, os.path.basename(p)))
        print("COPIED", os.path.basename(p))
# 拷贝用到的法线贴图
used_nrm = {s.get("normal") for o in objects for s in o["submeshes"] if s.get("normal")}
for bn in used_nrm:
    if bn in normal_paths:
        shutil.copy(normal_paths[bn], os.path.join(OUT_DIR, bn))
        print("COPIED NORMAL", bn)
print("DONE")
