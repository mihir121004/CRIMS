from django.shortcuts import render, redirect
from django.conf import settings
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
import logging
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils.crypto import get_random_string

logger = logging.getLogger('crims.errors')

from .forms import (
    RegisterForm,
    OTPVerificationForm,
    CrimsAuthenticationForm,
    ForgotPasswordForm,
    ResetPasswordForm,
)
from .models import User
from .permissions import admin_required, approver_required
from .utils import (
    OTP_PURPOSE_RESET,
    OTP_PURPOSE_VERIFY,
    generate_otp,
    otp_is_valid,
    redact_email,
    send_otp_email,
)


def _pending_admin_username():
    """A placeholder username for an invited administrator.

    ``UserManager.make_random_username()`` was removed in Django 5.1, so this
    derives one from a cryptographic random string instead. Collision is
    irrelevant either way because the invitee's real username is set when they
    complete verification.
    """
    return 'invite_{}'.format(get_random_string(12, allowed_chars='abcdefghijklmnopqrstuvwxyz0123456789'))


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

            if not user.is_approved:
                return render(
                    request,
                    'accounts/registration_pending.html',
                    {
                        'message': 'Your registration as {0} is pending '
                                   'approval by a designated approver. You '
                                   'will be able to sign in once it is '
                                   'granted.'.format(
                                       user.get_role_display()),
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

            # Any role with is_approved=False is held back, not just officers.
            # An invited administrator is unapproved by construction, and this
            # is the only thing standing between "invited" and "signed in as
            # admin" - so it must not be narrowed to one role.
            if not user.is_approved:
                form.add_error(
                    None,
                    'Your {0} account is pending approval by a designated '
                    'approver.'.format(user.get_role_display().lower()),
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


# ---------------------------------------------------------------------------
# Administrator invitations
# ---------------------------------------------------------------------------
# `admin` is intentionally absent from RegisterForm.SELF_SERVICE_ROLES: letting
# a POST body choose the role is the privilege-escalation bug this project
# already fixed once. The only way in is an invitation from a designated
# approver, and the invitee still lands as `is_approved=False`, so nothing is
# granted at invite time. Approval is a separate, explicit act.

def _admin_invite(user):
    """Pending administrator invitations, excluding the approver's own row."""
    return User.objects.filter(role='admin', is_approved=False).exclude(
        email__in=settings.ADMIN_APPROVER_EMAILS
    )


@approver_required
def admin_invites(request):
    """Issue and review administrator invitations.

    Restricted by ``approver_required``, which requires both ``role='admin'``
    and an address listed in ``settings.ADMIN_APPROVER_EMAILS``. A plain
    admin who is not an approver gets a 403.
    """
    from accounts.forms import AdminInviteForm

    if request.method == 'POST':
        form = AdminInviteForm(request.POST)
        if form.is_valid():
            address = form.cleaned_data['email']
            user = getattr(form, 'existing_user', None) or User(
                username=_pending_admin_username(),
                email=address,
            )
            user.role = 'admin'
            # No password is set, so the account cannot be signed into even if
            # the address were somehow verified without the owner's say-so.
            # They set one via the password-reset flow after verifying.
            user.is_approved = False
            user.is_active = True
            user.set_unusable_password()
            user.save()
            logger.warning(
                'administrator invitation issued to %s by %s',
                redact_email(address), request.user.username,
            )
            messages.success(
                request,
                'Invitation created for {}. They hold no access until you '
                'approve it below.'.format(address),
            )
            return redirect('admin_invites')
    else:
        form = AdminInviteForm()

    return render(
        request,
        'accounts/admin_invites.html',
        {
            'form': form,
            'pending_invites': _admin_invite(request.user),
        },
    )


@approver_required
@require_POST
def approve_invite(request, user_id):
    """Approve an administrator invitation.

    ``is_approved`` alone only unlocks sign-in. It is deliberately *not* an
    escalation to ``is_superuser``: Django's own admin site keys off that
    flag, and this project's admin role does not need it.
    """
    user = User.objects.filter(
        id=user_id, role='admin', is_approved=False
    ).first()
    if user is None:
        messages.error(request, 'That invitation could not be found.')
    elif not user.email_verified:
        messages.error(
            request,
            'That address has not completed email verification yet, so '
            'approving it would grant access to an unproven address. Ask '
            'them to finish verifying first.',
        )
    else:
        user.is_approved = True
        user.save(update_fields=['is_approved'])
        logger.warning(
            'administrator invitation approved for %s by %s',
            redact_email(user.email), request.user.username,
        )
        messages.success(
            request, 'Administrator {} has been approved.'.format(user.username)
        )
    return redirect('admin_invites')


@approver_required
@require_POST
def reject_invite(request, user_id):
    """Decline an invitation. The row is deactivated, never deleted, so any
    complaint history or audit entries keep a valid foreign key."""
    user = User.objects.filter(
        id=user_id, role='admin', is_approved=False
    ).first()
    if user:
        username = user.username
        user.is_active = False
        user.is_approved = False
        user.save(update_fields=['is_active', 'is_approved'])
        logger.warning(
            'administrator invitation rejected for %s by %s',
            redact_email(user.email), request.user.username,
        )
        messages.success(
            request, 'Invitation for {} has been rejected.'.format(username)
        )
    else:
        messages.error(request, 'That invitation could not be found.')
    return redirect('admin_invites')


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
