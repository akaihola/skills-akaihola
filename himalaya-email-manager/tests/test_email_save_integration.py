#!/usr/bin/env python3
"""Integration tests for email_save.py with real functionality."""

import json
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, patch, call
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from email_save import _download_attachments_internal, save


class TestDownloadAttachmentsInternal:
    """Test _download_attachments_internal() function with mocked subprocess."""

    def test_attachments_moved_to_specified_directory(self, tmp_path):
        """Verify attachments are moved to specified directory."""
        message_id = 57039
        folder = "INBOX"

        himalaya_output = dedent("""\
            Downloading "obf_attachment_001.png"…
            Downloading "obf_attachment_002.png"…
            Downloading "obf_attachment_003.png"…
            Downloading "obf_attachment_004.png"…
            Downloading "obf_attachment_005.png"…
            """)

        moved_files = []

        def mock_move(src, dst):
            moved_files.append((Path(src), Path(dst)))

        with (
            patch("email_save.subprocess.run") as mock_run,
            patch("email_save.shutil.move", side_effect=mock_move),
            patch("pathlib.Path.mkdir"),
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=["himalaya"],
                returncode=0,
                stdout="",
                stderr=himalaya_output,
            )

            result = _download_attachments_internal(
                message_id, folder, tmp_path, verbose=False
            )

            assert len(result) == 5
            assert all(isinstance(f, Path) for f in result)
            assert len(moved_files) == 5

            for src, dst in moved_files:
                assert dst.parent == tmp_path
                assert "obf_attachment" in dst.name

    def test_attachments_default_to_current_directory(self, tmp_path):
        """Verify attachments move to current directory when dir specified."""
        message_id = 57039
        folder = "INBOX"

        himalaya_output = dedent("""\
            Downloading "obf_img_001.png"…
            Downloading "obf_img_002.png"…
            Downloading "obf_img_003.png"…
            """)

        moved_files = []

        def mock_move(src, dst):
            moved_files.append((Path(src), Path(dst)))

        with (
            patch("email_save.subprocess.run") as mock_run,
            patch("email_save.shutil.move", side_effect=mock_move),
            patch("pathlib.Path.mkdir"),
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=["himalaya"],
                returncode=0,
                stdout="",
                stderr=himalaya_output,
            )

            result = _download_attachments_internal(
                message_id, folder, tmp_path, verbose=False
            )

            assert len(result) == 3
            for src, dst in moved_files:
                assert dst.parent == tmp_path

    def test_no_attachments_returns_empty_list(self, tmp_path):
        """Verify empty list when no attachments found."""
        message_id = 57039
        folder = "INBOX"

        himalaya_output = ""

        with (
            patch("email_save.subprocess.run") as mock_run,
            patch("email_save.shutil.move") as mock_move,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=["himalaya"],
                returncode=0,
                stdout="",
                stderr=himalaya_output,
            )

            result = _download_attachments_internal(
                message_id, folder, tmp_path, verbose=False
            )

            assert result == []
            mock_move.assert_not_called()

    def test_attachment_dir_creation(self, tmp_path):
        """Verify attachment directory is created if it doesn't exist."""
        attachment_dir = tmp_path / "subdir" / "attachments"
        message_id = 57039
        folder = "INBOX"

        himalaya_output = 'Downloading "obf_file.png"…\n'

        with (
            patch("email_save.subprocess.run") as mock_run,
            patch("email_save.shutil.move"),
            patch.object(Path, "mkdir") as mock_mkdir,
            patch.object(Path, "exists", return_value=False),
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=["himalaya"],
                returncode=0,
                stdout="",
                stderr=himalaya_output,
            )

            _download_attachments_internal(
                message_id, folder, attachment_dir, verbose=False
            )

            mock_mkdir.assert_called_once()

    def test_attachment_names_preserved(self, tmp_path):
        """Verify attachment names are preserved from himalaya output."""
        message_id = 57039
        folder = "INBOX"

        himalaya_output = dedent("""\
            Downloading "obf_spreadsheet.xlsx"…
            Downloading "obf_document.pdf"…
            """)

        moved_files = []

        def mock_move(src, dst):
            moved_files.append((Path(src), Path(dst)))

        with (
            patch("email_save.subprocess.run") as mock_run,
            patch("email_save.shutil.move", side_effect=mock_move),
            patch("pathlib.Path.mkdir"),
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=["himalaya"],
                returncode=0,
                stdout="",
                stderr=himalaya_output,
            )

            result = _download_attachments_internal(
                message_id, folder, tmp_path, verbose=False
            )

            assert len(result) == 2
            assert "spreadsheet.xlsx" in str(result[0])
            assert "document.pdf" in str(result[1])


