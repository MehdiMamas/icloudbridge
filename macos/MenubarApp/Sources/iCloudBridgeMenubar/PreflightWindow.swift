import Cocoa
import SwiftUI

struct PreflightSnapshot {
    let statuses: [RequirementStatus]
    let suppressNext: Bool
    let allSatisfied: Bool
    let progress: [Requirement: Double]
    let logs: [Requirement: URL?]
}

final class PreflightModel: ObservableObject {
    @Published var snapshot: PreflightSnapshot

    init(snapshot: PreflightSnapshot) {
        self.snapshot = snapshot
    }
}

/// The setup window.
///
/// iCloudBridge normally runs as an accessory app, with no Dock icon and no
/// Cmd-Tab entry. That suits the menu bar, but it left this window with no way
/// back once it lost focus: clicking another app, or a macOS permission prompt
/// or System Settings coming forward, buried it behind other windows, where it
/// looked as if it had been dismissed. While the window is open the app is a
/// regular one, so it stays reachable from the Dock and the app switcher. The
/// window keeps the normal level on purpose; floating it would cover System
/// Settings while the user is granting access there.
final class PreflightWindowController: NSWindowController, NSWindowDelegate {
    private let model = PreflightModel(snapshot: PreflightSnapshot(statuses: [], suppressNext: true, allSatisfied: false, progress: [:], logs: [:]))
    private let hostingController: NSHostingController<PreflightView>

    var onInstallHomebrew: (() -> Void)? {
        didSet { setCallbacks() }
    }
    var onInstallXcodeCLT: (() -> Void)? {
        didSet { setCallbacks() }
    }
    var onInstallPython: (() -> Void)? {
        didSet { setCallbacks() }
    }
    var onInstallRuby: (() -> Void)? {
        didSet { setCallbacks() }
    }
    var onOpenFullDiskAccess: (() -> Void)? {
        didSet { setCallbacks() }
    }
    var onOpenNotesAutomation: (() -> Void)? {
        didSet { setCallbacks() }
    }
    var onOpenRemindersAutomation: (() -> Void)? {
        didSet { setCallbacks() }
    }
    var onOpenPhotosAutomation: (() -> Void)? {
        didSet { setCallbacks() }
    }
    var onOpenPhotosAppAutomation: (() -> Void)? {
        didSet { setCallbacks() }
    }
    var onRefresh: (() -> Void)? {
        didSet { setCallbacks() }
    }
    /// Called when the window regains focus, e.g. on returning from System Settings.
    var onBecameKey: (() -> Void)?
    var onCloseRequested: (() -> Void)? {
        didSet { setCallbacks() }
    }
    var onToggleSuppress: ((Bool) -> Void)? {
        didSet { setCallbacks() }
    }

