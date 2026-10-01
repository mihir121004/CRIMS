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
    id_document = models.FileField(
        upload_to='id_uploads/%Y/%m/',
        blank=True,
        null=True,
    )

    # --- OTP storage -----------------------------------------------------
    # Previously a plaintext 6-digit code sat in `otp`. A database leak handed
    # an attacker every live verification and password-reset code. The code is
    # now salted+hashed, bound to a purpose, and time-limited.
    otp = models.CharField(max_length=64, blank=True, null=True)
    otp_salt = models.CharField(max_length=64, blank=True, null=True)
    otp_purpose = models.CharField(max_length=16, blank=True, null=True)
    otp_issued_at = models.DateTimeField(blank=True, null=True)

    email_verified = models.BooleanField(default=False)

    current_case_count = models.IntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=['role', 'is_approved']),
            models.Index(fields=['role', 'current_case_count']),
        ]

    def set_otp(self, code, purpose):
        """Store a hashed, purpose-bound OTP."""
        from .utils import (
            OTP_PURPOSE_RESET,
            OTP_PURPOSE_VERIFY,
            make_otp_salt,
            hash_otp,
        )
        from django.utils import timezone

        assert purpose in (OTP_PURPOSE_VERIFY, OTP_PURPOSE_RESET)

        self.otp_salt = make_otp_salt()
        self.otp = hash_otp(code, self.otp_salt)
        self.otp_purpose = purpose
        self.otp_issued_at = timezone.now()
        self._plain_otp = code  # transient, never persisted

    def get_otp_code(self):
        """The plaintext code, available only in the request that issued it."""
        return getattr(self, '_plain_otp', None)

    def clear_otp(self):
        self.otp = None
        self.otp_salt = None
        self.otp_purpose = None
        self.otp_issued_at = None
        self._plain_otp = None
