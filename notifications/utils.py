from .models import Notification
from django.core.mail import send_mail
from django.conf import settings


def create_notification(user, title, message):

    Notification.objects.create(user=user,title=title, message=message)

def send_complaint_email(
    complaint
):

    send_mail(

        subject='Complaint Submitted',

        message=f'''
Tracking ID:

{complaint.tracking_id}

Your complaint has been submitted.
''',

        from_email=settings.DEFAULT_FROM_EMAIL,

        recipient_list=[
            complaint.citizen.email
        ],

        fail_silently=True
    )

    send_mail(

    subject='Complaint Status Updated',

    message=f'''

Complaint:

{complaint.tracking_id}

Status:

{complaint.status}

''',

    from_email=settings.DEFAULT_FROM_EMAIL,

    recipient_list=[
        complaint.citizen.email
    ],

    fail_silently=True
)

    send_mail(

    subject='Complaint Resolved',

    message=f'''

Complaint:

{complaint.tracking_id}

has been resolved.

''',

    from_email=settings.DEFAULT_FROM_EMAIL,

    recipient_list=[
        complaint.citizen.email
    ],

    fail_silently=True
)