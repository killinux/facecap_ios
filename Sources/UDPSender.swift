import Foundation
import Network

/// 向目标主机发送 OSC 数据包的 UDP 客户端。
final class UDPSender {

    private let connection: NWConnection
    private let queue = DispatchQueue(label: "facecap.udp", qos: .userInteractive)

    init?(host: String, port: UInt16) {
        guard let nwPort = NWEndpoint.Port(rawValue: port) else { return nil }
        connection = NWConnection(host: NWEndpoint.Host(host), port: nwPort, using: .udp)
        connection.start(queue: queue)
    }

    func send(_ data: Data) {
        connection.send(content: data, completion: .idempotent)
    }

    func cancel() {
        connection.cancel()
    }
}
