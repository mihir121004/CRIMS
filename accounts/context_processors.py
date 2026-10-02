"""Template context for the administrator-invitation surface.

The sidebar needs to know whether the viewer may see "Admin Invitations", and
duplicating the approver rule in a template would let the two drift apart.
This exposes the same helper the view guard uses.
"""


def approver_context(request):
    from accounts.permissions import is_account_approver

    user = getattr(request, 'user', None)
    return {'is_account_approver': is_account_approver(user)}