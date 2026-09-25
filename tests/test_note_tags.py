"""Hashtags in markdown become real Apple Notes tags via the Upsert Shortcut."""
from __future__ import annotations

import plistlib
import subprocess

import pytest

from icloudbridge.core.sync import NotesSyncEngine
from icloudbridge.sources.notes import shortcuts
from icloudbridge.sources.notes.shortcuts import NotesShortcutAdapter, shortcut_version_from_actions
from icloudbridge.utils.converters import extract_hashtags


@pytest.mark.parametrize(
    ("markdown", "body", "tags"),
    [
        ("Tagged with #icbtest", "Tagged with", ["icbtest"]),
        ("#a #b\nBody\n\nEnds #c.", "Body\n\nEnds.", ["a", "b", "c"]),
        ("#One and #one", "and", ["One"]),
        ("# Heading\nIssue #18, page#top, [x](#anchor)", "# Heading\nIssue #18, page#top, [x](#anchor)", []),
        ("`#code` and #real", "`#code` and", ["real"]),
        ("```\n#fenced\n```\n#after", "```\n#fenced\n```", ["after"]),
    ],
)
def test_extract_hashtags(markdown, body, tags):
    assert extract_hashtags(markdown) == (body, tags)


def comment_actions(text: str) -> bytes:
    return plistlib.dumps(
        [{"WFWorkflowActionIdentifier": "is.workflow.actions.comment", "WFWorkflowActionParameters": {"WFCommentActionText": text}}]
    )


def test_shortcut_version_marker():
    assert shortcut_version_from_actions(comment_actions("iCloudBridge version: 2\nUsage...")) == 2
    assert shortcut_version_from_actions(comment_actions("Here's how to run this")) == 1
    assert shortcut_version_from_actions(b"not a plist") == 1


def test_upsert_input_omits_empty_tags(monkeypatch):
    sent = []

    def fake_run(cmd, input=None, **kwargs):
        sent.append(input)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(shortcuts.subprocess, "run", fake_run)
    adapter = NotesShortcutAdapter()
    adapter._run_upsert("Work", "Plan", [])
    adapter._run_upsert("Work", "Plan", ["alpha", "beta"])

    assert sent == ["Work;;Plan", "Work;;Plan;;alpha,beta"]


class FakeNotes:
    """Just enough of Notes.app for the Shortcuts pull path."""

    def __init__(self) -> None:
        self.notes: dict[str, str] = {}

    def is_ignored_folder(self, name: str) -> bool:
        return False

    async def list_folders(self, include_unsyncable: bool = False):
        from icloudbridge.sources.notes.applescript import AppleScriptFolder

        return [AppleScriptFolder(uuid="f", name="iCloud/Work")]

    async def refresh_rich_cache(self) -> None:
        pass

    def clear_rich_cache(self, *, cleanup_workspace: bool = False) -> None:
        pass

    async def get_notes(self, folder: str):
        return []

    async def get_recently_deleted_notes(self):
        return []

    async def find_notes_by_name(self, folder: str, name: str) -> list[str]:
        return [uuid for uuid, title in self.notes.items() if title == name]


class FakeShortcuts:
    def __init__(self, notes: FakeNotes, supports: bool) -> None:
        self.notes, self.supports = notes, supports
        self.upserts: list[tuple[str, str, list[str]]] = []
        self.appended: list[str] = []

    def supports_tags(self) -> bool:
        return self.supports

    async def upsert_note(self, folder: str, title: str, tags: list[str] | None = None) -> None:
        self.upserts.append((folder, title, tags or []))
        self.notes.notes[f"note-{len(self.upserts)}"] = title

    async def append_content(self, folder: str, title: str, markdown: str) -> None:
        self.appended.append(markdown)


@pytest.mark.parametrize("supports", [True, False])
async def test_pull_moves_hashtags_into_tags_only_when_supported(tmp_path, supports):
    engine = NotesSyncEngine(markdown_base_path=tmp_path / "md", db_path=tmp_path / "notes.db")
    await engine.initialize()
    notes = FakeNotes()
    engine.notes_adapter = notes
    engine.shortcuts = FakeShortcuts(notes, supports)
    path = tmp_path / "md/Work/Plan.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Plan\n\nShip it #release #q3\n", encoding="utf-8")

    await engine.sync_folder("iCloud/Work", markdown_subfolder="Work")

    (folder, title, tags), = engine.shortcuts.upserts
    assert (folder, title) == ("Work", "Plan")
    appended = "\n".join(engine.shortcuts.appended)
    if supports:
        assert tags == ["release", "q3"]
        assert "#release" not in appended and "Ship it" in appended
    else:
        assert tags == []
        assert "#release" in appended


def test_shortcut_payload_file_is_plain_text(monkeypatch):
    """Without an extension, a payload full of Python imports reads as a script,
    and the Shortcut gets the file's name instead of its text."""
    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(shortcuts.subprocess, "run", fake_run)
    NotesShortcutAdapter()._run_file_shortcut(
        NotesShortcutAdapter.APPEND_CONTENT_SHORTCUT, "Linux Hacks", "Wacom", "from evdev import InputDevice\n"
    )

    input_path = commands[0][commands[0].index("--input-path") + 1]
    assert input_path.endswith(".txt")
