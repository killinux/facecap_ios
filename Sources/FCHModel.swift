import Foundation
import SceneKit
import UIKit

/// FCH (FaceCap Head) 自定义头模格式加载器。
/// 文件布局：magic "FCH1" + uint32 JSON长度 + JSON元数据 + 二进制缓冲区。
/// JSON 描述若干 object（Head / EyeLeft / EyeRight），Head 带 ARKit 命名的
/// 稀疏 morph 差量，加载后转成 SCNMorpher 的完整 morph target。
enum FCHModel {

    struct LoadedModel {
        let rootNode: SCNNode
        let morpher: SCNMorpher?
        /// ARKit blendshape 名（如 "eyeBlinkLeft"）→ morph target 下标
        let morphTargetIndex: [String: Int]
        let eyeLeftNode: SCNNode?
        let eyeRightNode: SCNNode?
    }

    // MARK: - JSON 结构

    private struct Manifest: Decodable {
        let version: Int
        let objects: [Object]
    }

    private struct BufferRef: Decodable {
        let offset: Int
        let count: Int
    }

    private struct Submesh: Decodable {
        let name: String
        let texture: String?
        let normal: String?   // 可选，旧 FCH 无此字段时解码为 nil
        let transparent: Bool
        let indices: BufferRef
    }

    private struct Morph: Decodable {
        let name: String
        let vertexIndices: BufferRef
        let deltas: BufferRef
    }

    private struct Object: Decodable {
        let name: String
        let position: [Float]
        let vertexCount: Int
        let positions: BufferRef
        let normals: BufferRef
        let uvs: BufferRef
        let submeshes: [Submesh]
        let morphs: [Morph]
    }

    // MARK: - 加载

    static func load(from url: URL, texturesDir: URL) throws -> LoadedModel {
        let data = try Data(contentsOf: url)
        guard data.count > 8, data.prefix(4) == Data("FCH1".utf8) else {
            throw CocoaError(.fileReadCorruptFile)
        }
        let jsonLength = data.subdata(in: 4..<8).withUnsafeBytes {
            Int($0.loadUnaligned(as: UInt32.self).littleEndian)
        }
        let manifest = try JSONDecoder().decode(
            Manifest.self, from: data.subdata(in: 8..<(8 + jsonLength)))
        let blob = data.subdata(in: (8 + jsonLength)..<data.count)

        func floats(_ ref: BufferRef) -> [Float] {
            blob.subdata(in: ref.offset..<(ref.offset + ref.count * 4)).withUnsafeBytes {
                Array($0.bindMemory(to: Float.self))
            }
        }
        func uint32s(_ ref: BufferRef) -> [UInt32] {
            blob.subdata(in: ref.offset..<(ref.offset + ref.count * 4)).withUnsafeBytes {
                Array($0.bindMemory(to: UInt32.self))
            }
        }

        let root = SCNNode()
        var morpher: SCNMorpher?
        var morphIndex: [String: Int] = [:]
        var eyeLeft: SCNNode?
        var eyeRight: SCNNode?

        for object in manifest.objects {
            let node = try buildNode(
                object: object, texturesDir: texturesDir,
                floats: floats, uint32s: uint32s)
            node.position = SCNVector3(
                object.position[0], object.position[1], object.position[2])
            root.addChildNode(node)

            switch object.name {
            case "EyeLeft": eyeLeft = node
            case "EyeRight": eyeRight = node
            default:
                if !object.morphs.isEmpty {
                    let (m, index) = buildMorpher(
                        object: object, floats: floats, uint32s: uint32s)
                    node.morpher = m
                    morpher = m
                    morphIndex = index
                }
            }
        }

        return LoadedModel(
            rootNode: root, morpher: morpher, morphTargetIndex: morphIndex,
            eyeLeftNode: eyeLeft, eyeRightNode: eyeRight)
    }

    // MARK: - 几何构建

    private static func buildNode(
        object: Object, texturesDir: URL,
        floats: (BufferRef) -> [Float], uint32s: (BufferRef) -> [UInt32]
    ) throws -> SCNNode {
        let positions = floats(object.positions)
        let normals = floats(object.normals)
        var uvs = floats(object.uvs)
        // Blender UV 原点在左下，SceneKit 贴图原点在左上：翻转 V
        for i in stride(from: 1, to: uvs.count, by: 2) {
            uvs[i] = 1 - uvs[i]
        }

        let vertexSource = geometrySource(positions, semantic: .vertex, perVector: 3)
        let normalSource = geometrySource(normals, semantic: .normal, perVector: 3)
        let uvSource = geometrySource(uvs, semantic: .texcoord, perVector: 2)

        var elements: [SCNGeometryElement] = []
        var materials: [SCNMaterial] = []
        for submesh in object.submeshes {
            let indices = uint32s(submesh.indices)
            let element = SCNGeometryElement(
                data: indices.withUnsafeBufferPointer { Data(buffer: $0) },
                primitiveType: .triangles,
                primitiveCount: indices.count / 3,
                bytesPerIndex: 4)
            elements.append(element)
            materials.append(makeMaterial(submesh: submesh, texturesDir: texturesDir))
        }

        let geometry = SCNGeometry(
            sources: [vertexSource, normalSource, uvSource], elements: elements)
        geometry.materials = materials
        return SCNNode(geometry: geometry)
    }

