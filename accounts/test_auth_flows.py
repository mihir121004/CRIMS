"""
PHASE 3: registration, email verification and password reset.

These tests prove the journey the brief requires to work end to end:

    register -> verify email -> sign in -> file a complaint

and that a mail outage cannot 500 the signup (the failure that made
production registration return HTTP 500).
"""

import os
from contextlib import contextmanager
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.utils import OTP_PURPOSE_RESET, OTP_PURPOSE_VERIFY

User = get_user_model()


@contextmanager
def mock_env(value):
    """Set CRON_SECRET for the duration of the block."""
    with mock.patch.dict(os.environ, {'CRON_SECRET': value}):
        yield


@contextmanager
def no_env():
    """Run with CRON_SECRET absent, leaving the rest of the env intact."""
    remaining = {k: v for k, v in os.environ.items() if k != 'CRON_SECRET'}
    with mock.patch.dict(os.environ, remaining, clear=True):
        yield

PASSWORD = 'Str0ngTestPass!234'


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_VERIFICATION_REQUIRED=True,
)
class RegistrationWithVerificationTests(TestCase):

    def register(self, **overrides):
        payload = {
            'username': 'newcitizen',
            'email': 'new@test.local',
            'role': 'citizen',
            'password1': PASSWORD,
            'password2': PASSWORD,
        }
        payload.update(overrides)
        return self.client.post(reverse('register'), payload)

    def test_registration_creates_unverified_user(self):
        response = self.register()
        self.assertRedirects(response, reverse('verify_email'))

        user = User.objects.get(username='newcitizen')
        self.assertFalse(user.email_verified)
        self.assertEqual(user.role, 'citizen')
        self.assertIsNotNone(user.otp)
        self.assertNotEqual(user.otp, user.get_otp_code())

    def test_registration_sends_verification_email(self):
        self.register()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('verif', mail.outbox[0].subject.lower())

    @staticmethod
    def otp_from_latest_email():
        """Read the code out of the email body, as a real user would.

        The plaintext OTP is deliberately never persisted - only a salted hash
        is stored - so it can only be obtained from the message itself.
        """
        import re
        body = mail.outbox[-1].body
        match = re.search(r'\b(\d{6})\b', body)
        assert match, 'No 6-digit code found in the email body.'
        return match.group(1)

    def test_unverified_user_cannot_log_in(self):
        self.register()
        response = self.client.post(
            reverse('login'),
            {'username': 'newcitizen', 'password': PASSWORD},
        )
        # Redirected back to verification rather than signed in.
        self.assertEqual(
            self.client.session.get('_auth_user_id'), None
        )
        self.assertIn(response.status_code, (200, 302))

    def test_verification_with_correct_code_signs_the_account_in(self):
        self.register()
        user = User.objects.get(username='newcitizen')
        code = self.otp_from_latest_email()

        self.client.post(reverse('verify_email'), {'otp': code})
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        self.assertIsNone(user.otp)

        response = self.client.post(
            reverse('login'),
            {'username': 'newcitizen', 'password': PASSWORD},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.session.get('_auth_user_id'), str(user.pk)
        )

    def test_verification_with_wrong_code_is_rejected(self):
        self.register()
        user = User.objects.get(username='newcitizen')
        self.client.post(reverse('verify_email'), {'otp': '000000'})
        user.refresh_from_db()
        self.assertFalse(user.email_verified)

    def test_verify_without_session_redirects_to_login(self):
        response = self.client.get(reverse('verify_email'))
        self.assertRedirects(response, reverse('login'))

    def test_officer_registration_requires_approval(self):
        self.register(
            username='newofficer', role='officer', id_number='ID-99',
        )
        user = User.objects.get(username='newofficer')
        self.assertFalse(user.is_approved)
        self.assertEqual(user.role, 'officer')

    def test_officer_registration_without_id_number_is_rejected(self):
        self.register(username='noidofficer', role='officer')
        self.assertFalse(
            User.objects.filter(username='noidofficer').exists()
        )

    def test_unapproved_officer_cannot_log_in(self):
        officer = User.objects.create_user(
            username='pending', email='p@test.local', password=PASSWORD,
            role='officer',
        )
        officer.is_approved = False
        officer.email_verified = True
        officer.save()

        self.client.post(
            reverse('login'),
            {'username': 'pending', 'password': PASSWORD},
        )
        self.assertIsNone(self.client.session.get('_auth_user_id'))


