from django.conf import settings
from django.db import models

from complaints.models import Complaint

from accounts.validators import evidence_upload_path


class Evidence(models.Model):

    complaint = models.ForeignKey(
        Complaint,
        on_delete=models.CASCADE,
        related_name='evidence',
    )

    #: Root cause of the audit findings
    #:
    #: * ``upload_to='evidence/'`` stored files under the client's original
    #:   filename. Now randomised per complaint via
    #:   ``accounts.validators.evidence_upload_path``.
    #: * No size/type validation. Enforced in ``evidence.forms.EvidenceForm``.
    #: * **No record of who uploaded.** ``evidence/detail.html`` therefore
    #:   rendered ``evidence.complaint.citizen`` as "Uploaded By", showing the
    #:   *complainant* no matter which officer actually filed the file. Added
    #:   below (nullable so existing rows migrate cleanly).
    file = models.FileField(upload_to=evidence_upload_path)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_evidence',
    )

    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.file.name


class EvidenceCustody(models.Model):

    evidence = models.ForeignKey(
        Evidence, on_delete=models.CASCADE, related_name='custody_logs'
    )

    transferred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='evidence_sent',
    )

    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='evidence_received',
    )

    location = models.CharField(max_length=255)

    remarks = models.TextField(blank=True)

    transferred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-transferred_at']
        indexes = [
            models.Index(fields=['evidence', '-transferred_at']),
        ]

    def __str__(self):
        return '{} = {}'.format(self.evidence_id, self.location)
