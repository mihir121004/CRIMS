from django import forms

from accounts.validators import validate_uploaded_evidence
from .models import (Evidence, EvidenceCustody)


class EvidenceForm(forms.ModelForm):
    """Root cause of the audit findings
    ---------------------------------
    * No file validation at all - any extension and any size was accepted.
    * No uploader recorded, so ``evidence/detail.html`` displayed the
      *complainant* as "Uploaded By" regardless of who actually uploaded.
    """

    file = forms.FileField(validators=[validate_uploaded_evidence])

    class Meta:
        model = Evidence

        fields = ['file']

    def clean_file(self):
        upload = self.cleaned_data.get('file')
        if upload is not None and not upload.name:
            raise forms.ValidationError('The uploaded file has no name.')
        return upload


class EvidenceCustodyForm(forms.ModelForm):
    class Meta:
        model = EvidenceCustody

        fields = [
            'received_by',
            'location',
            'remarks'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from accounts.models import User
        # Only active staff may take custody of evidence.
        self.fields['received_by'].queryset = User.objects.filter(
            role__in=('officer', 'admin'),
            is_active=True,
            is_approved=True,
        ).order_by('username')