class MailOutageTests(TestCase):
    """Root cause of the production outage: an expired OAuth token made
    send_otp_email raise and POST /register/ return 500, leaving an orphaned
    un-verifiable user row."""

    def _post(self):
        return self.client.post(
            reverse('register'),
            {
                'username': 'mailfail',
                'email': 'mf@test.local',
                'role': 'citizen',
                'password1': PASSWORD,
                'password2': PASSWORD,
            },
        )

    def test_mail_failure_does_not_return_500(self):
        with override_settings(
            EMAIL_BACKEND='accounts.tests.BrokenEmailBackend',
            EMAIL_VERIFICATION_REQUIRED=True,
        ):
            response = self._post()
        self.assertEqual(response.status_code, 200)

    def test_mail_failure_does_not_orphan_the_user(self):
        with override_settings(
            EMAIL_BACKEND='accounts.tests.BrokenEmailBackend',
            EMAIL_VERIFICATION_REQUIRED=True,
        ):
            self._post()
        user = User.objects.filter(username='mailfail').first()
        self.assertIsNone(
            user,
            'VULNERABILITY: a user row survived a failed verification email, '
            'leaving an account nobody can ever verify.',
        )

    def test_mail_failure_surfaces_a_readable_error(self):
        with override_settings(
            EMAIL_BACKEND='accounts.tests.BrokenEmailBackend',
            EMAIL_VERIFICATION_REQUIRED=True,
        ):
            response = self._post()
        body = response.content.decode()
        self.assertIn('could not send the verification email', body.lower())

    def test_mail_failure_is_logged(self):
        """A swallowed exception must not vanish.

        With no log line, an expired OAuth refresh token and a user simply
        not receiving mail are indistinguishable from the outside.
        """
        with self.assertLogs('crims.errors', level='ERROR') as captured:
            with override_settings(
                EMAIL_BACKEND='accounts.tests.BrokenEmailBackend',
                EMAIL_VERIFICATION_REQUIRED=True,
            ):
                self._post()
        joined = '\n'.join(captured.output)
        self.assertIn('verification email', joined)

    def test_mail_success_is_logged(self):
        """'Was it sent?' must be answerable without an inbox.

        send_mail returning means the provider accepted the message; that is
        the strongest claim this code can make, and it needs to be recorded.
        """
        with self.assertLogs('crims.errors', level='INFO') as captured:
            with override_settings(
                EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                EMAIL_VERIFICATION_REQUIRED=True,
            ):
                response = self._post()
        self.assertEqual(response.status_code, 302)
        self.assertIn('/verify-email/', response['Location'])
        joined = '\n'.join(captured.output)
        self.assertIn('accepted by the mail provider', joined)
        self.assertNotIn('mf@test.local', joined)

    def test_mail_failure_log_redacts_the_address(self):
        """The recipient's local part must not reach the log store."""
        with self.assertLogs('crims.errors', level='ERROR') as captured:
            with override_settings(
                EMAIL_BACKEND='accounts.tests.BrokenEmailBackend',
                EMAIL_VERIFICATION_REQUIRED=True,
            ):
                self._post()
        joined = '\n'.join(captured.output)
        self.assertNotIn('mf@test.local', joined)
        self.assertIn('mf***@test.local', joined)


class MailFailureDiagnosticsTests(TestCase):
    """The helpers that make a mail failure diagnosable from logs."""

    def test_redact_hides_the_local_part(self):
        from accounts.utils import _redact
        self.assertEqual(_redact('someone@example.com'), 'so***@example.com')

    def test_redact_copes_with_junk(self):
        from accounts.utils import _redact
        for value in ('', None, 'not-an-email'):
            self.assertEqual(_redact(value), 'unknown')

    def test_google_oauth_error_is_surfaced(self):
        """invalid_grant vs invalid_client is the whole diagnosis."""
        import io
        import urllib.error

        from accounts.utils import _describe_mail_error

        body = (
            b'{"error": "invalid_grant", '
            b'"error_description": "Token has been expired or revoked."}'
        )
        exc = urllib.error.HTTPError(
            'https://oauth2.googleapis.com/token', 400, 'Bad Request',
            {}, io.BytesIO(body),
        )
        described = _describe_mail_error(exc)
        self.assertIn('400', described)
        self.assertIn('invalid_grant', described)
        self.assertIn('expired or revoked', described)

    def test_non_http_errors_report_only_the_type(self):
        from accounts.utils import _describe_mail_error
        self.assertEqual(
            _describe_mail_error(ConnectionResetError('boom')),
            'ConnectionResetError',
        )

    def test_unparseable_error_body_does_not_raise(self):
        import io
        import urllib.error

        from accounts.utils import _describe_mail_error

        exc = urllib.error.HTTPError(
            'https://oauth2.googleapis.com/token', 500, 'Server Error',
            {}, io.BytesIO(b'<html>gateway timeout</html>'),
        )
        self.assertEqual(_describe_mail_error(exc), 'HTTP 500 from the mail provider')


