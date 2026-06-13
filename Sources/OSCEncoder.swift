import Foundation

/// 极简 OSC 1.0 编码器，只实现 Face Cap 协议需要的部分：
/// int32 / float32 参数的 message，以及立即执行（timetag=1）的 bundle。
enum OSC {

    enum Argument {
        case int32(Int32)
        case float32(Float)
    }

    /// 编码单条 OSC message。
    static func message(_ address: String, _ args: [Argument]) -> Data {
        var data = Data()
        data.append(paddedString(address))

        var typeTags = ","
        for arg in args {
            switch arg {
            case .int32: typeTags += "i"
            case .float32: typeTags += "f"
            }
        }
        data.append(paddedString(typeTags))

        for arg in args {
            switch arg {
            case .int32(let v):
                appendBigEndian(UInt32(bitPattern: v), to: &data)
            case .float32(let v):
                appendBigEndian(v.bitPattern, to: &data)
            }
        }
        return data
    }

    /// 把多条已编码的 message 打成一个 bundle（timetag = 1，立即执行）。
    static func bundle(_ messages: [Data]) -> Data {
        var data = Data()
        data.append(paddedString("#bundle"))
        appendBigEndian(UInt64(1), to: &data)
        for message in messages {
            appendBigEndian(UInt32(message.count), to: &data)
            data.append(message)
        }
        return data
    }

    // MARK: - 私有工具

    /// OSC 字符串：UTF-8 + 至少一个 \0，总长补齐到 4 字节倍数。
    private static func paddedString(_ s: String) -> Data {
        var data = Data(s.utf8)
        let paddedCount = (data.count / 4 + 1) * 4
        data.append(contentsOf: [UInt8](repeating: 0, count: paddedCount - data.count))
        return data
    }

    private static func appendBigEndian<T: FixedWidthInteger>(_ value: T, to data: inout Data) {
        var be = value.bigEndian
        withUnsafeBytes(of: &be) { data.append(contentsOf: $0) }
    }
}
