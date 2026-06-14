import ARKit
import SceneKit
import SwiftUI

/// 仿 Face Cap 的 3D 头模预览：优先加载内置 FCH 完整头模（SCNMorpher 驱动表情、
/// 眼球节点驱动视线、头部节点位置表现远近），无头模时回退 ARKit 面罩网格。
struct HeadPreviewView: UIViewRepresentable {

    let engine: FaceCaptureEngine
    /// 当前选中的头模 id（HeadCatalog.Head.id）。变化时热切换模型。
    let selectedHead: String

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        view.scene = context.coordinator.scene
        view.backgroundColor = UIColor(white: 0.18, alpha: 1)
        view.antialiasingMode = .multisampling4X
        view.rendersContinuously = true
        view.isUserInteractionEnabled = false

        let coordinator = context.coordinator
        engine.onFrame = { [weak coordinator] frame, geometry in
            coordinator?.apply(frame: frame, geometry: geometry)
        }
        coordinator.setHead(selectedHead)
        return view
    }

    func updateUIView(_ uiView: SCNView, context: Context) {
        context.coordinator.setHead(selectedHead)
    }

    final class Coordinator {

        let scene = SCNScene()
        private let headNode = SCNNode()

        // FCH 完整头模
        private var currentHeadID: String?
        private var modelRoot: SCNNode?
        private var morpher: SCNMorpher?
        /// Face Cap 索引 → morph target 下标（无对应通道为 -1）
        private var shapeToTarget: [Int] = []
        private var eyeLeftNode: SCNNode?
        private var eyeRightNode: SCNNode?

        // 回退：ARKit 面罩
        private var maskRoot: SCNNode?
        private var maskGeometry: ARSCNFaceGeometry?
        private var maskEyeLeft: SCNNode?
        private var maskEyeRight: SCNNode?

        init() {
            scene.background.contents = UIColor(white: 0.18, alpha: 1)

            let camera = SCNCamera()
            camera.fieldOfView = 30
            camera.zNear = 0.01
            let cameraNode = SCNNode()
            cameraNode.camera = camera
            cameraNode.position = SCNVector3(0, 0, 0.55)
            scene.rootNode.addChildNode(cameraNode)

            let keyLight = SCNLight()
            keyLight.type = .directional
            keyLight.intensity = 900
            let keyNode = SCNNode()
            keyNode.light = keyLight
            keyNode.eulerAngles = SCNVector3(-0.3, 0.25, 0)
            scene.rootNode.addChildNode(keyNode)

            let ambient = SCNLight()
            ambient.type = .ambient
            ambient.intensity = 450
            let ambientNode = SCNNode()
            ambientNode.light = ambient
            scene.rootNode.addChildNode(ambientNode)

            scene.rootNode.addChildNode(headNode)
        }

        // MARK: - FCH 头模切换

        /// 切到指定 id 的头模；与当前相同则忽略。加载失败时保留当前头模，
        /// 若从未成功加载过任何头模则回退 ARKit 面罩。
        func setHead(_ id: String) {
            guard id != currentHeadID else { return }
            if loadHead(id: id) {
                currentHeadID = id
                removeMaskFallback()
            } else if currentHeadID == nil && maskRoot == nil {
                setupMaskFallback()
            }
        }

        private func loadHead(id: String) -> Bool {
            guard let head = HeadCatalog.head(id: id),
                  let model = try? FCHModel.load(
                    from: head.fchURL, texturesDir: head.texturesDir)
            else { return false }

            modelRoot?.removeFromParentNode()
            headNode.addChildNode(model.rootNode)
            modelRoot = model.rootNode
            morpher = model.morpher
            eyeLeftNode = model.eyeLeftNode
            eyeRightNode = model.eyeRightNode

            // Face Cap 索引 → morph target 下标映射表
            shapeToTarget = FaceCapProtocol.blendShapeOrder.map {
                model.morphTargetIndex[$0.rawValue] ?? -1
            }
            return true
        }

        // MARK: - ARKit 面罩回退

        private func removeMaskFallback() {
            maskRoot?.removeFromParentNode()
            maskRoot = nil
            maskGeometry = nil
            maskEyeLeft = nil
            maskEyeRight = nil
        }

        private func setupMaskFallback() {
            guard let device = MTLCreateSystemDefaultDevice(),
                  let geometry = ARSCNFaceGeometry(device: device, fillMesh: false)
            else { return }
            let material = geometry.firstMaterial
            material?.lightingModel = .physicallyBased
            material?.diffuse.contents = UIColor(white: 0.72, alpha: 1)
            material?.roughness.contents = 0.88
            maskGeometry = geometry

            let root = SCNNode()
            root.addChildNode(SCNNode(geometry: geometry))
            maskEyeLeft = Self.makeEyeball()
            maskEyeRight = Self.makeEyeball()
            root.addChildNode(maskEyeLeft!)
            root.addChildNode(maskEyeRight!)
            headNode.addChildNode(root)
            maskRoot = root
        }

        // MARK: - 每帧更新

        func apply(frame: FaceFrame, geometry: ARFaceGeometry?) {
            // 头部姿态：旋转 + 位移（xy 限 ±15cm 防出画面，z 放宽体现远近）
            headNode.simdOrientation = frame.headRotation
            headNode.simdPosition = simd_clamp(
                frame.previewPosition,
                SIMD3(-0.15, -0.15, -0.30), SIMD3(0.15, 0.15, 0.25))

            if let morpher {
                for (shapeIndex, targetIndex) in shapeToTarget.enumerated()
                where targetIndex >= 0 {
                    morpher.setWeight(
                        CGFloat(frame.shapes[shapeIndex]), forTargetAt: targetIndex)
                }
                eyeLeftNode?.simdOrientation = frame.leftEyeRotation
                eyeRightNode?.simdOrientation = frame.rightEyeRotation
            } else {
                if let geometry, let maskGeometry {
                    maskGeometry.update(from: geometry)
                }
                maskEyeLeft?.simdPosition = frame.leftEyePosition
                maskEyeLeft?.simdOrientation = frame.leftEyeRotation
                maskEyeRight?.simdPosition = frame.rightEyePosition
                maskEyeRight?.simdOrientation = frame.rightEyeRotation
            }
        }

        private static func makeEyeball() -> SCNNode {
            let eyeball = SCNSphere(radius: 0.0115)
            eyeball.segmentCount = 32
            let white = SCNMaterial()
            white.lightingModel = .physicallyBased
            white.diffuse.contents = UIColor(white: 0.92, alpha: 1)
            white.roughness.contents = 0.35
            eyeball.firstMaterial = white
            let node = SCNNode(geometry: eyeball)

            let iris = SCNSphere(radius: 0.0045)
            iris.segmentCount = 24
            let irisMaterial = SCNMaterial()
            irisMaterial.lightingModel = .constant
            irisMaterial.diffuse.contents = UIColor(white: 0.35, alpha: 1)
            iris.firstMaterial = irisMaterial
            let irisNode = SCNNode(geometry: iris)
            irisNode.position = SCNVector3(0, 0, 0.0095)
            node.addChildNode(irisNode)

            return node
        }
    }
}
