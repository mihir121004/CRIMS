"""
Account utility helpers.

Root cause this module fixes
---------------------------
``generate_otp`` used :func:`random.randint`, which draws from the Mersenne
Twister. That generator is *not* cryptographically secure: its internal state
is recoverable from ~624 observed outputs, after which every future OTP is
predictable. A predictable OTP means account takeover via email verification
and password reset.

OTPs are now generated with :mod:`secrets` (backed by the OS CSPRNG), bound to
a purpose ('verify' vs 'reset'), and stored hashed so a database leak does not
hand an attacker valid codes.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.core.mail import send_mail
from django.utils import timezone

#: OTPs are short-lived.
OTP_TTL = timedelta(minutes=15)

#: Purposes an OTP can be issued for. An OTP issued for 'reset' must not
#: satisfy email verification, and vice versa.
OTP_PURPOSE_VERIFY = 'verify'
OTP_PURPOSE_RESET = 'reset'


def generate_otp():
    """Return a cryptographically random 6-digit OTP.

    Uses :func:`secrets.randbelow`, not :func:`random.randint`.
    """
    return '{:06d}'.format(secrets.randbelow(1_000_000))


def hash_otp(otp, salt):
    """Hash an OTP for at-rest storage."""
    return hashlib.sha256(
        '{}{}'.format(salt, otp).encode('utf-8')
    ).hexdigest()


def make_otp_salt():
    return secrets.token_hex(16)


def otp_is_valid(user, purpose, candidate):
    """Constant-time comparison of ``candidate`` against the stored OTP.

    Returns False if the OTP is missing, expired, or issued for a different
    purpose.
    """
    salt = user.otp_salt
    if not salt or not user.otp or not candidate:
        return False

    # An OTP issued for one purpose must never satisfy the other. Without this
    # a password-reset code would also verify an email address.
    if user.otp_purpose != purpose:
        return False

    if purpose == OTP_PURPOSE_VERIFY:
        if user.email_verified:
            return False
    else:
        issued = getattr(user, 'otp_issued_at', None)
        if not issued:
            return False
        if timezone.now() - issued > OTP_TTL:
            return False

    expected = hash_otp(candidate, salt)
    return hmac.compare_digest(expected, user.otp)


def send_otp_email(user, purpose=OTP_PURPOSE_VERIFY):
    """Send the OTP to ``user``. Never raises - a mail outage must not 500 the
    signup flow (this was a production outage: an expired OAuth token made
    ``POST /register/`` raise)."""
    if purpose == OTP_PURPOSE_RESET:
        subject = 'CRIMS Password Reset Code'
        intro = 'Use the code below to reset your password.'
    else:
        subject = 'CRIMS Email Verification'
        intro = 'Use the code below to verify your email address.'

    try:
        send_mail(
            subject=subject,
            message=(
                'Hello {username},\n\n{intro}\n\n{otp}\n\n'
                'This code expires in {minutes} minutes.\n'
            ).format(
                username=user.username,
                intro=intro,
                otp=user.get_otp_code(),
                minutes=int(OTP_TTL.total_seconds() // 60),
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        return True
    except Exception:
        # Logged by the caller; a failed send must not abort registration.
        return False


def admin_required(view_func=None):
    """Allow access only to users with role 'admin'.

    Retained for backwards compatibility - new code should import
    ``accounts.permissions.admin_required``, which also returns a 403 (rather
    than a login redirect) for authenticated users with the wrong role.
    """
    actual_decorator = user_passes_test(
        lambda u: u.is_authenticated and u.role == 'admin',
        login_url='login',
    )
    if view_func is None:
        return actual_decorator
    return actual_decorator(view_func)
