from pathlib import Path

from app.importers import build_default_registry

SUPPORTED = ["pdf", "xlsx", "xlsm", "xlsb", "xls", "docx", "doc", "csv", "txt", "png", "jpg", "jpeg", "tif", "tiff"]


def test_registry_finds_an_importer_for_every_supported_extension() -> None:
    registry = build_default_registry()
    for extension in SUPPORTED:
        importer = registry.find_for(Path(f"document.{extension}"))
        assert importer is not None, f"No importer registered for .{extension}"


def test_registry_returns_none_for_unsupported_extension() -> None:
    registry = build_default_registry()
    assert registry.find_for(Path("document.dwg")) is None
    assert registry.find_for(Path("document.zip")) is None


def test_registry_is_case_insensitive_on_extension() -> None:
    registry = build_default_registry()
    assert registry.find_for(Path("QUOTE.PDF")) is not None
    assert registry.find_for(Path("Quote.Xlsx")) is not None
