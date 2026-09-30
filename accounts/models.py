from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):

    ROLE_CHOICES = (
        ('citizen', 'Citizen'),
        ('officer', 'Officer'),
        ('admin', 'Admin'),
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='citizen'
    )
    is_approved = models.BooleanField(default=True)
    id_number = models.CharField(max_length=50, blank=True, null=True)
    id_document = models.FileField(upload_to='id_uploads/', blank=True, null=True)
    otp = models.CharField(max_length=6, blank=True, null=True)
    email_verified = models.BooleanField(default=False)

    current_case_count = models.IntegerField(default=0)