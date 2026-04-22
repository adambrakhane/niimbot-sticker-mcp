import Foundation
import SwiftUI

@MainActor
final class AppViewModel: ObservableObject {
    @Published var prompt = ""
    @Published var drafts: [StickerDraft] = []
    @Published var selectedDraftID: UUID?
    @Published var statusMessage = "Enter a prompt to generate sticker drafts."
    @Published var errorMessage: String?
    @Published var errorExpanded: Bool = false
    @Published var isBusy = false
    @Published var printingProgress: String?
    @Published var agentLog: String = ""

    private let backend: BackendServing
    private let dismissWindow: () -> Void
    private var previewDebounceTask: Task<Void, Never>?

    init(
        backend: BackendServing = BackendBridge(),
        dismissWindow: @escaping () -> Void = {}
    ) {
        self.backend = backend
        self.dismissWindow = dismissWindow
    }

    private func reportError(_ error: Error, context: String) {
        let detail = Self.formatError(error, context: context)
        NSLog("[Niimbot] %@", detail)
        errorMessage = detail
        errorExpanded = true
    }

    private static func formatError(_ error: Error, context: String) -> String {
        let ns = error as NSError
        var parts: [String] = []
        parts.append("[\(context)] \(error.localizedDescription)")
        parts.append("Domain: \(ns.domain)  Code: \(ns.code)")
        if let reason = ns.localizedFailureReason { parts.append("Reason: \(reason)") }
        if let suggestion = ns.localizedRecoverySuggestion { parts.append("Suggestion: \(suggestion)") }
        if !ns.userInfo.isEmpty {
            parts.append("UserInfo: \(ns.userInfo)")
        }
        return parts.joined(separator: "\n")
    }

    var canGenerate: Bool {
        !prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isBusy
    }

    var canPrintAll: Bool {
        !drafts.isEmpty && !isBusy && drafts.contains { !$0.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }

    func generate() {
        guard canGenerate else { return }
        let prompt = self.prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        isBusy = true
        errorMessage = nil
        errorExpanded = false
        agentLog = ""
        selectedDraftID = nil
        statusMessage = "Generating drafts..."
        let backend = self.backend

        Task {
            do {
                let generated = try await backend.generateDrafts(prompt: prompt) { [weak self] chunk in
                    self?.agentLog.append(chunk)
                }
                drafts = generated
                agentLog = ""
                statusMessage = generated.isEmpty ? "No drafts returned." : "Generated \(generated.count) draft\(generated.count == 1 ? "" : "s")."
            } catch {
                reportError(error, context: "generate")
                statusMessage = "Generation failed."
            }
            isBusy = false
        }
    }

    func selectDraft(id: UUID) {
        selectedDraftID = selectedDraftID == id ? nil : id
    }

    func addBlankCard() {
        let draft = StickerDraft.blank()
        drafts.append(draft)
        selectedDraftID = draft.id
        statusMessage = "Added a blank draft."
    }

    func removeDraft(id: UUID) {
        if selectedDraftID == id { selectedDraftID = nil }
        drafts.removeAll { $0.id == id }
        statusMessage = drafts.isEmpty ? "No drafts." : "Removed draft."
    }

    func fieldChanged(id: UUID) {
        guard let index = drafts.firstIndex(where: { $0.id == id }) else { return }
        drafts[index].isDirty = true
        if drafts[index].status == .printed || drafts[index].status == .failed {
            drafts[index].status = .idle
            drafts[index].errorMessage = nil
        }
        schedulePreviewRefresh(id: id)
    }

    private func schedulePreviewRefresh(id: UUID) {
        previewDebounceTask?.cancel()
        previewDebounceTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(500))
            guard !Task.isCancelled, let self else { return }
            self.refreshPreview(id: id)
        }
    }

    func refreshPreview(id: UUID) {
        guard let draft = drafts.first(where: { $0.id == id }),
              !draft.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !isBusy else { return }
        updateDraft(id: id) {
            $0.status = .regenerating
            $0.errorMessage = nil
        }
        let backend = self.backend

        Task {
            do {
                let updated = try await backend.refreshPreview(draft: draft)
                replaceDraft(updated)
            } catch {
                let detail = Self.formatError(error, context: "refreshPreview")
                updateDraft(id: id) {
                    $0.status = .failed
                    $0.errorMessage = detail
                }
            }
        }
    }

    func printOne(id: UUID) {
        guard let draft = drafts.first(where: { $0.id == id }), !isBusy else { return }
        isBusy = true
        errorMessage = nil
        printingProgress = "Printing…"
        updateDraft(id: id) {
            $0.status = .printing
            $0.errorMessage = nil
        }
        let backend = self.backend

        Task {
            do {
                let printed = try await backend.printOne(draft: draft)
                replaceDraft(printed)
                statusMessage = "Printed."
            } catch {
                let detail = Self.formatError(error, context: "printOne")
                updateDraft(id: id) {
                    $0.status = .failed
                    $0.errorMessage = detail
                }
                reportError(error, context: "printOne")
                statusMessage = "Print failed."
            }
            printingProgress = nil
            isBusy = false
        }
    }

    func printAll() {
        guard canPrintAll else { return }
        isBusy = true
        errorMessage = nil
        statusMessage = "Printing drafts..."
        for index in drafts.indices {
            drafts[index].status = .printing
            drafts[index].errorMessage = nil
        }

        let currentDrafts = drafts
        let backend = self.backend
        Task {
            do {
                let printedDrafts = try await backend.printAll(drafts: currentDrafts) { [weak self] event in
                    self?.printingProgress = "Printing \(event.current) of \(event.total)"
                }
                drafts = printedDrafts
                let failures = printedDrafts.filter { $0.status == .failed }.count
                if failures == 0 {
                    statusMessage = "Printed \(printedDrafts.count) draft\(printedDrafts.count == 1 ? "" : "s")."
                    printingProgress = "Done"
                    try? await Task.sleep(for: .milliseconds(500))
                    dismissWindow()
                } else {
                    errorMessage = "\(failures) draft\(failures == 1 ? "" : "s") failed to print."
                    statusMessage = "Print completed with errors."
                    printingProgress = nil
                }
            } catch {
                let detail = Self.formatError(error, context: "printAll")
                reportError(error, context: "printAll")
                statusMessage = "Print failed."
                printingProgress = nil
                for index in drafts.indices where drafts[index].status == .printing {
                    drafts[index].status = .failed
                    drafts[index].errorMessage = detail
                }
            }
            isBusy = false
        }
    }

    private func updateDraft(id: UUID, _ body: (inout StickerDraft) -> Void) {
        guard let index = drafts.firstIndex(where: { $0.id == id }) else { return }
        body(&drafts[index])
    }

    private func replaceDraft(_ draft: StickerDraft) {
        guard let index = drafts.firstIndex(where: { $0.id == draft.id }) else {
            drafts.append(draft)
            return
        }
        drafts[index] = draft
    }

}
