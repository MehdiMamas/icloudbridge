import Cocoa
import ApplicationServices
import EventKit
import Photos

enum RequirementCategory: String, CaseIterable {
    case essential
    case notes
    case reminders
    case photos

    var title: String {
        switch self {
        case .essential: return "Essential"
        case .notes: return "Notes Sync"
        case .reminders: return "Reminders Sync"
        case .photos: return "Photos Sync"
        }
    }

    var subtitle: String {
        switch self {
        case .essential: return "Needed for iCloudBridge to run at all"
        case .notes: return "Needed only for Apple Notes sync"
        case .reminders: return "Needed only for Apple Reminders sync"
        case .photos: return "Needed only for Apple Photos sync"
        }
    }

    /// Only essentials stop the backend from starting. Everything else is a
    /// macOS permission for one sync feature, and can be skipped by anyone not
    /// using that feature.
    var isOptional: Bool {
        self != .essential
    }
}

/// An app the backend drives with AppleScript (`osascript`).
///
/// macOS attributes those Apple Events to iCloudBridge, as the app that
/// launched the backend, so this is where Automation access has to be granted.
/// Keep this in step with the `tell application` targets under
/// `icloudbridge/sources/`: a target missing here is one the user gets asked
/// about in the middle of a sync instead of during setup.
struct AutomationTarget {
    let appName: String
    let bundleIdentifier: String
    /// The key this target's access is recorded under in permissions.json.
    let permissionKey: String

    static let notes = AutomationTarget(appName: "Notes", bundleIdentifier: "com.apple.Notes", permissionKey: "notes_automation")
    static let photos = AutomationTarget(appName: "Photos", bundleIdentifier: "com.apple.Photos", permissionKey: "photos_app_automation")
}

/// `~/.icloudbridge/permissions.json`: which permissions setup last found
/// granted. The backend reads it to decide which sync features can be enabled.
enum PermissionsFile {
    static var url: URL {
        URL(fileURLWithPath: NSHomeDirectory())
            .appendingPathComponent(".icloudbridge", isDirectory: true)
            .appendingPathComponent("permissions.json")
    }

    static func read() -> [String: Bool] {
        guard let data = try? Data(contentsOf: url),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Bool] else {
            return [:]
        }
        return object
    }
}

enum Requirement: CaseIterable {
    case homebrew
    case xcodeCommandLineTools
    case python
    case ruby
    case fullDiskAccess
    case notesAutomation
    case remindersAutomation
    /// Photo library access through PhotoKit, used by the app itself.
    case photosAutomation
    /// Apple Events to Photos, used by the backend's AppleScript.
    case photosAppAutomation

    var title: String {
        switch self {
        case .homebrew: return "Homebrew"
        case .xcodeCommandLineTools: return "Xcode Command Line Tools"
        case .python: return "Python 3.12 (Homebrew)"
        case .ruby: return "Ruby >= 3.4 (Homebrew)"
        case .fullDiskAccess: return "Full Disk Access"
        case .notesAutomation: return "Notes Automation"
        case .remindersAutomation: return "Apple Reminders"
        case .photosAutomation: return "Photos Library"
        case .photosAppAutomation: return "Photos Automation"
        }
    }

    var category: RequirementCategory {
        switch self {
        case .homebrew, .xcodeCommandLineTools, .python, .ruby:
            return .essential
        case .fullDiskAccess, .notesAutomation:
            return .notes
        case .remindersAutomation:
            return .reminders
        case .photosAutomation, .photosAppAutomation:
            return .photos
        }
    }

    var isEssential: Bool {
        category == .essential
    }

    /// The app this requirement grants Automation (Apple Events) access to.
    var automationTarget: AutomationTarget? {
        switch self {
        case .notesAutomation: return .notes
        case .photosAppAutomation: return .photos
        default: return nil
        }
    }
}

