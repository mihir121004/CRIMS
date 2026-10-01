import uuid
from datetime import datetime

from django.conf import settings
from django.db import models, transaction

from ai_engine.utils import predict_category


class Complaint(models.Model):

    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('review', 'Under Review'),
        ('investigation', 'Investigation Started'),
        ('evidence', 'Evidence Collection'),
        ('resolved', 'Resolved'),
    )

    CATEGORY_CHOICES = (
        ('theft', 'Theft'),
        ('cybercrime', 'Cyber Crime'),
        ('fraud', 'Fraud'),
        ('assault', 'Assault'),
        ('other', 'Other'),
    )

    PRIORITY_CHOICES = (
        ('High', 'High'),
        ('Medium', 'Medium'),
        ('Low', 'Low'),
    )

    #: Words that escalate a report to High priority.
    #:
    #: Root cause of the audit finding
    #: --------------------------------
    #: The view called ``ai_engine.utils.detect_priority()``, which uses a
    #: *different and much narrower* list (murder/weapon/terrorist/attack/
    #: kidnap/bomb) and then overwrote whatever this model computed. That made
    #: an armed robbery - "a man pointed a gun at me", "armed robbery with a
    #: firearm", "I was shot" - classify as **Medium**. This list is now the
    #: single authoritative source and covers weapons, assault and
    #: child-safety terms.
    HIGH_PRIORITY_WORDS = [
        # Homicide / lethal weapons
        'murder', 'homicide', 'manslaughter', 'killed', 'killing',
        'gun', 'firearm', 'pistol', 'revolver', 'rifle', 'shotgun',
        'shot', 'shooting', 'stab', 'stabbed', 'blade', 'knife',
        'weapon', 'armed', 'ammunition',
        'bomb', 'explosive', 'grenade', 'ammunition',
        # Assault / sexual violence
        'assault', 'attack', 'attacked', 'beaten', 'beating', 'torture',
        'rape', 'sexual assault', 'molest',
        # Coercion / abduction
        'kidnap', 'kidnapped', 'abduct', 'abducted', 'hostage', 'ransom',
        'terror', 'terrorist', 'siege',
        # Child safety
        'child abuse', 'minor', 'underage',
    ]

    citizen = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='complaints',
    )

    title = models.CharField(max_length=200)

    category = models.CharField(
        max_length=50, choices=CATEGORY_CHOICES, blank=True
    )

    description = models.TextField()

    location = models.CharField(max_length=255)

    incident_date = models.DateField()

    status = models.CharField(
        max_length=50, choices=STATUS_CHOICES, default='pending'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    tracking_id = models.CharField(max_length=50, unique=True, blank=True)

    priority = models.CharField(
        max_length=20, choices=PRIORITY_CHOICES, default='Medium'
    )

    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    #: Raw classifier output, kept for analytics. Never used as `category`
    #: because the model emits labels that are not valid CATEGORY_CHOICES.
    ai_category = models.CharField(max_length=100, blank=True, null=True)

    suspects = models.ForeignKey(
        'suspects.Suspect',
        blank=True,
        null=True,
        related_name='complaints',
        on_delete=models.SET_NULL,
    )

    witnesses = models.ManyToManyField(
        'witnesses.Witness', blank=True, related_name='complaints'
    )

    class Meta:
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['citizen', '-created_at']),
            models.Index(fields=['priority', 'status']),
        ]

    def __str__(self):
        return self.tracking_id or self.title

    # -- helpers ---------------------------------------------------------

    @classmethod
    def _generate_tracking_id(cls):
        year = datetime.now().year
        for _attempt in range(10):
            candidate = 'CRIMS-{}-{}'.format(
                year, uuid.uuid4().hex[:6].upper()
            )
            if not cls.objects.filter(tracking_id=candidate).exists():
                return candidate
        # 16^6 space exhausted after 10 collisions is effectively impossible,
        # but fall back to a full uuid rather than raising IntegrityError.
        return 'CRIMS-{}-{}'.format(year, uuid.uuid4().hex[:12].upper())

    @staticmethod
    def normalise_category(raw):
        """Map classifier output onto a valid ``CATEGORY_CHOICES`` value.

        Root cause of the audit finding
        ------------------------------
        ``predict_category`` returns labels such as ``'Cyber Crime'`` and
        ``'Theft'``, but ``CATEGORY_CHOICES`` stores ``'cybercrime'`` and
        ``'theft'``. The raw value was written straight into the column, so
        **100% of AI-assigned categories violated the declared choices** and
        matched no ``{% if category == ... %}`` filter or dropdown.
        """
        if not raw:
            return 'other'

        slug = str(raw).strip().lower().replace(' ', '').replace('-', '')
        mapping = {
            'theft': 'theft',
            'stolen': 'theft',
            'burglary': 'theft',
            'cybercrime': 'cybercrime',
            'fraud': 'fraud',
            'scam': 'fraud',
            'assault': 'assault',
            'violence': 'assault',
        }
        return mapping.get(slug, 'other')

    def _derive_priority(self, text):
        haystack = (text or '').lower()
        for word in self.HIGH_PRIORITY_WORDS:
            if word in haystack:
                return 'High'
        return 'Medium'

    def save(self, *args, **kwargs):
        # Root cause of the audit findings
        # --------------------------------
        # 1. Tracking id used ``uuid4()[:6]`` - a 16.7M space on a
        #    ``unique=True`` column with no retry, so a collision raised an
        #    IntegrityError and lost the report.
        # 2. Priority was recomputed on *every* save, so an officer changing
        #    the status silently rewrote the triage priority. The view also
        #    overwrote it with the weaker ai_engine list.
        # 3. ``predict_category(self.description)`` crashed with
        #    AttributeError when description was None/empty.
        # 4. AI ran twice per submission (once in the view, once here).

        if not self.tracking_id:
            self.tracking_id = self._generate_tracking_id()

        is_new = self._state.adding

        if is_new:
            description = (self.description or '').strip()
            if not description:
                # Cannot classify an empty report; caller should have
                # validated this already. Fail loudly rather than 500 later.
                from django.core.exceptions import ValidationError
                raise ValidationError(
                    {'description': 'A description is required.'}
                )

            if not self.category:
                try:
                    raw_prediction = predict_category(description)
                except Exception:
                    raw_prediction = None
                self.ai_category = str(raw_prediction) if raw_prediction else None
                self.category = self.normalise_category(raw_prediction)

            self.priority = self._derive_priority(description)

        super().save(*args, **kwargs)
