"""
Shared fixtures for the CRIMS test suite.

Every test runs against an isolated MySQL test database created by
Django's test runner (prefix ``test_``), so no production data is touched.
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase

from complaints.models import Complaint
from evidence.models import Evidence
from investigations.models import Investigation
from suspects.models import Suspect
from witnesses.models import Witness

User = get_user_model()

PASSWORD = 'Str0ngTestPass!234'


class RoleTestCase(TestCase):
    """Base class providing one user per role plus seeded case data."""

    def setUp(self):
        self.citizen = self.make_user('citizen_one', 'citizen')
        self.other_citizen = self.make_user('citizen_two', 'citizen')
        self.officer = self.make_user('officer_one', 'officer')
        self.other_officer = self.make_user('officer_two', 'officer')
        self.admin = self.make_user('admin_one', 'admin')

        self.citizen_complaint = Complaint.objects.create(
            citizen=self.citizen,
            title='Citizen One Burglary',
            description='A stranger broke into my flat and stole documents.',
            location='12 Residency Road',
            incident_date=date.today() - timedelta(days=2),
            status='pending',
            priority='Medium',
            category='theft',
        )
        self.other_complaint = Complaint.objects.create(
            citizen=self.other_citizen,
            title='Citizen Two Fraud',
            description='Someone drained my bank account without consent.',
            location='44 Market Street',
            incident_date=date.today() - timedelta(days=1),
            status='review',
            priority='High',
            category='fraud',
        )

        self.investigation = Investigation.objects.create(
            complaint=self.citizen_complaint, assigned_officer=self.officer
        )
        self.other_investigation = Investigation.objects.create(
            complaint=self.other_complaint, assigned_officer=self.other_officer
        )

        self.suspect = Suspect.objects.create(
            full_name='Suspect Alpha',
            age=34,
            gender='Male',
            complaint=self.citizen_complaint,
            address='9 Back Alley',
            wanted=True,
        )
        self.witness = Witness.objects.create(
            full_name='Witness Bravo',
            age=29,
            phone='+91 90000 00001',
            statement='Observed a figure near the stairwell.',
        )
        self.citizen_complaint.witnesses.add(self.witness)

        self.evidence = Evidence.objects.create(
            complaint=self.citizen_complaint,
            file='evidence/{}/seed.png'.format(self.citizen_complaint.id),
            uploaded_by=self.officer,
        )

    @staticmethod
    def make_user(username, role, **extra):
        user = User.objects.create_user(
            username=username,
            email='{}@test.local'.format(username),
            password=PASSWORD,
            role=role,
        )
        user.is_approved = True
        user.email_verified = True
        for key, value in extra.items():
            setattr(user, key, value)
        user.save()
        return user

    def login_as(self, user):
        self.assertTrue(
            self.client.login(username=user.username, password=PASSWORD)
        )
        return user
