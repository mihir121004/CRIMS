from django import forms
from .models import Witness

class WitnessForm(forms.ModelForm):
    class Meta:
        model = Witness

        fields = '__all__'