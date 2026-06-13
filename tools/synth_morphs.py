"""过程化合成 head.fch 中 PMX 模型缺失/错误的 ARKit 形态 key。

本模型（Reika18_Children.pmx）只有 19 个骨骼 morph，烘焙出的头模缺很多 ARKit
通道（颧骨、上唇、鼻翼、撅嘴左右、下巴侧移……），且个别映射方向错误
（mouthFrown 来自「激怒」只有横向运动、嘴角不下垂）。

这里按头模几何位置过程化合成这些通道：用眼/嘴/鼻等关键点定位区域，
做高斯加权位移。被本脚本管理的 morph 见 MANAGED——重复运行幂等
（先删同名再加）。坐标为头模本地 SceneKit 空间（y-up，+Z 朝前，米）。

用法：
    python3 tools/synth_morphs.py Resources/head.fch
烘焙脚本 bake_head_from_pmx.py 末尾也会调用 synth_into_fch()，保证重新烘焙不丢。
"""
import struct, json, sys
import numpy as np

# 头模本地 SceneKit 关键点（来自 head.fch 几何探测）
EYE_L = np.array([0.0277, 0.010, 0.060])
EYE_R = np.array([-0.0277, 0.010, 0.060])
SEAM_Y = -0.047                       # 上下唇缝高度
CORNER_L = np.array([0.022, -0.047, 0.077])
CORNER_R = np.array([-0.022, -0.047, 0.077])
MOUTH_C = np.array([0.0, -0.047, 0.080])
NOSTRIL_L = np.array([0.013, -0.016, 0.095])
NOSTRIL_R = np.array([-0.013, -0.016, 0.095])
JAW_C = np.array([0.0, -0.075, 0.065])

# 本脚本管理（合成/覆盖）的通道；重新运行时先按名删除再重建
MANAGED = [
    "cheekSquint_L", "cheekSquint_R", "cheekPuff",
    "mouthFrown_L", "mouthFrown_R",
    "mouthUpperUp_L", "mouthUpperUp_R", "noseSneer_L", "noseSneer_R",
    "mouthShrugUpper", "mouthShrugLower",
    "mouthPress_L", "mouthPress_R", "mouthDimple_L", "mouthDimple_R",
    "mouthLeft", "mouthRight", "jawLeft", "jawRight", "jawForward",
    "mouthClose", "mouthRollUpper", "mouthRollLower",
]

# 原生（烘焙）morph 的温和增益：MMD 骨骼形变量小，几个关键通道在预览里偏弱。
# 中间档——比保守原值明显，但不夸张（目标峰值约 5-9mm）。
NATIVE_GAIN = {
    "eyeWide_L": 2.0, "eyeWide_R": 2.0,        # 1.8mm -> ~3.6mm（睁大眼，真机偏夸张再收）
    "mouthSmile_L": 1.8, "mouthSmile_R": 1.8,  # 3.3mm -> ~6mm（微笑嘴角）
    "mouthStretch_L": 1.2, "mouthStretch_R": 1.2,  # 3.5 -> ~4.2
    "mouthPucker": 1.5,                        # 4.0 -> ~6
    "browDown_L": 1.5, "browDown_R": 1.5,      # 3.4 -> ~5（皱眉）
    "browOuterUp_R": 1.4,                      # 6.3 -> ~8.8（补左右不对称）
}


def _unit(v):
    v = np.asarray(v, float)
    return v / (np.linalg.norm(v) + 1e-12)


def _gauss(P, center, sigma):
    return np.exp(-(((P - center) / sigma) ** 2).sum(1))