    private static func buildMorpher(
        object: Object,
        floats: (BufferRef) -> [Float], uint32s: (BufferRef) -> [UInt32]
    ) -> (SCNMorpher, [String: Int]) {
        let morpher = SCNMorpher()
        morpher.calculationMode = .additive
        morpher.unifiesNormals = true

        var index: [String: Int] = [:]
        var targets: [SCNGeometry] = []
        for morph in object.morphs {
            let vertexIndices = uint32s(morph.vertexIndices)
            let deltas = floats(morph.deltas)
            // additive 模式下 target 是纯差量：未参与的顶点为 0
            var positions = [Float](repeating: 0, count: object.vertexCount * 3)
            for (k, vi) in vertexIndices.enumerated() {
                let base = Int(vi) * 3
                positions[base] = deltas[k * 3]
                positions[base + 1] = deltas[k * 3 + 1]
                positions[base + 2] = deltas[k * 3 + 2]
            }
            let target = SCNGeometry(
                sources: [geometrySource(positions, semantic: .vertex, perVector: 3)],
                elements: [])
            index[normalizedName(morph.name)] = targets.count
            targets.append(target)
        }
        morpher.targets = targets
        return (morpher, index)
    }

    /// 统一 morph 命名为 ARKit rawValue 风格（eyeBlinkLeft → eyeBlink_L），
    /// 兼容两种命名的 FCH 资产。
    /// 注意：jawLeft/jawRight/mouthLeft/mouthRight 是「方向」通道，ARKit rawValue
    /// 保留驼峰（不是 _L/_R 的左右成对通道），这里原样透传，否则会错拆成 jaw_L 等
    /// 而匹配不上。
    private static func normalizedName(_ name: String) -> String {
        switch name {
        case "jawLeft", "jawRight", "mouthLeft", "mouthRight": return name
        default: break
        }
        if name.hasSuffix("Left") { return String(name.dropLast(4)) + "_L" }
        if name.hasSuffix("Right") { return String(name.dropLast(5)) + "_R" }
        return name
    }

    private static func geometrySource(
        _ values: [Float], semantic: SCNGeometrySource.Semantic, perVector: Int
    ) -> SCNGeometrySource {
        SCNGeometrySource(
            data: values.withUnsafeBufferPointer { Data(buffer: $0) },
            semantic: semantic,
            vectorCount: values.count / perVector,
            usesFloatComponents: true,
            componentsPerVector: perVector,
            bytesPerComponent: 4,
            dataOffset: 0,
            dataStride: perVector * 4)
    }

    /// 是否眼球材质（排除睫毛/眉毛/眼影）。
    private static func isEyeball(_ name: String) -> Bool {
        let n = name.lowercased()
        return n.contains("eye") && !n.contains("lash") && !n.contains("brow")
            && !n.contains("shadow")
    }

    /// 按部位选粗糙度：眼球湿润高光、牙齿/口腔次之、头发哑光、皮肤带轻微光泽
    /// （比原先一律 0.85 更有质感，配合 IBL/三点光更自然）。
    private static func roughness(for name: String) -> CGFloat {
        if isEyeball(name) { return 0.08 }
        let n = name.lowercased()
        if n.contains("teeth") || n.contains("tooth") || n.contains("歯") { return 0.30 }
        if n.contains("mouth") || n.contains("tongue") || n.contains("舌") { return 0.42 }
        if n.contains("hair") { return 0.72 }
        return 0.58   // 皮肤
    }

    private static func makeMaterial(submesh: Submesh, texturesDir: URL) -> SCNMaterial {
        let material = SCNMaterial()
        material.lightingModel = .physicallyBased
        material.roughness.contents = roughness(for: submesh.name)
        material.metalness.contents = 0.0
        material.isDoubleSided = true
        // 眼球加清漆层：在凸面上产生锐利高光点（catchlight），让眼睛有神
        if isEyeball(submesh.name) {
            material.clearCoat.contents = 1.0
            material.clearCoatRoughness.contents = 0.03
        }
        // 口腔/舌头用 Genesis 8 的 UDIM 平铺 UV（u 可达 4~5，tile 1005）。SceneKit 默认
        // clamp 会把 u 钳到 1.0 采到纹理黑边导致发黑；用 repeat 让 u 取小数部分映回 tile。
        material.diffuse.wrapS = .repeat
        material.diffuse.wrapT = .repeat

        var transparent = submesh.transparent
        if var name = submesh.texture {
            // 优先用同名 .png（带 alpha 通道，如睫毛/眉毛/头发）
            if name.lowercased().hasSuffix(".jpg") {
                let pngName = (name as NSString).deletingPathExtension + ".png"
                if FileManager.default.fileExists(
                    atPath: texturesDir.appendingPathComponent(pngName).path) {
                    name = pngName
                    transparent = true
                }
            }
            let url = texturesDir.appendingPathComponent(name)
            if let image = UIImage(contentsOfFile: url.path) {
                material.diffuse.contents = image
            } else {
                material.diffuse.contents = UIColor(white: 0.72, alpha: 1)
            }
        } else {
            material.diffuse.contents = UIColor(white: 0.72, alpha: 1)
        }
        // 法线贴图（脸部 Face_N 等）：增加皮肤/唇/皱纹表面细节
        if let normalName = submesh.normal,
           let normalImage = UIImage(
            contentsOfFile: texturesDir.appendingPathComponent(normalName).path) {
            material.normal.contents = normalImage
            material.normal.wrapS = .repeat
            material.normal.wrapT = .repeat
        }
        if transparent {
            material.transparencyMode = .aOne
            material.blendMode = .alpha
        }
        return material
    }
}
