"""
Regression tests for every Critical/High finding in the CRIMS security audit.

Each test names the exact vulnerability it prevents from returning. If one of
these fails, a previously-exploitable hole has been reopened.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from crims.test_support import PASSWORD, RoleTestCase
from accounts.forms import RegisterForm
from accounts.models import User
from accounts.utils import generate_otp, hash_otp, otp_is_valid
from accounts.validators import validate_uploaded_evidence
from complaints.models import Complaint
from communications.models import Message
from evidence.models import Evidence, EvidenceCustody

User = get_user_model()


class PrivilegeEscalationTests(TestCase):
    """#1 Self-service registration could create a full administrator."""

    def test_cannot_self_register_as_admin(self):
        response = self.client.post(
            reverse('register'),
            {
                'username': 'sneaky_admin',
                'email': 'sneaky@test.local',
                'role': 'admin',
                'id_number': 'FORGED-1',
                'password1': 'Str0ngTestPass!234',
                'password2': 'Str0ngTestPass!234',
            },
            follow=True,
        )
        user = User.objects.filter(username='sneaky_admin').first()
        # The role field is a whitelist ChoiceField, so `admin` is not a valid
        # input at all: the form is rejected and no account is created. That is
        # stronger than downgrading the role after the fact.
        self.assertIsNone(
            user,
            'VULNERABILITY: an account was created from role=admin.',
        )
        self.assertContains(response, 'Select a valid choice')

    def test_role_field_rejects_unknown_values(self):
        form = RegisterForm(
            data={
                'username': 'someone',
                'email': 'x@test.local',
                'role': 'superuser',
                'password1': 'Str0ngTestPass!234',
                'password2': 'Str0ngTestPass!234',
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn('role', form.errors)

    def test_citizen_registration_defaults_to_citizen(self):
        form = RegisterForm(
            data={
                'username': 'goodcitizen',
                'email': 'c@test.local',
                'role': 'citizen',
                'password1': 'Str0ngTestPass!234',
                'password2': 'Str0ngTestPass!234',
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save(commit=False)
        self.assertEqual(user.role, 'citizen')


class UnauthenticatedAccessTests(TestCase):
    """#5/#6 Views with no authentication, verified live on production."""

    PROTECTED_ANONYMOUS = [
        '/pending-officers/',
        '/reports/activity/',
        '/analytics/crime-map/',
        '/analytics/ai-dashboard/',
        '/analytics/ai-command-center/',
        '/complaints/officer/',
        '/suspects/',
        '/witnesses/',
        '/investigations/',
        '/evidence/upload/1/',
        '/complaints/officer-dashboard/',
    ]

    def test_anonymous_cannot_reach_protected_pages(self):
        for url in self.PROTECTED_ANONYMOUS:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertIn(
                    response.status_code, (302, 403),
                    'VULNERABILITY: {} returned {} anonymously.'.format(
                        url, response.status_code
                    ),
                )

    def test_officer_approval_endpoints_reject_anonymous_get(self):
        """approve/reject were plain <a href> GETs with no auth and no CSRF.

        A 302 to the login page IS the block here - the assertion is that the
        request is redirected to /login/ and never executes the action.
        """
        for name in ('approve_officer', 'reject_officer'):
            with self.subTest(name=name):
                url = reverse(name, args=[999999])
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn('/login/', response['Location'])

    def test_officer_approval_endpoints_reject_anonymous_post(self):
        officer = User.objects.create_user(
            username='pending_officer', email='p@test.local',
            password=PASSWORD, role='officer',
        )
        officer.is_approved = False
        officer.save()

        response = self.client.post(
            reverse('approve_officer', args=[officer.id])
        )
        officer.refresh_from_db()
        self.assertFalse(
            officer.is_approved,
            'VULNERABILITY: anonymous POST approved an officer.',
        )

    def test_officer_approval_requires_admin_role(self):
        officer = User.objects.create_user(
            username='pending_officer2', email='p2@test.local',
            password=PASSWORD, role='officer',
        )
        officer.is_approved = False
        officer.save()

        citizen = User.objects.create_user(
            username='plain_citizen', email='pc@test.local',
            password=PASSWORD, role='citizen',
        )
        self.client.login(username='plain_citizen', password=PASSWORD)
        response = self.client.post(
            reverse('approve_officer', args=[officer.id])
        )
        officer.refresh_from_db()
        self.assertFalse(officer.is_approved)
        self.assertEqual(response.status_code, 403)

    def test_logout_requires_post(self):
        user = User.objects.create_user(
            username='lo', email='lo@test.local', password=PASSWORD
        )
        self.client.login(username='lo', password=PASSWORD)
        response = self.client.get(reverse('logout'))
        self.assertEqual(
            response.status_code, 405,
            'VULNERABILITY: GET logout still works (CSRF logout).',
        )

    def test_chat_does_not_500_on_anonymous_post(self):
        """Was IntegrityError: AnonymousUser into a non-null FK."""
        complaint = Complaint.objects.create(
            citizen=User.objects.create_user(
                username='chat_owner', email='co@test.local',
                password=PASSWORD,
            ),
            title='Chat owner case',
            description='Something happened on the road.',
            location='Somewhere',
            incident_date='2026-01-01',
            category='theft',
        )
        response = self.client.post(
            reverse('complaint_chat', args=[complaint.id]),
            {'content': 'hello from anonymous'},
        )
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(Message.objects.count(), 0)


class IDORTests(RoleTestCase):
    """#2/#3/#4 Every data view took an unfiltered pk."""

    def test_citizen_cannot_read_another_citizens_complaint(self):
        self.login_as(self.citizen)
        response = self.client.get(
            reverse('complaint_detail', args=[self.other_complaint.id])
        )
        # 404 (not 403) so the response does not confirm the record exists.
        self.assertEqual(response.status_code, 404)

    def test_citizen_cannot_read_another_citizens_fir_pdf(self):
        """The FIR embeds complainant name, address and the full narrative.
        It is now staff-only, so a citizen is refused before the id is even
        considered - no pk leaks."""
        self.login_as(self.citizen)
        response = self.client.get(
            reverse('fir_pdf', args=[self.other_complaint.id])
        )
        self.assertEqual(response.status_code, 403)

    def test_anonymous_cannot_read_any_fir_pdf(self):
        """The audit found this reachable with no authentication at all."""
        response = self.client.get(
            reverse('fir_pdf', args=[self.citizen_complaint.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_officer_can_read_fir_for_any_case(self):
        self.login_as(self.officer)
        response = self.client.get(
            reverse('fir_pdf', args=[self.other_complaint.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_citizen_cannot_open_another_citizens_chat(self):
        self.login_as(self.citizen)
        response = self.client.get(
            reverse('complaint_chat', args=[self.other_complaint.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_citizen_cannot_change_case_status(self):
        """A citizen POSTed status=resolved and closed a real open case."""
        self.login_as(self.citizen)
        response = self.client.post(
            reverse('update_status', args=[self.citizen_complaint.id]),
            {'status': 'resolved'},
        )
        self.citizen_complaint.refresh_from_db()
        self.assertEqual(
            self.citizen_complaint.status, 'pending',
            'VULNERABILITY: a citizen closed an open case.',
        )
        self.assertIn(response.status_code, (302, 403))

    def test_citizen_cannot_change_status_of_others_case(self):
        self.login_as(self.citizen)
        self.client.post(
            reverse('update_status', args=[self.other_complaint.id]),
            {'status': 'resolved'},
        )
        self.other_complaint.refresh_from_db()
        self.assertEqual(self.other_complaint.status, 'review')

    def test_citizen_cannot_add_investigation_note(self):
        """Forged the evidentiary audit trail by writing officer notes."""
        self.login_as(self.citizen)
        response = self.client.post(
            reverse('add_note', args=[self.investigation.id]),
            {'note': 'forged note from a citizen'},
        )
        self.assertIn(response.status_code, (302, 403, 404))
        self.assertEqual(self.investigation.timeline.count(), 0)

    def test_officer_cannot_note_on_unassigned_case(self):
        self.login_as(self.officer)
        self.client.post(
            reverse('add_note', args=[self.other_investigation.id]),
            {'note': 'not my case'},
        )
        self.assertEqual(self.other_investigation.timeline.count(), 0)

    def test_citizen_cannot_list_suspects_or_witnesses(self):
        self.login_as(self.citizen)
        for url in (reverse('suspect_list'), reverse('witness_list')):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_citizen_cannot_upload_evidence_to_others_case(self):
        self.login_as(self.citizen)
        before = Evidence.objects.count()
        upload = SimpleUploadedFile(
            'proof.png', b'\x89PNG\r\n\x1a\n' + b'0' * 32,
            content_type='image/png',
        )
        response = self.client.post(
            reverse('upload_evidence', args=[self.other_complaint.id]),
            {'file': upload},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Evidence.objects.count(), before)

    def test_citizen_cannot_read_evidence_from_others_case(self):
        evidence = Evidence.objects.create(
            complaint=self.other_complaint, file='evidence/x/secret.png'
        )
        self.login_as(self.citizen)
        response = self.client.get(
            reverse('evidence_detail', args=[evidence.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_citizen_cannot_transfer_evidence_custody(self):
        evidence = Evidence.objects.create(
            complaint=self.citizen_complaint, file='evidence/x/e.png'
        )
        self.login_as(self.citizen)
        response = self.client.post(
            reverse('transfer_evidence', args=[evidence.id]),
            {'received_by': self.officer.id, 'location': 'Annex'},
        )
        self.assertIn(response.status_code, (302, 403))
        self.assertEqual(EvidenceCustody.objects.count(), 0)


class ObjectLevelScopingTests(RoleTestCase):
    """Staff scoping and the own-record allowance."""

    def test_citizen_can_read_own_complaint(self):
        self.login_as(self.citizen)
        response = self.client.get(
            reverse('complaint_detail', args=[self.citizen_complaint.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Citizen One Burglary')

    def test_officer_can_read_any_complaint(self):
        self.login_as(self.officer)
        response = self.client.get(
            reverse('complaint_detail', args=[self.other_complaint.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_officer_investigation_list_is_scoped_to_assignments(self):
        self.login_as(self.officer)
        response = self.client.get(reverse('investigation_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Citizen One Burglary')
        self.assertNotContains(response, 'Citizen Two Fraud')

    def test_officer_cannot_read_unassigned_investigation(self):
        self.login_as(self.officer)
        response = self.client.get(
            reverse('investigation_detail', args=[self.other_investigation.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_admin_sees_every_investigation(self):
        self.login_as(self.admin)
        response = self.client.get(reverse('investigation_list'))
        self.assertContains(response, 'Citizen One Burglary')
        self.assertContains(response, 'Citizen Two Fraud')

    def test_officer_can_advance_status_of_assigned_case(self):
        self.login_as(self.officer)
        self.client.post(
            reverse('update_status', args=[self.citizen_complaint.id]),
            {'status': 'investigation'},
        )
        self.citizen_complaint.refresh_from_db()
        self.assertEqual(self.citizen_complaint.status, 'investigation')


class StatusValidationTests(RoleTestCase):
    """#3c request.POST.get('status') was written unvalidated."""

    def test_arbitrary_status_string_is_rejected(self):
        self.login_as(self.officer)
        self.client.post(
            reverse('update_status', args=[self.citizen_complaint.id]),
            {'status': '<script>alert(1)</script>'},
        )
        self.citizen_complaint.refresh_from_db()
        self.assertEqual(self.citizen_complaint.status, 'pending')

    def test_valid_status_is_accepted(self):
        self.login_as(self.officer)
        for code, _label in Complaint.STATUS_CHOICES:
            with self.subTest(status=code):
                self.client.post(
                    reverse('update_status',
                            args=[self.citizen_complaint.id]),
                    {'status': code},
                )
                self.citizen_complaint.refresh_from_db()
                self.assertEqual(self.citizen_complaint.status, code)


class OTPSecurityTests(TestCase):
    """#12 OTPs used random.randint and sat in the database in plaintext."""

    def test_generate_otp_uses_secure_source(self):
        import random
        codes = {generate_otp() for _ in range(50)}
        self.assertEqual(len(codes), 50, 'OTP generator is repeating')
        for code in codes:
            self.assertEqual(len(code), 6)
            self.assertTrue(code.isdigit())

    def test_otp_is_not_stored_in_plaintext(self):
        user = User.objects.create_user(
            username='otpuser', email='otp@test.local', password=PASSWORD
        )
        user.set_otp('123456', 'verify')
        user.save()
        user.refresh_from_db()
        self.assertNotEqual(user.otp, '123456')
        self.assertEqual(len(user.otp), 64)

    def test_otp_is_bound_to_purpose(self):
        user = User.objects.create_user(
            username='otpuser2', email='otp2@test.local', password=PASSWORD
        )
        user.set_otp('123456', 'reset')
        user.save()
        user.refresh_from_db()
        self.assertFalse(
            otp_is_valid(user, 'verify', '123456'),
            'VULNERABILITY: a reset OTP satisfied email verification.',
        )
        self.assertTrue(otp_is_valid(user, 'reset', '123456'))

    def test_otp_verification_is_bound_to_session_user(self):
        user = User.objects.create_user(
            username='otpuser3', email='otp3@test.local', password=PASSWORD
        )
        user.set_otp('123456', 'verify')
        user.save()

        session = self.client.session
        session['verify_user_id'] = user.id
        session.save()

        self.client.post(reverse('verify_email'), {'otp': '123456'})
        user.refresh_from_db()
        self.assertTrue(user.email_verified)

    def test_reset_otp_does_not_verify_email(self):
        user = User.objects.create_user(
            username='otpuser4', email='otp4@test.local', password=PASSWORD
        )
        user.set_otp('654321', 'reset')
        user.save()
        session = self.client.session
        session['verify_user_id'] = user.id
        session.save()
        self.client.post(reverse('verify_email'), {'otp': '654321'})
        user.refresh_from_db()
        self.assertFalse(user.email_verified)


class UserEnumerationTests(TestCase):
    """forgot_password revealed whether an address was registered."""

    def test_response_is_identical_for_known_and_unknown_email(self):
        User.objects.create_user(
            username='known', email='known@test.local', password=PASSWORD
        )

        known = self.client.post(
            reverse('forgot_password'), {'email': 'known@test.local'}
        )
        unknown = self.client.post(
            reverse('forgot_password'), {'email': 'nobody@test.local'}
        )

        known_body = known.content.decode()
        unknown_body = unknown.content.decode()
        self.assertNotIn('No account found', known_body)
        self.assertNotIn('No account found', unknown_body)
        self.assertEqual(known.status_code, unknown.status_code)


class UploadValidationTests(TestCase):
    """#13 FileFields accepted any type and any size."""

    def test_rejects_executable_html_upload(self):
        upload = SimpleUploadedFile('xss.html', b'<script>alert(1)</script>')
        with self.assertRaises(ValidationError):
            validate_uploaded_evidence(upload)

    def test_rejects_oversized_upload(self):
        oversized = SimpleUploadedFile('big.pdf', b'%PDF' + b'0' * (26 * 1024 * 1024))
        with self.assertRaises(ValidationError):
            validate_uploaded_evidence(oversized)

    def test_accepts_allowed_upload(self):
        ok = SimpleUploadedFile('report.pdf', b'%PDF-1.4 fake')
        self.assertEqual(validate_uploaded_evidence(ok), ok)


class EvidenceUploadPermissionTests(RoleTestCase):
    def test_citizen_can_upload_to_own_case(self):
        self.login_as(self.citizen)
        upload = SimpleUploadedFile(
            'scene.png', b'\x89PNG\r\n\x1a\n' + b'0' * 64,
            content_type='image/png',
        )
        before = Evidence.objects.count()
        response = self.client.post(
            reverse('upload_evidence', args=[self.citizen_complaint.id]),
            {'file': upload},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Evidence.objects.count(), before + 1)

    def test_rejected_upload_does_not_create_a_row(self):
        self.login_as(self.citizen)
        before = Evidence.objects.count()
        bad = SimpleUploadedFile('evil.html', b'<script>alert(1)</script>')
        self.client.post(
            reverse('upload_evidence', args=[self.citizen_complaint.id]),
            {'file': bad},
        )
        self.assertEqual(
            Evidence.objects.count(), before,
            'A rejected upload must not create a row.',
        )


class MassAssignmentTests(RoleTestCase):
    """suspects/forms.py and witnesses/forms.py used fields='__all__'."""

    def test_suspect_form_does_not_accept_arbitrary_fields(self):
        """`fields = '__all__'` is the defect.

        `complaint` is a required FK so it stays as a form field, but it is a
        ModelChoiceField constrained to cases the user may attach to - the
        client picks among permitted cases, it cannot write an arbitrary id.
        Everything unlisted (audit columns, pk) is no longer reachable.
        """
        from suspects.forms import SuspectForm
        form = SuspectForm(
            user=self.officer,
            data={
                'full_name': 'Injected',
                'age': 30,
                'gender': 'Male',
                'address': 'x',
                'wanted': 'on',
                'complaint': self.other_complaint.id,
                'created_at': '1999-01-01',
                'id': 999999,
            },
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn('created_at', form.fields)
        self.assertNotIn('id', form.fields)

        suspect = form.save()
        self.assertNotEqual(suspect.pk, 999999)
        self.assertNotEqual(suspect.created_at.year, 1999)

    def test_suspect_form_rejects_case_outside_scope(self):
        """A non-staff user cannot attach a suspect to a case they cannot see."""
        from suspects.forms import SuspectForm
        form = SuspectForm(
            user=self.citizen,
            data={
                'full_name': 'Out of scope',
                'age': 30,
                'gender': 'Male',
                'address': 'x',
                'complaint': self.other_complaint.id,
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn('complaint', form.errors)

    def test_witness_form_does_not_accept_arbitrary_fields(self):
        """`fields = '__all__'` is the defect; `protected_witness` is now
        listed deliberately (officers set it) while unlisted columns cannot
        be injected."""
        from witnesses.forms import WitnessForm
        form = WitnessForm(
            data={
                'full_name': 'Injected Witness',
                'age': 30,
                'address': 'Somewhere',
                'statement': 'test statement',
                'protected_witness': 'on',
                # Not a form field: must be ignored entirely.
                'created_at': '1999-01-01',
                'id': 999999,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn('created_at', form.fields)
        self.assertNotIn('id', form.fields)

        witness = form.save()
        self.assertNotEqual(witness.pk, 999999)
        self.assertNotEqual(witness.created_at.year, 1999)
