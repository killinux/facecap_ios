import ARKit
import simd

/// 一帧面捕数据，捕捉 / 录制 / 回放 / OSC 推流共用。
struct FaceFrame {
    /// 相对录制起点的时间（秒）；实时帧为捕捉时刻。
    var time: TimeInterval
    /// 52 个 blendshape 权重，按 Face Cap 索引顺序。
    var shapes: [Float]
    /// 头部变换（世界空间；校正后为相对校正姿态）。
    var headTransform: simd_float4x4
    var leftEyeRotation: simd_quatf
    var rightEyeRotation: simd_quatf
    var leftEyePosition: SIMD3<Float>
    var rightEyePosition: SIMD3<Float>
    /// 3D 预览用的头部位移（相对基准点，由引擎填充），表现远近/平移。
    var previewPosition: SIMD3<Float> = .zero

    /// 竖屏修正：ARKit 相机坐标系原生为横屏（landscape-right 基准，固有朝向为横躺 90°），
    /// 绕视线轴 z 旋转 -90° 转正，使竖屏正对相机时头部姿态为单位旋转（正立正脸）。
    /// 真机验证：0°→横躺、+90°→上下颠倒、-90°→正立。
    private static let portraitFix = simd_float4x4(
        simd_quatf(angle: -.pi / 2, axis: SIMD3(0, 0, 1)))

    init(anchor: ARFaceAnchor, cameraTransform: simd_float4x4?, time: TimeInterval) {
        self.time = time
        let dict = anchor.blendShapes
        shapes = FaceCapProtocol.blendShapeOrder.map { dict[$0]?.floatValue ?? 0 }
        if let camera = cameraTransform {
            // 相机参考系（Face Cap 行为）：正视摄像头 = 零旋转，
            // 手机靠近/远离同样反映为位置变化
            headTransform = Self.portraitFix * camera.inverse * anchor.transform
        } else {
            headTransform = anchor.transform
        }
        leftEyeRotation = simd_quatf(anchor.leftEyeTransform)
        rightEyeRotation = simd_quatf(anchor.rightEyeTransform)
        let l = anchor.leftEyeTransform.columns.3
        let r = anchor.rightEyeTransform.columns.3
        leftEyePosition = SIMD3(l.x, l.y, l.z)
        rightEyePosition = SIMD3(r.x, r.y, r.z)
    }

    var headPosition: SIMD3<Float> {
        let c = headTransform.columns.3
        return SIMD3(c.x, c.y, c.z)
    }

    var headRotation: simd_quatf { simd_quatf(headTransform) }

    /// 用于 ARFaceGeometry(blendShapes:) 合成回放网格。
    var blendShapeDictionary: [ARFaceAnchor.BlendShapeLocation: NSNumber] {
        var d = [ARFaceAnchor.BlendShapeLocation: NSNumber](minimumCapacity: shapes.count)
        for (i, key) in FaceCapProtocol.blendShapeOrder.enumerated() {
            d[key] = NSNumber(value: shapes[i])
        }
        return d
    }
}
