from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


def _strip_wrapping_quotes(value: str) -> str:
    trimmed = value.strip()
    if (
        len(trimmed) >= 2
        and trimmed[0] == trimmed[-1]
        and trimmed[0] in {"\"", "'"}
    ):
        return trimmed[1:-1].strip()
    return trimmed


def _is_file_uri(candidate: str) -> bool:
    return candidate.casefold().startswith("file:")


def _is_windows_drive_path(path: str) -> bool:
    return len(path) >= 3 and path[1] == ":" and path[0].isalpha()


def _file_uri_to_local_path(candidate: str, *, os_name: str) -> str | None:
    split = urlsplit(candidate)
    if split.scheme.casefold() != "file":
        return None

    netloc = split.netloc.strip()
    path = unquote(split.path or split.netloc or "")

    if netloc and netloc.casefold() != "localhost":
        path = f"//{netloc}{unquote(split.path or '')}"

    if os_name == "nt" and len(path) >= 3 and path[0] == "/" and _is_windows_drive_path(path[1:]):
        path = path[1:]

    return path.strip() or None


def _iter_text_drop_candidates(raw_text: str):
    normalized = (
        raw_text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\x00", "\n")
    )
    for line in normalized.split("\n"):
        candidate = _strip_wrapping_quotes(line)
        if not candidate:
            continue
        lower_candidate = candidate.casefold()
        if candidate.startswith("#"):
            continue
        if lower_candidate in {"copy", "cut"}:
            continue
        yield candidate


def _path_dedupe_key(path: str, *, os_name: str, platform: str) -> str:
    if os_name == "nt" or platform.startswith("darwin"):
        return path.casefold()
    return path


def _paths_from_mime_urls(mime_data, *, os_name: str) -> list[str]:
    paths: list[str] = []
    for url in mime_data.urls():
        local_path = ""
        try:
            if url.isLocalFile():
                local_path = str(url.toLocalFile()).strip()
        except Exception:
            local_path = ""
        if local_path:
            paths.append(local_path)
            continue

        uri_candidate = ""
        to_string = getattr(url, "toString", None)
        if callable(to_string):
            try:
                uri_candidate = str(to_string()).strip()
            except Exception:
                uri_candidate = ""
        local_path = (
            _file_uri_to_local_path(uri_candidate, os_name=os_name)
            if uri_candidate
            else None
        )
        if local_path:
            paths.append(local_path)
    return paths


def extract_dropped_file_paths(
    mime_data,
    *,
    os_name: str | None = None,
    platform: str | None = None,
) -> list[str]:
    if mime_data is None:
        return []

    os_name = os_name or os.name
    platform = platform or sys.platform

    paths: list[str] = []

    if mime_data.hasUrls():
        paths.extend(_paths_from_mime_urls(mime_data, os_name=os_name))

    if mime_data.hasText():
        raw_text = str(mime_data.text() or "")
        for candidate in _iter_text_drop_candidates(raw_text):
            if _is_file_uri(candidate):
                local_path = _file_uri_to_local_path(candidate, os_name=os_name)
                if local_path:
                    paths.append(local_path)
                continue
            if "://" in candidate:
                continue
            paths.append(candidate)

    deduped_paths: list[str] = []
    seen: set[str] = set()
    for path in paths:
        expanded = str(Path(path).expanduser())
        key = _path_dedupe_key(expanded, os_name=os_name, platform=platform)
        if key in seen:
            continue
        seen.add(key)
        as_path = Path(expanded)
        if as_path.exists() and as_path.is_dir():
            continue
        deduped_paths.append(expanded)
    return deduped_paths
