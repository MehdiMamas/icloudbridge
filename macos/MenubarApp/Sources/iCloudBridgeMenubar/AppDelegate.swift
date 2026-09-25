import Cocoa

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let backendManager = BackendProcessManager()
    private let launchAgentManager = LaunchAgentManager()
    private let photoKitBridge = PhotoKitBridge()
    private var preflightCoordinator: PreflightCoordinator?
    private var menuController: MenuController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMainMenu()

        // Started before the backend so the handshake file is in place by the
        // time the first photo sync looks for it.
        photoKitBridge.start()

        let coordinator = PreflightCoordinator(backendManager: backendManager)
        preflightCoordinator = coordinator
        photoKitBridge.onPermissionRequest = { [weak coordinator] service in
            coordinator?.requestPermissions(for: service) ?? false
        }
        menuController = MenuController(
            backendManager: backendManager,
            launchAgentManager: launchAgentManager,
            preflightCoordinator: coordinator
        )
        coordinator.start()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        // Menubar app should keep running even when its preflight window closes.
        return false
    }

    func applicationWillTerminate(_ notification: Notification) {
        backendManager.stop()
        photoKitBridge.stop()
    }

    /// The app is a regular one, with the menu bar, while the setup window is
    /// open (see PreflightWindowController). Give it the standard app and
    /// Window menus so it doesn't show an empty menu bar and Cmd-Q, Cmd-H and
    /// Cmd-M behave as expected.
    private func installMainMenu() {
        let mainMenu = NSMenu()

        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Hide iCloudBridge", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let hideOthers = appMenu.addItem(withTitle: "Hide Others", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        hideOthers.keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(withTitle: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit iCloudBridge", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let appItem = NSMenuItem()
        appItem.submenu = appMenu
        mainMenu.addItem(appItem)

        let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        let windowItem = NSMenuItem()
        windowItem.submenu = windowMenu
        mainMenu.addItem(windowItem)

        NSApp.mainMenu = mainMenu
        NSApp.windowsMenu = windowMenu
    }
}
