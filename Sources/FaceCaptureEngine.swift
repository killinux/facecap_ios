import ARKit
import Combine
import Foundation
import QuartzCore

/// 管理 ARKit 面部追踪、录制/回放、校正，以及 Face Cap 协议 OSC 推流。
final class FaceCaptureEngine: NSObject, ObservableObject, ARSessionDelegate {

    @Published var faceTracked = false
    @Published var isStreaming = false
    @Published var isRecording = false
    @Published var isPreviewing = false
    @Published var hasRecording = false
    @Published var fps: Int = 0
    @Published var statusText: String?

    let session = ARSession()

    /// 每帧回调，驱动 3D 头模预览。geometry 为 nil 时由接收方按 blendshape 合成。
    var onFrame: ((FaceFrame, ARFaceGeometry?) -> Void)?

    private var sender: UDPSender?
    private var calibrationRef: simd_float4x4?
    private var lastRawTransform: simd_float4x4?

    // jawOpen 闭口基线：ARKit 即使闭口也持续报小幅 jawOpen（下巴没咬死），直接用会让头模
    // 嘴闭不严。减去「闭口时的基线」让其能闭实。校正(校正按钮)时捕获当前值为基线，自适应
    // 每人/每次坐姿；未校正时用默认值兜底。
    private let jawOpenIdx = FaceCapProtocol.blendShapeOrder.firstIndex(of: .jawOpen)
    private var jawOpenBaseline: Float = 0.10
    private var lastJawOpenRaw: Float = 0
    /// 基线之上再留的小死区，吸收抖动；阈值 = 基线 + 此值。
    private static let jawResidualDeadzone: Float = 0.04
    /// 3D 预览的位置基准（首帧自动捕获；校正后归零）
    private var previewOrigin: SIMD3<Float>?

    private var recordedFrames: [FaceFrame] = []
    private var recordStart: CFTimeInterval = 0

    private var playbackLink: CADisplayLink?
    private var playbackStart: CFTimeInterval = 0
    private var playbackIndex = 0

    private var frameCount = 0
    private var fpsWindowStart = CFAbsoluteTimeGetCurrent()

    var isSupported: Bool { ARFaceTrackingConfiguration.isSupported }

    override init() {
        super.init()
        session.delegate = self // 默认派发到主队列
    }

    // MARK: - 追踪

    func startTracking() {
        guard isSupported else {
            statusText = "此设备不支持 ARKit 面部追踪（需要原深感摄像头或 A12+ 芯片）"
            return
        }
        let config = ARFaceTrackingConfiguration()
        config.maximumNumberOfTrackedFaces = 1
        session.run(config, options: [.resetTracking, .removeExistingAnchors])
    }

    func stopTracking() {
        session.pause()
    }

    // MARK: - 校正：把当前头部姿态设为零点

    func calibrate() {
        guard let raw = lastRawTransform else {
            statusText = "未检测到面部，无法校正"
            return
        }
        calibrationRef = raw
        previewOrigin = .zero // 校正后帧数据已是相对零点
        // 把当前（应为放松闭口）的 jawOpen 设为闭口基线，之后逐帧减去 → 头模能闭严。
        jawOpenBaseline = min(0.5, max(0, lastJawOpenRaw))
        statusText = "已校正：头部姿态归零，闭口基线已记录"
    }

    // MARK: - 实况（OSC 推流）

    func startStreaming(host: String, port: UInt16) {
        sender?.cancel()
        guard let newSender = UDPSender(host: host, port: port) else {
            statusText = "无效的目标地址 \(host):\(port)"
            return
        }
        sender = newSender
        statusText = "实况中 → \(host):\(port)"
        isStreaming = true
    }

    func stopStreaming() {
        sender?.cancel()
        sender = nil
        isStreaming = false
        statusText = nil
    }

    // MARK: - 录制 / 预览回放

    func toggleRecording() {
        if isRecording {
            isRecording = false
            hasRecording = !recordedFrames.isEmpty
            statusText = "录制完成：\(recordedFrames.count) 帧"
        } else {
            stopPreview()
            recordedFrames = []
            recordStart = CACurrentMediaTime()
            isRecording = true
            statusText = "录制中…"
        }
    }

    func togglePreview() {
        if isPreviewing {
            stopPreview()
        } else {
            startPreview()
        }
    }