    init() {
        hostingController = NSHostingController(rootView: PreflightView(model: model))
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 900, height: 720),
            styleMask: [.titled, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.center()
        window.title = "iCloudBridge Setup"
        window.contentViewController = hostingController
        window.isReleasedWhenClosed = false
        super.init(window: window)
        window.delegate = self
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func apply(snapshot: PreflightSnapshot) {
        model.snapshot = snapshot
    }

    /// Show the window in front and make iCloudBridge the active app.
    func present() {
        NSApp.setActivationPolicy(.regular)
        showWindow(nil)
        window?.makeKeyAndOrderFront(nil)
        // Since macOS 14 another app can decline to hand over focus, so don't
        // rely on activation alone to bring the window forward.
        window?.orderFrontRegardless()
        if #available(macOS 14.0, *) {
            NSApp.activate()
        } else {
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    /// Return to the window after something else took focus. Does nothing if
    /// the user closed or minimised it in the meantime.
    func bringToFront() {
        guard window?.isVisible == true else { return }
        present()
    }

    func windowDidBecomeKey(_ notification: Notification) {
        onBecameKey?()
    }

    func windowWillClose(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
    }

    private func setCallbacks() {
        hostingController.rootView.onInstallHomebrew = onInstallHomebrew
        hostingController.rootView.onInstallXcodeCLT = onInstallXcodeCLT
        hostingController.rootView.onInstallPython = onInstallPython
        hostingController.rootView.onInstallRuby = onInstallRuby
        hostingController.rootView.onOpenFullDiskAccess = onOpenFullDiskAccess
        hostingController.rootView.onOpenNotesAutomation = onOpenNotesAutomation
        hostingController.rootView.onOpenRemindersAutomation = onOpenRemindersAutomation
        hostingController.rootView.onOpenPhotosAutomation = onOpenPhotosAutomation
        hostingController.rootView.onOpenPhotosAppAutomation = onOpenPhotosAppAutomation
        hostingController.rootView.onRefresh = onRefresh
        hostingController.rootView.onCloseRequested = onCloseRequested
        hostingController.rootView.onToggleSuppress = onToggleSuppress
    }
}

struct PreflightView: View {
    @ObservedObject var model: PreflightModel

    var onInstallHomebrew: (() -> Void)?
    var onInstallXcodeCLT: (() -> Void)?
    var onInstallPython: (() -> Void)?
    var onInstallRuby: (() -> Void)?
    var onOpenFullDiskAccess: (() -> Void)?
    var onOpenNotesAutomation: (() -> Void)?
    var onOpenRemindersAutomation: (() -> Void)?
    var onOpenPhotosAutomation: (() -> Void)?
    var onOpenPhotosAppAutomation: (() -> Void)?
    var onRefresh: (() -> Void)?
    var onCloseRequested: (() -> Void)?
    var onToggleSuppress: ((Bool) -> Void)?

    private var snapshot: PreflightSnapshot { model.snapshot }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Confirm the prerequisites below before starting the sync engine.")
                        .font(.system(size: 14, weight: .semibold))
                    Text("Only the Essential items are required. Each optional section is needed only for the sync feature it names, so skip any you don't plan to use. Passwords sync needs no macOS permissions.")
                        .font(.system(size: 12))
                        .foregroundColor(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                VStack(alignment: .leading, spacing: 12) {
                    // Essential (runtimes) - these block the daemon
                    SectionHeader(category: .essential)
                    VStack(spacing: 8) {
                        RequirementRow(
                            title: "Homebrew",
                            status: status(for: .homebrew),
                            actionTitle: buttonTitle(for: .homebrew, defaultTitle: "Install Homebrew"),
                            actionEnabled: isActionEnabled(for: .homebrew),
                            showsProgress: isInProgress(for: .homebrew),
                            progress: progress(for: .homebrew),
                            logURL: logURL(for: .homebrew),
                            onShowLogs: { openLogs(for: .homebrew) },
                            action: { onInstallHomebrew?() }
                        )
                        RequirementRow(
                            title: "Xcode Command Line Tools",
                            status: status(for: .xcodeCommandLineTools),
                            actionTitle: buttonTitle(for: .xcodeCommandLineTools, defaultTitle: "Install Command Line Tools"),
                            actionEnabled: isActionEnabled(for: .xcodeCommandLineTools),
                            showsProgress: isInProgress(for: .xcodeCommandLineTools),
                            progress: progress(for: .xcodeCommandLineTools),
                            logURL: logURL(for: .xcodeCommandLineTools),
                            onShowLogs: { openLogs(for: .xcodeCommandLineTools) },
                            action: { onInstallXcodeCLT?() }
                        )
                        RequirementRow(
                            title: "Python 3.12",
                            status: status(for: .python),
                            actionTitle: buttonTitle(for: .python, defaultTitle: "Install python@3.12"),
                            actionEnabled: isActionEnabled(for: .python),
                            showsProgress: isInProgress(for: .python),
                            progress: progress(for: .python),
                            logURL: logURL(for: .python),
                            onShowLogs: { openLogs(for: .python) },
                            action: { onInstallPython?() }
                        )
                        RequirementRow(
                            title: "Ruby",
                            status: status(for: .ruby),
                            actionTitle: buttonTitle(for: .ruby, defaultTitle: "Install Ruby"),
                            actionEnabled: isActionEnabled(for: .ruby),
                            showsProgress: isInProgress(for: .ruby),
                            progress: progress(for: .ruby),
                            logURL: logURL(for: .ruby),
                            onShowLogs: { openLogs(for: .ruby) },
                            action: { onInstallRuby?() }
                        )
                    }
                    .padding(12)
                    .background(.quaternary.opacity(0.6))
                    .cornerRadius(10)

                    // Notes Sync permissions (optional)
                    SectionHeader(category: .notes)
                        .padding(.top, 8)
                    VStack(spacing: 8) {
                        RequirementRow(
                            title: "Full Disk Access",
                            status: status(for: .fullDiskAccess),
                            actionTitle: "Open System Settings",
                            actionEnabled: isActionEnabled(for: .fullDiskAccess),
                            showsProgress: false,
                            progress: nil,
                            logURL: nil,
                            onShowLogs: nil,
                            action: { onOpenFullDiskAccess?() }
                        )
                        RequirementRow(
                            title: "Notes Automation",
                            status: status(for: .notesAutomation),
                            actionTitle: "Request Access",
                            actionEnabled: isActionEnabled(for: .notesAutomation),
                            showsProgress: false,
                            progress: nil,
                            logURL: nil,
                            onShowLogs: nil,
                            action: { onOpenNotesAutomation?() }
                        )
                    }
                    .padding(12)
                    .background(.quaternary.opacity(0.6))
                    .cornerRadius(10)

                    // Reminders Sync permissions (optional)
                    SectionHeader(category: .reminders)
                        .padding(.top, 8)
                    VStack(spacing: 8) {
                        RequirementRow(
                            title: "Apple Reminders",
                            status: status(for: .remindersAutomation),
                            actionTitle: "Request Access",
                            actionEnabled: isActionEnabled(for: .remindersAutomation),
                            showsProgress: false,
                            progress: nil,
                            logURL: nil,
                            onShowLogs: nil,
                            action: { onOpenRemindersAutomation?() }
                        )
                    }
                    .padding(12)
                    .background(.quaternary.opacity(0.6))
                    .cornerRadius(10)

                    // Photos Sync permissions (optional)
                    SectionHeader(category: .photos)
                        .padding(.top, 8)
                    VStack(spacing: 8) {
                        RequirementRow(
                            title: "Photos Library",
                            status: status(for: .photosAutomation),
                            actionTitle: "Request Access",
                            actionEnabled: isActionEnabled(for: .photosAutomation),
                            showsProgress: false,
                            progress: nil,
                            logURL: nil,
                            onShowLogs: nil,
                            action: { onOpenPhotosAutomation?() }
                        )
                        RequirementRow(
                            title: "Photos Automation",
                            status: status(for: .photosAppAutomation),
                            actionTitle: "Request Access",
                            actionEnabled: isActionEnabled(for: .photosAppAutomation),
                            showsProgress: false,
                            progress: nil,
                            logURL: nil,
                            onShowLogs: nil,
                            action: { onOpenPhotosAppAutomation?() }
                        )
                    }
                    .padding(12)
                    .background(.quaternary.opacity(0.6))
                    .cornerRadius(10)
                }

                Text(summaryText)
                    .font(.system(size: 13))
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                let essentialsReady = snapshot.statuses
                    .filter { $0.requirement.isEssential }
                    .allSatisfy { $0.state.isSatisfied }

                Toggle("Don't show this next time", isOn: Binding(
                    get: { essentialsReady ? snapshot.suppressNext : false },
                    set: { value in
                        guard essentialsReady else { return }
                        setSuppress(value)
                    }
                ))
                .toggleStyle(.switch)
                .disabled(!essentialsReady)
                .onChange(of: essentialsReady) { newValue in
                    if newValue && !snapshot.suppressNext {
                        setSuppress(true)
                    } else if !newValue {
                        setSuppress(false)
                    }
                }

                HStack {
                    Button("Refresh") { onRefresh?() }
                    Spacer()
                    Button("Close") { onCloseRequested?() }
                }
            }
            .padding(24)
        }
        .frame(minWidth: 900, minHeight: 720)
    }

