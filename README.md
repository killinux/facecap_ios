# FaceCap Streamer

仿 Face Cap（bannaflak）的 iOS 面部捕捉 App：用 ARKit 前置深度相机捕捉 52 个 blendshape + 头部/眼球姿态，按 **Face Cap live mode OSC 协议**通过 UDP 实时推送，可被 Blender 的 **Faceit** 插件（Live Recorder）直接接收驱动面部表情。

界面仿照 Face Cap 主界面：内置完整 3D 头模实时预览（从 MMD/PMX 模型烘焙，**52/52 ARKit 通道全覆盖**——44 个顶点 morph 通道 + 8 个眼神由独立眼球节点驱动；含模型自带真舌头 tongueOut；头部位置实时反映远近/平移；无头模资源时回退 ARKit 面罩网格）。内置 **5 个可切换头模**（Children/Office/AC/inase/Remake，主界面「头模」键切换）。渲染采用三点布光 + 环境光 IBL + HDR 色调映射、分部位 PBR 材质、脸部法线贴图与眼球高光。底部功能键：

| 按钮 | 功能 |
|------|------|
| 录制 | 把面捕数据录到内存（帧序列） |
| 预览 | 在 3D 头模上循环回放录制内容（实况开启时同时推流到 Blender） |
| 校正 | 把当前头部姿态设为零点，并记录闭口 jawOpen 基线（**放松闭口时点一次**，头模才能闭严） |
| 优化 | 对录制的表情曲线做 5 帧滑动平均平滑 |
| 导出 | 把录制内容导出为 CSV（52 通道 + 头部/眼球姿态）并分享 |
| 实况 | 开/关 OSC 推流（未配置目标时自动打开设置） |
| 头模 | 在 5 个内置头模之间切换（即时生效，记住上次选择） |
| 全屏 | 隐藏控制面板，点击屏幕任意处恢复 |
| 设置 | 配置 Blender 主机 IP 与端口（默认 9001） |

## 协议（与 Face Cap 完全一致）

每帧发送一个 OSC bundle（UDP），包含：

| 地址 | 参数 | 含义 |
|------|------|------|
| `/HT` | fff | 头部位置 x,y,z（厘米） |
| `/HR` | fff | 头部旋转欧拉角 x,y,z（度） |
| `/HRQ` | ffff | 头部旋转四元数 x,y,z,w |
| `/ELR` | ff | 左眼旋转 pitch,yaw（度） |
| `/ERR` | ff | 右眼旋转 pitch,yaw（度） |
| `/W` | if | blendshape（索引 0–51，权重 0~1） |

52 个 blendshape 的索引顺序按 Face Cap 官方文档（0=browInnerUp … 51=tongueOut），定义见 `Sources/FaceCapProtocol.swift`。

## 构建

