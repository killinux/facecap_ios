# FaceCap Streamer

仿 Face Cap（bannaflak）的 iOS 面部捕捉 App：用 ARKit 前置深度相机捕捉 52 个 blendshape + 头部/眼球姿态，按 **Face Cap live mode OSC 协议**通过 UDP 实时推送，可被 Blender 的 **Faceit** 插件（Live Recorder）直接接收驱动面部表情。

界面仿照 Face Cap 主界面：内置完整 3D 头模实时预览（从 MMD/PMX 模型烘焙，43 个 ARKit 表情通道 + 独立眼球节点驱动眼神，共覆盖 52 通道中的 51 个，仅 tongueOut 因无舌头网格缺省；头部位置实时反映远近/平移；无头模资源时回退 ARKit 面罩网格），底部功能键：

| 按钮 | 功能 |
|------|------|
| 录制 | 把面捕数据录到内存（帧序列） |
| 预览 | 在 3D 头模上循环回放录制内容（实况开启时同时推流到 Blender） |
| 校正 | 把当前头部姿态设为零点（/HT、/HR 归零基准） |
| 优化 | 对录制的表情曲线做 5 帧滑动平均平滑 |
| 导出 | 把录制内容导出为 CSV（52 通道 + 头部/眼球姿态）并分享 |
| 实况 | 开/关 OSC 推流（未配置目标时自动打开设置） |
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

`Resources/head.fch` 是从 MMD/PMX 模型烘焙的头模（当前为 Reika18_Children.pmx）。
更换模型：编辑 `tools/bake_head_from_pmx.py` 顶部的 `PMX` 路径，然后运行

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --python tools/bake_head_from_pmx.py
```

脚本流程：mmd_tools 导入 PMX → 绑定骨骼 morph 滑条 → 逐个表情烘焙顶点差量 →
按 MMD→ARKit 映射表（あ→jawOpen、ウィンク→eyeBlink、にやり→mouthSmile 左右拆分等）
生成 ARKit 通道 → 按颈部高度+材质裁出头部、左右眼球按眼骨拆分 → 写出 FCH 二进制 + 纹理
→ 调用 `tools/synth_morphs.py` 过程化补齐 PMX 缺失/错误的通道。

MMD 模型（如本例 Reika18 只有 19 个骨骼 morph）远不够 52 个 ARKit 通道，且个别
语义不符（「激怒」并不会让嘴角下垂）。`tools/synth_morphs.py` 按头模几何位置
过程化合成这些缺口：颧骨上提（cheekSquint）、上唇上提、鼻翼、撇嘴下垂（mouthFrown）、
鼓腮、抿唇、酒窝、嘴/下巴侧移前伸、闭唇、卷唇等共 20+ 个通道。该脚本幂等、可单独
运行（`python3 tools/synth_morphs.py Resources/head.fch`），不需重新烘焙整模。

FCH 布局：`"FCH1"` + uint32 JSON 长度 + JSON 元数据（objects/submeshes/morphs 及
缓冲区偏移）+ 二进制缓冲区（float32 位置/法线/UV、uint32 索引、稀疏 morph 差量）。
坐标已转为 SceneKit 约定（y-up，面朝 +Z，米）。

## 代码结构

```
Sources/
├── FaceCapStreamerApp.swift   # App 入口
├── FCHModel.swift             # FCH 自定义头模格式加载器（SCNMorpher）
├── ContentView.swift          # 仿 Face Cap 主界面：头模预览 + 按钮区
├── SettingsView.swift         # 设置页（IP/端口）+ 系统分享面板
├── HeadPreviewView.swift      # SceneKit 3D 头模预览（面部网格 + 眼球）
├── FaceCaptureEngine.swift    # ARKit 会话 + 录制/回放/校正/平滑/导出 + 推流
├── FaceFrame.swift            # 单帧面捕数据（捕捉/录制/回放/编码共用）
├── FaceCapProtocol.swift      # Face Cap 协议：blendshape 索引表 + 帧编码
├── OSCEncoder.swift           # 最小 OSC 1.0 编码器（message / bundle）
└── UDPSender.swift            # Network.framework UDP 客户端
```