def _emit(P, weight, direction, peak, front_z=0.04):
    """weight>thr 的顶点按 direction*peak*weight 位移；direction 可为 (3,) 或 (n,3)。"""
    w = np.where((weight > 0.06) & (P[:, 2] > front_z), weight, 0.0)
    nz = np.where(w > 0)[0]
    if len(nz) == 0:
        return None
    d = np.asarray(direction, float)
    if d.ndim == 1:
        delta = (w[nz, None] * peak) * _unit(d)[None]
    else:
        dn = d[nz] / (np.linalg.norm(d[nz], axis=1, keepdims=True) + 1e-12)
        delta = (w[nz, None] * peak) * dn
    return nz.astype(np.uint32), delta.astype(np.float32)


def synth_all(P):
    """返回 {name: (idx_uint32, delta_fx3)}。P 为头模本地顶点 (n,3)。"""
    out = {}

    def add(name, res):
        if res is not None:
            out[name] = res

    # 颧骨上提（笑）：眼下外侧抬起，上+前+略内
    for nm, eye, sgn in (("cheekSquint_L", EYE_L, +1.0), ("cheekSquint_R", EYE_R, -1.0)):
        c = np.array([eye[0] * 1.10, eye[1] - 0.030, eye[2] - 0.006])
        w = _gauss(P, c, [0.027, 0.028, 0.038])
        w[(P[:, 0] * sgn < 0.010) | (P[:, 1] > eye[1] + 0.006) | (P[:, 1] < -0.062)
          | (P[:, 0] * sgn > 0.075)] = 0
        add(nm, _emit(P, w, [-0.12 * sgn, 1.0, 0.40], 0.008, front_z=0.015))

    # 鼓腮：两颊向外+向前鼓出（单通道，左右同时）
    wsum = np.zeros(len(P))
    dirs = np.zeros((len(P), 3))
    for sgn in (+1.0, -1.0):
        c = np.array([0.045 * sgn, -0.028, 0.055])
        w = _gauss(P, c, [0.028, 0.030, 0.035])
        w[(P[:, 0] * sgn < 0.018) | (P[:, 2] < 0.02)] = 0
        wsum = np.maximum(wsum, w)
        dirs[w > 0] = _unit([1.0 * sgn, 0.0, 0.7])
    add("cheekPuff", _emit(P, wsum, dirs, 0.009, front_z=0.02))

    # 嘴角下拉（皱眉/撇嘴）——替换错误的「激怒」映射：嘴角向下+略外
    for nm, corner, sgn in (("mouthFrown_L", CORNER_L, +1.0), ("mouthFrown_R", CORNER_R, -1.0)):
        w = _gauss(P, corner, [0.020, 0.022, 0.024])
        w[(P[:, 0] * sgn < 0.006) | (P[:, 1] > -0.032)] = 0
        add(nm, _emit(P, w, [0.10 * sgn, -1.0, 0.0], 0.007))

    # 上唇上提（露齿/讥笑）
    for nm, sgn in (("mouthUpperUp_L", +1.0), ("mouthUpperUp_R", -1.0)):
        c = np.array([0.014 * sgn, -0.038, 0.086])
        w = _gauss(P, c, [0.022, 0.018, 0.024])
        w[(P[:, 0] * sgn < -0.004) | (P[:, 1] < SEAM_Y) | (P[:, 1] > -0.028)] = 0
        add(nm, _emit(P, w, [0.0, 1.0, 0.25], 0.0035))

    # 鼻翼上提（嫌恶）
    for nm, nostril, sgn in (("noseSneer_L", NOSTRIL_L, +1.0), ("noseSneer_R", NOSTRIL_R, -1.0)):
        w = _gauss(P, nostril, [0.012, 0.014, 0.014])
        w[(P[:, 0] * sgn < 0.002) | (P[:, 1] < -0.035)] = 0
        add(nm, _emit(P, w, [0.0, 1.0, 0.10], 0.005))

    # 上唇/下唇向中缝聚拢（抿/耸）
    c = np.array([0.0, -0.036, 0.086])
    w = _gauss(P, c, [0.024, 0.012, 0.020]); w[P[:, 1] < SEAM_Y] = 0
    add("mouthShrugUpper", _emit(P, w, [0.0, 1.0, 0.10], 0.003))
    c = np.array([0.0, -0.060, 0.080])
    w = _gauss(P, c, [0.024, 0.014, 0.020]); w[P[:, 1] > SEAM_Y] = 0
    add("mouthShrugLower", _emit(P, w, [0.0, 1.0, 0.10], 0.003))

    # 抿唇（嘴角向内收，唇变薄）
    for nm, corner, sgn in (("mouthPress_L", CORNER_L, +1.0), ("mouthPress_R", CORNER_R, -1.0)):
        w = _gauss(P, corner, [0.018, 0.016, 0.020])
        w[P[:, 0] * sgn < 0.006] = 0
        add(nm, _emit(P, w, [-1.0 * sgn, 0.0, 0.0], 0.004))

    # 酒窝（嘴角向后+略内）
    for nm, corner, sgn in (("mouthDimple_L", CORNER_L, +1.0), ("mouthDimple_R", CORNER_R, -1.0)):
        w = _gauss(P, corner, [0.018, 0.018, 0.020])
        w[P[:, 0] * sgn < 0.010] = 0
        add(nm, _emit(P, w, [-0.3 * sgn, 0.15, -1.0], 0.004))

    # 嘴整体左右移
    w = _gauss(P, MOUTH_C, [0.030, 0.020, 0.030]); w[P[:, 1] > -0.028] = 0
    add("mouthLeft", _emit(P, w, [1.0, 0.0, 0.0], 0.0055))
    add("mouthRight", _emit(P, w, [-1.0, 0.0, 0.0], 0.0055))

    # 下巴左右移 / 前伸（下半脸）
    w = _gauss(P, JAW_C, [0.032, 0.030, 0.030]); w[P[:, 1] > -0.050] = 0
    add("jawLeft", _emit(P, w, [1.0, 0.0, 0.0], 0.0068))
    add("jawRight", _emit(P, w, [-1.0, 0.0, 0.0], 0.0068))
    add("jawForward", _emit(P, w, [0.0, 0.0, 1.0], 0.0068))

    # 闭唇（张口时合上）：上唇下压、下唇上抬向缝靠拢
    w = _gauss(P, np.array([0.0, -0.040, 0.085]), [0.026, 0.012, 0.022]); w[P[:, 1] < SEAM_Y] = 0
    add("mouthClose", _emit(P, w, [0.0, -1.0, 0.0], 0.004))
    # 下唇部分单独叠加为同名 morph：合成时合并
    wl = _gauss(P, np.array([0.0, -0.058, 0.082]), [0.026, 0.012, 0.022]); wl[P[:, 1] > SEAM_Y] = 0
    low = _emit(P, wl, [0.0, 1.0, 0.0], 0.004)
    if low is not None and "mouthClose" in out:
        out["mouthClose"] = _merge(out["mouthClose"], low, len(P))
    elif low is not None:
        out["mouthClose"] = low

    # 卷唇（唇缘向口内卷：后+朝缝）
    w = _gauss(P, np.array([0.0, -0.040, 0.086]), [0.024, 0.012, 0.018]); w[P[:, 1] < SEAM_Y] = 0
    add("mouthRollUpper", _emit(P, w, [0.0, -0.3, -1.0], 0.004))
    w = _gauss(P, np.array([0.0, -0.058, 0.082]), [0.024, 0.012, 0.018]); w[P[:, 1] > SEAM_Y] = 0
    add("mouthRollLower", _emit(P, w, [0.0, 0.3, -1.0], 0.004))

    return out


