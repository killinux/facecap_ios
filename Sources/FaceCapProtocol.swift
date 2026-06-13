import ARKit
import simd

/// Face Cap (bannaflak) live mode OSC 协议。
/// 参考: https://www.bannaflak.com/face-cap/livemode.html
///
/// 地址表:
///   /HT  fff   头部位置 (cm)
///   /HR  fff   头部旋转 欧拉角 (度)
///   /HRQ ffff  头部旋转 四元数 (x,y,z,w)
///   /ELR ff    左眼旋转 (pitch, yaw, 度)
///   /ERR ff    右眼旋转 (pitch, yaw, 度)
///   /W   if    blendshape (索引, 权重 0~1)
///
/// Blender Faceit 的 Live Recorder 按这套地址解析，默认监听 UDP 9001。
enum FaceCapProtocol {

    /// Face Cap 协议规定的 52 个 blendshape 的索引顺序（0~51），
    /// 值为对应的 ARKit blendshape key。
    static let blendShapeOrder: [ARFaceAnchor.BlendShapeLocation] = [
        .browInnerUp,        // 00 browInnerUp
        .browDownLeft,       // 01 browDown_L
        .browDownRight,      // 02 browDown_R
        .browOuterUpLeft,    // 03 browOuterUp_L
        .browOuterUpRight,   // 04 browOuterUp_R
        .eyeLookUpLeft,      // 05 eyeLookUp_L
        .eyeLookUpRight,     // 06 eyeLookUp_R
        .eyeLookDownLeft,    // 07 eyeLookDown_L
        .eyeLookDownRight,   // 08 eyeLookDown_R
        .eyeLookInLeft,      // 09 eyeLookIn_L
        .eyeLookInRight,     // 10 eyeLookIn_R
        .eyeLookOutLeft,     // 11 eyeLookOut_L
        .eyeLookOutRight,    // 12 eyeLookOut_R
        .eyeBlinkLeft,       // 13 eyeBlink_L
        .eyeBlinkRight,      // 14 eyeBlink_R
        .eyeSquintLeft,      // 15 eyeSquint_L
        .eyeSquintRight,     // 16 eyeSquint_R
        .eyeWideLeft,        // 17 eyeWide_L
        .eyeWideRight,       // 18 eyeWide_R
        .cheekPuff,          // 19 cheekPuff
        .cheekSquintLeft,    // 20 cheekSquint_L
        .cheekSquintRight,   // 21 cheekSquint_R
        .noseSneerLeft,      // 22 noseSneer_L
        .noseSneerRight,     // 23 noseSneer_R
        .jawOpen,            // 24 jawOpen
        .jawForward,         // 25 jawForward
        .jawLeft,            // 26 jawLeft
        .jawRight,           // 27 jawRight
        .mouthFunnel,        // 28 mouthFunnel
        .mouthPucker,        // 29 mouthPucker
        .mouthLeft,          // 30 mouthLeft
        .mouthRight,         // 31 mouthRight
        .mouthRollUpper,     // 32 mouthRollUpper
        .mouthRollLower,     // 33 mouthRollLower
        .mouthShrugUpper,    // 34 mouthShrugUpper
        .mouthShrugLower,    // 35 mouthShrugLower
        .mouthClose,         // 36 mouthClose
        .mouthSmileLeft,     // 37 mouthSmile_L
        .mouthSmileRight,    // 38 mouthSmile_R
        .mouthFrownLeft,     // 39 mouthFrown_L
        .mouthFrownRight,    // 40 mouthFrown_R
        .mouthDimpleLeft,    // 41 mouthDimple_L
        .mouthDimpleRight,   // 42 mouthDimple_R
        .mouthUpperUpLeft,   // 43 mouthUpperUp_L
        .mouthUpperUpRight,  // 44 mouthUpperUp_R
        .mouthLowerDownLeft, // 45 mouthLowerDown_L
        .mouthLowerDownRight,// 46 mouthLowerDown_R
        .mouthPressLeft,     // 47 mouthPress_L
        .mouthPressRight,    // 48 mouthPress_R
        .mouthStretchLeft,   // 49 mouthStretch_L
        .mouthStretchRight,  // 50 mouthStretch_R
        .tongueOut,          // 51 tongueOut
    ]

