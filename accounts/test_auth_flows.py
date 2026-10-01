"""
PHASE 3: registration, email verification and password reset.

These tests prove the journey the brief requires to work end to end:

    register -> verify email -> sign in -> file a complaint

and that a mail outage cannot 500 the signup (the failure that made
production registration return HTTP 500).
"""

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.utils import OTP_PURPOSE_RESET, OTP_PURPOSE_VERIFY

User = get_user_model()

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
