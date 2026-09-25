# iCloudBridge

A small window into Apple's walled garden. Keep your Apple Notes, Reminders, Passwords and Photos in sync with other services. Mainly targeted towards Nextcloud (reminders, notes, photos) and Bitwarden/Vaultwarden (passwords) - however, can easily be used for any other services too.

> iCloudBridge is in no way affiliated with or endorsed by Apple, Inc.

> [!NOTE]
> <img width="200" height="auto" alt="friendly-manifesto-badge" src="https://github.com/user-attachments/assets/cb91210b-0f66-46fe-93a8-a3a67857593c" /> <br>
> This project voluntarily adheres to The Friendly Manifesto. Read more [here](https://friendlymanifesto.org)

## Features

- 🗒️ Apple Notes can be synced with a folder containing Markdown files. If using Nextcloud, this can then be synced to your instance and used via the Nextcloud Notes app. Supports images, URLs, attachments, folders, tags and checkboxes (TODO items).

- 📋 Apple Reminders can be synced with a CalDAV server, such as the one provided by Nextcloud. Supports due dates, alerts, priorities, URLs, notes, folders, recurring reminders & completion status.

- 📸 Apple Photos sync. This one is quite specific to Nextcloud. When the Nextcloud app is installed on iOS, it can automatically upload photos to Nextcloud - however - it is a one-way sync. Photos added on Nextcloud are not synced back to your Apple Photos library. iCloudBridge fixes this by downloading new photos from Nextcloud and adding them to Apple Photos. **Bidirectional sync** is also supported - export photos from Apple Photos (including shared family libraries) back to Nextcloud.

- 🔐 Apple Passwords can be synced with Bitwarden or Vaultwarden, or optionally Nextcloud passwords. Supports all common fields and TOTP codes. This is a manual sync, but iCloudBridge tries to make it as easy as possible.

## Limitations

- iCloudBridge requires a macOS machine to run on. The machine does not need to be always on, but the syncs will only run when it is powered on (duh!). A macOS VM is also possible, but not officially supported.

- Apple Notes: Checklists are supported, but a ticked item in your markdown can't be ticked in Apple Notes, because Apple provides no way to do it. Instead, iCloudBridge adds ✅ to the start of the line and leaves the item unticked. Sub-folders are supported, with one exception: a note with a checklist can't be synced into a folder that has the same name as another folder (for example `Work/Archive` and `Personal/Archive`). Rename one of the folders to sync it.

- Apple Photos: Sync is additive only - deletions or modifications are not synced. When importing, photos always go to your personal library (not shared library) - this is an Apple limitation. When exporting, the default "going forward" mode only exports new photos added after enabling export.

- Apple Passwords: At this time, only manual syncs are supported. No automatic or scheduled syncs. Passkeys are also not synced at this time. It is also recommended to use Bitwarden or Vaultwarden, as Nextcloud Passwords does not support TOTP. 

## Installation

Grab the latest release, then double-click!

## Usage

### WebUI
iCloudBridge features a web-based GUI. After launching the app, click on the menubar icon and select "Open Web UI". For documentation on how to use the WebUI, see the [User Guide](docs/user.md).

### Command Line
iCloudBridge can also be run from the command line. For documentation on how to use the command line interface, see the [Usage](docs/USAGE.md) guide.

## Development & Contribution

iCloudBridge is a one-man show - I basically built this to scratch my own itch. However, if you find it useful and would like to contribute, please feel free to open issues or pull requests on GitHub.

### Tech Stack

- **Backend**: Python 3.11+ with FastAPI. The app ships the backend source and runs it in its own Python environment, built from Homebrew's `python@3.12`
- **Frontend**: React + TypeScript with Vite, TailwindCSS, and shadcn/ui components
- **Desktop App**: Swift-based macOS menubar app
- **Build Tool**: Just command runner for task automation
- **Apple Integration**: AppleScript, Shortcuts and Apple Cloud Notes Parser (Ruby) for Notes; PyObjC (EventKit) for Reminders; AppleScript and PhotoKit (via the menubar app) for Photos; CSV import/export for Passwords

### Prerequisites

Before you begin, ensure you have:

- **macOS 13.0+** (Ventura or later)
- **Xcode Command Line Tools**: Install with `xcode-select --install`
- **Python >= 3.11**: `brew install python3`
- **Poetry**: Python dependency management - `pipx install poetry`
- **Node.js 20.19+**: `brew install node`
- **Ruby >= 3.4**: For Notes Ripper - `brew install ruby`
- **Just**: Command runner - `brew install just`

Quick install (Homebrew):
```bash
brew install python3 node just ruby pipx
pipx install poetry
just install
```

### Getting Started

1. **Clone the repository**

   ```bash
   git clone https://github.com/keithvassallomt/icloudbridge.git
   cd icloudbridge
   ```

2. **Install dependencies**

   ```bash
   # Install backend, frontend and Notes Ripper dependencies
   just install
   ```

3. **Run the development environment**

   Open two terminal windows/tabs:

   **Terminal 1 - Backend (FastAPI server with hot reload)**:
   ```bash
   just dev
   ```
   Backend runs on `http://localhost:8000` with `/api/*` and WebSocket at `/api/ws`

   **Terminal 2 - Frontend (Vite dev server)**:
   ```bash
   npm --prefix frontend run dev
   ```
   Frontend runs on `http://localhost:3000` with API proxy to backend

   Navigate to `http://localhost:3000` in your browser to see the WebUI.

4. **Optional: Activate the Poetry environment**

   For running ad-hoc commands or debugging:
   ```bash
   eval $(poetry env activate)
   ```

### Development Workflow

#### Code Quality

Before committing, ensure your code passes quality checks:

```bash
# Run linter
just lint

# Auto-format code
just format

# Run tests
just test
```

#### Building the App

iCloudBridge offers several build configurations:

**Debug Build (ad-hoc signed, no DMG)**:
```bash
just build-debug
```
Output: `build/Release/iCloudBridge.app`

**Production Build (Developer ID signed, no DMG)**:
```bash
just build
```
Output: `build/Release/iCloudBridge.app`

Both builds write to the same folder, so each one replaces the other.

**Full Release (signed + notarized DMG)**:
```bash
just release
```
Output: `build/Release/iCloudBridge.dmg`

#### Cleaning Build Artifacts

```bash
just clean
```
Removes `build/`, `dist/`, DMG files, and Python cache.

#### Verifying Code Signing

After building a production app:
```bash
just verify-signing
```
Validates code signature and Gatekeeper acceptance.

### Project Structure

```
icloudbridge/
├── icloudbridge/          # Python backend source
│   ├── api/              # FastAPI routes, WebSocket and scheduler
│   ├── cli/              # Command-line interface
│   ├── core/             # Sync engines (notes, reminders, photos, passwords)
│   ├── sources/          # Adapters for Apple apps and remote services
│   └── utils/            # Databases, credentials, converters and other helpers
├── frontend/             # React frontend
│   ├── src/
│   │   ├── components/   # React components
│   │   ├── pages/        # Page components
│   │   ├── hooks/        # Custom hooks
│   │   ├── lib/          # Utilities and API client
│   │   └── store/        # Zustand state management
│   └── public/           # Static assets
├── macos/                # macOS menubar app
│   └── MenubarApp/       # Swift menubar application
├── tools/                # Notes Ripper (Ruby) and Notes database copy helper
├── tests/                # pytest suite
├── scripts/              # Build and automation scripts
├── docs/                 # User documentation
├── justfile              # Task runner configuration
└── pyproject.toml        # Python dependencies
```

### Key Components

**Sync Engines** (`icloudbridge/core/`):
- `sync.py` - Apple Notes ↔ Markdown, using AppleScript, Shortcuts and the Notes Ripper
- `reminders_sync.py` - Apple Reminders ↔ CalDAV, using EventKit
- `photos_sync.py` - Imports photos into Apple Photos using AppleScript
- `photos_export_engine.py` - Exports photos from the Photos library, fetching iCloud-only photos through PhotoKit
- `passwords_sync.py` - Apple Passwords ↔ Bitwarden/Vaultwarden/Nextcloud Passwords, via CSV

**Frontend Pages**:
- Dashboard, Notes, Reminders, Photos, Passwords, Schedules, Logs, Settings

**API Endpoints**:
- REST API at `/api/*` for CRUD operations
- WebSocket at `/api/ws` for real-time sync updates

### Debugging Tips

1. **Backend logs**: Backend server logs appear in the terminal running `just dev`
2. **Frontend debugging**: Use React DevTools and browser console
3. **WebSocket issues**: Check WebSocket connection status in the sidebar footer
4. **Build issues**: Try `just clean` before rebuilding
5. **Permission errors**: Ensure Full Disk Access is granted in System Settings > Privacy & Security

### Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Make your changes
4. Run quality checks: `just lint && just test`
5. Commit your changes: `git commit -m 'Add amazing feature'`
6. Push to the branch: `git push origin feature/amazing-feature`
7. Open a Pull Request

**Note**: All PRs should pass linting and tests before merging.

### Release Process

For maintainers creating a release:

1. Update the version in `pyproject.toml` and the frontend (`npm --prefix frontend version <x.y.z> --no-git-tag-version`), and move the `changelog.md` entries under a heading for the new version
2. Build and notarize: `just release`
3. Create GitHub release with `build/Release/iCloudBridge.dmg`
4. Update documentation site if needed

## Acknowledgements

iCloudBridge uses some existing open-source code created by the fantastic community. In particular:

- [Apple Cloud Notes Parser](https://github.com/threeplanetssoftware/apple_cloud_notes_parser) - a fantastic project which decodes as much as possible of Apple's arcane Notes format.
- [/u/z1ts](https://www.reddit.com/user/z1ts/) on Reddit, who created a fantastic sample Apple Shortcut for how to add rich content to Apple Notes (see their [Reddit Post](https://www.reddit.com/r/shortcuts/comments/1h54bkh/notes_checkbox_lists_rtf_md_pics_links_etc/)). 

## Disclaimer

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

