"""MEDIA_STORAGE wiring.

The deployed function bundle is read-only, so the filesystem backend cannot
work in production and every upload fails. Pointing MEDIA_STORAGE at an
object store is what actually fixes it, and the failure mode of getting that
wrong is bad enough to be worth pinning: a wrong value used to stay latent
until the first upload, by which point it surfaced as a 500 on a user's form.
"""
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_check_with(**env_overrides):
    """Run ``manage.py check`` in a subprocess with a modified environment.

    Settings are read once at import, so the only honest way to test how a
    given environment is interpreted is to start a fresh interpreter.
    """
    env = dict(os.environ)
    env.pop('MEDIA_STORAGE', None)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, 'manage.py', 'check'],
        cwd=str(PROJECT_ROOT), env=env,
        capture_output=True, text=True,
    )


class MediaStorageSettingTests(SimpleTestCase):
    def test_local_development_uses_the_filesystem(self):
        self.assertEqual(
            settings.STORAGES['default']['BACKEND'],
            'django.core.files.storage.FileSystemStorage',
        )

    def test_media_storage_selects_the_object_store(self):
        result = run_check_with(
            MEDIA_STORAGE='storages.backends.s3boto3.S3Boto3Storage',
            AWS_S3_ENDPOINT_URL='https://example.r2.cloudflarestorage.com',
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_an_unimportable_backend_fails_loudly_at_startup(self):
        """Not on the first user's upload, but on the first request."""
        result = run_check_with(MEDIA_STORAGE='storages.backends.nope.Missing')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('MEDIA_STORAGE', result.stderr)
        self.assertIn('requirements.txt', result.stderr)

    def test_requirements_pin_django_storages(self):
        """The backend is useless without the dependency that provides it."""
        text = (PROJECT_ROOT / 'requirements.txt').read_text()
        self.assertIn('django-storages', text)

    def test_addressing_style_is_path_based(self):
        """Supabase's S3 endpoint rejects the virtual-host default."""
        self.assertEqual(settings.AWS_S3_ADDRESSING_STYLE, 'path')

    def test_urls_are_presigned(self):
        """ID documents and evidence must not sit behind a permanent URL."""
        self.assertTrue(settings.AWS_QUERYSTRING_AUTH)
        self.assertIsNone(settings.AWS_DEFAULT_ACL)

    def test_s3_credentials_are_forwarded_to_django(self):
        """django-storages reads settings, not the environment."""
        for name in (
            'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
            'AWS_STORAGE_BUCKET_NAME', 'AWS_S3_ENDPOINT_URL',
        ):
            self.assertTrue(
                hasattr(settings, name),
                '{} must exist for an S3-compatible store'.format(name),
            )