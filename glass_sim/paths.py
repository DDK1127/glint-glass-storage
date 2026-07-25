from __future__ import annotations

from pathlib import Path


def repository_root_for_config(path: str | Path) -> Path:
    config_path = Path(path).expanduser().resolve()
    for parent in config_path.parents:
        if parent.name == "experiments":
            return parent.parent
    return Path.cwd()


def portable_path(path: str | Path) -> str:
    resolved = Path(path).expanduser().resolve()
    candidates = (Path.cwd().resolve(), Path(__file__).resolve().parents[1])
    for repository_root in candidates:
        if not (repository_root / "pyproject.toml").is_file():
            continue
        try:
            return str(resolved.relative_to(repository_root))
        except ValueError:
            continue
    return str(resolved)
