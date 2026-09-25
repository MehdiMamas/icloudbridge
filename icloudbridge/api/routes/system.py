"""System and utility endpoints."""

import json
import logging
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request, HTTPException, status
from pydantic import BaseModel

from icloudbridge import __version__
from icloudbridge.api.dependencies import ConfigDep
from icloudbridge.api.models import (
    SetupVerificationResponse,
    ShortcutStatus,
    FullDiskAccessStatus,
    NotesFolderStatus,
    PermissionRequest,
    PermissionsResponse,
    ServicePermissionStatus,
)
from icloudbridge.sources.notes.shortcuts import UPSERT_TAGS_VERSION, installed_shortcut_version
from icloudbridge.sources.photos.photokit_bridge import PhotoKitBridgeClient, PhotoKitUnavailable
from icloudbridge.utils.db import SettingsDB
from icloudbridge.utils.logging import set_logging_level

logger = logging.getLogger(__name__)

router = APIRouter()


class LogLevelPayload(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


@router.get("/db-paths")
async def get_database_paths(config: ConfigDep) -> dict:
    """Get all database file locations.

    Returns:
        Dictionary with database paths for notes, reminders, and passwords,
        including existence status for each.
    """
    config.ensure_data_dir()

    notes_db = config.general.data_dir / "notes.db"
    reminders_db = config.general.data_dir / "reminders.db"
    passwords_db = config.general.data_dir / "passwords.db"

    return {
        "notes_db": str(notes_db),
        "reminders_db": str(reminders_db),
        "passwords_db": str(passwords_db),
        "metadata": {
            "notes_exists": notes_db.exists(),
            "reminders_exists": reminders_db.exists(),
            "passwords_exists": passwords_db.exists(),
        }
    }


@router.get("/info")
async def get_system_info(config: ConfigDep) -> dict:
    """Get system information and application metadata.

    Returns:
        System and application information including version,
        platform details, and configuration path.
    """
    return {
        "version": __version__,
        "platform": platform.system(),
        "platform_version": platform.version(),
        "python_version": platform.python_version(),
        "data_dir": str(config.general.data_dir),
    }


@router.get("/log-level")
async def get_log_level(config: ConfigDep) -> dict:
    """Return the current runtime log level."""

    settings_db = SettingsDB(config.general.data_dir / "settings.db")
    await settings_db.initialize()
    level = await settings_db.get_setting("log_level")
    return {"log_level": level or config.general.log_level}


@router.put("/log-level")
async def update_log_level(payload: LogLevelPayload, config: ConfigDep) -> dict:
    """Update the runtime log level and persist the preference."""

    try:
        settings_db = SettingsDB(config.general.data_dir / "settings.db")
        await settings_db.initialize()
        await settings_db.set_setting("log_level", payload.level)
        set_logging_level(payload.level)
        logger.info(f"Log level changed to {payload.level}")
        return {"log_level": payload.level}
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Failed to update log level: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update log level",
        )


