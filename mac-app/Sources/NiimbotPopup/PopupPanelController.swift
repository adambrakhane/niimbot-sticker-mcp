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
            contentRect: NSRect(x: 0, y: 0, width: 760, height: 620),
            styleMask: [.titled, .closable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.isFloatingPanel = true
        panel.level = .statusBar          // above all normal app windows even when inactive
        panel.hidesOnDeactivate = false   // don't hide when another app becomes active
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.moveToActiveSpace, .fullScreenAuxiliary, .ignoresCycle]
        panel.standardWindowButton(.zoomButton)?.isHidden = true
        panel.standardWindowButton(.miniaturizeButton)?.isHidden = true
        panel.contentView = NSHostingView(rootView: contentView)
        panel.center()
        panel.makeKeyAndOrderFront(nil)

        self.panel = panel
        NSApp.activate(ignoringOtherApps: true)
    }

    func closePanel() {
        panel?.orderOut(nil)
    }
}

final class PopupPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }

    override func cancelOperation(_ sender: Any?) {
        close()
    }

    override func close() {
        orderOut(nil)
    }
}
