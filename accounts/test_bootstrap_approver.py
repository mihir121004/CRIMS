"""The bootstrap route that unlocks the approver loop.

The approver named in ADMIN_APPROVER_EMAILS cannot invite anyone until they are
already an approved admin, and production cannot be edited by hand because
DATABASE_URL is a write-only secret. This route resolves that, so its blast
radius is the thing under test: it must fail closed without CRON_SECRET, and a
valid secret must still not be enough to promote an arbitrary address.
"""
import os
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()

OWNER = 'solankimihir1210@gmail.com'
STRANGER = 'attacker@example.test'
SECRET = 'test-cron-secret'


@override_settings(ADMIN_APPROVER_EMAILS=[OWNER])
class BootstrapApproverTests(TestCase):
    def setUp(self):
        self.url = reverse('bootstrap_approver')

    def post(self, email, secret=SECRET, **extra):
        return self.client.post(
            self.url, {'email': email},
            HTTP_AUTHORIZATION='Bearer {}'.format(secret), **extra,
        )

    # -- the guards that matter -----------------------------------------

    @mock.patch.dict(os.environ, {'CRON_SECRET': SECRET}, clear=False)
    def test_refuses_without_the_secret(self):
        response = self.post(OWNER, secret='wrong-secret')
        self.assertEqual(response.status_code, 401)
        self.assertFalse(User.objects.exists())

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_refuses_outright_when_cron_secret_is_unset(self):
        """A deployment without the secret must fail closed."""
        response = self.post(OWNER)
        self.assertEqual(response.status_code, 503)
        self.assertFalse(User.objects.exists())

    @mock.patch.dict(os.environ, {'CRON_SECRET': SECRET}, clear=False)
    def test_get_is_not_allowed(self):
        response = self.client.get(
            self.url, HTTP_AUTHORIZATION='Bearer {}'.format(SECRET)
        )
        self.assertEqual(response.status_code, 405)
        self.assertFalse(User.objects.exists())

    @mock.patch.dict(os.environ, {'CRON_SECRET': SECRET}, clear=False)
    def test_valid_secret_still_cannot_promote_an_unlisted_address(self):
        """A leaked secret must not be a general admin-minting key."""
        response = self.post(STRANGER)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.exists())

    @mock.patch.dict(os.environ, {'CRON_SECRET': SECRET}, clear=False)
    def test_email_is_required(self):
        response = self.post('')
        self.assertEqual(response.status_code, 400)

    # -- the behaviour it does grant ------------------------------------

    @mock.patch.dict(os.environ, {'CRON_SECRET': SECRET}, clear=False)
    def test_creates_a_usable_approved_admin(self):
        response = self.post(OWNER)
        self.assertEqual(response.status_code, 200)

        user = User.objects.get(email=OWNER)
        self.assertEqual(user.role, 'admin')
        self.assertTrue(user.is_approved)
        self.assertTrue(user.is_active)
        self.assertTrue(user.email_verified)
        self.assertTrue(user.has_usable_password())

    @mock.patch.dict(os.environ, {'CRON_SECRET': SECRET}, clear=False)
    def test_returns_a_password_once(self):
        payload = self.post(OWNER).json()
        self.assertIn('generated_password', payload)

        user = User.objects.get(email=OWNER)
        self.assertTrue(user.check_password(payload['generated_password']))

        # Second call must not re-issue or echo it.
        again = self.post(OWNER).json()
        self.assertNotIn('generated_password', again)

    @mock.patch.dict(os.environ, {'CRON_SECRET': SECRET}, clear=False)
    def test_never_grants_django_admin_site_access(self):
        self.post(OWNER)
        user = User.objects.get(email=OWNER)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)

    @mock.patch.dict(os.environ, {'CRON_SECRET': SECRET}, clear=False)
    def test_is_idempotent(self):
        self.post(OWNER)
        first_pk = User.objects.get(email=OWNER).pk

        response = self.post(OWNER)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['created'])
        self.assertEqual(User.objects.get(email=OWNER).pk, first_pk)
        self.assertEqual(User.objects.count(), 1)

    @mock.patch.dict(os.environ, {'CRON_SECRET': SECRET}, clear=False)
    def test_does_not_clobber_an_existing_password(self):
        """Re-running bootstrap must not invalidate a password in use."""
        user = User.objects.create_user(
            username='owner', email=OWNER, password='AlreadySet!2345',
            role='citizen',
        )
        response = self.post(OWNER)
        self.assertNotIn('generated_password', response.json())

        user.refresh_from_db()
        self.assertTrue(user.check_password('AlreadySet!2345'))

    @mock.patch.dict(os.environ, {'CRON_SECRET': SECRET}, clear=False)
    def test_promotes_an_existing_citizen_in_place(self):
        """Keeps their complaint history attached to the same row."""
        user = User.objects.create_user(
            username='owner', email=OWNER, password='AlreadySet!2345',
            role='citizen',
        )
        self.post(OWNER)

        user.refresh_from_db()
        self.assertEqual(user.role, 'admin')
        self.assertEqual(user.username, 'owner')

    @mock.patch.dict(os.environ, {'CRON_SECRET': SECRET}, clear=False)
    def test_address_matching_ignores_case(self):
        self.post(OWNER.upper())
        self.assertTrue(User.objects.filter(email=OWNER).exists())

    @mock.patch.dict(os.environ, {'CRON_SECRET': SECRET}, clear=False)
    def test_reactivates_a_deactivated_admin(self):
        user = User.objects.create_user(
            username='owner', email=OWNER, password='AlreadySet!2345',
            role='admin',
        )
        user.is_active = False
        user.is_approved = False
        user.save()

        self.post(OWNER)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_approved)

    @mock.patch.dict(os.environ, {'CRON_SECRET': SECRET}, clear=False)
    def test_a_bootstrapped_approver_can_reach_the_invitation_screen(self):
        """The point of the route: it unblocks the chicken-and-egg."""
        payload = self.post(OWNER).json()
        user = User.objects.get(email=OWNER)
        self.assertTrue(
            self.client.login(
                username=payload['username'],
                password=payload['generated_password'],
            )
        )
        self.assertEqual(
            self.client.get(reverse('admin_invites')).status_code, 200
        )


@override_settings(ADMIN_APPROVER_EMAILS=[])
class EmptyAllowListTests(TestCase):
    @mock.patch.dict(os.environ, {'CRON_SECRET': SECRET}, clear=False)
    def test_nothing_is_bootstrappable_when_the_list_is_empty(self):
        response = self.client.post(
            reverse('bootstrap_approver'), {'email': OWNER},
            HTTP_AUTHORIZATION='Bearer {}'.format(SECRET),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.exists())


class BootstrapUrlTests(TestCase):
    def test_the_route_is_named_and_reversible(self):
        self.assertEqual(
            reverse('bootstrap_approver'), '/internal/bootstrap-approver/'
        )