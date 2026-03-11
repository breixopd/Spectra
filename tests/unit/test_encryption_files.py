"""Tests for file encryption, password-based encryption, and export endpoints."""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.encryption import (
    decrypt_data_with_password,
    decrypt_file,
    encrypt_data_with_password,
    encrypt_file,
)


class TestEncryptFile:
    def test_encrypt_decrypt_roundtrip(self, tmp_path: Path):
        p = tmp_path / "test.txt"
        p.write_text("hello world")
        key = "test-secret-key"

        encrypt_file(p, key=key)

        # File should no longer be plaintext
        assert p.read_bytes() != b"hello world"

        decrypted = decrypt_file(p, key=key)
        assert decrypted == b"hello world"

    def test_encrypt_binary_file(self, tmp_path: Path):
        p = tmp_path / "test.bin"
        data = bytes(range(256))
        p.write_bytes(data)

        encrypt_file(p, key="binary-key")
        assert p.read_bytes() != data

        assert decrypt_file(p, key="binary-key") == data

    def test_decrypt_wrong_key_raises(self, tmp_path: Path):
        from cryptography.fernet import InvalidToken

        p = tmp_path / "test.txt"
        p.write_text("secret")
        encrypt_file(p, key="correct-key")

        with pytest.raises(InvalidToken):
            decrypt_file(p, key="wrong-key")

    def test_default_key_uses_settings(self, tmp_path: Path):
        p = tmp_path / "test.txt"
        p.write_text("data")

        with patch("app.core.encryption._get_default_secret", return_value="app-secret"):
            encrypt_file(p)
            result = decrypt_file(p)

        assert result == b"data"


class TestPasswordEncryption:
    def test_roundtrip(self):
        data = b"export payload"
        password = "strong-password-123"

        encrypted = encrypt_data_with_password(data, password)
        assert encrypted != data
        # Salt (16) + Fernet token
        assert len(encrypted) > 16

        decrypted = decrypt_data_with_password(encrypted, password)
        assert decrypted == data

    def test_wrong_password_raises(self):
        from cryptography.fernet import InvalidToken

        encrypted = encrypt_data_with_password(b"data", "pw1")
        with pytest.raises(InvalidToken):
            decrypt_data_with_password(encrypted, "pw2")

    def test_different_salts(self):
        data = b"same data"
        e1 = encrypt_data_with_password(data, "pw")
        e2 = encrypt_data_with_password(data, "pw")
        # Random salt means different ciphertexts
        assert e1 != e2
        # Both decrypt correctly
        assert decrypt_data_with_password(e1, "pw") == data
        assert decrypt_data_with_password(e2, "pw") == data


class TestReportEncryptionAtRest:
    @pytest.mark.asyncio
    async def test_save_report_encrypts(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        with patch("app.services.mission.report_generator._get_default_secret", return_value="test-key"):
            from app.services.mission.report_generator import save_report

            path = await save_report("mission-1", "<html>report</html>")

        # In local-fallback mode, StorageService writes to data/missions/
        saved = Path(path)
        assert saved.exists()
        # Should be encrypted, not plaintext
        assert saved.read_bytes() != b"<html>report</html>"

        with patch("app.core.encryption._get_default_secret", return_value="test-key"):
            from cryptography.fernet import Fernet

            from app.core.encryption import _derive_fernet_key
            f = Fernet(_derive_fernet_key("test-key"))
            content = f.decrypt(saved.read_bytes())
        assert content == b"<html>report</html>"

    @pytest.mark.asyncio
    async def test_save_pdf_report_encrypts(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pdf_data = b"%PDF-1.4 fake pdf content"

        with patch("app.services.mission.report_generator._get_default_secret", return_value="test-key"):
            from app.services.mission.report_generator import save_pdf_report

            path = await save_pdf_report("mission-2", pdf_data)

        assert path is not None
        saved = Path(path)
        assert saved.exists()
        assert saved.read_bytes() != pdf_data

        with patch("app.core.encryption._get_default_secret", return_value="test-key"):
            from cryptography.fernet import Fernet

            from app.core.encryption import _derive_fernet_key
            f = Fernet(_derive_fernet_key("test-key"))
            assert f.decrypt(saved.read_bytes()) == pdf_data
