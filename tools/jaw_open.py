"""通用 jawOpen（张嘴）生成器——自动适配不同 PMX 的张嘴机制。

为什么需要它（问题综述，详见 tools/JAW_OPEN.md）：
ARKit 的 jawOpen 通道要让头模张大嘴、露出牙/口腔。但 MMD 模型实现张嘴的方式分两类，
直接烘元音 morph 会在部分模型上失败：

  A 类·元音自带开颌：「あ」morph 本身就把下颌拉开（Children/Office/Remake）。直接用。
  B 类·骨骼驱动开颌：「あ」只是嘴型微调，真正张嘴靠下颌骨（AC=head jaw / inase=Jaw Bone）。
        只烘 morph 嘴张不开；且牙齿/口腔是蒙皮在下颌骨上的几何，必须转骨才会被带出来露牙。

B 类还有个附带问题：源模型给下颌骨刷权重时，下唇内缘常留权重缺口（一圈顶点没绑到下颌骨）。
纯转骨时这些「漏网点」不随颌下沉，在张开的上缘戳出小凸起/接缝。需在唇缝以下局部平滑修补。

本模块把「判 A/B → 选轴转骨 → 补漏 → 归一化幅度」整套封装。bake_head_from_pmx.py 调用
build_jaw_open()。**新增模型无需改代码**：阈值/角度/目标幅度都是参数，自动检测下颌骨与旋转轴。

坐标系：全程 Blender 世界系（z-up、面朝 -Y），与 bake 的 basis 一致。
"""
import numpy as np

# 唇缝在 Blender z 的位置 = 眼高 - 0.057（由 FCH 标定 SceneKit 眼 y=+0.010 / 唇缝 y=-0.047
# 反推，各 Reika 模型眼睛已对齐到同一头模本地系）。
SEAM_BELOW_EYE = 0.057


def _pose_reset(arm):
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0, 0, 0)


def find_jaw_bones(arm):
    """按名找下颌骨候选（排除 jaw upper… 那种上颌/上齿骨），短名优先（主下颌骨）。"""
    cands = [b.name for b in arm.data.bones
             if (("jaw" in b.name.lower() or "あご" in b.name.lower() or "顎" in b.name)
                 and "upper" not in b.name.lower())]
    cands.sort(key=len)
    return cands


def mouth_region(basis, eye_z, neck_z):
    """打分用的嘴/下颌区（脸最前 18%、眼下、颈上）。"""
    front = basis[:, 1] < np.percentile(basis[:, 1], 18)
    lower = (basis[:, 2] < eye_z - 0.03) & (basis[:, 2] > neck_z - 0.015)
    return front & lower


def open_score(delta, region):
    """嘴区平均向下（z 减小）位移，越大表示张得越开。"""
    return -float(delta[region, 2].mean()) if region.sum() else 0.0


def fill_static_holes(delta, mesh, region, iters=15, lam=0.5):
    """只填补 region 内「漏网静止点」——自身位移≈0、但被运动顶点包围的洞，从邻居向内
    扩散填充。**绝不改动本来就运动正确的顶点**（嘴角/下巴等保持骨骼旋转的干净结果）。
    这是关键：整片平滑会把嘴角运动顶点也搅乱、拉出尖刺；只填洞则两者兼得。"""
    ne = len(mesh.data.edges)
    ev = np.empty(ne * 2, dtype=np.int64)
    mesh.data.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    keep = region[ev[:, 0]] & region[ev[:, 1]]    # 只在 region 内邻接（不跨唇缝）
    ea, eb = ev[keep, 0], ev[keep, 1]
    fill = region & (np.linalg.norm(delta, axis=1) < 0.001)   # 待填的静止洞
    d = delta.copy()
    for _ in range(iters):
        acc = np.zeros_like(d)
        cnt = np.zeros(len(d))
        np.add.at(acc, ea, d[eb]); np.add.at(cnt, ea, 1.0)
        np.add.at(acc, eb, d[ea]); np.add.at(cnt, eb, 1.0)
        upd = fill & (cnt > 0)                     # 只更新洞，运动顶点原样不动
        d[upd] = (1 - lam) * d[upd] + lam * (acc[upd] / cnt[upd, None])
    return d


def upper_lip_lift(basis, eye_z, jaw_mag, lift_mm=6.0):
    """上唇中央（门牙宽度）微抬的位移场（Blender 系），露出上门牙。
    转下颌骨只动下颌，静止的上唇下边缘会垂下挡住上前牙；自然张嘴时上唇本会略抬。
    关键：用 jaw_mag 门控「不随下颌动的顶点才抬」——既自动只命中上唇（排除下沉的下唇），
    又能覆盖到最容易估偏的下边缘。在唇缝附近一层、前脸、中央高斯加权抬升（+z=上）。"""
    x, y, z = basis[:, 0], basis[:, 1], basis[:, 2]
    seam_z = eye_z - SEAM_BELOW_EYE
    band = (np.clip((z - (seam_z - 0.008)) / 0.004, 0, 1)    # 含下边缘（seam-8mm 起渐入）
            * np.clip((seam_z + 0.012 - z) / 0.012, 0, 1))    # 向上 ~12mm 渐隐
    front = np.clip((np.percentile(y, 25) - y) / 0.02, 0, 1)
    cen = np.exp(-(x / 0.030) ** 2)                          # 中央（门牙）高斯
    static = np.clip((0.0015 - jaw_mag) / 0.0015, 0, 1)      # 只抬不随颌动的（排除下唇）
    w = band * front * cen * static
    lift = np.zeros((len(basis), 3))
    lift[:, 2] = (lift_mm / 1000.0) * w                      # 抬升
    lift[:, 1] = (0.2 * lift_mm / 1000.0) * w                # 略向内贴齿列
    return lift