    /// Face Cap 协议中 52 个 blendshape 的官方命名（与索引一一对应），导出时使用。
    static let blendShapeNames: [String] = [
        "browInnerUp", "browDown_L", "browDown_R", "browOuterUp_L", "browOuterUp_R",
        "eyeLookUp_L", "eyeLookUp_R", "eyeLookDown_L", "eyeLookDown_R",
        "eyeLookIn_L", "eyeLookIn_R", "eyeLookOut_L", "eyeLookOut_R",
        "eyeBlink_L", "eyeBlink_R", "eyeSquint_L", "eyeSquint_R", "eyeWide_L", "eyeWide_R",
        "cheekPuff", "cheekSquint_L", "cheekSquint_R", "noseSneer_L", "noseSneer_R",
        "jawOpen", "jawForward", "jawLeft", "jawRight",
        "mouthFunnel", "mouthPucker", "mouthLeft", "mouthRight",
        "mouthRollUpper", "mouthRollLower", "mouthShrugUpper", "mouthShrugLower", "mouthClose",
        "mouthSmile_L", "mouthSmile_R", "mouthFrown_L", "mouthFrown_R",
        "mouthDimple_L", "mouthDimple_R", "mouthUpperUp_L", "mouthUpperUp_R",
        "mouthLowerDown_L", "mouthLowerDown_R", "mouthPress_L", "mouthPress_R",
        "mouthStretch_L", "mouthStretch_R", "tongueOut",
    ]

    /// 把一帧面捕数据编码成 Face Cap 协议的 OSC bundle（一个 UDP 包）。
    static func encode(frame: FaceFrame) -> Data {
        var messages: [Data] = []
        messages.reserveCapacity(blendShapeOrder.count + 5)

        // 头部位置：ARKit 单位是米，Face Cap 用厘米
        let p = frame.headPosition
        messages.append(OSC.message("/HT", [
            .float32(p.x * 100), .float32(p.y * 100), .float32(p.z * 100),
        ]))

        // 头部旋转：欧拉角（度）+ 四元数
        let q = frame.headRotation
        let euler = eulerDegrees(from: q)
        messages.append(OSC.message("/HR", [
            .float32(euler.x), .float32(euler.y), .float32(euler.z),
        ]))
        messages.append(OSC.message("/HRQ", [
            .float32(q.imag.x), .float32(q.imag.y), .float32(q.imag.z), .float32(q.real),
        ]))

        // 左右眼旋转（pitch / yaw，度）
        let leftEye = eulerDegrees(from: frame.leftEyeRotation)
        let rightEye = eulerDegrees(from: frame.rightEyeRotation)
        messages.append(OSC.message("/ELR", [.float32(leftEye.x), .float32(leftEye.y)]))
        messages.append(OSC.message("/ERR", [.float32(rightEye.x), .float32(rightEye.y)]))

        // 52 个 blendshape
        for (index, value) in frame.shapes.enumerated() {
            messages.append(OSC.message("/W", [.int32(Int32(index)), .float32(value)]))
        }

        return OSC.bundle(messages)
    }

    /// 四元数 → 欧拉角（度），ZYX 顺序（roll→x, pitch→y, yaw→z）。
    static func eulerDegrees(from q: simd_quatf) -> SIMD3<Float> {
        let x = q.imag.x, y = q.imag.y, z = q.imag.z, w = q.real

        let sinrCosp = 2 * (w * x + y * z)
        let cosrCosp = 1 - 2 * (x * x + y * y)
        let roll = atan2f(sinrCosp, cosrCosp)

        let sinp = max(-1, min(1, 2 * (w * y - z * x)))
        let pitch = asinf(sinp)

        let sinyCosp = 2 * (w * z + x * y)
        let cosyCosp = 1 - 2 * (y * y + z * z)
        let yaw = atan2f(sinyCosp, cosyCosp)

        let toDeg = Float(180 / Double.pi)
        return SIMD3<Float>(roll * toDeg, pitch * toDeg, yaw * toDeg)
    }
}
