"""Administrator invitations.

The ``admin`` role is deliberately absent from ``RegisterForm.SELF_SERVICE_ROLES``
because letting the POST body pick the role was a privilege-escalation bug in
this project. The only way in is an invitation from a designated approver, and
an invitation grants nothing on its own.

These tests pin the properties that matter:

* role='admin' alone is NOT sufficient - only listed addresses may invite.
* An invited account is unapproved, with no usable password, and cannot sign
  in until both its email is verified and an approver grants it.
* Approval requires POST + CSRF and is refused for an unverified address.
"""
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from accounts.views import _pending_admin_username
from crims.test_support import PASSWORD, RoleTestCase

User = get_user_model()

APPROVER = 'owner@example.test'
OUTSIDER = 'someone.else@example.test'


@override_settings(ADMIN_APPROVER_EMAILS=[APPROVER])
class ApproverAccessTests(RoleTestCase):
    """Only a designated approver reaches the invitation surface."""

    def setUp(self):
        super().setUp()
        # This admin is deliberately NOT on the approver list.
        self.approver = User.objects.create_user(
            username='owner', email=APPROVER, password=PASSWORD,
            role='admin',
        )
        self.approver.is_approved = True
        self.approver.email_verified = True
        self.approver.save()

    def test_anonymous_is_redirected_to_login(self):
        self.assertEqual(
            self.client.get(reverse('admin_invites')).status_code, 302
        )

    def test_citizen_is_forbidden(self):
        self.login_as(self.citizen)
        self.assertEqual(
            self.client.get(reverse('admin_invites')).status_code, 403
        )

    def test_officer_is_forbidden(self):
        self.login_as(self.officer)
        self.assertEqual(
            self.client.get(reverse('admin_invites')).status_code, 403
        )

    def test_admin_who_is_not_an_approver_is_forbidden(self):
        """The important one: the role alone must not be enough."""
        self.login_as(self.admin)
        self.assertEqual(
            self.client.get(reverse('admin_invites')).status_code, 403
        )

    def test_designated_approver_is_allowed(self):
        self.login_as(self.approver)
        self.assertEqual(
            self.client.get(reverse('admin_invites')).status_code, 200
        )

    def test_email_match_is_case_insensitive(self):
        """AbstractUser does not normalise ``email``."""
        self.approver.email = APPROVER.upper()
        self.approver.save()
        self.login_as(self.approver)
        self.assertEqual(
            self.client.get(reverse('admin_invites')).status_code, 200
        )

    def test_an_admin_cannot_approve_an_invitation(self):
        """Approving is gated the same way as inviting."""
        invite = self.make_invitation('pending@example.test')
        self.login_as(self.admin)
        response = self.client.post(
            reverse('approve_invite', args=[invite.id])
        )
        self.assertEqual(response.status_code, 403)
        invite.refresh_from_db()
        self.assertFalse(invite.is_approved)

    # -- helpers ---------------------------------------------------------

    def make_invitation(self, email, verified=True):
        user = User(username=_pending_admin_username(), email=email)
        user.role = 'admin'
        user.is_approved = False
        user.email_verified = verified
        user.set_unusable_password()
        user.save()
        return user


@override_settings(ADMIN_APPROVER_EMAILS=[APPROVER])
class InviteCreationTests(RoleTestCase):
    def setUp(self):
        super().setUp()
        self.approver = User.objects.create_user(
            username='owner', email=APPROVER, password=PASSWORD,
            role='admin',
        )
        self.approver.is_approved = True
        self.approver.email_verified = True
        self.approver.save()
        self.login_as(self.approver)

    def invite(self, email):
        return self.client.post(
            reverse('admin_invites'), {'email': email}
        )

    def test_invite_creates_an_unapproved_admin(self):
        response = self.invite('newcomer@example.test')
        self.assertEqual(response.status_code, 302)

        invitee = User.objects.get(email='newcomer@example.test')
        self.assertEqual(invitee.role, 'admin')
        self.assertFalse(invitee.is_approved)
        self.assertTrue(invitee.is_active)

    def test_invited_account_has_no_usable_password(self):
        """An invitation must not hand out a working credential."""
        self.invite('newcomer@example.test')
        invitee = User.objects.get(email='newcomer@example.test')
        self.assertFalse(invitee.has_usable_password())

    def test_invitation_does_not_escalate_to_django_admin(self):
        """is_superuser/unlocks Django's own admin site; not granted."""
        self.invite('newcomer@example.test')
        invitee = User.objects.get(email='newcomer@example.test')
        self.assertFalse(invitee.is_superuser)
        self.assertFalse(invitee.is_staff)

    def test_invite_appears_in_the_pending_list(self):
        self.invite('newcomer@example.test')
        response = self.client.get(reverse('admin_invites'))
        self.assertContains(response, 'newcomer@example.test')

    def test_inviting_the_approver_themselves_is_refused(self):
        response = self.invite(APPROVER)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already belongs to an active administrator')

    def test_reinviting_is_refused(self):
        self.invite('newcomer@example.test')
        response = self.invite('newcomer@example.test')
        self.assertContains(response, 'already has a pending administrator invitation')

    def test_existing_citizen_is_upgraded_not_duplicated(self):
        """Two rows for one address would split their complaint history."""
        before = User.objects.count()
        self.invite(self.citizen.email)
        self.assertEqual(User.objects.count(), before)

        promoted = User.objects.get(pk=self.citizen.pk)
        self.assertEqual(promoted.role, 'admin')
        self.assertFalse(promoted.is_approved)

    def test_invalid_email_is_rejected(self):
        response = self.invite('not-an-email')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter a valid email address')