def build_jaw_open(*, arm, mesh, basis, capture, zero_all, eye_z, neck_z,
                   vowel_delta=None, deficient_mm=1.2, angle=0.42,
                   target_mm=14.0, upper_lip_lift_mm=6.0):
    """生成一个可用的 jawOpen 位移（Blender 系，[n,3]）。

    参数：
      arm/mesh        ：MMD 骨架对象 / 主网格对象
      basis           ：静止顶点位置 [n,3]（Blender 世界系）
      capture         ：无参回调，返回当前 evaluated 网格顶点位置 [n,3]
      zero_all        ：无参回调，把所有 morph 滑条归零
      eye_z/neck_z    ：眼/颈高度（Blender z），定位嘴区与唇缝
      vowel_delta     ：已烘的元音「あ」位移 [n,3] 或 None
      deficient_mm    ：元音嘴区开口<此值(mm) 判为 B 类骨骼驱动，改转下颌骨
      angle           ：试转角（弧度）
      target_mm       ：归一化后的满 weight 最大张嘴位移（对齐 Children 原生 ~14mm）

    返回 (delta 或 None, info_str)。delta=None 表示「元音足够好，沿用元音」。
    """
    region = mouth_region(basis, eye_z, neck_z)
    aa = open_score(vowel_delta, region) if vowel_delta is not None else 0.0
    jaw_cands = find_jaw_bones(arm)
    info = f"vowel あ={aa*1000:.1f}mm jaw_bones={jaw_cands}"

    # A 类：元音自带开颌，或没有下颌骨可用 → 沿用元音
    if aa * 1000 >= deficient_mm or not jaw_cands:
        return None, info + " -> 保留元音"

    # B 类：转下颌骨。自动在 3 轴 × 2 方向里挑「最能让嘴区下沉」的旋转
    jb = arm.pose.bones[jaw_cands[0]]
    best = (aa, None, None)
    for axis in range(3):
        for sgn in (1, -1):
            _pose_reset(arm); zero_all()
            e = [0.0, 0.0, 0.0]; e[axis] = sgn * angle
            jb.rotation_euler = e
            sc = open_score(capture() - basis, region)
            if sc > best[0]:
                best = (sc, axis, sgn)
    _pose_reset(arm); zero_all()
    if best[1] is None:
        return None, info + " -> 无能开口的轴，保留元音"

    e = [0.0, 0.0, 0.0]; e[best[1]] = best[2] * angle
    jb.rotation_euler = e
    jd = capture() - basis
    _pose_reset(arm); zero_all()
    raw_mm = float(np.linalg.norm(jd, axis=1).max()) * 1000

    # 补漏：唇缝以下、贴嘴前部的小盒区内平滑，填掉下唇内缘的权重缺口（漏网静止点）。
    # 收紧到嘴/下巴前部，不碰脖子/后脑/牙齿/上唇。
    seam_z = eye_z - SEAM_BELOW_EYE
    mouth_box = ((basis[:, 2] < seam_z) & (basis[:, 2] > seam_z - 0.045)
                 & (basis[:, 1] < np.percentile(basis[:, 1], 25))
                 & (np.abs(basis[:, 0]) < 0.06))
    n_static = int((mouth_box & (np.linalg.norm(jd, axis=1) < 0.002)).sum())
    jd = fill_static_holes(jd, mesh, mouth_box, iters=15, lam=0.5)

    # 归一化满 weight 张嘴幅度，跨模型一致（下颌为主，先归一化再叠加上唇抬升）
    mx = float(np.linalg.norm(jd, axis=1).max()) * 1000
    if mx > 1e-3:
        jd *= target_mm / mx

    # 上唇略抬，露出上门牙（在归一化后叠加，按绝对 mm；按 jaw_mag 门控只抬上唇）
    if upper_lip_lift_mm > 0:
        jaw_mag = np.linalg.norm(jd, axis=1)
        jd = jd + upper_lip_lift(basis, eye_z, jaw_mag, lift_mm=upper_lip_lift_mm)

    info += (f" -> 下颌骨 {jaw_cands[0]} axis={best[1]} sign={best[2]} "
             f"raw={raw_mm:.0f}mm 补漏{n_static}点 归一化{target_mm:.0f}mm "
             f"上唇抬{upper_lip_lift_mm:.0f}mm")
    return jd, info