enum RequirementState {
    case pending
    case checking
    case installing(String)
    case satisfied(String)
    case actionRequired(String)
    case failed(String)

    var isSatisfied: Bool {
        if case .satisfied = self { return true }
        return false
    }

    var isActionable: Bool {
        switch self {
        case .actionRequired, .failed:
            return true
        default:
            return false
        }
    }

    var message: String {
        switch self {
        case .pending: return "Pending"
        case .checking: return "Checking…"
        case .installing(let detail): return detail
        case .satisfied(let detail): return detail
        case .actionRequired(let detail): return detail
        case .failed(let detail): return detail
        }
    }
}

struct RequirementStatus {
    let requirement: Requirement
    var state: RequirementState
}

struct Semver: Comparable {
    private let parts: [Int]

    init(_ string: String) {
        let filtered = string.split(whereSeparator: { !$0.isNumber && $0 != "." })
        if let first = filtered.first {
            parts = first.split(separator: ".").compactMap { Int($0) }
        } else {
            parts = []
        }
    }

    static func < (lhs: Semver, rhs: Semver) -> Bool {
        let maxCount = max(lhs.parts.count, rhs.parts.count)
        for idx in 0..<maxCount {
            let l = idx < lhs.parts.count ? lhs.parts[idx] : 0
            let r = idx < rhs.parts.count ? rhs.parts[idx] : 0
            if l != r { return l < r }
        }
        return false
    }
}

struct ShellResult {
    let status: Int32
    let output: String
}

enum PreflightEvent {
    case statusesUpdated([RequirementStatus])
    case allSatisfied
}

final class Shell {
    /// Run a command, capturing stdout+stderr.
    ///
    /// `timeout` is a backstop, not a schedule: a child that outlives it is
    /// killed and the partial output returned. Without it, one wedged
    /// subprocess strands the installer's serial queue forever, and the setup
    /// window sits on whatever message it last drew with no way to recover.
    static func run(
        _ launchPath: String,
        _ arguments: [String],
        environment: [String: String] = [:],
        timeout: TimeInterval = 3600
    ) -> ShellResult {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: launchPath)
        task.arguments = arguments
        // Nothing here is interactive; give every child an immediate EOF so it
        // can never block waiting on input that will never arrive.
        task.standardInput = FileHandle.nullDevice
        var env = ProcessInfo.processInfo.environment
        environment.forEach { env[$0.key] = $0.value }
        task.environment = env

        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = pipe

        // Drain the pipe while the child runs, not after it exits. A pipe holds
        // about 64KB; once it fills, the child blocks writing and we block in
        // waitUntilExit(), and neither side ever moves again. `pip install` and
        // `bundle install` both produce far more than that, so reading after
        // waiting deadlocks the installer with no output and no error.
        var collected = Data()
        let lock = NSLock()
        let drained = DispatchSemaphore(value: 0)
        pipe.fileHandleForReading.readabilityHandler = { handle in
            let chunk = handle.availableData
            if chunk.isEmpty {
                handle.readabilityHandler = nil
                drained.signal()
                return
            }
            lock.lock()
            collected.append(chunk)
            lock.unlock()
        }

        do {
            try task.run()
        } catch {
            pipe.fileHandleForReading.readabilityHandler = nil
            return ShellResult(status: -1, output: "Failed to start: \(error.localizedDescription)")
        }
        // Enforce the timeout without blocking on waitUntilExit(), which cannot
        // be interrupted once entered.
        let exited = DispatchSemaphore(value: 0)
        task.terminationHandler = { _ in exited.signal() }

        var timedOut = false
        if exited.wait(timeout: .now() + timeout) == .timedOut {
            timedOut = true
            task.terminate()                                  // SIGTERM
            if exited.wait(timeout: .now() + 10) == .timedOut {
                kill(task.processIdentifier, SIGKILL)
                _ = exited.wait(timeout: .now() + 10)
            }
        }

