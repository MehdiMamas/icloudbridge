set shell := ["zsh", "-c"]

# Install dependencies
install:
	poetry install
	cd frontend && npm install
	cd tools/notes_cloud_ripper && bundle install

# Install only main dependencies (no dev tools)
install-main:
	poetry install --only main
	cd frontend && npm install
	cd tools/notes_cloud_ripper && bundle install

# Clean all build artifacts
clean:
	rm -rf build/ dist/
	rm -f *.dmg 2>/dev/null || true
	rm -rf frontend/dist frontend/node_modules/.cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

# Build app bundle only (debug/ad-hoc signed)
build-debug:
	python3 scripts/build_release.py --skip-dmg

# Build app bundle + DMG (debug/ad-hoc signed)
release-debug:
	python3 scripts/build_release.py

# Build app bundle only (production signed with Developer ID)
build:
	python3 scripts/build_release.py --production --skip-dmg

# Build app bundle + DMG with notarization (production signed)
release:
	python3 scripts/build_release.py --production --notarize

# Removes the app, data, settings, Keychain items and macOS permissions, for testing
# a first run. Synced notes and photos are left alone. `just --yes nuke` skips the question.
[doc("Wipe all iCloudBridge state and permissions, then install a fresh debug build")]
[confirm("This deletes the installed iCloudBridge app, all of its data, its Keychain items and its macOS permissions. Continue?")]
nuke:
	#!/usr/bin/env zsh
	set -eu
	bundles=(app.icloudbridge.menubar app.icloudbridge.loginhelper)

	echo "==> Stopping iCloudBridge"
	pkill -x iCloudBridgeMenubar 2>/dev/null || true
	lsof -ti tcp:27731 2>/dev/null | xargs kill 2>/dev/null || true
	for job in app.icloudbridge.loginhelper com.icloudbridge.server; do
		launchctl bootout "gui/$(id -u)/$job" 2>/dev/null || true
	done

	echo "==> Removing the app, data, logs, caches and preferences"
	rm -rf /Applications/iCloudBridge.app \
		~/.icloudbridge ~/.icloudbridge_settings.db \
		~/Library/"Application Support"/iCloudBridge \
		~/Library/iCloudBridge \
		~/Library/Logs/iCloudBridge \
		~/Library/LaunchAgents/com.icloudbridge.server.plist
	for bundle in $bundles; do
		defaults delete "$bundle" 2>/dev/null || true
		rm -rf ~/Library/Caches/"$bundle" ~/Library/HTTPStorages/"$bundle" ~/Library/WebKit/"$bundle" \
			~/Library/"Saved Application State"/"$bundle".savedState
	done

	echo "==> Removing Keychain items"
	while security delete-generic-password -s iCloudBridge >/dev/null 2>&1; do :; done

	echo "==> Revoking macOS permissions"
	for bundle in $bundles; do
		tccutil reset All "$bundle" >/dev/null 2>&1 || true
	done

	echo "==> Building the debug app"
	python3 scripts/build_release.py --skip-dmg
	ditto build/Release/iCloudBridge.app /Applications/iCloudBridge.app
	echo "==> Installed /Applications/iCloudBridge.app"

# Run the development server
dev:
	poetry run dev-server

# Run tests
test:
	poetry run pytest

# Run linter
lint:
	poetry run ruff check .

# Format code
format:
	poetry run ruff format .

# Verify code signing of built app
verify-signing:
	codesign -vvv --deep --strict build/Release/iCloudBridge.app
	spctl -a -vvv build/Release/iCloudBridge.app
       