def _merge(a, b, nverts):
    """把两个 (idx,delta) 合并成一个稀疏 morph（同顶点相加）。"""
    acc = np.zeros((nverts, 3), np.float64)
    for idx, dl in (a, b):
        acc[idx] += dl
    nz = np.where(np.linalg.norm(acc, axis=1) > 1e-6)[0]
    return nz.astype(np.uint32), acc[nz].astype(np.float32)


def make_tongue():
    """生成简易舌头网格（单层弯曲舌背，模型 doubleSided 渲染），静止平放口腔内。
    返回 (V, N, UV, F, u)：顶点(米, 头模本地 SceneKit)、法线、UV、三角索引(局部)、
    每顶点 u 参数(0=舌根 1=舌尖)。"""
    nu, nv = 14, 9
    root = np.array([0.0, -0.049, 0.043])   # 舌根（口腔深处）
    tip = np.array([0.0, -0.052, 0.073])    # 舌尖（门牙后方，唇内侧，闭嘴时被遮）
    us = np.linspace(0, 1, nu)
    vs = np.linspace(-1, 1, nv)
    V, U, UV = [], [], []
    for u in us:
        hw = 0.0135 * (1 - 0.5 * u * u)      # 舌尖收窄
        cz = root[2] + (tip[2] - root[2]) * u
        cy = root[1] + (tip[1] - root[1]) * u
        for v in vs:
            arch = 0.0040 * (1 - v * v) * (0.45 + 0.55 * np.sin(np.pi * min(u * 1.1, 1.0)))
            V.append([hw * v, cy + arch, cz]); U.append(u); UV.append([(v + 1) / 2, u])
    V = np.array(V); U = np.array(U); UV = np.array(UV)
    F = []
    def vid(i, j): return i * nv + j
    for i in range(nu - 1):
        for j in range(nv - 1):
            a, b, c, e = vid(i, j), vid(i + 1, j), vid(i + 1, j + 1), vid(i, j + 1)
            F += [[a, b, c], [a, c, e]]
    F = np.array(F, dtype=np.int64)
    N = np.zeros_like(V)
    for f in F:
        nrm = np.cross(V[f[1]] - V[f[0]], V[f[2]] - V[f[0]])
        N[f[0]] += nrm; N[f[1]] += nrm; N[f[2]] += nrm
    N /= np.linalg.norm(N, axis=1, keepdims=True) + 1e-9
    N[N[:, 1] < 0] *= -1                     # 法线统一朝上（舌背）
    return V, N, UV, F, U


