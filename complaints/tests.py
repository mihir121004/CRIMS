"""End-to-end workflow tests: the ten stages of the complaint lifecycle."""

from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from crims.test_support import RoleTestCase
from accounts.models import User
from complaints.models import Complaint
from communications.models import Message
from evidence.models import Evidence, EvidenceCustody
from investigations.models import Investigation, InvestigationNote
from notifications.models import Notification
from reports.models import ActivityLog
from suspects.models import Suspect
from witnesses.models import Witness


class ComplaintLifecycleTests(RoleTestCase):
    """Create -> assign -> investigate -> evidence -> witnesses/suspects ->
    status updates -> closure."""

    def test_stage_1_citizen_creates_complaint(self):
        self.client.logout()
        self.login_as(self.citizen)
        response = self.client.post(
            reverse('create_complaint'),
            {
                'title': 'Bike snatched near market',
                'description': 'A man on a motorbike snatched my bike.',
                'location': 'Market Road',
                'incident_date': str(date.today()),
                'priority': 'Medium',
                'latitude': '23.02',
                'longitude': '72.57',
            },
        )
        self.assertEqual(response.status_code, 302)
        complaint = Complaint.objects.filter(title='Bike snatched near market').first()
        self.assertIsNotNone(complaint)
        self.assertEqual(complaint.citizen_id, self.citizen.id)
        self.assertTrue(complaint.tracking_id.startswith('CRIMS-'))
        self.assertIn(complaint.priority, ('High', 'Medium', 'Low'))

    def test_stage_1_rejects_empty_description(self):
        self.login_as(self.citizen)
        response = self.client.post(
            reverse('create_complaint'),
            {
                'title': 'No narrative',
                'description': '',
                'location': 'x',
                'incident_date': str(date.today()),
                'priority': 'Medium',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Complaint.objects.filter(title='No narrative').count(), 0)

    def test_stage_2_least_loaded_officer_is_assigned(self):
        self.client.logout()
        self.citizen_complaint.delete()
        self.officer.current_case_count = 5
        self.officer.save()
        self.other_officer.current_case_count = 1
        self.other_officer.save()

        self.login_as(self.citizen)
        self.client.post(
            reverse('create_complaint'),
            {
                'title': 'Auto load test',
                'description': 'A van parked outside my gate.',
                'location': 'Gate 4',
                'incident_date': str(date.today()),
                'priority': 'Medium',
            },
        )
        complaint = Complaint.objects.filter(title='Auto load test').first()
        investigation = Investigation.objects.filter(complaint=complaint).first()
        self.assertIsNotNone(investigation)
        self.assertEqual(investigation.assigned_officer_id, self.other_officer.id)

    def test_stage_2_admin_can_reassign_officer(self):
        self.login_as(self.admin)
        response = self.client.post(
            reverse('assign_officer', args=[self.citizen_complaint.id]),
            {'officer': self.other_officer.id},
        )
        self.assertEqual(response.status_code, 302)
        self.investigation.refresh_from_db()
        self.assertEqual(
            self.investigation.assigned_officer_id, self.other_officer.id
        )

    def test_stage_2_reassignment_adjusts_workload_counters(self):
        self.officer.current_case_count = 3
        self.officer.save()
        self.other_officer.current_case_count = 0
        self.other_officer.save()

        self.login_as(self.admin)
        self.client.post(
            reverse('assign_officer', args=[self.citizen_complaint.id]),
            {'officer': self.other_officer.id},
        )
        self.officer.refresh_from_db()
        self.other_officer.refresh_from_db()
        self.assertEqual(self.officer.current_case_count, 2)
        self.assertEqual(self.other_officer.current_case_count, 1)

    def test_stage_3_assigned_officer_adds_note(self):
        self.login_as(self.officer)
        response = self.client.post(
            reverse('add_note', args=[self.investigation.id]),
            {'note': 'Scene visited, no forced entry found.'},
        )
        self.assertEqual(response.status_code, 302)
        note = InvestigationNote.objects.get()
        self.assertEqual(note.officer_id, self.officer.id)
        self.assertIn('Scene visited', note.note)

    def test_stage_3_empty_note_is_rejected(self):
        self.login_as(self.officer)
        self.client.post(
            reverse('add_note', args=[self.investigation.id]), {'note': '   '}
        )
        self.assertEqual(InvestigationNote.objects.count(), 0)

    def test_stage_4_citizen_uploads_evidence_to_own_case(self):
        self.login_as(self.citizen)
        upload = SimpleUploadedFile(
            'scene.png', b'\x89PNG\r\n\x1a\n' + b'a' * 64,
            content_type='image/png',
        )
        response = self.client.post(
            reverse('upload_evidence', args=[self.citizen_complaint.id]),
            {'file': upload},
        )
        self.assertEqual(response.status_code, 302)
        evidence = Evidence.objects.exclude(
            pk=self.evidence.pk
        ).latest('uploaded_at')
        self.assertEqual(evidence.complaint_id, self.citizen_complaint.id)
        self.assertEqual(
            evidence.uploaded_by_id, self.citizen.id,
            'Uploader must be recorded, not inferred from the complainant.',
        )
        self.assertNotIn(
            'scene.png', evidence.file.name,
            'Client filename must not be used verbatim.',
        )

    def test_stage_4_custody_chain_transfer(self):
        evidence = Evidence.objects.create(
            complaint=self.citizen_complaint,
            file='evidence/1/abc.png',
            uploaded_by=self.citizen,
        )
        self.login_as(self.officer)
        response = self.client.post(
            reverse('transfer_evidence', args=[evidence.id]),
            {
                'received_by': self.other_officer.id,
                'location': 'Evidence locker A3',
                'remarks': 'Sealed bag transferred.',
            },
        )
        self.assertEqual(response.status_code, 302)
        custody = EvidenceCustody.objects.get()
        self.assertEqual(custody.transferred_by_id, self.officer.id)
        self.assertEqual(custody.received_by_id, self.other_officer.id)
        self.assertEqual(custody.location, 'Evidence locker A3')

    def test_stage_5_witness_management_and_protection_toggle(self):
        self.login_as(self.officer)
        response = self.client.post(
            reverse('witness_create'),
            {
                'full_name': 'New Witness',
                'age': 31,
                'phone': '+91 98888 77777',
                'email': 'nw@test.local',
                'address': 'Sector 9',
                'statement': 'Saw a vehicle reversing away.',
                'protected_witness': 'on',
            },
        )
        self.assertEqual(response.status_code, 302)
        witness = Witness.objects.get(full_name='New Witness')
        self.assertTrue(witness.protected_witness)

        self.client.post(reverse('toggle_protection', args=[witness.id]))
        witness.refresh_from_db()
        self.assertFalse(
            witness.protected_witness,
            'VULNERABILITY: the Change Protection link was a no-op.',
        )

    def test_stage_5_witness_list_status_filter_now_works(self):
        Witness.objects.create(
            full_name='Protected One', age=40,
            statement='stmt', protected_witness=True,
        )
        self.login_as(self.officer)
        response = self.client.get(reverse('witness_list'), {'status': 'protected'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Protected One')
        self.assertNotContains(response, 'Witness Bravo')

    def test_stage_6_suspect_management_and_clear_toggle(self):
        self.login_as(self.officer)
        response = self.client.post(
            reverse('suspect_create'),
            {
                'full_name': 'New Suspect',
                'age': 29,
                'gender': 'Male',
                'complaint': self.citizen_complaint.id,
                'address': 'Lane 4',
                'phone': '+91 90000 11111',
                'criminal_history': 'Prior theft conviction.',
                'wanted': 'on',
            },
        )
        self.assertEqual(response.status_code, 302)
        suspect = Suspect.objects.get(full_name='New Suspect')
        self.assertTrue(suspect.wanted)

        self.client.post(reverse('clear_suspect', args=[suspect.id]))
        suspect.refresh_from_db()
        self.assertFalse(
            suspect.wanted,
            'VULNERABILITY: the Mark Cleared link was a no-op.',
        )

    def test_stage_7_citizen_posts_in_case_chat(self):
        self.login_as(self.citizen)
        response = self.client.post(
            reverse('complaint_chat', args=[self.citizen_complaint.id]),
            {'content': 'The thief returned, please call me.'},
        )
        self.assertEqual(response.status_code, 302)
        message = Message.objects.get()
        self.assertEqual(message.sender_id, self.citizen.id)

    def test_stage_7_officer_replies_in_case_chat(self):
        self.login_as(self.officer)
        self.client.post(
            reverse('complaint_chat', args=[self.citizen_complaint.id]),
            {'content': 'Officer dispatched to your location.'},
        )
        self.assertEqual(Message.objects.count(), 1)

    def test_stage_8_status_change_notifies_complainant(self):
        self.login_as(self.officer)
        self.client.post(
            reverse('update_status', args=[self.citizen_complaint.id]),
            {'status': 'resolved'},
        )
        self.citizen_complaint.refresh_from_db()
        self.assertEqual(self.citizen_complaint.status, 'resolved')
        self.assertTrue(
            Notification.objects.filter(user=self.citizen).exists(),
            'Citizen must be notified of their own case status.',
        )

    def test_stage_9_citizen_sees_their_case_progress(self):
        self.citizen_complaint.status = 'investigation'
        self.citizen_complaint.save(update_fields=['status'])
        self.login_as(self.citizen)
        response = self.client.get(reverse('my_complaints'))
        self.assertContains(response, 'Citizen One Burglary')

    def test_stage_10_case_closure_and_activity_trail(self):
        self.login_as(self.officer)
        self.client.post(
            reverse('update_status', args=[self.citizen_complaint.id]),
            {'status': 'resolved'},
        )
        self.assertTrue(
            ActivityLog.objects.filter(
                user=self.officer, action__icontains='Status changed'
            ).exists(),
            'Every status change must leave an audit entry.',
        )

    def test_full_lifecycle_end_to_end(self):
        """All ten stages in sequence, exactly as a real case progresses."""
        self.client.logout()
        self.login_as(self.citizen)
        self.client.post(
            reverse('create_complaint'),
            {
                'title': 'End to end robbery',
                'description': 'A person attacked me with a knife and took cash.',
                'location': 'Bus stand',
                'incident_date': str(date.today()),
                'priority': 'Medium',
            },
        )
        complaint = Complaint.objects.get(title='End to end robbery')

        self.client.logout()
        self.login_as(self.officer)
        for status in ('review', 'investigation', 'evidence', 'resolved'):
            self.client.post(
                reverse('update_status', args=[complaint.id]),
                {'status': status},
            )

        complaint.refresh_from_db()
        self.assertEqual(complaint.status, 'resolved')
        self.assertEqual(
            complaint.priority, 'High',
            'A knife attack must triage as High priority.',
        )
        self.assertIsNotNone(complaint.ai_category)
        self.assertIn(
            complaint.category,
            {c for c, _ in Complaint.CATEGORY_CHOICES},
        )


class CitizenDashboardTests(RoleTestCase):
    """Root cause of the audit finding: the KPI context keys did not match the
    template, so 3 of 4 cards rendered permanently blank."""

    def test_kpi_values_are_present_in_context(self):
        self.citizen_complaint.status = 'pending'
        self.citizen_complaint.save(update_fields=['status'])
        self.other_complaint.status = 'resolved'
        self.other_complaint.save(update_fields=['status'])

        self.login_as(self.citizen)
        response = self.client.get(reverse('citizen_dashboard'))
        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.context['pending_count'], 1)
        self.assertEqual(response.context['resolved_count'], 0)
        self.assertEqual(response.context['total_complaints'], 1)

    def test_rendered_counters_are_not_empty(self):
        self.login_as(self.citizen)
        response = self.client.get(reverse('citizen_dashboard'))
        body = response.content.decode()
        self.assertNotIn('<h3 class="counter"></h3>', body)
        self.assertNotIn('data: [,,]', body)
        self.assertIn('data: [', body)


class DashboardAccessTests(RoleTestCase):
    def test_dashboard_redirects_by_role(self):
        for user, expected in (
            (self.citizen, 'citizen_dashboard'),
            (self.officer, 'officer_dashboard'),
            (self.admin, 'admin_dashboard'),
        ):
            with self.subTest(role=user.role):
                self.client.logout()
                self.login_as(user)
                response = self.client.get(reverse('dashboard'))
                self.assertRedirects(
                    response, reverse(expected), fetch_redirect_response=False
                )

    def test_citizen_cannot_open_officer_dashboard(self):
        self.login_as(self.citizen)
        self.assertEqual(
            self.client.get(reverse('officer_dashboard')).status_code, 403
        )

    def test_officer_cannot_open_admin_dashboard(self):
        self.login_as(self.officer)
        self.assertEqual(
            self.client.get(reverse('admin_dashboard')).status_code, 403
        )


class NotificationTests(RoleTestCase):
    def test_cannot_mark_another_users_notification_read(self):
        from notifications.models import Notification as N
        other = N.objects.create(
            user=self.other_citizen, message='Not yours'
        )
        self.login_as(self.citizen)
        response = self.client.post(reverse('mark_read', args=[other.id]))
        self.assertEqual(response.status_code, 404)
        other.refresh_from_db()
        self.assertFalse(other.is_read)

    def test_mark_read_requires_post(self):
        self.login_as(self.citizen)
        self.assertEqual(
            self.client.get(reverse('mark_read', args=[1])).status_code, 405
        )


class ErrorPageTests(RoleTestCase):
    def test_unknown_url_returns_404(self):
        response = self.client.get('/definitely-not-a-real-url/')
        self.assertEqual(response.status_code, 404)

    def test_403_page_does_not_leak_internals(self):
        self.login_as(self.citizen)
        response = self.client.get(reverse('suspect_list'))
        self.assertEqual(response.status_code, 403)
        body = response.content.decode()
        self.assertNotIn('Traceback', body)
        self.assertNotIn('settings.py', body)


class ModelIntegrityTests(TestCase):
    """PHASE 4: model-level correctness."""

    def test_tracking_id_is_unique_and_generated(self):
        user = User.objects.create_user(
            username='mk', email='mk@test.local', password='x'
        )
        ids = set()
        for i in range(25):
            complaint = Complaint.objects.create(
                citizen=user,
                title='Case {}'.format(i),
                description='Some narrative for case {}'.format(i),
                location='Loc',
                incident_date=date.today(),
                category='theft',
            )
            self.assertTrue(complaint.tracking_id)
            ids.add(complaint.tracking_id)
        self.assertEqual(len(ids), 25, 'Tracking IDs collided.')

    def test_ai_category_is_normalised_to_valid_choice(self):
        valid = {c for c, _ in Complaint.CATEGORY_CHOICES}
        self.assertEqual(Complaint.normalise_category('Theft'), 'theft')
        self.assertEqual(Complaint.normalise_category('Cyber Crime'), 'cybercrime')
        self.assertEqual(Complaint.normalise_category('Fraud'), 'fraud')
        self.assertEqual(Complaint.normalise_category('Assault'), 'assault')
        self.assertEqual(Complaint.normalise_category('nonsense'), 'other')
        self.assertEqual(Complaint.normalise_category(''), 'other')
        self.assertTrue(
            all(
                Complaint.normalise_category(v) in valid
                for v in ['Theft', 'Cyber Crime', 'Fraud', 'zzz']
            )
        )

    def test_armed_crime_is_high_priority(self):
        user = User.objects.create_user(
            username='pri', email='pri@test.local', password='x'
        )
        armed = [
            'A man pointed a gun at me and took my phone',
            'armed robbery with a firearm',
            'I was shot and bleeding',
            'someone attacked me with a knife',
            'they threatened me with a weapon',
            'bomb threat at the school',
        ]
        for text in armed:
            with self.subTest(text=text):
                complaint = Complaint.objects.create(
                    citizen=user,
                    title='t',
                    description=text,
                    location='l',
                    incident_date=date.today(),
                    category='assault',
                )
                complaint.refresh_from_db()
                self.assertEqual(
                    complaint.priority, 'High',
                    'Armed crime must be High priority.',
                )

    def test_minor_offence_is_medium_priority(self):
        user = User.objects.create_user(
            username='min', email='min@test.local', password='x'
        )
        complaint = Complaint.objects.create(
            citizen=user, title='t',
            description='I lost my wallet on the bus.',
            location='l', incident_date=date.today(), category='theft',
        )
        self.assertEqual(complaint.priority, 'Medium')

    def test_status_update_does_not_recompute_priority(self):
        """Priority was recomputed on every save, so a status change silently
        rewrote the triage level."""
        user = User.objects.create_user(
            username='st', email='st@test.local', password='x'
        )
        complaint = Complaint.objects.create(
            citizen=user, title='t',
            description='A person attacked me with a knife.',
            location='l', incident_date=date.today(), category='assault',
        )
        self.assertEqual(complaint.priority, 'High')
        complaint.status = 'resolved'
        complaint.save(update_fields=['status', 'updated_at'])
        complaint.refresh_from_db()
        self.assertEqual(complaint.priority, 'High')

    def test_empty_description_raises_validation_error(self):
        from django.core.exceptions import ValidationError
        user = User.objects.create_user(
            username='ed', email='ed@test.local', password='x'
        )
        with self.assertRaises(ValidationError):
            Complaint.objects.create(
                citizen=user, title='t', description='   ',
                location='l', incident_date=date.today(), category='theft',
            )

    def test_ai_confidence_is_not_fabricated(self):
        from ai_engine.utils import predict_confidence
        self.assertEqual(predict_confidence(''), 0)
        self.assertEqual(predict_confidence('The sky is blue today'), 0)
