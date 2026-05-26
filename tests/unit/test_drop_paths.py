from __future__ import annotations

from pathlib import Path

from vhsdecode.drop_paths import extract_dropped_file_paths


class _DummyUrl:
    def __init__(self, *, local_file: str | None = None, uri: str = ""):
        self._local_file = local_file
        self._uri = uri

    def isLocalFile(self) -> bool:
        return self._local_file is not None

    def toLocalFile(self) -> str:
        return self._local_file or ""

    def toString(self) -> str:
        return self._uri


class _DummyMimeData:
    def __init__(self, *, urls: list[_DummyUrl] | None = None, text: str = ""):
        self._urls = urls or []
        self._text = text

    def hasUrls(self) -> bool:
        return bool(self._urls)

    def urls(self) -> list[_DummyUrl]:
        return list(self._urls)

    def hasText(self) -> bool:
        return bool(self._text)

    def text(self) -> str:
        return self._text


def test_extract_paths_merges_urls_and_text_and_filters_directories(tmp_path: Path):
    rf_path = tmp_path / "capture.rf"
    json_path = tmp_path / "params.json"
    dropped_dir = tmp_path / "drop-folder"
    rf_path.write_text("rf")
    json_path.write_text("{}")
    dropped_dir.mkdir()

    mime_data = _DummyMimeData(
        urls=[
            _DummyUrl(local_file=str(rf_path)),
            _DummyUrl(local_file=str(dropped_dir)),
        ],
        text="\n".join([rf_path.as_uri(), json_path.as_uri()]),
    )

    assert extract_dropped_file_paths(mime_data) == [str(rf_path), str(json_path)]


def test_extract_paths_handles_uppercase_file_uri_and_clipboard_metadata(
    tmp_path: Path,
):
    rf_path = tmp_path / "capture one.rf"
    rf_path.write_text("rf")
    uri_text = rf_path.as_uri().replace("file://", "FILE://", 1)
    mime_data = _DummyMimeData(
        text=f"# ignored metadata\ncopy\n\"{uri_text}\"",
    )

    assert extract_dropped_file_paths(mime_data) == [str(rf_path)]


def test_extract_paths_handles_null_delimited_plain_text(tmp_path: Path):
    first = tmp_path / "first.rf"
    second = tmp_path / "second.rf"
    first.write_text("1")
    second.write_text("2")

    mime_data = _DummyMimeData(text=f"{first}\x00{second}\x00")

    assert extract_dropped_file_paths(mime_data) == [str(first), str(second)]


def test_extract_paths_normalizes_windows_drive_file_uri():
    mime_data = _DummyMimeData(text="file:///C:/Users/Harry/Capture%201.rf")

    assert extract_dropped_file_paths(
        mime_data,
        os_name="nt",
        platform="win32",
    ) == ["C:/Users/Harry/Capture 1.rf"]


def test_extract_paths_keeps_windows_unc_paths():
    mime_data = _DummyMimeData(text="file://server/share/Capture%201.rf")

    assert extract_dropped_file_paths(
        mime_data,
        os_name="nt",
        platform="win32",
    ) == ["//server/share/Capture 1.rf"]


def test_extract_paths_ignores_non_file_uris(tmp_path: Path):
    rf_path = tmp_path / "capture.rf"
    rf_path.write_text("rf")
    mime_data = _DummyMimeData(
        text="\n".join(["https://example.com/capture.rf", str(rf_path)]),
    )

    assert extract_dropped_file_paths(mime_data) == [str(rf_path)]