def synth_into_fch(path):
    d = open(path, "rb").read()
    assert d[:4] == b"FCH1", "not an FCH1 file"
    jlen = struct.unpack_from("<I", d, 4)[0]
    meta = json.loads(d[8:8 + jlen])
    blob = bytearray(d[8 + jlen:])
    head = next(o for o in meta["objects"] if o["name"] == "Head")

    # 幂等：移除上一次合成的舌头（顶点连续追加在尾部），还原纯脸部几何后再处理。
    def _vec(ref, comp):
        return np.frombuffer(bytes(blob), dtype="<f4", count=ref["count"],
                             offset=ref["offset"]).reshape(-1, comp)
    face_n = int(head.get("_faceVertexCount", head["vertexCount"]))
    face_pos = _vec(head["positions"], 3)[:face_n].astype(np.float64)
    face_nrm = _vec(head["normals"], 3)[:face_n].astype(np.float32).copy()
    face_uv = _vec(head["uvs"], 2)[:face_n].astype(np.float32).copy()
    head["submeshes"] = [s for s in head["submeshes"] if s["name"] != "Tongue"]
    head["morphs"] = [m for m in head["morphs"] if m["name"] != "tongueOut"]
    head["vertexCount"] = face_n
    P = face_pos

    # 幂等：去掉本脚本管理的旧 morph（按名）
    head["morphs"] = [m for m in head["morphs"] if m["name"] not in MANAGED]

    # 原生 morph 温和增益。_gain 记录「当前 delta 已含的增益倍数」，重复运行幂等；
    # 改了 NATIVE_GAIN 后再跑会按 目标/已应用 的比例修正，不必从 pristine 重来。
    for m in head["morphs"]:
        target = float(NATIVE_GAIN.get(m["name"], 1.0))
        applied = float(m.get("_gain", 1.0))
        if abs(target - applied) > 1e-9:
            r = m["deltas"]
            arr = np.frombuffer(bytes(blob), dtype="<f4",
                                count=r["count"], offset=r["offset"]).copy()
            factor = target / applied
            m["deltas"] = {"_data": (arr * factor).astype(np.float32)}
            m["_gain"] = target
            print(f"  * {m['name']:16} gain {applied:.2f}->{target:.2f}  -> maxmm "
                  f"{float(np.linalg.norm(arr.reshape(-1,3)*factor,axis=1).max())*1000:.1f}")

    synth = synth_all(P)
    for name in MANAGED:
        if name not in synth:
            continue
        idx, delta = synth[name]
        head["morphs"].append({
            "name": name,
            "vertexIndices": {"_data": idx}, "deltas": {"_data": delta},
        })
        mm = float(np.linalg.norm(delta, axis=1).max())
        print(f"  + {name:16} verts={len(idx):6d} maxmm={mm*1000:.1f}")

    # 加舌头几何（新顶点追加在脸部之后）+ tongueOut morph（舌头前伸下垂伸出嘴外）
    Vt, Nt, UVt, Ft, ut = make_tongue()
    base = int(head["vertexCount"])
    head["positions"] = {"_data": np.vstack([face_pos, Vt]).astype(np.float32)}
    head["normals"] = {"_data": np.vstack([face_nrm, Nt]).astype(np.float32)}
    head["uvs"] = {"_data": np.vstack([face_uv, UVt]).astype(np.float32)}
    head["vertexCount"] = base + len(Vt)
    head["_faceVertexCount"] = base
    head["submeshes"].append({
        "name": "Tongue", "texture": None, "transparent": False,
        "indices": {"_data": (Ft + base).astype(np.uint32).ravel()},
    })
    tdir = np.array([0.0, -0.020, 0.033])    # 前伸 +z、下垂 -y
    tdelta = (0.15 + 0.85 * ut[:, None] ** 1.3) * tdir
    head["morphs"].append({
        "name": "tongueOut",
        "vertexIndices": {"_data": (base + np.arange(len(Vt))).astype(np.uint32)},
        "deltas": {"_data": tdelta.astype(np.float32)},
    })
    print(f"  + tongueOut        舌头顶点={len(Vt)} "
          f"伸出={float(np.linalg.norm(tdelta,axis=1).max())*1000:.1f}mm")

    # 重新打包 blob：只保留被引用的缓冲区（清掉历次替换留下的孤儿字节），
    # 新合成的 morph 用 {"_data": ndarray} 占位，旧引用从原 blob 取数据。
    old = bytes(blob)
    newblob = bytearray()

    def repack(ref):
        if "_data" in ref:                       # 新合成的 morph：ndarray 直接打包
            b = ref["_data"].tobytes()
        else:                                    # 已有缓冲：每元素 4 字节，原样搬运
            b = old[ref["offset"]: ref["offset"] + ref["count"] * 4]
        off = len(newblob); newblob.extend(b)
        ref.clear()
        ref["offset"] = off
        ref["count"] = len(b) // 4

    for o in meta["objects"]:
        for key in ("positions", "normals", "uvs"):
            repack(o[key])
        for s in o["submeshes"]:
            repack(s["indices"])
        for m in o["morphs"]:
            repack(m["vertexIndices"])
            repack(m["deltas"])

    blob = newblob
    js = json.dumps(meta).encode("utf-8")
    with open(path, "wb") as f:
        f.write(b"FCH1"); f.write(struct.pack("<I", len(js))); f.write(js); f.write(bytes(blob))
    print(f"  morphs now: {len(head['morphs'])}  file: {path}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "Resources/head.fch"
    synth_into_fch(target)
