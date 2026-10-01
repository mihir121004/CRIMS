"""Tests for how the mail transport is chosen.

The OAuth credentials are Vercel secrets and cannot be read back, so the
transport has to be switchable by naming it rather than by deleting a
variable. Both helpers are called directly instead of reloading the settings
module, which would disturb Django's already-imported state.
"""
import os
from unittest import mock

from django.test import SimpleTestCase

from crims import settings as settings_module

SMTP = 'django.core.mail.backends.smtp.EmailBackend'
CONSOLE = 'django.core.mail.backends.console.EmailBackend'
OAUTH = 'accounts.email_backend.GmailOAuthBackend'


class AutoEmailBackendTests(SimpleTestCase):
    def select(self, client_id='', refresh_token='',
               user='someone@gmail.com', password='app-password'):
        environ = {}
        if client_id:
            environ['GMAIL_OAUTH_CLIENT_ID'] = client_id
        if refresh_token:
            environ['GMAIL_REFRESH_TOKEN'] = refresh_token
        if user:
            environ['EMAIL_HOST_USER'] = user
        if password:
            environ['EMAIL_HOST_PASSWORD'] = password

        with mock.patch.dict(os.environ, environ, clear=True):
            with mock.patch.object(settings_module, 'EMAIL_HOST_USER', user):
                with mock.patch.object(
                    settings_module, 'EMAIL_HOST_PASSWORD', password
                ):
                    return settings_module._auto_email_backend()

    def test_complete_oauth_credentials_select_oauth(self):
        self.assertEqual(
            self.select(client_id='id.apps.googleusercontent.com',
                        refresh_token='refresh'),
            OAUTH,
        )

    def test_partial_oauth_pair_does_not_select_oauth(self):
        """A half-configured OAuth pair must fall through to SMTP."""
        self.assertEqual(
            self.select(client_id='id.apps.googleusercontent.com'), SMTP
        )

    def test_password_credentials_select_smtp(self):
        self.assertEqual(self.select(), SMTP)

    def test_nothing_configured_falls_back_to_console(self):
        self.assertEqual(self.select(user='', password=''), CONSOLE)

    def test_user_without_password_is_not_smtp(self):
        self.assertEqual(self.select(password=''), CONSOLE)


class EmailBackendOverrideTests(SimpleTestCase):
    """The explicit override that makes the transport reversible."""

    def test_explicit_value_wins(self):
        self.assertEqual(settings_module._resolve_email_backend(SMTP), SMTP)

    def test_override_survives_the_oauth_credentials_being_present(self):
        """This is the case that motivated it: OAuth set, but unused.

        Deleting a write-only Vercel secret to get here would be
        unrecoverable, so naming the backend must be enough.
        """
        self.assertEqual(
            settings_module._resolve_email_backend(OAUTH), OAUTH
        )

    def test_missing_value_falls_back_to_auto(self):
        for empty in (None, '', '   '):
            self.assertNotEqual(settings_module._resolve_email_backend(empty), '')

    def test_whitespace_only_value_falls_back_to_auto(self):
        self.assertEqual(
            settings_module._resolve_email_backend('   ').strip() != '   ', True
        )
