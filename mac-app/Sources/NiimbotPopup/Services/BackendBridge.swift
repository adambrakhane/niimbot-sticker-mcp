import AppKit
import Foundation

struct PrintProgressEvent {
    let current: Int
    let total: Int
    let draftID: UUID?
    let phase: String
    let status: String?
    let error: String?
}

@MainActor
protocol BackendServing: AnyObject {
    func generateDrafts(prompt: String, onProgress: @escaping @MainActor (String) -> Void) async throws -> [StickerDraft]
    func refreshPreview(draft: StickerDraft) async throws -> StickerDraft
    func printOne(draft: StickerDraft) async throws -> StickerDraft
    func printAll(
        drafts: [StickerDraft],
        progress: @escaping @MainActor (PrintProgressEvent) -> Void
    ) async throws -> [StickerDraft]
}

@MainActor
final class BackendBridge: NSObject, BackendServing {
    private var process: Process?
    private var stdinHandle: FileHandle?
    private var stdoutHandle: FileHandle?
    private var stderrHandle: FileHandle?
    private var stdoutBuffer = Data()
    private var pending: [String: PendingRequest] = [:]
    private var stderrTail: [String] = []
    private let stderrTailLimit = 200
    private var logFileHandle: FileHandle?

    private struct PendingRequest {
        let continuation: CheckedContinuation<Data, Error>
        let printProgressHandler: (@MainActor (PrintProgressEvent) -> Void)?
        let textProgressHandler: (@MainActor (String) -> Void)?
    }

    func generateDrafts(prompt: String, onProgress: @escaping @MainActor (String) -> Void) async throws -> [StickerDraft] {
        let payloadData = try await sendRequest(method: "generate_drafts", params: ["prompt": prompt], textProgressHandler: onProgress)
        let payload = try JSONSerialization.jsonObject(with: payloadData) as? [String: Any] ?? [:]
        let draftsData = try JSONSerialization.data(withJSONObject: payload["drafts"] ?? [])
        return try JSONDecoder().decode([StickerDraftDTO].self, from: draftsData).map(\.model)
    }

    func refreshPreview(draft: StickerDraft) async throws -> StickerDraft {
        let payloadData = try await sendRequest(method: "refresh_preview", params: ["draft": StickerDraftDTO(model: draft).dictionary])
        let payload = try JSONSerialization.jsonObject(with: payloadData) as? [String: Any] ?? [:]
        let draftData = try JSONSerialization.data(withJSONObject: payload["draft"] ?? [:])
        return try JSONDecoder().decode(StickerDraftDTO.self, from: draftData).model
    }

    func printOne(draft: StickerDraft) async throws -> StickerDraft {
        let payloadData = try await sendRequest(method: "print_one", params: ["draft": StickerDraftDTO(model: draft).dictionary])
        let payload = try JSONSerialization.jsonObject(with: payloadData) as? [String: Any] ?? [:]
        let draftData = try JSONSerialization.data(withJSONObject: payload["draft"] ?? [:])
        return try JSONDecoder().decode(StickerDraftDTO.self, from: draftData).model
    }

    func printAll(
        drafts: [StickerDraft],
        progress: @escaping @MainActor (PrintProgressEvent) -> Void
    ) async throws -> [StickerDraft] {
        let payloadData = try await sendRequest(
            method: "print_all",
            params: ["drafts": drafts.map { StickerDraftDTO(model: $0).dictionary }],
            printProgressHandler: progress
        )
        let payload = try JSONSerialization.jsonObject(with: payloadData) as? [String: Any] ?? [:]
        let draftsData = try JSONSerialization.data(withJSONObject: payload["drafts"] ?? [])
        return try JSONDecoder().decode([StickerDraftDTO].self, from: draftsData).map(\.model)
    }

    private func sendRequest(
        method: String,
        params: [String: Any],
        printProgressHandler: (@MainActor (PrintProgressEvent) -> Void)? = nil,
        textProgressHandler: (@MainActor (String) -> Void)? = nil
    ) async throws -> Data {
        try launchIfNeeded()

        let id = UUID().uuidString
        let request: [String: Any] = [
            "id": id,
            "method": method,
            "params": params,
        ]
        let data = try JSONSerialization.data(withJSONObject: request)
        try stdinHandle?.write(contentsOf: data + Data([0x0a]))

        return try await withCheckedThrowingContinuation { continuation in
            pending[id] = PendingRequest(
                continuation: continuation,
                printProgressHandler: printProgressHandler,
                textProgressHandler: textProgressHandler
            )
        }
    }

