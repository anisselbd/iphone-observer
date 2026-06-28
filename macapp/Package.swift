// swift-tools-version: 5.10
import PackageDescription

// App macOS native (SwiftUI). Le collector Python (GPL) reste un process sidecar
// separe: cette app ne le linke jamais, elle le lance et lui parle en WebSocket.
let package = Package(
    name: "iPhoneObserver",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "iPhoneObserver",
            path: "Sources/iPhoneObserver"
        )
    ]
)
