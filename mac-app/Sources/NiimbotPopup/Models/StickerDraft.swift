import Foundation

enum StickerCategory: String, CaseIterable, Codable, Identifiable {
    case urgent
    case ticket
    case idea
    case bigIdea = "big_idea"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .urgent: return "Urgent"
        case .ticket: return "Ticket"
        case .idea: return "Idea"
        case .bigIdea: return "Big Idea"
        }
    }
}

enum StickerDraftStatus: String, Codable {
    case idle
    case regenerating
    case ready
    case printing
    case printed
    case failed
}

struct StickerDraft: Identifiable, Codable, Equatable {
    var id: UUID
    var category: StickerCategory
    var title: String
    var body: String
    var project: String
    var reference: String
    var previewPNGBase64: String
    var isDirty: Bool
    var status: StickerDraftStatus
    var errorMessage: String?

    init(
        id: UUID = UUID(),
        category: StickerCategory,
        title: String,
        body: String = "",
        project: String = "niimbot",
        reference: String = "",
        previewPNGBase64: String = "",
        isDirty: Bool = false,
        status: StickerDraftStatus = .ready,
        errorMessage: String? = nil
    ) {
        self.id = id
        self.category = category
        self.title = title
        self.body = body
        self.project = project
        self.reference = reference
        self.previewPNGBase64 = previewPNGBase64
        self.isDirty = isDirty
        self.status = status
        self.errorMessage = errorMessage
    }
}

extension StickerDraft {
    static func blank() -> StickerDraft {
        StickerDraft(category: .ticket, title: "", body: "", project: "niimbot", status: .idle)
    }
}