需要 Xcode 和 [xcodegen](https://github.com/yonas-kanyo/XcodeGen)（`brew install xcodegen`）：

```bash
xcodegen generate
open FaceCapStreamer.xcodeproj
```

在 Xcode 中选择你的开发者 Team（Signing & Capabilities），连接真机运行。
**必须使用支持面部追踪的真机**（iPhone X 及以后），模拟器不支持 ARKit 面捕。

## 配合 Blender Faceit 使用

1. 手机和电脑连同一个局域网。
2. Blender 中安装 Faceit，完成角色注册和 ARKit 表情生成（52 个 shape key）。
3. Faceit → **Mocap** 面板 → Live Recorder，来源选 **Face Cap**，端口保持默认 **9001**，点击 *Connect / Start Listening*。
4. 查看电脑的局域网 IP（macOS：`ipconfig getifaddr en0`）。
5. 在 App 里填入电脑 IP 和端口 9001，点「开始发送到 Blender」。
6. 首次发送时 iOS 会弹出"本地网络"权限请求，必须允许。

Faceit 端可在接收设置里调整头部旋转/位置的轴向与缩放；如果方向镜像，优先在 Faceit 侧翻转对应轴。

## 自定义头模（FCH 格式）

头模放在 `Resources/heads/<id>/`，每个子目录一份 `head.fch` + 自带纹理（独立子目录避免
跨模型纹理重名压平）。App 用 `HeadCatalog` 扫描该目录自动列出，「头模」键切换。`project.yml`
把 `heads/` 设为文件夹引用以保留子目录结构。

烘焙全部头模：

```bash
bash tools/bake_all_heads.sh   # 把 tools/bake_all_heads.sh 里列的多个 PMX 各烘到 heads/<id>/
# 单个：Blender --background --python tools/bake_head_from_pmx.py -- <PMX路径> <输出目录>
```

`tools/bake_head_from_pmx.py` 流程：mmd_tools 导入 PMX → 绑定骨骼 morph 滑条 → 烘焙顶点
差量 → 按 MMD→ARKit 映射生成通道 → 处理 jawOpen（见下）→ 裁头部 + 左右眼球拆分 →
提取漫反射/法线纹理 → 写 FCH → 调 `tools/synth_morphs.py` 过程化补齐缺失通道。

- **`tools/synth_morphs.py`**：MMD 模型骨骼 morph 远不够 52 通道且个别语义不符，按头模
  几何过程化合成颧骨/上唇/鼻翼/撇嘴/鼓腮/抿唇/酒窝/嘴下巴侧移/闭唇/卷唇等 20+ 通道。
  幂等、可单独运行（`python3 tools/synth_morphs.py Resources/heads/<id>/head.fch`）。
- **`tools/jaw_open.py`** + **`tools/JAW_OPEN.md`**：通用「张嘴」生成器。有的 PMX 张嘴是
  骨骼驱动（元音 morph 不开颌、牙蒙皮在下颌骨上）→ 自动判别后转模型自带下颌骨生成
  jawOpen 露真牙，并补下唇内缘权重缺口、抗嘴角撕裂、动态测唇线、上唇抬升露门牙。新模型免改代码。
- **法线贴图**：按 `_D→_N` 命名提取；脸皮漫反射常被换怪名贴图但都是 Genesis 8 标准 UV，
  兜底用源里的 `Face_N`。FCH submesh 存 `normal` 字段，`FCHModel` 加载为 `material.normal`。
- **`tools/inspect_pmx.py`**：排查某 PMX 的嘴/牙材质、下颌骨、各 morph 开口量。

FCH 布局：`"FCH1"` + uint32 JSON 长度 + JSON 元数据（objects/submeshes/morphs、纹理名、
缓冲区偏移）+ 二进制缓冲区（float32 位置/法线/UV、uint32 索引、稀疏 morph 差量）。
坐标已转为 SceneKit 约定（y-up，面朝 +Z，米）。

## 代码结构

```
Sources/
├── FaceCapStreamerApp.swift   # App 入口
├── FCHModel.swift             # FCH 头模加载器（SCNMorpher + PBR 材质/法线/眼球高光）
├── HeadCatalog.swift          # 扫描 Resources/heads/ 列出可切换头模
├── ContentView.swift          # 仿 Face Cap 主界面：头模预览 + 按钮区 + 头模选择
├── SettingsView.swift         # 设置页（IP/端口）+ 系统分享面板
├── HeadPreviewView.swift      # SceneKit 3D 头模预览（三点布光/IBL/HDR + 热切换头模）
├── FaceCaptureEngine.swift    # ARKit 会话 + 录制/回放/校正(含闭口基线)/平滑/导出 + 推流
├── FaceFrame.swift            # 单帧面捕数据（捕捉/录制/回放/编码共用）
├── FaceCapProtocol.swift      # Face Cap 协议：blendshape 索引表 + 帧编码
├── OSCEncoder.swift           # 最小 OSC 1.0 编码器（message / bundle）
└── UDPSender.swift            # Network.framework UDP 客户端

tools/                         # 头模烘焙工具链（Blender + Python）
├── bake_head_from_pmx.py      # PMX → FCH 主烘焙脚本
├── bake_all_heads.sh          # 批量烘焙多个 PMX → heads/<id>/
├── synth_morphs.py            # 过程化补齐缺失的 ARKit 通道
├── jaw_open.py / JAW_OPEN.md  # 通用张嘴生成器 + 说明
└── inspect_pmx.py             # 排查 PMX 的嘴/牙/下颌骨/morph
```
