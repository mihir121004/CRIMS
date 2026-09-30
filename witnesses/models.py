from django.db import models

class Witness(models.Model):

    full_name = models.CharField(max_length=255)

    age = models.PositiveIntegerField()

    phone = models.CharField(max_length=15, blank=True)

    email = models.EmailField(blank=True)

    address = models.TextField()

    statement = models.TextField()

    protected_witness = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name