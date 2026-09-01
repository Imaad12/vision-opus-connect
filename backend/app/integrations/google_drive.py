"""Google Drive integration interface.

No authentication or real API calls are implemented yet — this module only
defines the shape that a future implementation will fulfil, so the rest of
the application (services, importers, UI) can be written against it now.

Google Drive is document storage only. The SQLite database
(`GoogleDriveDocument`, see `app/models/document.py`) holds structured
references to files here; it never holds file content, and no financial
figure is ever derived from a Drive file except through the normal
import/data-entry path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DriveFile:
    """Metadata about a file in Google Drive, as returned by the API."""

    file_id: str
    name: str
    mime_type: str
    web_link: str | None = None
    parent_folder_id: str | None = None


class GoogleDriveService(Protocol):
    """The operations the rest of the application needs from Google Drive.

    A concrete implementation (backed by `google-api-python-client` and
    OAuth2 credentials) will be added in a later phase. Until then,
    `NullGoogleDriveService` below lets calling code be written and tested
    against this interface.
    """

    def authenticate(self) -> None:
        """Establish credentials for subsequent calls."""
        ...

    def list_files(self, folder_id: str) -> list[DriveFile]:
        """List the files directly inside a Drive folder."""
        ...

    def search_files(self, query: str) -> list[DriveFile]:
        """Search Drive for files matching a query string."""
        ...

    def download_file(self, file_id: str, destination: Path) -> Path:
        """Download a file's content to a local path, returning that path."""
        ...

    def upload_file(self, source: Path, folder_id: str) -> DriveFile:
        """Upload a local file into a Drive folder, returning its metadata."""
        ...


class NullGoogleDriveService:
    """A placeholder implementation used until real Drive/OAuth is built.

    Every method raises `NotImplementedError` with a clear message, rather
    than silently returning empty results, so a caller relying on real
    Drive access fails loudly instead of behaving as if Drive is empty.
    """

    def authenticate(self) -> None:
        raise NotImplementedError("Google Drive authentication is not implemented yet")

    def list_files(self, folder_id: str) -> list[DriveFile]:
        raise NotImplementedError("Google Drive integration is not implemented yet")

    def search_files(self, query: str) -> list[DriveFile]:
        raise NotImplementedError("Google Drive integration is not implemented yet")

    def download_file(self, file_id: str, destination: Path) -> Path:
        raise NotImplementedError("Google Drive integration is not implemented yet")

    def upload_file(self, source: Path, folder_id: str) -> DriveFile:
        raise NotImplementedError("Google Drive integration is not implemented yet")
