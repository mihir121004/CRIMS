import random

from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.decorators import user_passes_test

def generate_otp():

    return str(
        random.randint(100000, 999999)
    )

def send_otp_email(
        user
):
    send_mail(subject='CRIMS Email Verification', message=f'''
        Hello {user.username}
        Your Verification OTP is:
        {user.otp}
    ''',
        from_email=settings.DEFAULT_FROM_EMAIL, recipient_list=[user.email], fail_silently=False)

def admin_required(view_func=None):
    """Allow access only to users with role 'admin'."""
    actual_decorator = user_passes_test(
        lambda u: u.is_authenticated and u.role == 'admin',
        login_url='login',
    )
    if view_func is None:
        return actual_decorator
    return actual_decorator(view_func)