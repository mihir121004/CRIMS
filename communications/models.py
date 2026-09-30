from django.db import models
from django.conf import settings
from complaints.models import Complaint

class Message(models.Model):

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='messages')

    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    content = models.TextField()

    is_read = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.sender} - {self.complaint.id}"