    private func launchIfNeeded() throws {
        if process?.isRunning == true { return }

        let process = Process()
        let stdinPipe = Pipe()
        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        let environment = backendEnvironment()

        let python = try resolvePython(environment: environment)
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-m", "niimbot.app_backend"]
        process.standardInput = stdinPipe
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe
        process.environment = environment
        process.currentDirectoryURL = environment["NIIMBOT_REPO_ROOT"].map(URL.init(fileURLWithPath:))

        stdoutPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { return }
            Task { @MainActor in
                self?.consume(data: data)
            }
        }

        stderrPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8), !text.isEmpty else { return }
            fputs(text, stderr)
            Task { @MainActor in
                self?.recordStderr(text)
            }
        }

        process.terminationHandler = { [weak self] process in
            let status = process.terminationStatus
            let reason = process.terminationReason
            Task { @MainActor in
                guard let self else { return }
                let tail = self.stderrTail.joined()
                let reasonLabel: String
                switch reason {
                case .exit: reasonLabel = "exit"
                case .uncaughtSignal: reasonLabel = "uncaught signal"
                @unknown default: reasonLabel = "unknown"
                }
                let header = "Backend exited (status=\(status), reason=\(reasonLabel)).\nLog file: \(self.logFilePath() ?? "<unavailable>")"
                let message: String
                if tail.isEmpty {
                    message = "\(header)\n\n(no stderr captured — try running the backend manually: PYTHONPATH=<repo>/src python3 -m niimbot.app_backend)"
                } else {
                    message = "\(header)\n\n--- last stderr ---\n\(tail)"
                }
                self.failAllPending(message: message)
                self.cleanupHandles()
            }
        }

        openLogFile()
        stderrTail.removeAll()
        try process.run()
        self.process = process
        self.stdinHandle = stdinPipe.fileHandleForWriting
        self.stdoutHandle = stdoutPipe.fileHandleForReading
        self.stderrHandle = stderrPipe.fileHandleForReading
        appendToLog("--- backend launched pid=\(process.processIdentifier) python=\(python) at \(Date()) ---\n")
    }

    private func resolvePython(environment: [String: String]) throws -> String {
        if let override = environment["NIIMBOT_PYTHON"], !override.isEmpty,
           FileManager.default.isExecutableFile(atPath: override) {
            return override
        }

        if let bundled = Bundle.main.url(forResource: "python-path", withExtension: "txt"),
           let raw = try? String(contentsOf: bundled, encoding: .utf8) {
            let path = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if !path.isEmpty, FileManager.default.isExecutableFile(atPath: path) {
                return path
            }
        }

        let candidates = [
            "\(NSHomeDirectory())/.pyenv/shims/python3",
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3",
        ]
        for candidate in candidates {
            if FileManager.default.isExecutableFile(atPath: candidate),
               pythonHasModule(candidate, module: "bleak") {
                return candidate
            }
        }

        let checked = candidates.joined(separator: "\n  ")
        throw BackendError.message("""
            Could not find a Python 3 interpreter with the niimbot dependencies installed.

            Checked:
              \(checked)

            Fix one of these:
              • Set NIIMBOT_PYTHON=/absolute/path/to/python3 in the app's environment.
              • Add a python-path.txt resource to the app bundle with the interpreter path.
              • Install deps into one of the checked paths: pip install -e '.[app]'
            """)
    }

    private func pythonHasModule(_ python: String, module: String) -> Bool {
        let probe = Process()
        probe.executableURL = URL(fileURLWithPath: python)
        probe.arguments = ["-c", "import \(module)"]
        probe.standardOutput = Pipe()
        probe.standardError = Pipe()
        do {
            try probe.run()
            probe.waitUntilExit()
            return probe.terminationStatus == 0
        } catch {
            return false
        }
    }

    private func recordStderr(_ text: String) {
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false).map { "\($0)\n" }
        stderrTail.append(contentsOf: lines)
        if stderrTail.count > stderrTailLimit {
            stderrTail.removeFirst(stderrTail.count - stderrTailLimit)
        }
        appendToLog(text)
    }

    private func logFileURL() -> URL? {
        guard let libraryURL = try? FileManager.default.url(
            for: .libraryDirectory, in: .userDomainMask, appropriateFor: nil, create: false
        ) else { return nil }
        let dir = libraryURL.appendingPathComponent("Logs/Niimbot", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("backend-host.log")
    }

    private func logFilePath() -> String? {
        logFileURL()?.path
    }

    private func openLogFile() {
        guard let url = logFileURL() else { return }
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(atPath: url.path, contents: nil)
        }
        logFileHandle = try? FileHandle(forWritingTo: url)
        _ = try? logFileHandle?.seekToEnd()
    }

    private func appendToLog(_ text: String) {
        guard let data = text.data(using: .utf8) else { return }
        try? logFileHandle?.write(contentsOf: data)
    }

    private func backendEnvironment() -> [String: String] {
        var environment = ProcessInfo.processInfo.environment
        let repoRoot = Bundle.main.repoRootPath ?? FileManager.default.currentDirectoryPath
        let sourcePath = "\(repoRoot)/src"
        let pythonPath = environment["PYTHONPATH"].map { "\(sourcePath):\($0)" } ?? sourcePath
        environment["PYTHONPATH"] = pythonPath
        environment["NIIMBOT_REPO_ROOT"] = repoRoot
        return environment
    }

    private func consume(data: Data) {
        stdoutBuffer.append(data)
        let newline = Data([0x0a])

        while let range = stdoutBuffer.range(of: newline) {
            let lineData = stdoutBuffer.subdata(in: 0..<range.lowerBound)
            stdoutBuffer.removeSubrange(0..<range.upperBound)
            guard !lineData.isEmpty else { continue }
            handleLine(lineData)
        }
    }

    private func handleLine(_ data: Data) {
        guard
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let type = object["type"] as? String,
            let id = object["id"] as? String
        else {
            return
        }

        switch type {
        case "response":
            guard let pending = pending.removeValue(forKey: id) else { return }
            if object["ok"] as? Bool == true {
                let data = (try? JSONSerialization.data(withJSONObject: object["result"] as? [String: Any] ?? [:])) ?? Data("{}".utf8)
                pending.continuation.resume(returning: data)
            } else {
                pending.continuation.resume(throwing: BackendError.message(object["error"] as? String ?? "Unknown backend error"))
            }

        case "event":
            guard
                let pending = pending[id],
                let eventName = object["event"] as? String,
                let payload = object["payload"] as? [String: Any]
            else { return }

            if eventName == "agent_progress", let handler = pending.textProgressHandler {
                let text = payload["text"] as? String ?? ""
                handler(text)
            } else if eventName == "print_progress", let handler = pending.printProgressHandler {
                let event = PrintProgressEvent(
                    current: payload["current"] as? Int ?? 0,
                    total: payload["total"] as? Int ?? 0,
                    draftID: (payload["draft_id"] as? String).flatMap(UUID.init(uuidString:)),
                    phase: payload["phase"] as? String ?? "unknown",
                    status: payload["status"] as? String,
                    error: payload["error"] as? String
                )
                handler(event)
            }

        default:
            break
        }
    }

    private func failAllPending(message: String) {
        let error = BackendError.message(message)
        let currentPending = pending
        pending.removeAll()
        for pending in currentPending.values {
            pending.continuation.resume(throwing: error)
        }
    }

    private func cleanupHandles() {
        stdoutHandle?.readabilityHandler = nil
        stderrHandle?.readabilityHandler = nil
        stdinHandle = nil
        stdoutHandle = nil
        stderrHandle = nil
        process = nil
        try? logFileHandle?.close()
        logFileHandle = nil
    }
}