        // Wait for EOF so no trailing output is lost, but don't hang forever if
        // a grandchild inherited the write end and is still holding it open.
        if drained.wait(timeout: .now() + 5) == .timedOut {
            pipe.fileHandleForReading.readabilityHandler = nil
        }

        lock.lock()
        var output = String(data: collected, encoding: .utf8) ?? ""
        lock.unlock()
        if timedOut {
            output += "\n[timed out after \(Int(timeout))s and was killed]"
            return ShellResult(status: -2, output: output)
        }
        return ShellResult(status: task.terminationStatus, output: output)
    }
}

final class PreflightManager {
    private let queue = DispatchQueue(label: "app.icloudbridge.preflight")
    // Permission requests block until the user answers the macOS prompt, so they
    // get their own queue rather than waiting behind (or holding up) installs.
    private let permissionQueue = DispatchQueue(label: "app.icloudbridge.preflight.permissions")
    private var statuses: [RequirementStatus] = Requirement.allCases.map { RequirementStatus(requirement: $0, state: .pending) }
    private var brewPath: String?
    private var installing = Set<Requirement>()
    private let defaults = UserDefaults.standard

    var onEvent: ((PreflightEvent) -> Void)?

    func currentStatuses() -> [RequirementStatus] {
        statuses
    }

    func runFullCheck() {
        update(.homebrew, state: .checking)
        update(.xcodeCommandLineTools, state: .checking)
        update(.python, state: .checking)
        update(.ruby, state: .checking)
        update(.fullDiskAccess, state: .checking)
        update(.notesAutomation, state: .checking)
        update(.remindersAutomation, state: .checking)
        update(.photosAutomation, state: .checking)
        update(.photosAppAutomation, state: .checking)

        queue.async { [weak self] in
            guard let self else { return }
            let brewState = self.checkHomebrew()
            self.update(.homebrew, state: brewState)

            let cltState = self.checkXcodeCommandLineTools()
            self.update(.xcodeCommandLineTools, state: cltState)
            if !cltState.isSatisfied { self.installIfNeeded(.xcodeCommandLineTools) }

            if brewState.isSatisfied {
                let pythonState = self.checkPython()
                self.update(.python, state: pythonState)
                if !pythonState.isSatisfied { self.installIfNeeded(.python) }

                if cltState.isSatisfied {
                    let rubyState = self.checkRuby()
                    self.update(.ruby, state: rubyState)
                    if !rubyState.isSatisfied { self.installIfNeeded(.ruby) }
                } else {
                    self.update(.ruby, state: .actionRequired("Install Xcode Command Line Tools before setting up Ruby"))
                }
            } else {
                self.update(.python, state: .actionRequired("Requires Homebrew to install python@3.12"))
                self.update(.ruby, state: .actionRequired("Requires Homebrew to install Ruby"))
                self.installIfNeeded(.homebrew)
            }

            self.checkPermissions()
        }
    }

    /// Re-check the macOS permissions, without prompting or touching installs.
    ///
    /// Full Disk Access is granted in System Settings, not through a prompt, so
    /// nothing tells us when it changes. The setup window calls this whenever it
    /// regains focus, which is when the user comes back from granting it.
    func refreshPermissions() {
        permissionQueue.async { [weak self] in
            self?.checkPermissions()
        }
    }

    /// Check-only: nothing here may show a prompt. The user asks for those with
    /// the row buttons, so a prompt never appears without an obvious cause.
    private func checkPermissions() {
        update(.fullDiskAccess, state: checkFullDiskAccess())
        update(.notesAutomation, state: checkAutomationPermission(for: .notes))
        update(.remindersAutomation, state: checkRemindersPermission(requestIfNeeded: false))
        update(.photosAutomation, state: checkPhotosPermission(requestIfNeeded: false))
        update(.photosAppAutomation, state: checkAutomationPermission(for: .photos))
    }