class BrokenEmailBackend:
    """Stand-in for the Gmail OAuth backend when its token has expired."""

    def __init__(self, *args, **kwargs):
        pass

    def send_messages(self, messages):
        import urllib.error
        raise urllib.error.HTTPError(
            'https://oauth2.googleapis.com/token',
            401,
            'Unauthorized',
            {},
            None,
        )


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_VERIFICATION_REQUIRED=False,
)
class PasswordResetTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='resetme', email='reset@test.local', password=PASSWORD
        )
        self.user.email_verified = True
        self.user.save()

    def test_reset_flow_changes_the_password(self):
        self.client.post(
            reverse('forgot_password'), {'email': 'reset@test.local'}
        )
        self.user.refresh_from_db()
        import re
        body = mail.outbox[-1].body
        code = re.search(r'\b(\d{6})\b', body).group(1)

        response = self.client.post(
            reverse('reset_password'),
            {'otp': code, 'new_password1': 'BrandNewPass!99',
             'new_password2': 'BrandNewPass!99'},
        )
        self.assertRedirects(response, reverse('login'))

        self.user.refresh_from_db()
        self.assertTrue(
            self.user.check_password('BrandNewPass!99'),
            'Password was not changed.',
        )
        self.assertIsNone(self.user.otp, 'OTP must be cleared after use.')

    def test_reset_rejects_wrong_otp(self):
        self.client.post(
            reverse('forgot_password'), {'email': 'reset@test.local'}
        )
        self.client.post(
            reverse('reset_password'),
            {'otp': '000000', 'new_password1': 'BrandNewPass!99',
             'new_password2': 'BrandNewPass!99'},
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_reset_requires_matching_passwords(self):
        self.client.post(
            reverse('forgot_password'), {'email': 'reset@test.local'}
        )
        self.user.refresh_from_db()
        import re
        code = re.search(r'\b(\d{6})\b', mail.outbox[-1].body).group(1)
        response = self.client.post(
            reverse('reset_password'),
            {'otp': code, 'new_password1': 'BrandNewPass!99',
             'new_password2': 'Different!99'},
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_reset_without_session_redirects(self):
        response = self.client.get(reverse('reset_password'))
        self.assertRedirects(response, reverse('forgot_password'))


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_VERIFICATION_REQUIRED=False,
)
class LoginLogoutTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='loginer', email='log@test.local', password=PASSWORD
        )

    def test_valid_login_redirects_to_dashboard(self):
        response = self.client.post(
            reverse('login'),
            {'username': 'loginer', 'password': PASSWORD},
        )
        self.assertRedirects(
            response, reverse('dashboard'), fetch_redirect_response=False
        )

    def test_invalid_login_does_not_authenticate(self):
        self.client.post(
            reverse('login'),
            {'username': 'loginer', 'password': 'wrong'},
        )
        self.assertIsNone(self.client.session.get('_auth_user_id'))

    def test_post_logout_clears_the_session(self):
        self.client.login(username='loginer', password=PASSWORD)
        self.client.post(reverse('logout'))
        self.assertIsNone(self.client.session.get('_auth_user_id'))


