import AppKit
import SwiftUI

@MainActor
final class PopupPanelController {
    static let shared = PopupPanelController()

    private var panel: PopupPanel?

    func showPanel() {
        if let panel {
            panel.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let viewModel = AppViewModel(dismissWindow: { [weak self] in
            self?.closePanel()
        })
        let contentView = ContentView(viewModel: viewModel, dismissWindow: { [weak self] in
            self?.closePanel()
        })

        let panel = PopupPanel(
            contentRect: NSRect(x: 0, y: 0, width: 580, height: 520),
            styleMask: [.titled, .closable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        panel.title = "Niimbot"
        panel.titleVisibility = .visible
        panel.titlebarAppearsTransparent = true
        panel.isFloatingPanel = true
        panel.level = .statusBar
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.collectionBehavior = [.moveToActiveSpace, .fullScreenAuxiliary, .ignoresCycle]
        panel.standardWindowButton(.zoomButton)?.isHidden = true
        panel.standardWindowButton(.miniaturizeButton)?.isHidden = true

        // NSVisualEffectView as the root — gives the frosted glass background
        let fx = NSVisualEffectView()
        fx.blendingMode = .behindWindow
        fx.material = .popover
        fx.state = .active

        let hosting = NSHostingView(rootView: contentView)
        hosting.translatesAutoresizingMaskIntoConstraints = false
        hosting.wantsLayer = true
        hosting.layer?.backgroundColor = .clear
        fx.addSubview(hosting)
        NSLayoutConstraint.activate([
            hosting.topAnchor.constraint(equalTo: fx.topAnchor),
            hosting.leadingAnchor.constraint(equalTo: fx.leadingAnchor),
            hosting.trailingAnchor.constraint(equalTo: fx.trailingAnchor),
            hosting.bottomAnchor.constraint(equalTo: fx.bottomAnchor),
        ])

        panel.contentView = fx
        panel.center()
        panel.makeKeyAndOrderFront(nil)

        self.panel = panel
        NSApp.activate(ignoringOtherApps: true)
    }

    func closePanel() {
        panel?.close()
    }
}

final class PopupPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }

    override func cancelOperation(_ sender: Any?) {
        close()
    }
}
