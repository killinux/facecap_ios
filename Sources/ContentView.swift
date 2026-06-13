import SwiftUI

struct ContentView: View {

    @StateObject private var engine = FaceCaptureEngine()
    @AppStorage("targetHost") private var targetHost = ""
    @AppStorage("targetPort") private var targetPort = "9001"

    @State private var isFullscreen = false
    @State private var showSettings = false
    @State private var exportURL: URL?

    private let teal = Color(red: 0.36, green: 0.73, blue: 0.79)
    private let buttonGray = Color(white: 0.80)
    private let buttonTextGray = Color(white: 0.42)

    var body: some View {
        ZStack {
            Color(white: 0.18).ignoresSafeArea()

            if engine.isSupported {
                HeadPreviewView(engine: engine)
                    .ignoresSafeArea()
            }

            VStack {
                statusBar
                Spacer()
                if !isFullscreen {
                    buttonGrid
                }
            }
            .padding(.horizontal, 14)
            .padding(.bottom, 8)
        }
        .contentShape(Rectangle())
        .onTapGesture {
            if isFullscreen {
                withAnimation { isFullscreen = false }
            }
        }
        .onAppear { engine.startTracking() }
        .onDisappear {
            engine.stopStreaming()
            engine.stopPreview()
            engine.stopTracking()
        }
        .sheet(isPresented: $showSettings) {
            SettingsView(host: $targetHost, port: $targetPort)
        }
        .sheet(item: $exportURL) { url in
            ActivityView(items: [url])
        }
    }

    // MARK: - 顶部状态

    private var statusBar: some View {
        VStack(spacing: 6) {
            HStack(spacing: 12) {
                Circle()
                    .fill(engine.faceTracked ? Color.green : Color.orange)
                    .frame(width: 8, height: 8)
                Text(engine.faceTracked ? "捕捉中" : "未检测到面部")
                if engine.isStreaming {
                    Text("· \(engine.fps) fps").monospacedDigit().foregroundStyle(teal)
                }
            }
            .font(.footnote)
            .foregroundStyle(Color(white: 0.75))

            if let status = engine.statusText {
                Text(status)
                    .font(.caption)
                    .foregroundStyle(Color(white: 0.6))
                    .multilineTextAlignment(.center)
            }
        }
        .padding(.top, 4)
    }

    // MARK: - 仿 Face Cap 按钮区

    private var buttonGrid: some View {
        VStack(spacing: 10) {
            HStack(spacing: 10) {
                toggleButton("录制", isOn: engine.isRecording, activeColor: .red) {
                    engine.toggleRecording()
                }
                toggleButton("预览", isOn: engine.isPreviewing, activeColor: Color(white: 0.25)) {
                    engine.togglePreview()
                }
            }
            HStack(spacing: 10) {
                grayButton("校正") { engine.calibrate() }
                grayButton("优化") { engine.optimizeRecording() }
                grayButton("导出") {
                    if let url = engine.exportRecording() { exportURL = url }
                }
            }
            HStack(spacing: 10) {
                grayButton("实况", highlighted: engine.isStreaming) { toggleLive() }
                grayButton("全屏") { withAnimation { isFullscreen = true } }
                grayButton("设置") { showSettings = true }
            }
        }
    }

    /// 青色开关按钮（录制/预览），右侧白色方块为状态指示。
    private func toggleButton(
        _ title: String, isOn: Bool, activeColor: Color, action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack {
                Text(title)
                    .font(.system(size: 24))
                    .foregroundStyle(Color(white: 0.95))
                Spacer()
                RoundedRectangle(cornerRadius: 5)
                    .fill(isOn ? activeColor : Color(white: 0.93))
                    .frame(width: 34, height: 44)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(teal, in: RoundedRectangle(cornerRadius: 10))
        }
    }

    private func grayButton(
        _ title: String, highlighted: Bool = false, action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 24))
                .foregroundStyle(highlighted ? Color(white: 0.95) : buttonTextGray)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16)
                .background(
                    highlighted ? teal : buttonGray,
                    in: RoundedRectangle(cornerRadius: 10)
                )
        }
    }

    // MARK: - 实况开关

    private func toggleLive() {
        if engine.isStreaming {
            engine.stopStreaming()
            return
        }
        guard let port = UInt16(targetPort.trimmingCharacters(in: .whitespaces)),
              !targetHost.trimmingCharacters(in: .whitespaces).isEmpty
        else {
            showSettings = true
            return
        }
        engine.startStreaming(
            host: targetHost.trimmingCharacters(in: .whitespaces),
            port: port
        )
    }
}

extension URL: Identifiable {
    public var id: String { absoluteString }
}
