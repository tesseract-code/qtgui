"""
workspace_layout.py
-------------------
WorkspaceLayoutManager — handles all save/restore logic for WorkspaceManager.

Responsibilities
----------------
- Owns the ``_dynamic_panels`` mapping (``panel_id → Path``).
- Writes and reads the sidecar JSON file that accompanies every layout file.
- Patches the DockManager's ``save_layout_to_file`` /
  ``restore_layout_from_file`` so the sidecar is kept in sync even when the
  built-in View-menu shortcuts (Ctrl+Shift+S / Ctrl+Shift+R) trigger those
  methods directly.
- Restores code-editor tabs after a layout rebuild.

What it does *not* do
---------------------
- It does not know how to create viewer widgets — that stays in
  ``WorkspaceManager._create_widget_for_path``.
- It does not manage ``_open_paths`` directly; after a restore it calls the
  ``on_paths_restored`` callback so the workspace can update its own
  duplicate-detection set.

Sidecar schema
--------------
::

    {
        "__editor__": {
            "files":  ["<abs_path>", ...],   // open tabs, left-to-right
            "active": <int>                   // current tab index
        },
        "<panel_id>": "<abs_path>",           // dynamic viewer panels
        ...
    }

Typical usage
-------------
::

    layout_mgr = WorkspaceLayoutManager(
        dock_manager   = self._dock_manager,
        code_editor    = self._code_editor,
        open_in_editor = self._open_in_editor,
        on_paths_restored = lambda paths: self._open_paths.update(paths),
    )

    # Later:
    layout_mgr.save_layout("workspace.json")
    layout_mgr.restore_layout("workspace.json")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from qtgui.file.code.editor import CodeEditorWidget, CodeEditor
from qtdisplay.dock.mngr import DockManager

# Sidecar suffix appended to the layout file path.
_PANELS_SUFFIX = ".panels.json"


class WorkspaceLayoutManager:
    """
    Encapsulates all layout-persistence logic for a WorkspaceManager.

    Parameters
    ----------
    dock_manager:
        The DockManager whose ``save_layout_to_file`` /
        ``restore_layout_from_file`` will be patched and called.
    code_editor:
        The workspace's CodeEditorWidget; its open tabs are included in the
        sidecar so they survive a save/restore cycle.
    open_in_editor:
        Callable that opens a ``Path`` in the code editor.  Called for every
        file tab that needs to be restored.  Keeping this as an injected
        callback avoids a circular dependency on WorkspaceManager.
    on_paths_restored:
        Optional callable that receives the ``set[Path]`` of all dynamic-panel
        paths after a restore completes.  Lets the workspace keep its own
        ``_open_paths`` duplicate-detection set up to date.
    """

    def __init__(
        self,
        dock_manager: DockManager,
        code_editor: CodeEditorWidget,
        open_in_editor: Callable[[Path], None],
        on_paths_restored: Callable[[set[Path]], None] | None = None,
    ) -> None:
        self._dock_manager = dock_manager
        self._code_editor = code_editor
        self._open_in_editor = open_in_editor
        self._on_paths_restored = on_paths_restored

        # panel_id → Path for every dynamically opened file panel.
        self._dynamic_panels: dict[str, Path] = {}

        self._patch_dock_manager()

    # ── public API ────────────────────────────────────────────────────────────

    @property
    def dynamic_panels(self) -> dict[str, Path]:
        """
        Live mapping of ``panel_id → Path`` for all open dynamic panels.

        WorkspaceManager writes to this dict when a new file panel is opened
        so the manager can persist it on the next save.
        """
        return self._dynamic_panels

    def save_layout(self, path: str | Path) -> None:
        """
        Save the dock layout *and* the dynamic-panel / editor-tab state.

        Two files are written:
        - ``path``               — the DockManager tab/split layout
        - ``path.panels.json``   — sidecar with panel paths and editor tabs
        """
        layout_path = Path(path)
        self._dock_manager.save_layout_to_file(layout_path)
        # _patch_dock_manager already wires the sidecar write into
        # save_layout_to_file, so the call above is sufficient.  The explicit
        # delegation here exists only to provide a clean public entry point.

    def restore_layout(self, path: str | Path) -> None:
        """
        Restore the dock layout *and* recreate all dynamic panels from disk.

        Load order:

        1. ``_dynamic_panels`` is populated from the sidecar JSON so the
           panel provider has the path map ready *before* the DockManager
           calls it for each dynamic panel.
        2. ``restore_layout_from_file`` rebuilds the layout; for every dynamic
           panel ID the provider calls back into WorkspaceManager to recreate
           the actual widget.
        3. ``on_paths_restored`` is fired so the workspace can sync its
           duplicate-detection set.
        """
        self._dock_manager.restore_layout_from_file(Path(path))
        # _patch_dock_manager already wires steps 1–3 into
        # restore_layout_from_file, so the call above is sufficient.

    # ── DockManager patching ──────────────────────────────────────────────────

    def _patch_dock_manager(self) -> None:
        """
        Wrap DockManager's I/O methods so the sidecar is always kept in sync.

        This ensures that the View-menu shortcuts (Ctrl+Shift+S /
        Ctrl+Shift+R), which call the underlying methods directly, also
        trigger sidecar reads and writes.
        """
        dm = self._dock_manager
        _original_save = dm.save_layout_to_file
        _original_restore = dm.restore_layout_from_file

        def _save_with_sidecar(path: str | Path) -> None:
            _original_save(path)
            self._write_sidecar(Path(path))

        def _restore_with_sidecar(path: str | Path) -> None:
            layout_path = Path(path)
            # Populate path map BEFORE the DockManager calls the panel provider.
            editor_state = self._read_sidecar(layout_path)
            _original_restore(path)
            if self._on_paths_restored is not None:
                self._on_paths_restored(set(self._dynamic_panels.values()))
            # Reopen code-editor tabs AFTER the layout has been rebuilt.
            self._restore_editor_tabs(editor_state)

        dm.save_layout_to_file = _save_with_sidecar
        dm.restore_layout_from_file = _restore_with_sidecar

    # ── sidecar I/O ───────────────────────────────────────────────────────────

    @staticmethod
    def _sidecar_path(layout_path: Path) -> Path:
        """Return the companion JSON path for a given layout file path."""
        return layout_path.with_suffix(layout_path.suffix + _PANELS_SUFFIX)

    def _write_sidecar(self, layout_path: Path) -> None:
        """
        Persist ``_dynamic_panels`` and the code-editor tab list.

        Writes the sidecar JSON file adjacent to *layout_path*.
        """
        tabs = self._code_editor.tabs
        editor_files: list[str] = [
            str(Path(ed.filepath).resolve())
            for i in range(tabs.count())
            if (ed := tabs.widget(i)) and getattr(ed, "filepath", None)
        ]

        data: dict = {
            "__editor__": {
                "files": editor_files,
                "active": tabs.currentIndex(),
            },
            **{pid: str(p.resolve()) for pid, p in self._dynamic_panels.items()},
        }

        sidecar = self._sidecar_path(layout_path)
        sidecar.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _read_sidecar(self, layout_path: Path) -> dict:
        """
        Reload ``_dynamic_panels`` from the sidecar JSON file.

        Must be called *before* ``restore_layout_from_file`` so the panel
        provider has the path map ready.  Missing or malformed sidecar files
        are silently ignored; dynamic panels will simply not be restored.

        Returns the editor-state sub-dict (or ``{}``) so the caller can
        reopen code-editor tabs after the layout is rebuilt.
        """
        sidecar = self._sidecar_path(layout_path)
        if not sidecar.exists():
            return {}
        try:
            data: dict = json.loads(sidecar.read_text(encoding="utf-8"))
            editor_state: dict = data.pop("__editor__", {})
            self._dynamic_panels = {
                pid: Path(p) for pid, p in data.items() if isinstance(p, str)
            }
            return editor_state
        except Exception:
            # Corrupt sidecar — start clean rather than crashing.
            self._dynamic_panels = {}
            return {}

    # ── editor-tab restore ────────────────────────────────────────────────────

    def _restore_editor_tabs(self, editor_state: dict) -> None:
        """
        Reopen code-editor tabs described by *editor_state*.

        Called after the DockManager layout is rebuilt so the editor widget
        is already embedded and visible.  Tabs whose files no longer exist on
        disk are silently skipped.
        """
        files: list[str] = editor_state.get("files", [])
        active: int = editor_state.get("active", 0)

        for fp in files:
            path = Path(fp)
            if path.exists():
                self._open_in_editor(path)

        tabs = self._code_editor.tabs
        if 0 <= active < tabs.count():
            tabs.setCurrentIndex(active)