    func installHomebrew() {
        update(.homebrew, state: .installing("Installing Homebrew…"))
        queue.async { [weak self] in
            guard let self else { return }
            let script = "NONINTERACTIVE=1 /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
            let result = Shell.run("/bin/bash", ["-c", script])
            if result.status == 0 {
                self.brewPath = self.locateBrew()
                self.runFullCheck()
            } else {
                self.update(.homebrew, state: .failed("Homebrew install failed: \(result.output.trimmingCharacters(in: .whitespacesAndNewlines))"))
            }
        }
    }

    func installXcodeCommandLineTools() {
        update(.xcodeCommandLineTools, state: .installing("Requesting Command Line Tools install…"))
        queue.async { [weak self] in
            guard let self else { return }
            let result = Shell.run("/usr/bin/xcode-select", ["--install"])
            let output = result.output.trimmingCharacters(in: .whitespacesAndNewlines)
            // The installer returns a non-zero exit code even when it successfully prompts the user.
            if output.localizedCaseInsensitiveContains("already installed") {
                self.runFullCheck()
                return
            }

            if result.status == 0 || output.localizedCaseInsensitiveContains("install requested") {
                self.pollForXcodeCommandLineTools(start: Date())
            } else {
                self.update(.xcodeCommandLineTools, state: .failed("Command Line Tools install failed: \(output)"))
            }
        }
    }

    func installPython() {
        guard let brew = ensureBrew() else {
            update(.python, state: .actionRequired("Homebrew is required to install python@3.12"))
            return
        }
        update(.python, state: .installing("Installing python@3.12…"))
        queue.async { [weak self] in
            guard let self else { return }
            let result = Shell.run(brew, ["install", "python@3.12"], environment: ["HOMEBREW_NO_AUTO_UPDATE": "1", "NONINTERACTIVE": "1"])
            if result.status == 0 {
                self.runFullCheck()
            } else {
                self.update(.python, state: .failed("python@3.12 install failed: \(result.output.trimmingCharacters(in: .whitespacesAndNewlines))"))
            }
        }
    }

    func installRuby() {
        guard let brew = ensureBrew() else {
            update(.ruby, state: .actionRequired("Homebrew is required to install Ruby"))
            return
        }
        guard checkXcodeCommandLineTools().isSatisfied else {
            update(.ruby, state: .actionRequired("Install Xcode Command Line Tools first"))
            return
        }
        update(.ruby, state: .installing("Installing Ruby…"))
        queue.async { [weak self] in
            guard let self else { return }
            let result = Shell.run(brew, ["install", "ruby"], environment: ["HOMEBREW_NO_AUTO_UPDATE": "1", "NONINTERACTIVE": "1"])
            if result.status == 0 {
                self.runFullCheck()
            } else {
                self.update(.ruby, state: .failed("Ruby install failed: \(result.output.trimmingCharacters(in: .whitespacesAndNewlines))"))
            }
        }
    }

    private func pollForXcodeCommandLineTools(start: Date, attempt: Int = 0) {
        let state = checkXcodeCommandLineTools()
        if state.isSatisfied {
            update(.xcodeCommandLineTools, state: state)
            return
        }

        let elapsed = Date().timeIntervalSince(start)
        if elapsed > 900 {
            update(.xcodeCommandLineTools, state: .actionRequired("Command Line Tools install did not complete. Retry from Software Update."))
            return
        }

        let delay = min(15.0, 3.0 + Double(attempt))
        update(.xcodeCommandLineTools, state: .installing("Waiting for Command Line Tools to finish…"))
        queue.asyncAfter(deadline: .now() + delay) { [weak self] in
            self?.pollForXcodeCommandLineTools(start: start, attempt: attempt + 1)
        }
    }

    func openFullDiskAccessPreferences() {
        guard let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles") else { return }
        NSWorkspace.shared.open(url)
    }

