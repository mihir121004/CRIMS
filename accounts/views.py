from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
import logging
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger('crims.errors')

from .forms import (
    RegisterForm,
    OTPVerificationForm,
    CrimsAuthenticationForm,
    ForgotPasswordForm,
    ResetPasswordForm,
)
from .models import User
from .permissions import admin_required
from .utils import (
    OTP_PURPOSE_RESET,
    OTP_PURPOSE_VERIFY,
    generate_otp,
    otp_is_valid,
    send_otp_email,
)


def home(request):
    return render(request, 'public/home.html')


def register_view(request):
    """Self-service registration.

    Root cause of the audit's privilege-escalation finding
    ----------------------------------------------------
    ``RegisterForm`` used ``fields = [..., 'role', ...]`` straight off the
    model, so the client's POST body chose the role. Only ``officer`` was
    special-cased; posting ``role=admin`` produced an immediately logged-in
    administrator. The role is now taken from a whitelisted ChoiceField in the
    form and re-validated against ``User.ROLE_CHOICES`` here, so an unknown or
    tampered value falls back to 'citizen'.
    """
    if request.method == 'POST':
        form = RegisterForm(request.POST, request.FILES)

        if form.is_valid():
            user = form.save(commit=False)

            requested_role = form.cleaned_data.get('role', 'citizen')
            valid_roles = {code for code, _label in User.ROLE_CHOICES}
            if requested_role not in valid_roles:
                requested_role = 'citizen'

            user.role = requested_role
            # Public self-registration can never create an administrator.
            if requested_role == 'admin':
                user.role = 'citizen'

            if user.role == 'officer':
                user.is_approved = False
                id_number = form.cleaned_data.get('id_number')
                if not id_number:
                    form.add_error(
                        'id_number',
                        'ID number is required for officer registration.',
                    )
                    return render(
                        request,
                        'accounts/register.html',
                        {'form': form, 'stats': get_auth_stats()},
                    )
                user.id_number = id_number

            from django.conf import settings
            if settings.EMAIL_VERIFICATION_REQUIRED:
                code = generate_otp()
                user.set_otp(code, OTP_PURPOSE_VERIFY)
                user.save()
                request.session['verify_user_id'] = user.id
                # A mail outage must not abort registration (this raised an
                # unhandled HTTPError and 500'd the whole signup flow).
                if not send_otp_email(user, OTP_PURPOSE_VERIFY):
                    # Roll the account back. Saving the row before the send
                    # and merely clearing the OTP on failure left an orphaned
                    # account that could never be verified - nobody holds the
                    # code, and the username is now taken forever.
                    request.session.pop('verify_user_id', None)
                    user.delete()
                    form.add_error(
                        None,
                        'We could not send the verification email. '
                        'Please try again in a few minutes.',
                    )
                    return render(
                        request,
                        'accounts/register.html',
                        {'form': form, 'stats': get_auth_stats()},
                    )
                return redirect('verify_email')

            user.email_verified = True
            user.clear_otp()
            user.save()

            if user.role == 'officer' and not user.is_approved:
                return render(
                    request,
                    'accounts/registration_pending.html',
                    {
                        'message': 'Your registration as officer is pending '
                                   'admin approval. You will be notified once '
                                   'approved.'
                    },
                )
            login(request, user)
            return redirect('dashboard')

    else:
        form = RegisterForm()

    return render(
        request,
        'accounts/register.html',
        {'form': form, 'stats': get_auth_stats()},
    )


def get_auth_stats():
    from complaints.models import Complaint
    return {
        'total_cases': Complaint.objects.count(),
        'resolved_cases': Complaint.objects.filter(status='resolved').count(),
        'total_officers': User.objects.filter(role='officer').count(),
    }


def login_view(request):
    if request.method == 'POST':
        form = CrimsAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()

            from django.conf import settings
            if settings.EMAIL_VERIFICATION_REQUIRED and not user.email_verified:
                request.session['verify_user_id'] = user.id
                messages.error(
                    request,
                    'Your account requires email verification before login.',
                )
                return redirect('verify_email')

            if user.role == 'officer' and not user.is_approved:
                form.add_error(
                    None, 'Your officer account is pending admin approval.'
                )
            else:
                login(request, user)
                return redirect('dashboard')
    else:
        form = CrimsAuthenticationForm(request)

    return render(
        request,
        'accounts/login.html',
        {'form': form, 'stats': get_auth_stats()},
    )


