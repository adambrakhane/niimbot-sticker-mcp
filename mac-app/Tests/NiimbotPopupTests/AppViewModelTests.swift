import XCTest
@testable import NiimbotPopup

@MainActor
final class AppViewModelTests: XCTestCase {
    func testGenerateSuccessReplacesDrafts() async {
        let backend = MockBackend()
        backend.generatedDrafts = [StickerDraft(category: .ticket, title: "Check limits")]
        let viewModel = AppViewModel(backend: backend)
        viewModel.prompt = "make me a sticker"

        viewModel.generate()
        await Task.yield()

        XCTAssertEqual(viewModel.drafts.count, 1)
        XCTAssertEqual(viewModel.drafts.first?.title, "Check limits")
    }

    func testGenerateFailureSurfacesErrorAndKeepsDraftsEmpty() async {
        let backend = MockBackend()
        backend.generateError = TestError.sample
        let viewModel = AppViewModel(backend: backend)
        viewModel.prompt = "make me three stickers"

        viewModel.generate()
        await Task.yield()

        XCTAssertEqual(viewModel.drafts.count, 0)
        XCTAssertEqual(viewModel.statusMessage, "Generation failed.")
        XCTAssertNotNil(viewModel.errorMessage)
        XCTAssertTrue(viewModel.errorExpanded)
        XCTAssertTrue(viewModel.errorMessage?.contains("[generate]") ?? false)
    }

    func testPrintAllSuccessDismisses() async {
        let backend = MockBackend()
        let draft = StickerDraft(category: .ticket, title: "Check limits")
        backend.printAllResult = [StickerDraft(id: draft.id, category: .ticket, title: "Check limits", status: .printed)]

        var dismissed = false
        let viewModel = AppViewModel(backend: backend, dismissWindow: { dismissed = true })
        viewModel.drafts = [draft]

        viewModel.printAll()
        try? await Task.sleep(for: .milliseconds(650))

        XCTAssertTrue(dismissed)
        XCTAssertEqual(viewModel.drafts.first?.status, .printed)
    }

    func testPrintAllFailureLeavesWindowOpen() async {
        let backend = MockBackend()
        backend.printAllError = TestError.sample

        var dismissed = false
        let viewModel = AppViewModel(backend: backend, dismissWindow: { dismissed = true })
        viewModel.drafts = [StickerDraft(category: .ticket, title: "Check limits")]

        viewModel.printAll()
        await Task.yield()

        XCTAssertFalse(dismissed)
        XCTAssertEqual(viewModel.statusMessage, "Print failed.")
    }
}

@MainActor
private final class MockBackend: BackendServing {
    var generatedDrafts: [StickerDraft] = []
    var printAllResult: [StickerDraft] = []
    var generateError: Error?
    var printAllError: Error?

    func generateDrafts(prompt: String, onProgress: @escaping @MainActor (String) -> Void) async throws -> [StickerDraft] {
        if let generateError { throw generateError }
        return generatedDrafts
    }

    func refreshPreview(draft: StickerDraft) async throws -> StickerDraft {
        draft
    }

    func printOne(draft: StickerDraft) async throws -> StickerDraft {
        var updated = draft
        updated.status = .printed
        return updated
    }

    func printAll(
        drafts: [StickerDraft],
        progress: @escaping @MainActor (PrintProgressEvent) -> Void
    ) async throws -> [StickerDraft] {
        if let printAllError { throw printAllError }
        return printAllResult
    }
}

private enum TestError: Error {
    case sample
}
