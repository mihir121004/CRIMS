from django import forms

from accounts.validators import validate_uploaded_photo
from .models import Suspect


class SuspectForm(forms.ModelForm):
    """Root cause of the audit finding
    ---------------------------------
    ``fields = '__all__'`` exposed every model field to the client, so a POST
    could set ``wanted``, the audit ``created_at``, and any other column.

    ``complaint`` is a *required* FK on the model, so it cannot simply be
    dropped from the form (that made ``form.save()`` raise
    "complaint_id cannot be null"). It is re-declared here as a
    ``ModelChoiceField`` whose queryset is restricted to the cases the current
    user is permitted to attach a suspect to - the client may choose *among
    permitted cases*, never write an arbitrary id.

    (The submit button also sat outside the ``<form>`` element, making this
    form unusable - fixed in templates/suspects/suspect_form.html.)
    """

    photo = forms.ImageField(required=False, validators=[validate_uploaded_photo])

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from accounts.permissions import visible_complaints
        if user is not None:
            allowed = visible_complaints(user)
            if user.is_authenticated and user.role not in ('officer', 'admin'):
                allowed = allowed.filter(citizen=user)
            self.fields['complaint'].queryset = allowed

    class Meta:
        model = Suspect

        fields = [
            'full_name',
            'age',
            'gender',
            'complaint',
            'phone',
            'aadhaar_number',
            'address',
            'criminal_history',
            'wanted',
            'photo',
        ]

    def clean_photo(self):
        return validate_uploaded_photo(self.cleaned_data.get('photo'))

    def clean_age(self):
        age = self.cleaned_data.get('age')
        if age is not None and (age < 0 or age > 120):
            raise forms.ValidationError('Enter a realistic age (0-120).')
        return age

    def clean_full_name(self):
        name = (self.cleaned_data.get('full_name') or '').strip()
        if len(name) < 2:
            raise forms.ValidationError('Enter the suspect’s full name.')
        return name
