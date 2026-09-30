from django import forms
from .models import (Evidence, EvidenceCustody)


class EvidenceForm(forms.ModelForm):

    class Meta:
        model = Evidence

        fields = ['file']

class EvidenceCustodyForm(forms.ModelForm):
    class Meta:
        model = EvidenceCustody

        fields = [
            'received_by',
            'location',
            'remarks'
        ]