private enum BackendError: LocalizedError {
    case message(String)

    var errorDescription: String? {
        switch self {
        case .message(let message): return message
        }
    }
}

private struct StickerDraftDTO: Codable {
    let id: String
    let category: String
    let title: String
    let body: String
    let project: String
    let reference: String
    let preview_png_base64: String
    let is_dirty: Bool
    let status: String
    let error_message: String?

    init(model: StickerDraft) {
        self.id = model.id.uuidString
        self.category = model.category.rawValue
        self.title = model.title
        self.body = model.body
        self.project = model.project
        self.reference = model.reference
        self.preview_png_base64 = model.previewPNGBase64
        self.is_dirty = model.isDirty
        self.status = model.status.rawValue
        self.error_message = model.errorMessage
    }

    var model: StickerDraft {
        StickerDraft(
            id: UUID(uuidString: id) ?? UUID(),
            category: StickerCategory(rawValue: category) ?? .ticket,
            title: title,
            body: body,
            project: project,
            reference: reference,
            previewPNGBase64: preview_png_base64,
            isDirty: is_dirty,
            status: StickerDraftStatus(rawValue: status) ?? .ready,
            errorMessage: error_message
        )
    }

    var dictionary: [String: Any] {
        [
            "id": id,
            "category": category,
            "title": title,
            "body": body,
            "project": project,
            "reference": reference,
            "preview_png_base64": preview_png_base64,
            "is_dirty": is_dirty,
            "status": status,
            "error_message": error_message as Any,
        ]
    }
}

private extension Bundle {
    var repoRootPath: String? {
        guard let url = url(forResource: "repo-root", withExtension: "txt"),
              let text = try? String(contentsOf: url).trimmingCharacters(in: .whitespacesAndNewlines),
              !text.isEmpty
        else {
            return nil
        }
        return text
    }
}
