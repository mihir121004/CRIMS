from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm

from .models import User


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

    class Meta:
        model = User

        fields = [
            'username',
            'email',
            'role',
            'id_number',
            'id_document',
            'password1',
            'password2'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()


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