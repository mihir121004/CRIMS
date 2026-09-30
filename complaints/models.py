from django.db import models
from django.conf import settings
import uuid
from datetime import datetime
from ai_engine.utils import predict_category

class Complaint(models.Model):

    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('review', 'Under Review'),
        ('investigation', 'Investigation Started'),
        ('evidence', 'Evidence Collection'),
        ('resolved', "Resolved"),
    )

    CATEGORY_CHOICES = (
        ('theft', 'Theft'),
        ('cybercrime', 'Cyber Crime'),
        ('fraud', 'Fraud'),
        ('assault', 'Assault'),
        ('other', 'Other'),
    )

    HIGH_PRIORITY_WORDS = [
        'murder',
        'kidnap',
        'rape',
        'terror',
        'weapon',
        'gun',
    ]

    citizen = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    title = models.CharField(max_length=200)

    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)

    description = models.TextField()

    location = models.CharField(max_length=255)

    incident_date = models.DateField()

    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='pending')

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    tracking_id = models.CharField(max_length=50, unique=True, blank=True)

    priority = models.CharField(max_length=20, default='Medium')

    latitude = models.FloatField(null=True, blank=True)

    longitude = models.FloatField(null=True, blank=True)

    ai_category = models.CharField(max_length=100, blank=True, null=True)

    suspects = models.ForeignKey('suspects.Suspect', blank=True, null=True,related_name='complaints', on_delete=models.CASCADE)

    witnesses = models.ManyToManyField('witnesses.Witness', blank=True, related_name='complaints')

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.tracking_id:
            year = datetime.now().year
            unique = str(uuid.uuid4())[:6].upper()
            self.tracking_id = (
                f"CRIMS-{year}-{unique}"
            )

        if not self.category:
            self.category = predict_category(
                self.description
            )
            
        if self.description:
            description = self.description.lower()
            self.priority = 'Medium'
            for word in self.HIGH_PRIORITY_WORDS:
                if word in description:
                    self.priority = 'High'
                    break
        super().save(*args, **kwargs)