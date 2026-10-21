// swift-tools-version:6.0
import PackageDescription
let package = Package(
    name: "MembrainSDKSmoke",
    platforms: [.macOS(.v10_15)],
    dependencies: [.package(path: "../../../sdk/swift")],
    targets: [.executableTarget(name: "Smoke", dependencies: [.product(name: "MembrainSDK", package: "swift")])]
)
