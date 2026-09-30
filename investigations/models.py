from django.db import models 
from django.conf import settings
from complaints.models import Complaint

class Investigation(models.Model):

    complaint = models.OneToOneField(Complaint, on_delete=models.CASCADE)

    assigned_officer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_cases')

    notes = models.TextField(blank=True)

    started_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    # current_case_count = models.IntegerField(default=0)

    def __str__(self):
        return f"Investigation #{self.complaint.id}"

class InvestigationNote(models.Model):

    investigation = models.ForeignKey(Investigation, on_delete=models.CASCADE, related_name='timeline')

    officer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    note = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.note[:50]