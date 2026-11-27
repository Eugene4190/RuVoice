"""Resolve bundled and source-checkout paths for the local RuVoice book tool."""
from __future__ import annotations

import sys
from pathlib import Path

WORKFLOW_RELATIVE = Path("experiments") / "ruvoice-stress-dictionary"


def resolve_app_paths(
    module_file: str | Path,
    *,
    frozen: bool | None = None,
    bundle_root: str | Path | None = None,
) -> tuple[Path, Path]:
    """Return (repository_root, workflow_dir) in source and PyInstaller builds."""
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if is_frozen:
        root_value = bundle_root
        if root_value is None:
            root_value = getattr(sys, "_MEIPASS", None)
        if root_value is None:
            raise RuntimeError("Не удалось определить каталог ресурсов Windows-сборки RuVoice.")
        root = Path(root_value).resolve()
        return root, root / WORKFLOW_RELATIVE

    workflow_dir = Path(module_file).resolve().parent
    return workflow_dir.parents[1], workflow_dir
