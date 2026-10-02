from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm

from .models import User
from .validators import validate_uploaded_id_document


AUTH_PLACEHOLDERS = {
    'username': 'Enter your username',
    'email': 'Enter your email address',
    'password': 'Enter your password',
    'password1': 'Create a password',
    'password2': 'Confirm your password',
    'new_password1': 'New password',
    'new_password2': 'Confirm new password',
    'otp': 'Enter the 6-digit OTP',
    'id_number': 'Enter your ID number',
}


class CrimsStyleMixin:
    """
    Applies Bootstrap input classes and placeholders to every field,
    so manually rendered auth forms match the CRIMS dark theme.
    """

    def style_fields(self):
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'

            placeholder = AUTH_PLACEHOLDERS.get(name)
            if placeholder:
                field.widget.attrs['placeholder'] = placeholder


class RegisterForm(CrimsStyleMixin, UserCreationForm):
    id_number = forms.CharField(required=False, max_length=50)
    id_document = forms.FileField(required=False)

    #: Roles a member of the public is ever allowed to pick for themselves.
    #: ``admin`` is deliberately absent - self-registering as an administrator
    #: was the privilege-escalation bug found in the audit.
    SELF_SERVICE_ROLES = (
        ('citizen', 'Citizen'),
        ('officer', 'Officer'),
    )

    role = forms.ChoiceField(
        choices=SELF_SERVICE_ROLES,
        initial='citizen',
        help_text='Select Officer only if you are registering as law enforcement.',
    )

    class Meta:
        model = User

        # 'role' is intentionally NOT in this list. It is declared above as a
        # ChoiceField so the field is rendered and validated, but the model
        # default ('citizen') is applied unless the view explicitly overrides
        # it. This prevents clients from injecting an arbitrary role value.
        fields = [
            'username',
            'email',
            'id_number',
            'id_document',
            'password1',
            'password2'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Re-add the whitelisted role field after UserCreationForm stripped it.
        self.fields['role'] = forms.ChoiceField(
            choices=self.SELF_SERVICE_ROLES,
            initial='citizen',
            required=True,
            help_text=(
                'Select Officer only if you are registering as law enforcement.'
            ),
        )
        self.style_fields()

    def clean_id_document(self):
        return validate_uploaded_id_document(self.cleaned_data.get('id_document'))


class CrimsAuthenticationForm(CrimsStyleMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()


class OTPVerificationForm(CrimsStyleMixin, forms.Form):
    otp = forms.CharField(max_length=6)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()


class ForgotPasswordForm(CrimsStyleMixin, forms.Form):
    email = forms.EmailField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()


class ResetPasswordForm(CrimsStyleMixin, forms.Form):
    otp = forms.CharField(max_length=6)
    new_password1 = forms.CharField(widget=forms.PasswordInput)
    new_password2 = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('new_password1')
        password2 = cleaned_data.get('new_password2')

        if password1 and password2 and password1 != password2:
            raise forms.ValidationError(
                'The two password fields did not match.'
            )
        return cleaned_data


class AdminInviteForm(CrimsStyleMixin, forms.Form):
    """Invite someone to hold the ``admin`` role.

    Administrators cannot be self-registered - ``RegisterForm`` deliberately
    omits the role for exactly that reason. So the only path in is an
    invitation issued by a designated approver, which then creates the account
    *unapproved*. The invitee still has to verify their address and set a
    password before they can sign in.
    """

    email = forms.EmailField(
        max_length=254,
        help_text=(
            'They will hold no access until this address is approved. '
            'They sign in with a username they choose after verifying '
            'their email address.'
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()
        self.fields['email'].widget.attrs['placeholder'] = (
            'Enter the address to invite'
        )

    def clean_email(self):
        address = self.cleaned_data['email'].strip().lower()
        existing = User.objects.filter(email__iexact=address).first()
        if existing is None:
            return address

        if existing.role == 'admin' and existing.is_approved:
            raise forms.ValidationError(
                'That address already belongs to an active administrator.'
            )
        if existing.role == 'admin':
            raise forms.ValidationError(
                'That address already has a pending administrator invitation.'
            )
        # An existing citizen/officer account is upgraded in place rather than
        # duplicated: two rows for one address would split that person's
        # complaint history in half.
        self.existing_user = existing
        return address