    func openAutomationPreferences() {
        guard let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation") else { return }
        NSWorkspace.shared.open(url)
    }

    // MARK: Automation (Apple Events)

    /// Check Automation access to `target` without ever prompting.
    ///
    /// macOS can only answer for an app that is running, and opening Notes or
    /// Photos on every check would be a surprise of its own. When the app is
    /// closed, fall back to the last answer macOS gave; failing that, say so
    /// and leave it to Request Access, which opens the app first.
    private func checkAutomationPermission(for target: AutomationTarget) -> RequirementState {
        let status = determineAutomationPermission(for: target, askUserIfNeeded: false)
        guard Int(status) == procNotFound else {
            return automationState(for: status, target: target)
        }
        switch cachedAutomationDecision(for: target) {
        case true?:
            return automationState(for: OSStatus(noErr), target: target)
        case false?:
            return automationState(for: OSStatus(errAEEventNotPermitted), target: target)
        case nil:
            return .actionRequired("Not checked yet, as \(target.appName) isn't open. Click Request Access to open it in the background and ask")
        }
    }

    /// Ask for Automation access to the app behind `requirement`.
    ///
    /// This is the only place an Automation prompt is shown. `completion` runs
    /// on the main thread once macOS has an answer, unless the user was sent
    /// on to System Settings instead.
    func requestAutomation(for requirement: Requirement, completion: (() -> Void)? = nil) {
        guard let target = requirement.automationTarget else { return }
        update(requirement, state: .installing("Waiting for your answer to the macOS prompt…"))

        permissionQueue.async { [weak self] in
            guard let self else { return }
            var status = self.determineAutomationPermission(for: target, askUserIfNeeded: true)
            if Int(status) == procNotFound {
                self.update(requirement, state: .installing("Opening \(target.appName) in the background…"))
                status = self.launchAndRequestAutomation(for: target)
            }
            self.update(requirement, state: self.automationState(for: status, target: target))

            DispatchQueue.main.async {
                if Int(status) == errAEEventNotPermitted {
                    // Once denied, macOS never asks again; only System Settings can change it.
                    self.openAutomationPreferences()
                } else {
                    completion?()
                }
            }
        }
    }

    /// Launch `target` hidden and without activating it, so the setup window
    /// keeps focus, then ask.
    ///
    /// The app is left running; the backend starts it on every sync anyway.
    private func launchAndRequestAutomation(for target: AutomationTarget) -> OSStatus {
        guard let appURL = NSWorkspace.shared.urlForApplication(withBundleIdentifier: target.bundleIdentifier) else {
            return OSStatus(procNotFound)
        }

        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = false
        configuration.hides = true
        configuration.addsToRecentItems = false

        let launched = DispatchSemaphore(value: 0)
        DispatchQueue.main.async {
            NSWorkspace.shared.openApplication(at: appURL, configuration: configuration) { _, error in
                if let error {
                    NSLog("Could not open \(target.appName) to ask for Automation access: \(error.localizedDescription)")
                }
                launched.signal()
            }
        }
        _ = launched.wait(timeout: .now() + 30)

        // The launch can report success a moment before the app is registered to
        // receive Apple Events, and until then macOS still calls it not running.
        let deadline = Date().addingTimeInterval(15)
        var status = OSStatus(procNotFound)
        while Date() < deadline {
            status = determineAutomationPermission(for: target, askUserIfNeeded: true)
            if Int(status) != procNotFound { break }
            Thread.sleep(forTimeInterval: 0.5)
        }
        return status
    }

    /// Never call on the main thread with `askUserIfNeeded`: it blocks until
    /// the user answers the prompt.
    private func determineAutomationPermission(for target: AutomationTarget, askUserIfNeeded: Bool) -> OSStatus {
        let descriptor = NSAppleEventDescriptor(bundleIdentifier: target.bundleIdentifier)
        // Wildcards ask about every event: the backend sends many different
        // ones, and macOS grants Automation per app, not per event.
        let status = withExtendedLifetime(descriptor) {
            AEDeterminePermissionToAutomateTarget(descriptor.aeDesc, typeWildCard, typeWildCard, askUserIfNeeded)
        }
        recordAutomationDecision(status, for: target)
        return status
    }

