# 张嘴（jawOpen）通用工具

把不同 PMX「张嘴」表现不一致的问题，收敛成一个自动适配的工具：`tools/jaw_open.py`。
烘焙脚本 `bake_head_from_pmx.py` 调它，**新模型一般无需改代码**。

## 问题综述（为什么不能只烘元音 morph）

ARKit 的 `jawOpen` 通道要让头模张大嘴、露出牙/口腔。MMD 模型实现「张嘴」有两类机制，
直接把元音「あ」morph 烘成 jawOpen 会在一部分模型上失败：

| 类型 | 张嘴怎么实现 | 例子 | 只烘「あ」的结果 |
|------|------------|------|----------------|
| **A·元音自带开颌** | 「あ」morph 本身就拉开下颌 | Children / Office / Remake | 正常 ✅ |
| **B·骨骼驱动开颌** | 「あ」只是嘴型微调，张嘴靠**下颌骨** | AC（`head jaw`）/ inase（`Jaw Bone`） | 嘴张不开、不露牙 ❌ |

B 类的两个坑：
1. **嘴张不开**：元音 morph 几乎不动下颌（实测 AC「あ」嘴区下移 0.8mm、inase −0.1mm，
   而 A 类 1.8~2.3mm）。必须旋转模型自带的**下颌骨**才能开口。
2. **不露牙**：牙齿/口腔内壁是**蒙皮在下颌骨上**的几何，平时藏在闭合的嘴里。只有转下颌骨
   才会把它们带出来——顶点层面的程序化「撑开嘴唇」做不到（撑开了后面也是空的）。
3. **下唇内缘权重缺口（接缝）**：源模型给下颌骨刷权重时，下唇最内圈常漏掉一圈顶点
   （没绑到下颌骨）。纯转骨时这些「漏网点」不随颌下沉，在张开的上缘正中戳出小凸起
   ——表现为「上嘴唇中间和周围有一点差异」。需在唇缝以下局部平滑修补。

## 工具怎么做（`jaw_open.build_jaw_open`）

1. **判 A/B**：测元音「あ」在嘴区的平均下移。≥`deficient_mm`(默认 1.2mm) 判 A 类，
   直接沿用元音（返回 `None`）。
2. **找下颌骨**：按名匹配 `jaw / あご / 顎`，排除 `jaw upper…`（上颌/上齿），短名优先。
3. **自动选旋转轴**：在 3 轴 × 2 方向里试转 `angle`(默认 0.42rad)，挑「最让嘴区下沉」的。
4. **转骨捕捉**：用最优轴转下颌骨，capture 形变作 jawOpen——牙/口腔随之带出。
5. **补漏**：在「唇缝以下、贴嘴前部」的小盒区内对位移场做受限拉普拉斯平滑，填掉下唇内缘
   的权重缺口，**不碰上唇**（盒区外不动，唇缝边界保持锐利）。
6. **归一化**：把满 weight 最大张嘴位移缩到 `target_mm`(默认 14mm，对齐 Children 原生)。

坐标系全程 Blender 世界系（z-up、面朝 −Y），与 bake 的 `basis` 一致。

## 新模型怎么适配

正常情况**什么都不用改**，直接烘：

```bash
bash tools/bake_all_heads.sh          # 批烘全部
# 或单个：Blender --background --python tools/bake_head_from_pmx.py -- <PMX> <out_dir>
```

看日志 `JAW:` 行确认决策，例如：
```
JAW: vowel あ=2.1mm jaw_bones=['Jaw Bone'] -> 保留元音
JAW: vowel あ=0.8mm jaw_bones=['head jaw'] -> 下颌骨 head jaw axis=0 sign=1 raw=35mm 补漏787点 归一化14mm
```

需要微调时，改 `bake_head_from_pmx.py` 里对 `build_jaw_open()` 的传参（都有默认值）：
- `deficient_mm`：A/B 判定阈值。某模型该转骨却没转（或反之）时调。
- `angle`：试转角。开口太小/太大时调（之后还会被归一化，主要影响形状）。
- `target_mm`：满 weight 张嘴幅度。统一改所有骨骼驱动模型的张嘴大小。

## 排查工具

- **`tools/inspect_pmx.py`**：列某 PMX 的材质（找牙/口腔 `Mouth/teeth/歯`）、下颌骨、
  各 morph 的嘴区开口量。判一个新模型属 A 还是 B、有没有独立牙网格，先跑它：
  ```bash
  Blender --background --python tools/inspect_pmx.py -- <PMX>
  ```
- **离线渲染验证**（不用上真机先看一眼）：见 [[facecap-rebake-workflow]] 的「直连本地
  Blender」，对 FCH 的 jawOpen 加满 weight 渲染嘴部近摄；可把「动/不动」顶点染色成
  红/灰热力图，定位漏网静止点。

## 已知边界

- 若模型**既无开颌元音、又无下颌骨**：`build_jaw_open` 返回 `None`，由 `synth_morphs.py`
  的 `synth_jaw_open` 程序化兜底（撑开嘴唇，但**不会有牙**——模型本来也没有可带出的牙）。
- A 类模型完全不走本工具的骨骼路径，保持其原生「あ」效果，零回归。
- `inspect_pmx.py` 对极少数命名异常的下颌骨可能匹配不到，需在 `find_jaw_bones` 加别名。
