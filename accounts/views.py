from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.contrib import messages
from .forms import (RegisterForm, OTPVerificationForm, CrimsAuthenticationForm, ForgotPasswordForm, ResetPasswordForm)
from accounts.models import User
from .utils import(generate_otp, send_otp_email)
from complaints.models import Complaint

def home(request):
    return render(request, 'public/home.html')

def register_view(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST, request.FILES)

        if form.is_valid():
            user = form.save(commit=False)
            if user.role == 'officer':
                user.is_approved = False
                id_number = form.cleaned_data.get('id_number')
                if not id_number:
                    form.add_error('id_number', 'ID number is required for officer registration.')
                    return render(request, 'accounts/register.html', {
                        'form': form,
                        'stats': get_auth_stats()
                    })
                user.id_number = id_number
            if settings.EMAIL_VERIFICATION_REQUIRED:
                user.otp = generate_otp()
                user.save()
                if user.id_document:
                    user.save()
                request.session['verify_user_id'] = user.id
                send_otp_email(user)
                return redirect('verify_email')
            user.email_verified = True
            user.otp = None
            user.save()
            if user.role == 'officer' and not user.is_approved:
                return render(request, 'accounts/registration_pending.html', {
                    'message': 'Your registration as officer is pending admin approval. You will be notified once approved.'
                })
            login(request, user)
            return redirect('dashboard')

    else:
        form = RegisterForm()

    return render(request, 'accounts/register.html', {
        'form': form,
        'stats': get_auth_stats()
    })

def get_auth_stats():
    return {
        'total_cases': Complaint.objects.count(),
        'resolved_cases': Complaint.objects.filter(status='resolved').count(),
        'total_officers': User.objects.filter(role='officer').count(),
    }


def login_view(request):
    if request.method == 'POST':
        form = CrimsAuthenticationForm(request, data=request.POST)

        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)

            if user:
                if settings.EMAIL_VERIFICATION_REQUIRED and not user.email_verified:
                    form.add_error(
                        'username',
                        'Please verify your email address before logging in.'
                    )
                elif user.role == 'officer' and not user.is_approved:
                    form.add_error(
                        'username',
                        'Your account is pending admin approval. Please wait until an admin verifies your officer registration.'
                    )
                else:
                    login(request, user)
                    return redirect('dashboard')
    else:
        form = CrimsAuthenticationForm()

    return render(request, 'accounts/login.html', {
        'form': form,
        'stats': get_auth_stats()
    })

def logout_view(request):
    logout(request)
    return redirect('home')

@login_required
def dashboard(request):
    role = request.user.role

    if role == 'citizen':
        return redirect('citizen_dashboard')
    elif role == 'officer':
        return redirect('officer_dashboard')
    elif role == 'admin':
        return redirect('admin_dashboard')
    return redirect('home')

def pending_officers(request):
    pending = User.objects.filter(role='officer', is_approved=False)
    return render(request, 'accounts/pending_officers.html', {
        'pending_officers': pending,
    })

def approve_officer(request, user_id):
    user = User.objects.filter(id=user_id, role='officer', is_approved=False).first()
    if user:
        user.is_approved = True
        user.save()
        messages.success(request, f'Officer {user.username} has been approved.')
    return redirect('pending_officers')

def reject_officer(request, user_id):
    user = User.objects.filter(id=user_id, role='officer', is_approved=False).first()
    if user:
        user.delete()
        messages.success(request, f'Officer {user.username} has been rejected.')
    return redirect('pending_officers')

def verify_email(request):
    form = OTPVerificationForm()
    if request.method == 'POST':
        form = OTPVerificationForm(request.POST)
        if form.is_valid():
            otp = form.cleaned_data['otp']
            user = User.objects.filter(otp=otp).first()
            if user:
                user.email_verified = True
                user.otp = None
                user.save()
                request.session.pop('verify_user_id', None)
                return redirect('login')
            form.add_error('otp', 'Invalid or expired OTP code.')
    user_obj = None
    if request.session.get('verify_user_id'):
        try:
            user_obj = User.objects.get(id=request.session.get('verify_user_id'))
        except User.DoesNotExist:
            pass
    return render(request, 'accounts/verify_email.html',
                  {
                      'form': form,
                      'user': user_obj
                  })


def forgot_password(request):
    if request.method == 'POST':
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            user = User.objects.filter(email__iexact=email).first()
            if user:
                user.otp = generate_otp()
                user.save()
                send_otp_email(user)
                request.session['reset_user_id'] = user.id
                return redirect('reset_password')
            form.add_error(
                'email',
                'No account found with this email address.'
            )
    else:
        form = ForgotPasswordForm()
    return render(request, 'accounts/forgot_password.html', {'form': form})


def reset_password(request):
    user_id = request.session.get('reset_user_id')
    if not user_id:
        return redirect('forgot_password')

    user = User.objects.filter(id=user_id).first()
    if not user:
        return redirect('forgot_password')

    if request.method == 'POST':
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            otp = form.cleaned_data['otp']
            if user.otp and user.otp == otp:
                user.set_password(form.cleaned_data['new_password1'])
                user.otp = None
                user.save()
                del request.session['reset_user_id']
                return redirect('login')
            form.add_error('otp', 'Invalid OTP code.')
    else:
        form = ResetPasswordForm()
    return render(request, 'accounts/reset_password.html', {'form': form})