    private func automationState(for status: OSStatus, target: AutomationTarget) -> RequirementState {
        switch Int(status) {
        case Int(noErr):
            return .satisfied("Allowed to control \(target.appName)")
        case errAEEventNotPermitted:
            return .actionRequired("Denied. Turn on \(target.appName) under iCloudBridge in System Settings > Privacy & Security > Automation")
        case errAEEventWouldRequireUserConsent:
            return .actionRequired("Not allowed yet. Click Request Access to let iCloudBridge control \(target.appName)")
        case procNotFound:
            return .failed("Could not open \(target.appName) to ask for access")
        default:
            return .failed("Could not check access to \(target.appName) (error \(status))")
        }
    }

    private func automationCacheKey(for target: AutomationTarget) -> String {
        "preflight.automation.\(target.bundleIdentifier)"
    }

    /// Remember macOS's last definitive answer, for checks made while the app is closed.
    private func recordAutomationDecision(_ status: OSStatus, for target: AutomationTarget) {
        let key = automationCacheKey(for: target)
        switch Int(status) {
        case Int(noErr):
            defaults.set(true, forKey: key)
        case errAEEventNotPermitted:
            defaults.set(false, forKey: key)
        case errAEEventWouldRequireUserConsent:
            // Undecided again, e.g. after `tccutil reset`.
            defaults.removeObject(forKey: key)
        default:
            break
        }
    }

    private func cachedAutomationDecision(for target: AutomationTarget) -> Bool? {
        let key = automationCacheKey(for: target)
        if defaults.object(forKey: key) != nil {
            return defaults.bool(forKey: key)
        }
        // Earlier versions checked Notes by scripting it, opening Notes on every
        // launch, and kept only the result in permissions.json. Trust a grant
        // recorded there, so an upgrade doesn't report Notes sync as missing a
        // permission just because Notes isn't open yet.
        if PermissionsFile.read()[target.permissionKey] == true {
            defaults.set(true, forKey: key)
            return true
        }
        return nil
    }

    private func update(_ requirement: Requirement, state: RequirementState) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            if let idx = self.statuses.firstIndex(where: { $0.requirement == requirement }) {
                self.statuses[idx].state = state
            }
            self.onEvent?(.statusesUpdated(self.statuses))

