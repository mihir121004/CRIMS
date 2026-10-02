"""
Central authorization layer for CRIMS.

Root cause this module fixes
---------------------------
Every data view previously used only ``@login_required`` (or nothing at all)
and fetched objects with ``get_object_or_404(Model, pk=pk)``. That is an
Insecure Direct Object Reference (IDOR): any authenticated user could read or
write *any* row by guessing an integer id, and several views had no
authentication at all.

This module provides:

* ``role_required``      - role-based view decorators (who may call the URL)
* ``visible_complaints`` - object-level queryset scoping (whose rows may be read)
* ``can_access_complaint`` / ``can_access_investigation`` - single-object guards

Role model
----------
citizen - may only ever touch their own complaints and their own notifications
officer  - law-enforcement staff: all complaints, investigations, suspects,
           witnesses, evidence
admin   - full access, including officer approval and system analytics
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.conf import settings
from django.core.exceptions import PermissionDenied

#: Roles considered "law-enforcement staff" (i.e. not a member of the public).
STAFF_ROLES = ('officer', 'admin')

#: Roles allowed to approve/reject officer registrations.
ADMIN_ROLES = ('admin',)


def role_required(*roles):
    """Allow the view only to authenticated users whose ``role`` is in ``roles``.

    Anonymous users are redirected to the login page (preserving ``?next=``).
    Authenticated users with the wrong role get a 403 rather than a redirect,
    so a citizen hitting an officer URL cannot silently loop on login.
    """
    allowed = frozenset(roles)

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if getattr(user, 'role', None) not in allowed:
                raise PermissionDenied(
                    'Your account role is not permitted to use this resource.'
                )
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


# Convenience aliases used across the views.
admin_required = role_required(*ADMIN_ROLES)
staff_required = role_required(*STAFF_ROLES)
citizen_required = role_required('citizen')


def is_staff(user):
    """True for officers and admins (law-enforcement staff)."""
    return bool(
        user.is_authenticated and getattr(user, 'role', None) in STAFF_ROLES
    )


def is_admin(user):
    return bool(
        user.is_authenticated and getattr(user, 'role', None) in ADMIN_ROLES
    )


def is_account_approver(user):
    """True for the specific accounts allowed to mint administrators.

    Two conditions, both required:

    * ``role == 'admin'`` - so an ordinary citizen, or even a logged-in
      officer, can never reach the invitation surface.
    * the address is listed in ``settings.ADMIN_APPROVER_EMAILS`` - so the set
      of approvers is explicit and reviewable rather than "every admin".

    The comparison is case-insensitive because ``AbstractUser`` does not
    normalise ``email``.
    """
    if not is_admin(user):
        return False
    configured = getattr(settings, 'ADMIN_APPROVER_EMAILS', ())
    address = (user.email or '').strip().lower()
    return bool(address) and address in {
        str(entry).strip().lower() for entry in configured
    }


def approver_required(view_func):
    """Allow only designated approvers; 403 for everyone else.

    Deliberately stricter than ``admin_required``: an admin who is not on the
    approver list gets a 403 rather than a quiet invitation form.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not is_account_approver(request.user):
            raise PermissionDenied(
                'Only a designated account approver may do this.'
            )
        return view_func(request, *args, **kwargs)

    return _wrapped


# ---------------------------------------------------------------------------
# Object-level scoping
# ---------------------------------------------------------------------------

def visible_complaints(user):
    """Return the complaints ``user`` is allowed to read.

    * citizen -> only complaints they filed
    * officer / admin -> the full departmental queue
    """
    from complaints.models import Complaint

    queryset = Complaint.objects.all()
    if is_staff(user):
        return queryset
    return queryset.filter(citizen=user)


def can_access_complaint(user, complaint):
    """True if ``user`` may read/write ``complaint``."""
    if not user.is_authenticated:
        return False
    if is_staff(user):
        return True
    return complaint.citizen_id == user.id


def can_modify_complaint(user, complaint):
    """True if ``user`` may change a complaint's status.

    Only law-enforcement staff may close or advance a case. A citizen may
    never alter case state, regardless of what they post.
    """
    return is_staff(user) and can_access_complaint(user, complaint)


def can_access_investigation(user, investigation):
    """True if ``user`` may read ``investigation``."""
    return is_staff(user)


def can_modify_investigation(user, investigation):
    """True if ``user`` may edit the investigation or add notes to it.

    Officers may only work cases assigned to them; admins may work any case.
    """
    if not is_admin(user):
        if getattr(user, 'role', None) != 'officer':
            return False
        return investigation.assigned_officer_id == user.id
    return True


def visible_investigations(user):
    """Investigations ``user`` may list.

    Officers see their own assignments; admins see everything. Citizens see
    nothing - investigations are internal case work.
    """
    from investigations.models import Investigation

    if is_admin(user):
        return Investigation.objects.all()
    if getattr(user, 'role', None) == 'officer':
        return Investigation.objects.filter(assigned_officer=user)
    return Investigation.objects.none()


def can_access_evidence(user, evidence):
    """True if ``user`` may view a piece of evidence."""
    return can_access_complaint(user, evidence.complaint)


def can_access_message_thread(user, complaint):
    """True if ``user`` may read/post in a complaint's chat thread."""
    return can_access_complaint(user, complaint)
