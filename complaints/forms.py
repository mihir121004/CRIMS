from django import forms
from .models import Complaint


class ComplaintForm(forms.ModelForm):
    priority = forms.ChoiceField(
        choices=[('High', 'High'), ('Medium', 'Medium'), ('Low', 'Low')],
        initial='Medium',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = Complaint

        fields = [
            'title',
            'description',
            'location',
            'incident_date',
            'priority',
            'longitude',
            'latitude',
        ]

        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Mobile phone stolen near MG Road',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Describe what happened, when it happened, and any details that may help the investigation…',
            }),
            'location': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. MG Road, Ahmedabad',
            }),
            'incident_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'latitude': forms.HiddenInput(),
            'longitude': forms.HiddenInput(),
        }