    /// Record the suppress choice and republish the snapshot.
    ///
    /// The republish is deferred by one runloop turn on purpose. Both callers
    /// run inside SwiftUI's update dispatch - `.onChange` fires while the
    /// framework is already publishing this object - and assigning to an
    /// `@Published` there re-enters `ObservableObjectPublisher`'s lock. That
    /// lock is an `os_unfair_lock`, which is not recursive, so the main thread
    /// blocks on itself and the whole window freezes on whatever it last drew.
    /// `essentialsReady` flips the moment the runtime installs finish, which is
    /// what made this look like the installer hanging.
    private func setSuppress(_ value: Bool) {
        onToggleSuppress?(value)
        let current = snapshot
        DispatchQueue.main.async {
            model.snapshot = PreflightSnapshot(
                statuses: current.statuses,
                suppressNext: value,
                allSatisfied: current.allSatisfied,
                progress: current.progress,
                logs: current.logs
            )
        }
    }

    private var summaryText: String {
        let essentialsReady = snapshot.statuses
            .filter { $0.requirement.isEssential }
            .allSatisfy { $0.state.isSatisfied }
        if essentialsReady {
            return "Sync engine started. Optional permissions can be granted later from Show Initial Setup in the menu bar."
        }
        return "The sync engine will start automatically when the essential prerequisites are met."
    }