            if self.statuses.allSatisfy({ $0.state.isSatisfied }) {
                self.onEvent?(.allSatisfied)
            }
        }
    }

    private func installIfNeeded(_ requirement: Requirement) {
        guard !installing.contains(requirement) else { return }
        installing.insert(requirement)

        switch requirement {
        case .homebrew:
            installHomebrew()
        case .xcodeCommandLineTools:
            installXcodeCommandLineTools()
        case .python:
            installPython()
        case .ruby:
            installRuby()
        case .fullDiskAccess, .notesAutomation, .remindersAutomation, .photosAutomation, .photosAppAutomation:
            break
        }
    }

    @discardableResult
    private func checkHomebrew() -> RequirementState {
        if let path = locateBrew() {
            brewPath = path
            return .satisfied("Found Homebrew at \(path)")
        }
        return .actionRequired("Homebrew not found; required to install dependencies")
    }

    @discardableResult
    private func checkXcodeCommandLineTools() -> RequirementState {
        let result = Shell.run("/usr/bin/xcode-select", ["-p"])
        let path = result.output.trimmingCharacters(in: .whitespacesAndNewlines)
        if result.status == 0, !path.isEmpty {
            var isDir: ObjCBool = false
            if FileManager.default.fileExists(atPath: path, isDirectory: &isDir), isDir.boolValue {
                let clang = (path as NSString).appendingPathComponent("usr/bin/clang")
                if FileManager.default.isExecutableFile(atPath: clang) {
                    return .satisfied("Command Line Tools installed")
                }
                return .satisfied("Command Line Tools path found at \(path)")
            }
        }
        return .actionRequired("Install Xcode Command Line Tools (xcode-select --install)")
    }

    @discardableResult
    private func checkPython() -> RequirementState {
        guard let brew = ensureBrew() else {
            return .actionRequired("Install Homebrew first")
        }
        let result = Shell.run(brew, ["list", "--versions", "python@3.12"], environment: ["HOMEBREW_NO_AUTO_UPDATE": "1"])
        if result.status == 0, !result.output.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            let trimmedOutput = result.output.trimmingCharacters(in: .whitespacesAndNewlines)
            let components = trimmedOutput.split(separator: " ")
            let versionString = components.dropFirst().first.map(String.init) ?? ""
            let binDir = "/opt/homebrew/opt/python@3.12/bin"
            let py3 = "\(binDir)/python3"
            let py312 = "\(binDir)/python3.12"
            if FileManager.default.isExecutableFile(atPath: py3) || FileManager.default.isExecutableFile(atPath: py312) {
                return .satisfied("python@3.12 installed (\(versionString))")
            }
            return .actionRequired("python@3.12 not linked at expected path")
        }
        return .actionRequired("python@3.12 not installed")
    }

    @discardableResult
    private func checkRuby() -> RequirementState {
        guard let brew = ensureBrew() else {
            return .actionRequired("Install Homebrew first")
        }
        let result = Shell.run(brew, ["list", "--versions", "ruby"], environment: ["HOMEBREW_NO_AUTO_UPDATE": "1"])
        if result.status == 0, !result.output.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            let trimmedOutput = result.output.trimmingCharacters(in: .whitespacesAndNewlines)
            let parts = trimmedOutput.split(separator: " ")
            let versionString = parts.dropFirst().first.map(String.init) ?? ""
            let detected = Semver(versionString)
            if detected >= Semver("3.4.0") {
                let rubyPath = "/opt/homebrew/opt/ruby/bin/ruby"
                if FileManager.default.isExecutableFile(atPath: rubyPath) {
                    return .satisfied("Ruby installed (\(versionString))")
                }
                return .actionRequired("Ruby not linked at expected path")
            }
            return .actionRequired("Ruby \(versionString) found; need >= 3.4")
        }
        return .actionRequired("Ruby not installed")
    }

    @discardableResult
    private func checkFullDiskAccess() -> RequirementState {
        let notesPath = (NSHomeDirectory() as NSString).appendingPathComponent("Library/Group Containers/group.com.apple.notes")
        let fm = FileManager.default
        var isDir: ObjCBool = false
        if fm.fileExists(atPath: notesPath, isDirectory: &isDir), isDir.boolValue {
            do {
                _ = try fm.contentsOfDirectory(atPath: notesPath)
                return .satisfied("Notes data readable; Full Disk Access granted")
            } catch let error as NSError {
                if error.domain == NSCocoaErrorDomain && error.code == NSFileReadNoPermissionError {
                    return .actionRequired("Full Disk Access required to read Notes database")
                }
                return .failed("Could not verify Full Disk Access: \(error.localizedDescription)")
            }
        }
        // If Notes directory does not exist, treat as pass but surface message.
        return .satisfied("Notes database not found; Full Disk Access check passed")
    }

    private func locateBrew() -> String? {
        let candidates = ["/opt/homebrew/bin/brew", "/usr/local/bin/brew"]
        for path in candidates where FileManager.default.isExecutableFile(atPath: path) {
            return path
        }

        let which = Shell.run("/usr/bin/which", ["brew"])
        let path = which.output.trimmingCharacters(in: .whitespacesAndNewlines)
        return which.status == 0 && !path.isEmpty ? path : nil
    }

    private func ensureBrew() -> String? {
        if let brewPath { return brewPath }
        brewPath = locateBrew()
        return brewPath
    }

    private func checkRemindersPermission(requestIfNeeded: Bool) -> RequirementState {
        let status = EKEventStore.authorizationStatus(for: .reminder)
        switch status {
        case .authorized, .fullAccess:
            return .satisfied("Reminders permission granted")
        case .writeOnly:
            // The backend reads reminders, which write-only access does not allow
            return .actionRequired("Reminders access is add-only. Allow full access in System Settings > Privacy & Security > Reminders")
        case .notDetermined:
            if !requestIfNeeded {
                return .actionRequired("Allow Reminders access")
            }
            let store = EKEventStore()
            let semaphore = DispatchSemaphore(value: 0)
            var granted = false
            let completion: (Bool, Error?) -> Void = { ok, _ in
                granted = ok
                semaphore.signal()
            }
            // Full access, as the backend asks for; the older call is all macOS 13 has.
            if #available(macOS 14.0, *) {
                store.requestFullAccessToReminders(completion: completion)
            } else {
                store.requestAccess(to: .reminder, completion: completion)
            }
            // Only reached from requestRemindersAccess, off the main thread, so
            // give the user time to read the prompt. A late answer is still
            // picked up when the setup window next regains focus.
            _ = semaphore.wait(timeout: .now() + 300)
            return granted ? .satisfied("Reminders permission granted") : .actionRequired("Allow Reminders access")
        case .denied, .restricted:
            return .actionRequired("Allow Reminders access in System Settings > Privacy & Security > Reminders")
        @unknown default:
            return .failed("Unknown Reminders permission state")
        }
    }

    private func checkPhotosPermission(requestIfNeeded: Bool) -> RequirementState {
        let status = PHPhotoLibrary.authorizationStatus(for: .readWrite)
        switch status {
        case .authorized, .limited:
            return .satisfied("Photos permission granted")
        case .notDetermined:
            if !requestIfNeeded { return .actionRequired("Allow Photos access") }
            var result: PHAuthorizationStatus = .notDetermined
            let sema = DispatchSemaphore(value: 0)
            PHPhotoLibrary.requestAuthorization(for: .readWrite) { auth in
                result = auth
                sema.signal()
            }
            _ = sema.wait(timeout: .now() + 5)
            return (result == .authorized || result == .limited) ? .satisfied("Photos permission granted") : .actionRequired("Allow Photos access")
        case .denied, .restricted:
            return .actionRequired("Allow Photos access in System Settings > Privacy & Security > Photos")
        @unknown default:
            return .failed("Unknown Photos permission state")
        }
    }

    // User-initiated permission requests
    /// `completion` runs on the main thread once the prompt has been answered.
    func requestPhotosAutomation(completion: (() -> Void)? = nil) {
        DispatchQueue.main.async { [weak self] in
            PHPhotoLibrary.requestAuthorization(for: .readWrite) { auth in
                DispatchQueue.main.async {
                    guard let self else { return }
                    let finalState: RequirementState
                    if auth == .authorized || auth == .limited {
                        finalState = .satisfied("Photos permission granted")
                    } else {
                        finalState = .actionRequired("Allow Photos access in System Settings > Privacy & Security > Photos")
                    }
                    self.update(.photosAutomation, state: finalState)
                    completion?()
                }
            }
        }
    }

    /// `completion` runs on the main thread once the prompt has been answered.
    func requestRemindersAccess(completion: (() -> Void)? = nil) {
        // Waits for the user's answer, which must not block the main thread.
        permissionQueue.async { [weak self] in
            guard let self else { return }
            let state = self.checkRemindersPermission(requestIfNeeded: true)
            self.update(.remindersAutomation, state: state)
            DispatchQueue.main.async { completion?() }
        }
    }
}