class TestSaveCommandAttachmentBehavior:
    """Test save() command with attachment downloading."""

    def test_effective_attachment_dir_defaults_to_current(self):
        """Verify effective_attachment_dir defaults to current directory (issue #11)."""
        test_envelope = {
            "from": {"name": "Jane Smith", "address": "jane@example.org"},
            "to": {"name": "Recipient", "address": "recipient@example.org"},
            "date": "2026-01-17 10:30:00",
            "subject": "Obfuscated Test Email",
            "id": "57039",
        }
        test_body = "This is obfuscated test content."
        test_folder = "INBOX"

        downloaded_attachments = [Path("obf_img_001.png"), Path("obf_img_002.png")]

        captured_attachment_dir = None

        def capture_download_attachments(msg_id, folder, attach_dir, verbose):
            nonlocal captured_attachment_dir
            captured_attachment_dir = attach_dir
            return downloaded_attachments

        with (
            patch("email_save.get_message") as mock_get_message,
            patch(
                "email_save._download_attachments_internal",
                side_effect=capture_download_attachments,
            ),
            patch("email_save.generate_filename", return_value="57039.md"),
            patch("pathlib.Path.exists", return_value=False),
            patch("pathlib.Path.write_text"),
            patch("email_save.console"),
        ):
            mock_get_message.return_value = {
                "envelope": test_envelope,
                "body": test_body,
            }

            save(
                message_id=57039,
                folder=test_folder,
                output=None,
                format="markdown",
                date_prefix=False,
                overwrite=False,
                download_attachments=True,
                attachment_dir=None,
                verbose=False,
            )

            assert captured_attachment_dir == Path(".")

    def test_explicit_attachment_dir_respected(self):
        """Verify explicit attachment_dir is used when specified."""
        test_envelope = {
            "from": {"name": "Jane", "address": "jane@example.org"},
            "to": {"address": "recipient@example.org"},
            "date": "2026-01-17",
            "subject": "Test",
            "id": "12345",
        }
        test_body = "Obfuscated content."
        custom_dir = Path("/tmp/obf_custom_attachments")

        captured_attachment_dir = None

        def capture_download_attachments(msg_id, folder, attach_dir, verbose):
            nonlocal captured_attachment_dir
            captured_attachment_dir = attach_dir
            return [Path("obf_file.txt")]

        with (
            patch("email_save.get_message") as mock_get_message,
            patch(
                "email_save._download_attachments_internal",
                side_effect=capture_download_attachments,
            ),
            patch("email_save.generate_filename", return_value="12345.md"),
            patch("pathlib.Path.exists", return_value=False),
            patch("pathlib.Path.write_text"),
            patch("email_save.console"),
        ):
            mock_get_message.return_value = {
                "envelope": test_envelope,
                "body": test_body,
            }

            save(
                message_id=12345,
                folder="INBOX",
                output=None,
                format="markdown",
                date_prefix=False,
                overwrite=False,
                download_attachments=True,
                attachment_dir=custom_dir,
                verbose=False,
            )

            assert captured_attachment_dir == custom_dir

    def test_no_download_when_flag_false(self):
        """Verify attachments are not downloaded when flag is False."""
        test_envelope = {
            "from": {"address": "jane@example.org"},
            "to": {"address": "recipient@example.org"},
            "date": "2026-01-17",
            "subject": "Test",
            "id": "12345",
        }
        test_body = "Content."

        with (
            patch("email_save.get_message") as mock_get_message,
            patch("email_save._download_attachments_internal") as mock_download,
            patch("email_save.generate_filename", return_value="12345.md"),
            patch("pathlib.Path.exists", return_value=False),
            patch("pathlib.Path.write_text"),
            patch("email_save.console"),
        ):
            mock_get_message.return_value = {
                "envelope": test_envelope,
                "body": test_body,
            }

            save(
                message_id=12345,
                folder="INBOX",
                output=None,
                format="markdown",
                date_prefix=False,
                overwrite=False,
                download_attachments=False,
                attachment_dir=None,
                verbose=False,
            )

            mock_download.assert_not_called()

    def test_format_markdown_with_attachments(self):
        """Verify markdown formatting includes attachment list."""
        test_envelope = {
            "from": {"name": "Jane", "address": "jane@example.org"},
            "to": {"address": "recipient@example.org"},
            "date": "2026-01-17",
            "subject": "Test Email",
            "id": "12345",
        }
        test_body = "This is obfuscated test content."
        attachments = [Path("obf_img_001.png"), Path("obf_doc.pdf")]

        with (
            patch("email_save.get_message") as mock_get_message,
            patch(
                "email_save._download_attachments_internal", return_value=attachments
            ),
            patch("email_save.generate_filename", return_value="12345.md"),
            patch("pathlib.Path.exists", return_value=False),
            patch.object(Path, "write_text") as mock_write,
            patch("email_save.console"),
        ):
            mock_get_message.return_value = {
                "envelope": test_envelope,
                "body": test_body,
            }

            save(
                message_id=12345,
                folder="INBOX",
                output=None,
                format="markdown",
                date_prefix=False,
                overwrite=False,
                download_attachments=True,
                attachment_dir=None,
                verbose=False,
            )

            call_args = mock_write.call_args
            written_content = call_args[0][0]
            assert "obf_img_001.png" in written_content
            assert "obf_doc.pdf" in written_content
            assert "Attachments:" in written_content
