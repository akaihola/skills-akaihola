#!/usr/bin/env python3
"""Integration tests for email_save.py with real functionality."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from email_save import _download_attachments_internal, save


class TestDownloadAttachmentsInternal:
    """Exercise staged downloads without a mailbox or a himalaya binary."""

    def test_attachments_copied_from_private_directory(self, tmp_path) -> None:
        """Use directory entries rather than paths claimed by the download log."""
        destination = tmp_path / "subdir" / "attachments"
        outside = tmp_path / "outside.txt"
        outside.write_text("original")
        staging_paths = []

        def download(args, *, verbose=False):
            staging = Path(args[args.index("-d") + 1])
            staging_paths.append(staging)
            (staging / "document.pdf").write_text("synthetic attachment")
            return subprocess.CompletedProcess(args, 0, f'Downloading "{outside}"…', "")

        with patch("email_save.run_himalaya", side_effect=download):
            result = _download_attachments_internal(57039, "INBOX", destination)

        assert result == [destination / "document.pdf"]
        assert result[0].read_text() == "synthetic attachment"
        assert outside.read_text() == "original"
        assert not staging_paths[0].exists()

    def test_default_attachment_directory(self, tmp_path, monkeypatch) -> None:
        """Default downloads stay in a folder named after the message ID."""
        monkeypatch.chdir(tmp_path)

        def download(args, *, verbose=False):
            (Path(args[args.index("-d") + 1]) / "document.pdf").write_text("synthetic")
            return subprocess.CompletedProcess(args, 0, "", "")

        with patch("email_save.run_himalaya", side_effect=download):
            result = _download_attachments_internal(57039, "INBOX", None)
        assert result == [tmp_path / "57039-attachments" / "document.pdf"]

    def test_no_attachments_returns_empty_list(self, tmp_path) -> None:
        """An empty download directory produces no attachments."""
        with patch("email_save.run_himalaya"):
            assert _download_attachments_internal(57039, "INBOX", tmp_path) == []


class TestSaveCommandAttachmentBehavior:
    """Test save() command with attachment downloading."""

    def test_attachment_folder_defaults_to_message_id_when_output_none(
        self,
    ) -> None:
        """Default attachments stay in the message folder beside the saved email."""
        test_envelope = {
            "from": {"name": "Unknown sender", "address": "sender@example.org"},
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
                output_format="markdown",
                date_prefix=False,
                overwrite=False,
                download_attachments=True,
                attachment_dir=None,
                verbose=False,
            )

            assert captured_attachment_dir == Path("57039-attachments")

    def test_explicit_attachment_dir_respected(self) -> None:
        """Verify explicit attachment_dir is used when specified."""
        test_envelope = {
            "from": {"name": "Unknown sender", "address": "sender@example.org"},
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
                output_format="markdown",
                date_prefix=False,
                overwrite=False,
                download_attachments=True,
                attachment_dir=custom_dir,
                verbose=False,
            )

            assert captured_attachment_dir == custom_dir

    def test_no_download_when_flag_false(self) -> None:
        """Verify attachments are not downloaded when flag is False."""
        test_envelope = {
            "from": {"address": "sender@example.org"},
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
                output_format="markdown",
                date_prefix=False,
                overwrite=False,
                download_attachments=False,
                attachment_dir=None,
                verbose=False,
            )

            mock_download.assert_not_called()

    def test_attachments_default_to_output_directory(self) -> None:
        """Default attachment folders live beside the saved email."""
        test_envelope = {
            "from": {"name": "Unknown sender", "address": "sender@example.org"},
            "to": {"address": "recipient@example.org"},
            "date": "2026-01-17",
            "subject": "Obfuscated Test Email",
            "id": "57039",
        }
        test_body = (
            '<#part type=image/png filename="/home/user/Downloads/image.png"><#/part>'
        )
        output_dir = Path("/tmp/saved-emails")
        downloaded_attachments = [output_dir / "image.png"]

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
                folder="INBOX",
                output=output_dir,
                output_format="markdown",
                date_prefix=False,
                overwrite=False,
                download_attachments=True,
                attachment_dir=None,
                verbose=False,
            )

            assert captured_attachment_dir == output_dir / "57039-attachments"

    def test_format_markdown_with_attachments(self) -> None:
        """Verify markdown formatting includes attachment list."""
        test_envelope = {
            "from": {"name": "Unknown sender", "address": "sender@example.org"},
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
                output_format="markdown",
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