@router.get("/verify", response_model=SetupVerificationResponse)
async def verify_setup(request: Request, config: ConfigDep) -> SetupVerificationResponse:
    """Verify system setup and requirements for Notes sync.

    Checks:
    - Required Apple Shortcuts installation status
    - Full Disk Access for Python interpreter
    - Notes folder existence and writability
    - Whether request is from localhost

    Returns:
        Complete setup verification status
    """
    # Define required shortcuts
    # Note: "shortcut_name" is the actual name returned by `shortcuts list`
    # "display_name" is the user-friendly name shown in the UI
    REQUIRED_SHORTCUTS = [
        {
            "shortcut_name": "iCloudBridge_Upsert_Note",
            "display_name": "iCloudBridge - Create Note",
            "url": "https://www.icloud.com/shortcuts/7584390a886648d6b43b6ab1e150021d",
            "version": UPSERT_TAGS_VERSION,
            "update_note": "Keeps note tags when notes sync back from your markdown folder.",
        },
        {
            "shortcut_name": "iCloudBridge_Append_Content_To_Note",
            "display_name": "iCloudBridge - Add Note Content",
            "url": "https://www.icloud.com/shortcuts/9360561e13714bfb9183c76e732a2b4d",
        },
        {
            "shortcut_name": "iCloudBridge_Append_Checklist_To_Note",
            "display_name": "iCloudBridge - Note Todo Manager",
            "url": "https://www.icloud.com/shortcuts/e98b25e5519d44138a647e6db7b4782c",
        },
    ]

    # Check installed shortcuts
    installed_shortcuts = set()
    try:
        result = subprocess.run(
            ["shortcuts", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            installed_shortcuts = set(line.strip() for line in result.stdout.splitlines())
            logger.info(f"Found {len(installed_shortcuts)} installed shortcuts")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning(f"Failed to list shortcuts: {e}")

    shortcut_statuses = []
    for shortcut in REQUIRED_SHORTCUTS:
        installed = shortcut["shortcut_name"] in installed_shortcuts
        update_available = False
        if installed and "version" in shortcut:
            version = installed_shortcut_version(shortcut["shortcut_name"])
            update_available = version is not None and version < shortcut["version"]
        shortcut_statuses.append(
            ShortcutStatus(
                name=shortcut["display_name"],
                installed=installed,
                url=shortcut["url"],
                update_available=update_available,
                update_note=shortcut.get("update_note") if update_available else None,
            )
        )

    # Check Full Disk Access by trying to read Notes database
    python_path = sys.executable
    notes_db_path = Path.home() / "Library/Group Containers/group.com.apple.notes/NoteStore.sqlite"
    has_fda = False

    try:
        if notes_db_path.exists():
            # Try to read the file - will fail without FDA
            with open(notes_db_path, "rb") as f:
                f.read(1)  # Read just 1 byte
            has_fda = True
            logger.info("Full Disk Access verified - can read Notes database")
        else:
            logger.warning(f"Notes database not found at: {notes_db_path}")
    except (PermissionError, OSError) as e:
        logger.warning(f"No Full Disk Access - cannot read Notes database: {e}")
        has_fda = False

    fda_status = FullDiskAccessStatus(
        has_access=has_fda,
        python_path=python_path,
        notes_db_path=str(notes_db_path) if notes_db_path.exists() else None,
    )

    # Check notes folder
    notes_folder_path = config.notes.remote_folder
    folder_exists = False
    folder_writable = False

    if notes_folder_path:
        notes_folder_path = Path(notes_folder_path).expanduser()
        folder_exists = notes_folder_path.exists()

        if folder_exists:
            # Test writability
            try:
                test_file = notes_folder_path / ".icloudbridge_write_test"
                test_file.touch()
                test_file.unlink()
                folder_writable = True
                logger.info(f"Notes folder is writable: {notes_folder_path}")
            except (PermissionError, OSError) as e:
                logger.warning(f"Notes folder not writable: {e}")
                folder_writable = False

    notes_folder_status = NotesFolderStatus(
        exists=folder_exists,
        writable=folder_writable,
        path=str(notes_folder_path) if notes_folder_path else None,
    )

    # Check if request is from localhost
    client_host = request.client.host if request.client else None
    is_localhost = client_host in ("127.0.0.1", "::1", "localhost") if client_host else False

    # Determine if all requirements are met
    all_shortcuts_installed = all(s.installed for s in shortcut_statuses)
    all_ready = (
        all_shortcuts_installed
        and has_fda
        and folder_exists
        and folder_writable
    )

    return SetupVerificationResponse(
        shortcuts=shortcut_statuses,
        full_disk_access=fda_status,
        notes_folder=notes_folder_status,
        is_localhost=is_localhost,
        all_ready=all_ready,
    )


def _check_reminders_live() -> bool | None:
    """Query EventKit for the current Reminders authorization status.

    Returns True if access is granted, False if explicitly denied/restricted,
    or None when the result is indeterminate (e.g. EventKit unavailable,
    permission not yet determined). Callers should treat None as "fall back
    to the cached value from permissions.json".

    EKAuthorizationStatus values: 0=notDetermined, 1=restricted, 2=denied,
    3=authorized/fullAccess (reminders), 4=writeOnly (Sonoma calendar).
    """
    try:
        from EventKit import EKEntityTypeReminder, EKEventStore
    except ImportError:
        return None
    try:
        status = EKEventStore.authorizationStatusForEntityType_(EKEntityTypeReminder)
    except Exception as exc:
        logger.warning("Live reminders permission check failed: %s", exc)
        return None
    if status == 0:
        return None
    return status in (3, 4)


def _check_full_disk_access_live() -> bool | None:
    """Probe Full Disk Access by attempting to read the Notes database.

    Returns True/False when the probe succeeds or fails with a permission
    error, or None if the Notes DB doesn't exist (can't probe).
    """
    notes_db = Path.home() / "Library/Group Containers/group.com.apple.notes/NoteStore.sqlite"
    if not notes_db.exists():
        return None
    try:
        with open(notes_db, "rb") as f:
            f.read(1)
        return True
    except (PermissionError, OSError):
        return False


@router.post("/permissions/request")
async def request_permissions(body: PermissionRequest) -> dict[str, str]:
    """Show the macOS prompts for a service's missing permissions.

    Only the menubar app can show them, so this asks it over its loopback
    bridge and returns straight away. The answers land in permissions.json,
    so poll GET /permissions for the outcome.
    """
    try:
        await PhotoKitBridgeClient().request_permissions(body.service)
    except PhotoKitUnavailable as exc:
        logger.warning("Permission request for %s failed: %s", body.service, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The iCloudBridge menu bar app isn't reachable, so it can't ask macOS for "
                "permissions. Make sure it's running, then try again."
            ),
        ) from exc
    return {"status": "requested"}


@router.get("/permissions", response_model=PermissionsResponse)
async def get_permissions(config: ConfigDep) -> PermissionsResponse:
    """Get per-service permission availability.

    Reads permission states persisted by the macOS preflight window and,
    where possible, overrides them with live macOS queries so that grants
    made after the last Preflight cycle are reflected immediately.
    """
    permissions_file = config.general.data_dir / "permissions.json"

    perms: dict[str, bool] = {}
    if permissions_file.exists():
        try:
            perms = json.loads(permissions_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read permissions.json: %s", exc)

    fda = perms.get("full_disk_access", False)
    notes_auto = perms.get("notes_automation", False)
    reminders_auto = perms.get("reminders_automation", False)
    photos_auto = perms.get("photos_automation", False)
    photos_app_auto = perms.get("photos_app_automation", False)

    live_fda = _check_full_disk_access_live()
    if live_fda is not None:
        fda = live_fda

    live_reminders = _check_reminders_live()
    if live_reminders is not None:
        reminders_auto = live_reminders

    # Notes requires both permissions
    notes_missing: list[str] = []
    if not fda:
        notes_missing.append("Full Disk Access")
    if not notes_auto:
        notes_missing.append("Apple Notes automation")

    reminders_missing: list[str] = []
    if not reminders_auto:
        reminders_missing.append("Apple Reminders access")

    photos_missing: list[str] = []
    if not photos_auto:
        photos_missing.append("Apple Photos access")
    if not photos_app_auto:
        photos_missing.append("Apple Photos automation")

    return PermissionsResponse(
        notes=ServicePermissionStatus(
            permitted=not bool(notes_missing),
            missing=notes_missing,
        ),
        reminders=ServicePermissionStatus(
            permitted=not bool(reminders_missing),
            missing=reminders_missing,
        ),
        photos=ServicePermissionStatus(
            permitted=not bool(photos_missing),
            missing=photos_missing,
        ),
        passwords=ServicePermissionStatus(permitted=True, missing=[]),
    )


@router.get("/browse-folders")
async def browse_folders(path: str = "~") -> dict:
    """Browse server filesystem for folder selection.

    Args:
        path: Path to browse (defaults to user home directory)

    Returns:
        Dictionary containing current path, parent path, and list of subdirectories

    Security:
        - Does not expose hidden system directories
        - Returns only directories, not files
    """
    try:
        # Expand and resolve the path
        browse_path = Path(path).expanduser().resolve()
        home_path = Path.home().resolve()

        # Check if path exists and is a directory
        if not browse_path.exists() or not browse_path.is_dir():
            browse_path = home_path

        # Get parent directory (or None if at root)
        parent_path = None
        if browse_path.parent != browse_path:  # Not at filesystem root
            parent_path = str(browse_path.parent)

        # List subdirectories (excluding hidden directories)
        folders = []
        try:
            for item in sorted(browse_path.iterdir()):
                # Skip hidden directories (starting with .)
                if item.name.startswith('.'):
                    continue
                # Only include directories
                if item.is_dir():
                    folders.append({
                        "name": item.name,
                        "path": str(item),
                    })
        except PermissionError:
            logger.warning(f"Permission denied browsing: {browse_path}")

        return {
            "current_path": str(browse_path),
            "parent_path": parent_path,
            "folders": folders,
            "is_home": browse_path == home_path,
        }

    except Exception as e:
        logger.error(f"Error browsing folders: {e}")
        # Return home directory as fallback
        home_path = Path.home()
        return {
            "current_path": str(home_path),
            "parent_path": None,
            "folders": [],
            "is_home": True,
            "error": str(e),
        }
