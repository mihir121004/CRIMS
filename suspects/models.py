from django.db import models

class Suspect(models.Model):

    GENDER_CHOICES = (
        ('Male', 'Male'),
        ('Female', 'Female'),
        ('Other', 'Other'),
    )

    full_name = models.CharField(max_length=255)

    age = models.PositiveIntegerField()

    complaint = models.ForeignKey('complaints.Complaint', on_delete=models.CASCADE) 

    gender = models.CharField(max_length=20, choices=GENDER_CHOICES)

    photo = models.ImageField(upload_to='suspects/', blank=True, null=True)

    address = models.TextField()

    phone = models.CharField(max_length=15, blank=True)

    aadhaar_number = models.CharField(max_length=20, blank=True)

    wanted = models.BooleanField(default=False)

    criminal_history = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name