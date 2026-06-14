import Foundation

/// 可切换头模目录。扫描 bundle 内 `heads/<id>/head.fch`，每个子目录即一个头模，
/// 子目录名作为显示名与持久化 id。纹理与 head.fch 同目录（各头模独立，避免重名冲突）。
struct HeadCatalog {

    struct Head: Identifiable, Equatable {
        let id: String          // 子目录名，如 "Children"
        let fchURL: URL
        let texturesDir: URL
        var displayName: String { id }
    }

    /// 偏好排序：默认头模 Children 在前，其余按此顺序，未列出的追加在后。
    private static let preferredOrder = ["Children", "Office", "AC", "inase", "Remake"]

    static let all: [Head] = discover()

    static var `default`: Head? { all.first }

    static func head(id: String) -> Head? {
        all.first { $0.id == id }
    }

    private static func discover() -> [Head] {
        guard let root = Bundle.main.resourceURL?.appendingPathComponent("heads"),
              let entries = try? FileManager.default.contentsOfDirectory(
                at: root, includingPropertiesForKeys: [.isDirectoryKey])
        else { return [] }

        var heads: [Head] = []
        for dir in entries {
            let isDir = (try? dir.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory ?? false
            guard isDir else { continue }
            let fch = dir.appendingPathComponent("head.fch")
            guard FileManager.default.fileExists(atPath: fch.path) else { continue }
            heads.append(Head(
                id: dir.lastPathComponent, fchURL: fch, texturesDir: dir))
        }

        heads.sort { a, b in
            let ia = preferredOrder.firstIndex(of: a.id) ?? Int.max
            let ib = preferredOrder.firstIndex(of: b.id) ?? Int.max
            return ia != ib ? ia < ib : a.id < b.id
        }
        return heads
    }
}
