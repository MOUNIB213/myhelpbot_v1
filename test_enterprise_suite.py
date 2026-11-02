import ast
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.security import (
    DEFAULT_ALLOWED_SECTIONS,
    REQUIRED_UNAUTHORIZED_MESSAGE,
    verify_backup_file_integrity,
)
from app.core.security import JWTManager, PasswordManager, SecretVaultCipher
from app.services.code_generator import (
    format_link_code,
    format_project_code,
    generate_ai_session_code,
)
from app.services.text_utils import split_telegram_markdown_chunks


class TestSecurityAndCryptography(unittest.TestCase):
    def test_password_hashing_and_verification(self):
        pw = "SuperStrong#VaultPass2026!"
        hashed = PasswordManager.hash_password(pw)
        self.assertNotEqual(pw, hashed)
        self.assertTrue(PasswordManager.verify_password(pw, hashed))
        self.assertFalse(PasswordManager.verify_password("WrongPassword123!", hashed))

    def test_short_password_rejected(self):
        with self.assertRaises(ValueError):
            PasswordManager.hash_password("short")

    def test_secret_vault_cipher_encryption_and_masking(self):
        master_key = "0123456789abcdef0123456789abcdef0123456789abcdef"
        cipher = SecretVaultCipher(master_key)
        raw_api_key = "AIzaSyD-EXAMPLE_DO_NOT_EXPOSE_987654"
        encrypted = cipher.encrypt(raw_api_key)
        self.assertNotIn(raw_api_key, encrypted)
        decrypted = cipher.decrypt(encrypted)
        self.assertEqual(raw_api_key, decrypted)

        masked = SecretVaultCipher.mask_secret(raw_api_key)
        self.assertTrue(masked.startswith("AIza"))
        self.assertTrue(masked.endswith("7654"))
        self.assertNotIn("EXAMPLE", masked)

    def test_jwt_lifecycle_and_signature_verification(self):
        jwt_mgr = JWTManager(secret_key="enterprise-unit-test-secret-key-2026")
        token = jwt_mgr.create_token(
            subject="admin",
            role="OWNER",
            session_jti="jti_998877",
            expires_delta=timedelta(minutes=30),
        )
        decoded = jwt_mgr.decode_token(token)
        self.assertEqual(decoded["sub"], "admin")
        self.assertEqual(decoded["role"], "OWNER")
        self.assertEqual(decoded["jti"], "jti_998877")

        tampered = token[:-4] + "XXXX"
        with self.assertRaises(Exception):
            jwt_mgr.decode_token(tampered)


class TestCodeGeneratorsAndFormatting(unittest.TestCase):
    def test_project_code_sequence(self):
        self.assertEqual(format_project_code(1, year=2026), "PRJ-2026-A001")
        self.assertEqual(format_project_code(42, year=2026), "PRJ-2026-A042")
        self.assertEqual(format_project_code(1000, year=2026), "PRJ-2026-B001")

    def test_link_code_sequence(self):
        self.assertEqual(format_link_code(1, year=2026), "LNK-2026-B001")
        self.assertEqual(format_link_code(15, year=2026), "LNK-2026-B015")

    def test_ai_session_code_uniqueness(self):
        c1 = generate_ai_session_code()
        c2 = generate_ai_session_code()
        self.assertTrue(c1.startswith("AIS-"))
        self.assertNotEqual(c1, c2)


class TestTelegramMarkdownChunking(unittest.TestCase):
    def test_short_message_single_chunk(self):
        msg = "مرحباً بك في المساعد الذكي!"
        chunks = split_telegram_markdown_chunks(msg, max_len=4000)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], msg)

    def test_long_code_block_preserves_fences_across_chunks(self):
        code_lines = [f"print('Line number {i}')" for i in range(300)]
        long_markdown = "إليك الكود المطلوب:\n```python\n" + "\n".join(code_lines) + "\n```\nتم بنجاح."
        chunks = split_telegram_markdown_chunks(long_markdown, max_len=1200)
        self.assertGreater(len(chunks), 3)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 1200)
            fence_count = chunk.count("```")
            self.assertEqual(fence_count % 2, 0)


class TestAuthorizationBackupAndASTCompilation(unittest.TestCase):
    def test_exact_mandated_arabic_unauthorized_message(self):
        expected = "هذا البوت خاص ولا تملك صلاحية استخدامه. يرجى التواصل مع مالك البوت للحصول على إمكانية الوصول."
        self.assertEqual(REQUIRED_UNAUTHORIZED_MESSAGE, expected)
        self.assertEqual(len(DEFAULT_ALLOWED_SECTIONS), 10)

    def test_backup_sha256_integrity_verification(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {
                "version": "2.0.0",
                "projects": [{"code": "PRJ-2026-A001", "name": "Test"}],
                "links": [{"code": "LNK-2026-B001", "url": "https://example.com"}],
            }
            raw = json.dumps(payload).encode("utf-8")
            sha = hashlib.sha256(raw).hexdigest()
            fpath = Path(tmpdir) / "backup_test.json"
            fpath.write_bytes(raw)

            self.assertTrue(verify_backup_file_integrity(str(fpath), sha))
            self.assertFalse(verify_backup_file_integrity(str(fpath), "0" * 64))

    def test_all_python_modules_compile_cleanly(self):
        project_root = Path(__file__).resolve().parent.parent
        py_files = list(project_root.rglob("*.py"))
        self.assertGreaterEqual(len(py_files), 15)
        for py_file in py_files:
            source = py_file.read_text(encoding="utf-8")
            ast.parse(source, filename=str(py_file))


if __name__ == "__main__":
    unittest.main(verbosity=2)
