from django import forms

from .models import Witness


class WitnessForm(forms.ModelForm):
    """Root cause of the audit finding
    ---------------------------------
    ``fields = '__all__'`` let a client set ``protected_witness`` - the flag
    that drives witness-safety handling - along with any other column. Fields
    are now enumerated explicitly.

    (The submit button also sat outside the ``<form>`` element, making this
    form unusable - fixed in templates/witnesses/witness_form.html.)
    """

    class Meta:
        model = Witness

        fields = [
            'full_name',
            'age',
            'phone',
            'email',
            'address',
            'statement',
            'protected_witness',
        ]

    def clean_age(self):
        age = self.cleaned_data.get('age')
        if age is not None and (age < 0 or age > 120):
            raise forms.ValidationError('Enter a realistic age (0-120).')
        return age

    def clean_full_name(self):
        name = (self.cleaned_data.get('full_name') or '').strip()
        if len(name) < 2:
            raise forms.ValidationError('Enter the witness’s full name.')
        return name

    def clean_statement(self):
        statement = (self.cleaned_data.get('statement') or '').strip()
        if not statement:
            raise forms.ValidationError('A witness statement is required.')
        return statement