@require_POST
def logout_view(request):
    """POST-only.

    Previously any ``<img src="/logout/">`` on a third-party page could sign a
    police officer out.
    """
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


# ---------------------------------------------------------------------------
# Officer approval  (audit finding: unauthenticated, GET-mutating)
# ---------------------------------------------------------------------------

@admin_required
def pending_officers(request):
    """Was reachable by anonymous users with no role check at all."""
    pending = User.objects.filter(role='officer', is_approved=False)
    return render(
        request,
        'accounts/pending_officers.html',
        {'pending_officers': pending},
    )


@admin_required
@require_POST
def approve_officer(request, user_id):
    """Was a plain ``<a href>`` GET with no auth and no CSRF: anyone could
    approve an account, and ``reject_officer`` could permanently delete one.
    Now POST + CSRF + admin-only.
    """
    user = User.objects.filter(
        id=user_id, role='officer', is_approved=False
    ).first()
    if user:
        user.is_approved = True
        user.save(update_fields=['is_approved'])
        messages.success(
            request, 'Officer {} has been approved.'.format(user.username)
        )
    else:
        messages.error(request, 'That officer could not be found.')
    return redirect('pending_officers')


@admin_required
@require_POST
def reject_officer(request, user_id):
    """Admin-only POST. The account is deactivated rather than hard-deleted so
    its complaint history and audit trail survive."""
    user = User.objects.filter(
        id=user_id, role='officer', is_approved=False
    ).first()
    if user:
        username = user.username
        user.is_active = False
        user.is_approved = False
        user.save(update_fields=['is_active', 'is_approved'])
        messages.success(request, 'Officer {} has been rejected.'.format(username))
    else:
        messages.error(request, 'That officer could not be found.')
    return redirect('pending_officers')


def verify_email(request):
    """OTP verification.

    Root cause of the audit finding: the code was matched against *every* user
    (``User.objects.filter(otp=otp).first()``) rather than the user bound to
    this session, so a 6-digit guess could verify an arbitrary account. The
    code is now checked only against ``session['verify_user_id']`` using a
    constant-time comparison.
    """
    user_obj = None
    session_user_id = request.session.get('verify_user_id')
    if session_user_id:
        user_obj = User.objects.filter(id=session_user_id).first()
        if user_obj is None:
            request.session.pop('verify_user_id', None)

    if user_obj is None:
        messages.info(
            request, 'Start a registration or login to verify your email.'
        )
        return redirect('login')

    if request.method == 'POST':
        form = OTPVerificationForm(request.POST)
        if form.is_valid():
            if otp_is_valid(
                user_obj, OTP_PURPOSE_VERIFY, form.cleaned_data['otp']
            ):
                user_obj.email_verified = True
                user_obj.clear_otp()
                user_obj.save(update_fields=['email_verified', 'otp',
                                             'otp_salt', 'otp_purpose',
                                             'otp_issued_at'])
                request.session.pop('verify_user_id', None)
                messages.success(request, 'Email verified. Please sign in.')
                return redirect('login')
            form.add_error('otp', 'Invalid or expired OTP code.')
    else:
        form = OTPVerificationForm()

    return render(
        request,
        'accounts/verify_email.html',
        {'form': form, 'user': user_obj},
    )


def forgot_password(request):
    """Does not reveal whether an address is registered.

    Root cause of the audit finding: an unknown address returned the error
    "No account found with this email address", letting an attacker enumerate
    every registered account. The response is now identical either way.
    """
    generic = ('If an account exists for that address, a reset code has been '
               'sent.')

    if request.method == 'POST':
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            user = User.objects.filter(email__iexact=email).first()
            if user and user.is_active:
                code = generate_otp()
                user.set_otp(code, OTP_PURPOSE_RESET)
                user.save(update_fields=['otp', 'otp_salt', 'otp_purpose',
                                         'otp_issued_at'])
                request.session['reset_user_id'] = user.id
                send_otp_email(user, OTP_PURPOSE_RESET)

            messages.info(request, generic)
            return redirect('reset_password')
    else:
        form = ForgotPasswordForm()

    return render(request, 'accounts/forgot_password.html', {'form': form})


def reset_password(request):
    user_id = request.session.get('reset_user_id')
    if not user_id:
        return redirect('forgot_password')

    user = User.objects.filter(id=user_id, is_active=True).first()
    if not user:
        request.session.pop('reset_user_id', None)
        return redirect('forgot_password')

    if request.method == 'POST':
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            if otp_is_valid(
                user, OTP_PURPOSE_RESET, form.cleaned_data['otp']
            ):
                user.set_password(form.cleaned_data['new_password1'])
                user.clear_otp()
                user.save()
                request.session.pop('reset_user_id', None)
                messages.success(request, 'Password updated. Please sign in.')
                return redirect('login')
            form.add_error('otp', 'Invalid or expired OTP code.')
    else:
        form = ResetPasswordForm()

    return render(request, 'accounts/reset_password.html', {'form': form})