class HealthCheckTests(TestCase):
    """The uptime probe must work unauthenticated and disclose nothing."""

    def test_health_reports_ok(self):
        response = self.client.get(reverse('health_check'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        self.assertTrue(response.json()['database'])

    def test_health_leaks_no_configuration(self):
        body = self.client.get(reverse('health_check')).content.decode()
        for leak in ('SECRET_KEY', 'DATABASES', 'DEBUG', 'version',
                     'django', 'root:', 'MySQL'):
            self.assertNotIn(leak, body)


SECRET = 'test-cron-secret-value'


class MigrationRouteTests(TestCase):
    """The migrate route is a privileged, unauthenticated-by-session endpoint.

    Vercel offers no shell and no release phase, so this is the only way to
    bring the production schema up to date after a deploy. That makes its
    access control security-critical: it must fail closed, and it must never
    apply migrations to a request that merely happens to reach it.
    """

    url_name = 'run_migrations'

    def authorized(self, method='get', token=SECRET, **extra):
        headers = {'HTTP_AUTHORIZATION': f'Bearer {token}'}
        return getattr(self.client, method)(
            reverse(self.url_name), **headers, **extra
        )

    def test_unconfigured_deployment_refuses_outright(self):
        """No CRON_SECRET means no migrations, never a fallback open."""
        with no_env():
            response = self.client.get(reverse(self.url_name))
        self.assertEqual(response.status_code, 503)

    def test_missing_header_is_rejected(self):
        with mock_env(SECRET):
            response = self.client.get(reverse(self.url_name))
        self.assertEqual(response.status_code, 401)

    def test_wrong_token_is_rejected(self):
        with mock_env(SECRET):
            response = self.authorized(token='not-the-secret')
        self.assertEqual(response.status_code, 401)

    def test_wrong_scheme_is_rejected(self):
        with mock_env(SECRET):
            response = self.client.get(
                reverse(self.url_name), HTTP_AUTHORIZATION=SECRET
            )
        self.assertEqual(response.status_code, 401)

    def test_get_reports_pending_without_applying(self):
        """GET is read-only: it must not be able to mutate the schema."""
        with mock_env(SECRET):
            response = self.authorized()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn(body['status'], ('pending', 'up-to-date'))
        # 'applied' is only ever an empty list on GET; a non-empty one would
        # mean the read-only verb actually ran migrations.
        self.assertEqual(body.get('applied', []), [])

    def test_post_applies_and_reports(self):
        with mock_env(SECRET):
            response = self.authorized(method='post')
        self.assertEqual(response.status_code, 200)
        self.assertIn(response.json()['status'], ('ok', 'up-to-date'))

    def test_rejects_other_methods(self):
        with mock_env(SECRET):
            response = self.client.delete(
                reverse(self.url_name), HTTP_AUTHORIZATION=f'Bearer {SECRET}'
            )
        self.assertEqual(response.status_code, 405)

    def test_post_is_exempt_from_csrf_intentionally(self):
        """Documented exemption, not an oversight.

        With CSRF checks enforced the documented curl invocation fails with a
        403, because there is no cookie/token pair to send. The bearer token is
        the authority, so the exemption is what makes the route operable.
        """
        from django.test import Client

        strict = Client(enforce_csrf_checks=True)
        with mock_env(SECRET):
            response = strict.post(
                reverse(self.url_name),
                HTTP_AUTHORIZATION=f'Bearer {SECRET}',
            )
        self.assertEqual(response.status_code, 200)

        # Exempt must not mean unauthenticated: a CSRF-shaped request with no
        # token is still rejected.
        with mock_env(SECRET):
            response = strict.post(reverse(self.url_name))
        self.assertEqual(response.status_code, 401)

    def test_never_echoes_the_secret(self):
        with mock_env(SECRET):
            for response in (self.authorized(), self.authorized(method='post')):
                body = response.content.decode()
                self.assertNotIn(SECRET, body)
        # And nothing resembling connection details either.
        for leak in ('DATABASE_URL', 'SECRET_KEY', 'password', 'root:'):
            self.assertNotIn(leak, response.content.decode().lower())

    def test_authenticated_user_is_not_enough(self):
        """A logged-in session must not substitute for the bearer token."""
        User.objects.create_user(
            username='officer', password='Str0ngPassw0rd!', role='officer',
        )
        self.client.login(username='officer', password='Str0ngPassw0rd!')
        with mock_env(SECRET):
            response = self.client.get(reverse(self.url_name))
        self.assertEqual(response.status_code, 401)

    def test_pending_labels_are_parsed_cleanly(self):
        """Regression guard: a mangled label makes migrate() fail at runtime.

        The first version of this endpoint returned labels with a leading
        '] ' still attached, which would have been handed straight to
        migrate() and failed to resolve.
        """
        plan = (
            '[X]  auth.0001_initial\n'
            '[X]  contenttypes.0001_initial\n'
            '[ ]  accounts.0002_alter_user_options\n'
            '[ ]  suspects.0002_alter_suspect_photo\n'
        )

        def fake_call_command(name, *args, **kwargs):
            if name == 'showmigrations':
                kwargs['stdout'].write(plan)

        with mock_env(SECRET):
            with mock.patch(
                'django.core.management.call_command',
                side_effect=fake_call_command,
            ):
                response = self.authorized()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['pending'],
            ['accounts.0002_alter_user_options',
             'suspects.0002_alter_suspect_photo'],
        )

    def test_migrate_gets_app_label_and_name_separately(self):
        """Regression guard, found in production.

        migrate() takes 'app_label' and 'migration_name' as two separate
        arguments. Passing the combined 'app.0002_x' label as a single
        argument made Django treat the whole string as an app label and raise
        LookupError, so the endpoint reported CommandError against the live
        database.
        """
        plan = '[ ]  accounts.0002_alter_user_options\n'
        calls = []

        def fake_call_command(name, *args, **kwargs):
            if name == 'showmigrations':
                kwargs['stdout'].write(plan)
            elif name == 'migrate':
                calls.append((args, kwargs))

        with mock_env(SECRET):
            with mock.patch(
                'django.core.management.call_command',
                side_effect=fake_call_command,
            ):
                response = self.authorized(method='post')

        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(args, ('accounts', '0002_alter_user_options'))
        self.assertIs(kwargs['interactive'], False)
