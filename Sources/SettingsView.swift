import SwiftUI
import UIKit

/// 设置页：实况推流目标（Blender / Faceit）。
struct SettingsView: View {

    @Binding var host: String
    @Binding var port: String
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("实况目标（Blender / Faceit）") {
                    TextField("主机 IP，如 192.168.1.100", text: $host)
                        .keyboardType(.numbersAndPunctuation)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    TextField("端口", text: $port)
                        .keyboardType(.numberPad)
                }
                Section {
                    Text("协议：Face Cap OSC/UDP（/HT /HR /HRQ /ELR /ERR /W）。")
                    Text("Blender 端：Faceit → Mocap → Live Recorder，来源选 Face Cap，默认端口 9001，开始监听后在主界面点「实况」。")
                    Text("查看电脑 IP（macOS 终端）：ipconfig getifaddr en0")
                        .font(.footnote.monospaced())
                } header: {
                    Text("使用说明")
                }
                .foregroundStyle(.secondary)
            }
            .navigationTitle("设置")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") { dismiss() }
                }
            }
        }
    }
}

/// 系统分享面板，用于导出录制数据。
struct ActivityView: UIViewControllerRepresentable {
    let items: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }

    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
