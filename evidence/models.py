from django.db import models
from complaints.models import Complaint
from django.conf import settings

class Evidence(models.Model):

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='evidence')

    file = models.FileField(upload_to='evidence/')

    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.file.name

class EvidenceCustody(models.Model):

    evidence = models.ForeignKey('Evidence', on_delete=models.CASCADE, related_name='custody_logs')

    transferred_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='evidence_sent')

    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='evidence_received')

    location = models.CharField(max_length=255)

    remarks = models.TextField(blank=True)

    transferred_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.evidence.id} = {self.location}"