    private func startPreview() {
        guard !recordedFrames.isEmpty else {
            statusText = "还没有录制内容"
            return
        }
        if isRecording { toggleRecording() }
        isPreviewing = true
        playbackIndex = 0
        playbackStart = CACurrentMediaTime()
        let link = CADisplayLink(target: self, selector: #selector(playbackTick))
        link.add(to: .main, forMode: .common)
        playbackLink = link
        statusText = "回放中（循环）"
    }

    func stopPreview() {
        playbackLink?.invalidate()
        playbackLink = nil
        if isPreviewing {
            isPreviewing = false
            statusText = nil
        }
    }

    @objc private func playbackTick() {
        guard let last = recordedFrames.last else {
            stopPreview()
            return
        }
        let t = CACurrentMediaTime() - playbackStart
        if t > last.time {
            // 循环播放
            playbackStart = CACurrentMediaTime()
            playbackIndex = 0
            return
        }
        while playbackIndex + 1 < recordedFrames.count,
              recordedFrames[playbackIndex + 1].time <= t {
            playbackIndex += 1
        }
        var frame = recordedFrames[playbackIndex]
        frame.previewPosition = frame.headPosition - recordedFrames[0].headPosition
        onFrame?(frame, ARFaceGeometry(blendShapes: frame.blendShapeDictionary))
        if isStreaming {
            sender?.send(FaceCapProtocol.encode(frame: frame))
        }
    }

    // MARK: - 优化：对录制结果做滑动平均平滑

    func optimizeRecording() {
        guard recordedFrames.count > 4 else {
            statusText = "录制内容太短，无法优化"
            return
        }
        let source = recordedFrames
        let radius = 2 // 5 帧窗口
        for i in source.indices {
            let lo = max(0, i - radius), hi = min(source.count - 1, i + radius)
            let window = source[lo...hi]
            let n = Float(window.count)
            var shapes = [Float](repeating: 0, count: source[i].shapes.count)
            for f in window {
                for (k, v) in f.shapes.enumerated() { shapes[k] += v }
            }
            recordedFrames[i].shapes = shapes.map { $0 / n }
        }
        statusText = "已优化：表情曲线平滑完成"
    }

    // MARK: - 导出 CSV

    func exportRecording() -> URL? {
        guard !recordedFrames.isEmpty else {
            statusText = "还没有录制内容"
            return nil
        }
        var lines: [String] = []
        let header = (["time"] + FaceCapProtocol.blendShapeNames
            + ["headPosX_cm", "headPosY_cm", "headPosZ_cm",
               "headRotX_deg", "headRotY_deg", "headRotZ_deg",
               "eyeL_pitch", "eyeL_yaw", "eyeR_pitch", "eyeR_yaw"]).joined(separator: ",")
        lines.append(header)

        for f in recordedFrames {
            var cols = [String(format: "%.4f", f.time)]
            cols += f.shapes.map { String(format: "%.4f", $0) }
            let p = f.headPosition
            cols += [p.x * 100, p.y * 100, p.z * 100].map { String(format: "%.2f", $0) }
            let e = FaceCapProtocol.eulerDegrees(from: f.headRotation)
            cols += [e.x, e.y, e.z].map { String(format: "%.2f", $0) }
            let l = FaceCapProtocol.eulerDegrees(from: f.leftEyeRotation)
            let r = FaceCapProtocol.eulerDegrees(from: f.rightEyeRotation)
            cols += [l.x, l.y, r.x, r.y].map { String(format: "%.2f", $0) }
            lines.append(cols.joined(separator: ","))
        }

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("facecap_take.csv")
        do {
            try lines.joined(separator: "\n").write(to: url, atomically: true, encoding: .utf8)
            return url
        } catch {
            statusText = "导出失败：\(error.localizedDescription)"
            return nil
        }
    }

    // MARK: - ARSessionDelegate

    func session(_ session: ARSession, didUpdate anchors: [ARAnchor]) {
        guard let face = anchors.compactMap({ $0 as? ARFaceAnchor }).first else { return }

        if face.isTracked != faceTracked {
            faceTracked = face.isTracked
        }
        guard face.isTracked else { return }

        var frame = FaceFrame(
            anchor: face,
            cameraTransform: session.currentFrame?.camera.transform,
            time: CACurrentMediaTime())
        lastRawTransform = frame.headTransform // 校正基准与帧同处相机参考系

        // jawOpen 闭口基线扣除：减去基线 + 小死区，并把剩余区间平滑重映射回 [0,1]，
        // 闭口时归零（闭严），正常张嘴基本不受影响。预览/录制/推流统一在此处理。
        if let j = jawOpenIdx {
            lastJawOpenRaw = frame.shapes[j]
            let t = min(0.6, jawOpenBaseline + Self.jawResidualDeadzone)
            frame.shapes[j] = max(0, (frame.shapes[j] - t) / (1 - t))
        }
        if let ref = calibrationRef {
            frame.headTransform = ref.inverse * frame.headTransform
        }
        if previewOrigin == nil {
            previewOrigin = frame.headPosition
        }
        frame.previewPosition = frame.headPosition - (previewOrigin ?? .zero)

        if isRecording {
            var recorded = frame
            recorded.time = CACurrentMediaTime() - recordStart
            recordedFrames.append(recorded)
        }
        // 回放时 3D 预览和推流交给回放驱动
        guard !isPreviewing else { return }

        onFrame?(frame, face.geometry)
        if isStreaming {
            sender?.send(FaceCapProtocol.encode(frame: frame))
        }
        tickFPS()
    }

    func session(_ session: ARSession, didFailWithError error: Error) {
        statusText = error.localizedDescription
    }

    private func tickFPS() {
        frameCount += 1
        let now = CFAbsoluteTimeGetCurrent()
        let elapsed = now - fpsWindowStart
        if elapsed >= 1 {
            fps = Int((Double(frameCount) / elapsed).rounded())
            frameCount = 0
            fpsWindowStart = now
        }
    }
}
