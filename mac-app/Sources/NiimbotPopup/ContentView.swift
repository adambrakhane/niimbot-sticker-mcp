import AppKit
import SwiftUI

struct ContentView: View {
    @ObservedObject var viewModel: AppViewModel
    let dismissWindow: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            topBar
            Divider()
            if viewModel.errorExpanded, let error = viewModel.errorMessage {
                errorDetailView(error)
            } else if !viewModel.agentLog.isEmpty {
                agentLogView
            } else {
                draftList
            }
            Divider()
            bottomBar
        }
        .frame(minWidth: 580, minHeight: 440)
        .background(Color.clear)
    }

    private func errorDetailView(_ error: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Error details").font(.headline)
                Spacer()
                Button("Copy") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(error, forType: .string)
                }
                Button("Hide") { viewModel.errorExpanded = false }
            }
            .padding(.horizontal, 12)
            .padding(.top, 10)
            .padding(.bottom, 6)

            ScrollView {
                Text(error)
                    .font(.system(size: 11, design: .monospaced))
                    .textSelection(.enabled)
                    .foregroundStyle(.primary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
            }
            .background(Color.red.opacity(0.05))
        }
    }

    // MARK: - Top bar

    private var topBar: some View {
        VStack(alignment: .leading, spacing: 8) {
            SubmittableTextEditor(
                text: $viewModel.prompt,
                placeholder: "make me three stickers: one urgent for the deploy bug, two ideas about BLE",
                onSubmit: { viewModel.generate() }
            )
            .frame(height: 72)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(Color.black.opacity(0.05))
            )

            HStack(spacing: 8) {
                Button("Generate") { viewModel.generate() }
                    .buttonStyle(AccentButtonStyle())
                    .disabled(!viewModel.canGenerate)

                Button("Close") { dismissWindow() }
                    .disabled(viewModel.isBusy)

                Spacer()

                if viewModel.isBusy {
                    ProgressView().controlSize(.small)
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
    }

    // MARK: - Agent log

    private var agentLogView: some View {
        ScrollViewReader { proxy in
            ScrollView {
                Text(viewModel.agentLog)
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(.primary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                    .id("bottom")
            }
            .onChange(of: viewModel.agentLog) { _ in
                proxy.scrollTo("bottom", anchor: .bottom)
            }
        }
    }

    // MARK: - Draft list

    private var draftList: some View {
        ScrollView {
            VStack(spacing: 6) {
                if viewModel.drafts.isEmpty {
                    emptyState
                } else {
                    ForEach($viewModel.drafts) { $draft in
                        DraftRowView(
                            draft: $draft,
                            isSelected: viewModel.selectedDraftID == draft.id,
                            isBusy: viewModel.isBusy,
                            onTap: { viewModel.selectDraft(id: draft.id) },
                            onFieldChanged: { viewModel.fieldChanged(id: draft.id) },
                            onPrint: { viewModel.printOne(id: draft.id) },
                            onRemove: { viewModel.removeDraft(id: draft.id) }
                        )
                    }
                }
            }
            .padding(10)
        }
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Text("No drafts yet")
                .font(.headline)
            Text("Type a prompt above and hit Generate, or add a blank card.")
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(40)
    }

    private func errorSummary(_ error: String) -> String {
        let firstLine = error.split(separator: "\n", maxSplits: 1, omittingEmptySubsequences: true).first.map(String.init) ?? error
        return firstLine
    }

    // MARK: - Bottom bar

    private var bottomBar: some View {
        HStack(spacing: 8) {
            Button("+ Blank") { viewModel.addBlankCard() }
                .disabled(viewModel.isBusy)

            Button("Print All") { viewModel.printAll() }
                .disabled(!viewModel.canPrintAll)

            Spacer()

            if let progress = viewModel.printingProgress {
                Text(progress).font(.footnote).foregroundStyle(.secondary)
            } else if let error = viewModel.errorMessage {
                HStack(spacing: 6) {
                    Text(errorSummary(error))
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Button(viewModel.errorExpanded ? "Hide" : "Details") {
                        viewModel.errorExpanded.toggle()
                    }
                    .buttonStyle(.link)
                    .font(.footnote)
                }
            } else {
                Text(viewModel.statusMessage).font(.footnote).foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }
}

// MARK: - Draft row (compact + expandable)

private struct DraftRowView: View {
    @Binding var draft: StickerDraft
    let isSelected: Bool
    let isBusy: Bool
    let onTap: () -> Void
    let onFieldChanged: () -> Void
    let onPrint: () -> Void
    let onRemove: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            // Compact header — always visible, click to expand
            Button(action: onTap) {
                HStack(spacing: 12) {
                    previewThumbnail

                    VStack(alignment: .leading, spacing: 3) {
                        categoryBadge
                        Text(draft.title.isEmpty ? "Untitled" : draft.title)
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(.primary)
                            .lineLimit(2)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    Image(systemName: isSelected ? "chevron.up" : "chevron.down")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            // Expanded edit fields
            if isSelected {
                Divider().padding(.horizontal, 12)
                editFields
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
            }
        }
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(isSelected ? Color.accentColor.opacity(0.06) : Color.black.opacity(0.03))
                .overlay(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .stroke(isSelected ? Color.accentColor.opacity(0.25) : Color.clear, lineWidth: 1)
                )
        )
        .animation(.easeInOut(duration: 0.18), value: isSelected)
    }

    // MARK: Thumbnail

    private var previewThumbnail: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(Color.white)
                .overlay(
                    RoundedRectangle(cornerRadius: 6, style: .continuous)
                        .stroke(Color.black.opacity(0.1), lineWidth: 1)
                )

            if draft.status == .regenerating {
                ProgressView().controlSize(.small)
            } else if let image = decodedImage {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.none)
                    .scaledToFit()
                    .padding(4)
            } else {
                Image(systemName: "tag")
                    .foregroundStyle(.secondary)
                    .font(.system(size: 16))
            }
        }
        .frame(width: 96, height: 60)
    }

    private var decodedImage: NSImage? {
        guard !draft.previewPNGBase64.isEmpty,
              let data = Data(base64Encoded: draft.previewPNGBase64)
        else { return nil }
        return NSImage(data: data)
    }

    // MARK: Category badge

    private var categoryBadge: some View {
        Text(draft.category.label.uppercased())
            .font(.system(size: 10, weight: .bold))
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .background(badgeColor.opacity(0.15))
            .foregroundStyle(badgeColor)
            .clipShape(Capsule())
    }

    private var badgeColor: Color {
        switch draft.category {
        case .urgent: return .red
        case .ticket: return .blue
        case .idea: return .orange
        case .bigIdea: return .green
        }
    }

    // MARK: Edit fields

    private var editFields: some View {
        VStack(spacing: 8) {
            HStack(alignment: .top, spacing: 12) {
                // Larger preview on left
                ZStack {
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(Color.white)
                        .overlay(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .stroke(Color.black.opacity(0.1), lineWidth: 1)
                        )

                    if draft.status == .regenerating {
                        ProgressView().controlSize(.small)
                    } else if let image = decodedImage {
                        Image(nsImage: image)
                            .resizable()
                            .interpolation(.none)
                            .scaledToFit()
                            .padding(6)
                    } else {
                        Image(systemName: "tag")
                            .foregroundStyle(.secondary)
                            .font(.system(size: 24))
                    }
                }
                .frame(width: 190, height: 118)

                // Fields
                VStack(spacing: 6) {
                    Picker("", selection: fieldBinding(\.category)) {
                        ForEach(StickerCategory.allCases) { cat in
                            Text(cat.label).tag(cat)
                        }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()

                    TextField("Title", text: fieldBinding(\.title))
                        .textFieldStyle(.roundedBorder)

                    TextField("Body", text: fieldBinding(\.body))
                        .textFieldStyle(.roundedBorder)

                    HStack(spacing: 6) {
                        TextField("Project", text: fieldBinding(\.project))
                            .textFieldStyle(.roundedBorder)
                        TextField("Reference", text: fieldBinding(\.reference))
                            .textFieldStyle(.roundedBorder)
                    }

                    if let err = draft.errorMessage {
                        Text(err).font(.caption).foregroundStyle(.red).frame(maxWidth: .infinity, alignment: .leading)
                    }

                    HStack {
                        Button("Print") { onPrint() }
                            .disabled(isBusy || draft.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        Spacer()
                        Button("Remove", role: .destructive) { onRemove() }
                            .disabled(isBusy)
                    }
                }
            }
        }
    }

    private func fieldBinding<V>(_ kp: WritableKeyPath<StickerDraft, V>) -> Binding<V> {
        Binding(
            get: { draft[keyPath: kp] },
            set: { draft[keyPath: kp] = $0; onFieldChanged() }
        )
    }
}

// MARK: - Accent button style

private struct AccentButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .padding(.horizontal, 12)
            .padding(.vertical, 5)
            .background(Color.accentColor.opacity(configuration.isPressed ? 0.7 : 1))
            .foregroundStyle(.white)
            .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
            .fontWeight(.medium)
    }
}

// MARK: - SubmittableTextEditor

/// NSTextView wrapper: Return submits, Option+Return inserts a newline.
struct SubmittableTextEditor: NSViewRepresentable {
    @Binding var text: String
    var placeholder: String = ""
    let onSubmit: () -> Void

    func makeNSView(context: Context) -> NSScrollView {
        let scrollView = NSTextView.scrollableTextView()
        guard let textView = scrollView.documentView as? NSTextView else { return scrollView }
        textView.delegate = context.coordinator
        textView.isEditable = true
        textView.isRichText = false
        textView.font = .systemFont(ofSize: 13)
        textView.backgroundColor = .clear
        textView.drawsBackground = false
        textView.textContainerInset = CGSize(width: 6, height: 8)
        textView.isAutomaticQuoteSubstitutionEnabled = false
        textView.isAutomaticDashSubstitutionEnabled = false
        scrollView.drawsBackground = false
        scrollView.hasVerticalScroller = false
        scrollView.hasHorizontalScroller = false
        return scrollView
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        guard let textView = scrollView.documentView as? NSTextView else { return }
        context.coordinator.parent = self
        if textView.string != text {
            let sel = textView.selectedRanges
            textView.string = text
            textView.selectedRanges = sel
        }
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 13),
            .foregroundColor: NSColor.placeholderTextColor,
        ]
        textView.placeholderAttributedString = text.isEmpty
            ? NSAttributedString(string: placeholder, attributes: attrs)
            : nil
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    @MainActor
    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: SubmittableTextEditor

        init(_ parent: SubmittableTextEditor) { self.parent = parent }

        func textView(_ textView: NSTextView, doCommandBy sel: Selector) -> Bool {
            guard sel == #selector(NSResponder.insertNewline(_:)) else { return false }
            if NSApp.currentEvent?.modifierFlags.contains(.option) == true {
                textView.insertNewline(nil)
            } else {
                parent.onSubmit()
            }
            return true
        }

        func textDidChange(_ notification: Notification) {
            guard let tv = notification.object as? NSTextView else { return }
            parent.text = tv.string
        }
    }
}

private extension NSTextView {
    var placeholderAttributedString: NSAttributedString? {
        get { value(forKey: "placeholderAttributedString") as? NSAttributedString }
        set { setValue(newValue, forKey: "placeholderAttributedString") }
    }
}