def health_check(request):
    """Liveness/readiness probe.

    Reports only a boolean. Deliberately unauthenticated (a monitor has no
    session) but discloses nothing: no versions, no settings, no counts.
    """
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        database_ok = True
    except Exception:
        database_ok = False

    from django.http import JsonResponse

    return JsonResponse(
        {'status': 'ok' if database_ok else 'degraded', 'database': database_ok},
        status=200 if database_ok else 503,
    )


@csrf_exempt
def run_migrations(request):
    """Apply pending migrations against the deployed database.

    Why this exists
    ---------------
    Vercel has no release phase, the function bundle is read-only, and there is
    no shell to run ``manage.py migrate`` from. A deploy that ships new columns
    therefore leaves the production schema behind the code, and the first query
    touching that table raises ``OperationalError: Unknown column``. That is
    exactly how ``POST /login/`` started returning 500.

    Guards, all of which must pass
    ------------------------------
    * ``CRON_SECRET`` must be configured, otherwise the route refuses outright.
      A deployment without it cannot migrate at all - it fails closed rather
      than falling open.
    * ``Authorization: Bearer <CRON_SECRET>``, compared with
      ``secrets.compare_digest`` so the comparison is not timing-leaky. The
      token is never echoed back and never logged.
    * Only ``GET`` (list pending) and ``POST`` (apply) do anything; every other
      verb is a 405, so crawlers and link prefetch cannot trigger it.

    ``GET`` reports pending migrations without changing anything, which makes it
    safe to use as a drift check.

    Why ``csrf_exempt``
    -------------------
    CSRF defends endpoints whose authority comes from an ambient cookie. This
    route's authority comes from an explicit ``Authorization`` header, which a
    browser will not attach on its own - an attacker on another origin cannot
    make a victim send the bearer token. Leaving CSRF enforcement on would only
    mean the documented ``curl -X POST`` invocation fails with a 403, so the
    exemption removes no protection that anything else was providing.
    """
    import os
    import secrets
    from io import StringIO

    from django.core.management import call_command
    from django.http import JsonResponse

    expected = os.environ.get('CRON_SECRET', '').strip()
    if not expected:
        return JsonResponse(
            {'error': 'migrations are not configured on this deployment'},
            status=503,
        )

    scheme, _, presented = request.META.get('HTTP_AUTHORIZATION', '').partition(' ')
    if scheme.lower() != 'bearer' or not secrets.compare_digest(
        presented.strip(), expected
    ):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    if request.method not in ('GET', 'POST'):
        return JsonResponse({'error': 'method not allowed'}, status=405)

    def pending():
        out = StringIO()
        call_command('showmigrations', '--plan', stdout=out, verbosity=1)
        # Lines look like '[ ]  app.0001_initial'; keep only the label, which
        # is what migrate() must be handed back.
        return [
            line.split(']', 1)[-1].strip()
            for line in out.getvalue().splitlines()
            if line.startswith('[ ]')
        ]

    outstanding = pending()
    if not outstanding:
        return JsonResponse({'status': 'up-to-date', 'applied': []})

    if request.method == 'GET':
        return JsonResponse({'status': 'pending', 'pending': outstanding})

    applied = []
    try:
        for name in outstanding:
            # migrate() wants the app label and the migration name as two
            # separate arguments; passing "app.0001_x" as one argument is read
            # as an app label and raises LookupError.
            app_label, _, migration_name = name.partition('.')
            call_command(
                'migrate', app_label, migration_name,
                interactive=False, verbosity=0,
            )
            applied.append(name)
    except Exception as exc:
        # The caller only ever sees the exception *type*: driver text can echo
        # connection details. The traceback goes to the log, which is the only
        # place it is safe to be.
        logger.exception('migration failed at %s', name)
        return JsonResponse(
            {
                'status': 'failed',
                'applied': applied,
                'failed_on': name,
                'detail': type(exc).__name__,
            },
            status=500,
        )

    still_pending = pending()
    return JsonResponse(
        {
            'status': 'ok' if not still_pending else 'incomplete',
            'applied': applied,
            'still_pending': still_pending,
        }
    )
