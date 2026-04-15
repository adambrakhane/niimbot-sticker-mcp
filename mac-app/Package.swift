// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "NiimbotPopup",
    platforms: [
        .macOS(.v13),
    ],
    products: [
        .executable(name: "NiimbotPopup", targets: ["NiimbotPopup"]),
    ],
    targets: [
        .executableTarget(
            name: "NiimbotPopup",
            path: "Sources/NiimbotPopup"
        ),
        .testTarget(
            name: "NiimbotPopupTests",
            dependencies: ["NiimbotPopup"],
            path: "Tests/NiimbotPopupTests"
        ),
    ]
)