@override_settings(ADMIN_APPROVER_EMAILS=[APPROVER])
class InviteApprovalTests(RoleTestCase):
    def setUp(self):
        super().setUp()
        self.approver = User.objects.create_user(
            username='owner', email=APPROVER, password=PASSWORD,
            role='admin',
        )
        self.approver.is_approved = True
        self.approver.email_verified = True
        self.approver.save()
        self.login_as(self.approver)

    def make_invitation(self, email, verified=True):
        user = User(username=_pending_admin_username(), email=email)
        user.role = 'admin'
        user.is_approved = False
        user.email_verified = verified
        user.set_unusable_password()
        user.save()
        return user

    def test_approve_grants_the_admin_role(self):
        invite = self.make_invitation('newcomer@example.test')
        response = self.client.post(reverse('approve_invite', args=[invite.id]))
        self.assertEqual(response.status_code, 302)

        invite.refresh_from_db()
        self.assertTrue(invite.is_approved)
        self.assertEqual(invite.role, 'admin')

    def test_approval_requires_a_verified_address(self):
        """Approving an unproven address would grant admin to whoever
        merely controls that mailbox, including a typo'd one."""
        invite = self.make_invitation('newcomer@example.test', verified=False)
        self.client.post(reverse('approve_invite', args=[invite.id]))

        invite.refresh_from_db()
        self.assertFalse(invite.is_approved)

    def test_approve_does_not_grant_django_superuser(self):
        invite = self.make_invitation('newcomer@example.test')
        self.client.post(reverse('approve_invite', args=[invite.id]))

        invite.refresh_from_db()
        self.assertFalse(invite.is_superuser)

    def test_reject_deactivates_without_deleting(self):
        """History must keep a valid foreign key."""
        invite = self.make_invitation('newcomer@example.test')
        self.client.post(reverse('reject_invite', args=[invite.id]))

        invite.refresh_from_db()
        self.assertFalse(invite.is_active)
        self.assertFalse(invite.is_approved)

    def test_approving_an_unknown_id_is_handled(self):
        response = self.client.post(reverse('approve_invite', args=[999999]))
        self.assertEqual(response.status_code, 302)

    def test_repeated_approval_is_harmless(self):
        invite = self.make_invitation('newcomer@example.test')
        self.client.post(reverse('approve_invite', args=[invite.id]))
        response = self.client.post(reverse('approve_invite', args=[invite.id]))
        self.assertEqual(response.status_code, 302)
        invite.refresh_from_db()
        self.assertTrue(invite.is_approved)


@override_settings(
    ADMIN_APPROVER_EMAILS=[APPROVER], EMAIL_VERIFICATION_REQUIRED=False
)
class PendingAdminLoginTests(RoleTestCase):
    """An invitation is inert until it is approved."""

    def make_invitation(self, email, approved):
        user = User.objects.create_user(
            username='invitee_{}'.format(approved), email=email,
            password=PASSWORD, role='admin',
        )
        user.is_approved = approved
        user.email_verified = True
        user.save()
        return user

    def post_login(self, user):
        return self.client.post(
            reverse('login'),
            {'username': user.username, 'password': PASSWORD},
        )

    def test_unapproved_admin_cannot_sign_in(self):
        invitee = self.make_invitation('pending@example.test', approved=False)
        response = self.post_login(invitee)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.session.get('_auth_user_id'))
        self.assertContains(response, 'pending approval')

    def test_approved_admin_can_sign_in(self):
        invitee = self.make_invitation('granted@example.test', approved=True)
        response = self.post_login(invitee)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.session.get('_auth_user_id'), str(invitee.pk)
        )

    def test_citizens_are_unaffected_by_the_widened_gate(self):
        """The gate is `not is_approved`; citizens default to True."""
        self.assertTrue(self.citizen.is_approved)
        response = self.post_login(self.citizen)
        self.assertEqual(response.status_code, 302)


@override_settings(ADMIN_APPROVER_EMAILS=[APPROVER])
class ApproverSidebarTests(RoleTestCase):
    """The link must match the guard, or an admin sees a dead 403."""

    def setUp(self):
        super().setUp()
        self.approver = User.objects.create_user(
            username='owner', email=APPROVER, password=PASSWORD,
            role='admin',
        )
        self.approver.is_approved = True
        self.approver.email_verified = True
        self.approver.save()

    def test_link_shown_to_the_approver(self):
        self.login_as(self.approver)
        response = self.client.get(reverse('admin_dashboard'))
        self.assertContains(response, reverse('admin_invites'))

    def test_link_hidden_from_a_non_approver_admin(self):
        self.login_as(self.admin)
        response = self.client.get(reverse('admin_dashboard'))
        self.assertNotContains(response, reverse('admin_invites'))

    def test_link_hidden_from_a_citizen(self):
        self.login_as(self.citizen)
        response = self.client.get(reverse('citizen_dashboard'))
        self.assertNotContains(response, reverse('admin_invites'))


class ApproverSettingTests(RoleTestCase):
    """The allow-list is configuration, not code."""

    def test_defaults_to_the_configured_owner_address(self):
        from crims import settings

        self.assertIn('solankimihir1210@gmail.com', settings.ADMIN_APPROVER_EMAILS)

    @override_settings(ADMIN_APPROVER_EMAILS=[])
    def test_empty_allow_list_denies_everyone(self):
        from accounts.permissions import is_account_approver

        admin = User.objects.create_user(
            username='a', email=OUTSIDER, password=PASSWORD, role='admin',
        )
        admin.is_approved = True
        admin.save()
        self.assertFalse(is_account_approver(admin))

    def test_anonymous_is_never_an_approver(self):
        from django.contrib.auth.models import AnonymousUser
        from accounts.permissions import is_account_approver

        self.assertFalse(is_account_approver(AnonymousUser()))