    private func status(for requirement: Requirement) -> RequirementState {
        snapshot.statuses.first(where: { $0.requirement == requirement })?.state ?? .pending
    }

    private func isInProgress(for requirement: Requirement) -> Bool {
        let state = status(for: requirement)
        if case .installing = state { return true }
        if case .checking = state { return true }
        return false
    }

    private func progress(for requirement: Requirement) -> Double? {
        snapshot.progress[requirement]
    }

    private func logURL(for requirement: Requirement) -> URL? {
        snapshot.logs[requirement] ?? nil
    }

    private func openLogs(for requirement: Requirement) {
        guard let url = logURL(for: requirement) else { return }
        NSWorkspace.shared.open(url)
    }

    private func isActionEnabled(for requirement: Requirement) -> Bool {
        let state = status(for: requirement)
        switch state {
        case .pending, .checking, .installing, .satisfied:
            return false
        case .actionRequired, .failed:
            return true
        }
    }

    private func buttonTitle(for requirement: Requirement, defaultTitle: String) -> String {
        let state = status(for: requirement)
        switch state {
        case .installing:
            return "Installing…"
        case .checking:
            return "Checking…"
        case .satisfied:
            return "Installed"
        case .failed, .actionRequired:
            return "Retry"
        default:
            return defaultTitle
        }
    }
}

/// Section title with a Required/Optional badge and what the section is for.
private struct SectionHeader: View {
    let category: RequirementCategory

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Text(category.title).font(.headline)
            Text(category.isOptional ? "Optional" : "Required")
                .font(.system(size: 10, weight: .semibold))
                .foregroundColor(category.isOptional ? .secondary : .accentColor)
                .padding(.horizontal, 6)
                .padding(.vertical, 1)
                .background(
                    Capsule().fill(category.isOptional ? Color.secondary.opacity(0.15) : Color.accentColor.opacity(0.15))
                )
            Text(category.subtitle)
                .font(.system(size: 12))
                .foregroundColor(.secondary)
        }
    }
}

private struct RequirementRow: View {
    let title: String
    let status: RequirementState
    let actionTitle: String
    let actionEnabled: Bool
    let showsProgress: Bool
    let progress: Double?
    let logURL: URL?
    let onShowLogs: (() -> Void)?
    let action: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Text(title)
                .font(.system(size: 13, weight: .semibold))
                .frame(width: 180, alignment: .leading)

            if showsProgress {
                if let progress {
                    ProgressView(value: progress)
                        .progressViewStyle(.linear)
                        .frame(width: 100)
                } else {
                    ProgressView()
                        .progressViewStyle(.circular)
                        .controlSize(.small)
                        .frame(width: 14, height: 14)
                }
            } else {
                Circle()
                    .fill(color(for: status))
                    .frame(width: 10, height: 10)
            }

            Text(status.message)
                .font(.system(size: 13))
                .lineLimit(2)
                .truncationMode(.tail)
                .frame(maxWidth: .infinity, alignment: .leading)

            if actionEnabled {
                Button(actionTitle, action: action)
                    .controlSize(.small)
            }

            if let logURL {
                Button("Logs") { onShowLogs?() ?? openLog(logURL) }
                    .controlSize(.small)
            }
        }
    }

    private func color(for state: RequirementState) -> Color {
        switch state {
        case .satisfied:
            return .green
        case .installing, .checking:
            return .orange
        case .actionRequired, .failed:
            return .red
        case .pending:
            return .gray
        }
    }

    private func openLog(_ url: URL) {
        NSWorkspace.shared.open(url)
    }
}
#if DEBUG
struct PreflightView_Previews: PreviewProvider {
    static var previews: some View {
        let snapshot = PreflightSnapshot(
            statuses: [
                RequirementStatus(requirement: .homebrew, state: .satisfied("Found Homebrew")),
                RequirementStatus(requirement: .xcodeCommandLineTools, state: .installing("Installing…")),
                RequirementStatus(requirement: .python, state: .installing("Installing…")),
                RequirementStatus(requirement: .ruby, state: .actionRequired("Ruby not installed")),
                RequirementStatus(requirement: .fullDiskAccess, state: .failed("Needs Full Disk Access"))
            ],
            suppressNext: true,
            allSatisfied: false,
            progress: [.python: 0.3, .xcodeCommandLineTools: 0.1],
            logs: [:]
        )
        return PreflightView(model: PreflightModel(snapshot: snapshot))
            .frame(width: 560, height: 580)
    }
}
#endif
