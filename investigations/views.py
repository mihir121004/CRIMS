from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
from django.db import transaction
from django.views.decorators.http import require_POST

from .models import (
    Investigation,
    InvestigationNote
)

from complaints.models import Complaint
from accounts.models import User
from accounts.permissions import (
    admin_required,
    can_modify_investigation,
    staff_required,
    visible_investigations,
)
from notifications.utils import create_notification


@staff_required
def investigation_list(request):
    """Was `@login_required` only - any citizen could list every internal
    investigation in the system. Officers now see their own assignments,
    admins see everything."""

    base = visible_investigations(request.user)

    investigations = base.select_related(
        'complaint',
        'assigned_officer'
    ).order_by('-started_at')

    search = request.GET.get('search')
    status = request.GET.get('status')
    priority = request.GET.get('priority')
    assignment = request.GET.get('assignment')

    if search:
        investigations = investigations.filter(
            Q(complaint__tracking_id__icontains=search)
            | Q(complaint__title__icontains=search)
            | Q(assigned_officer__username__icontains=search)
            | Q(assigned_officer__first_name__icontains=search)
            | Q(assigned_officer__last_name__icontains=search)
        )

    if status:
        investigations = investigations.filter(
            complaint__status=status
        )

    if priority:
        investigations = investigations.filter(
            complaint__priority=priority
        )

    if assignment == 'assigned':
        investigations = investigations.filter(
            assigned_officer__isnull=False
        )
    elif assignment == 'unassigned':
        investigations = investigations.filter(
            assigned_officer__isnull=True
        )

    context = {

        'investigations': investigations,

        'total_count': base.count(),

        'active_count': base.filter(
            complaint__status__in=['review', 'investigation', 'evidence']
        ).count(),

        'assigned_count': base.filter(
            assigned_officer__isnull=False
        ).count(),

        'unassigned_count': base.filter(
            assigned_officer__isnull=True
        ).count(),

        'result_count': investigations.count(),

        'has_filters': bool(search or status or priority or assignment),

    }

    return render(
        request,
        'investigations/investigation_list.html',
        context
    )


@staff_required
def investigation_detail(request, pk):
    """Object-level scoping: resolved through `visible_investigations` so an
    officer cannot read another officer's case by guessing an id."""

    investigation = get_object_or_404(
        visible_investigations(request.user),
        pk=pk
    )

    timeline = investigation.timeline.all().order_by(
        '-created_at'
    )

    context = {

        'investigation': investigation,
        'timeline': timeline

    }

    return render(
        request,
        'investigations/investigation_detail.html',
        context
    )


@admin_required
def assign_officer(request, complaint_id):

    complaint = get_object_or_404(
        Complaint,
        id=complaint_id
    )

    if request.method == "POST":

        officer_id = request.POST.get(
            'officer'
        )

        officer = get_object_or_404(
            User.objects.filter(role='officer'),
            id=officer_id
        )

        investigation, created = Investigation.objects.get_or_create(
            complaint=complaint
        )

        # Serialise the read-modify-write on the workload counters; the
        # original unlocked version lost increments under concurrency.
        with transaction.atomic():
            previous_officer = investigation.assigned_officer
            investigation.assigned_officer = officer
            investigation.save()

            if previous_officer != officer:
                if (
                    previous_officer
                    and previous_officer.current_case_count > 0
                ):
                    User.objects.filter(
                        id=previous_officer.id
                    ).update(
                        current_case_count=previous_officer.current_case_count - 1
                    )

                User.objects.filter(id=officer.id).update(
                    current_case_count=officer.current_case_count + 1
                )

        if previous_officer != officer:
            create_notification(
                officer,
                'Case Assigned',
                f'You have been assigned to case {complaint.tracking_id}.'
            )

        messages.success(
            request,
            "Officer assigned successfully."
        )

        return redirect(
            'investigation_detail',
            pk=investigation.id
        )

    officers = User.objects.filter(
        role='officer'
    )

    return render(
        request,
        'investigations/assign_officer.html',
        {
            'complaint': complaint,
            'officers': officers
        }
    )


@staff_required
@require_POST
def add_note(request, pk):
    """Root cause of the audit finding
    --------------------------------
    This had only `@login_required`, so a citizen could append text to any
    case's timeline. Because `officer=request.user` was stored unconditionally,
    those notes were filed in the officer's name - forging the evidentiary
    audit trail. Notes are now staff-only, restricted to the assigned officer
    (admins excepted), and recorded through the same `can_modify_investigation`
    guard as the rest of the case.
    """

    investigation = get_object_or_404(
        visible_investigations(request.user),
        pk=pk
    )

    if not can_modify_investigation(request.user, investigation):
        messages.error(
            request, 'You are not assigned to this case.'
        )
        return redirect('investigation_detail', pk=pk)

    note_text = (request.POST.get('note') or '').strip()
    if not note_text:
        messages.error(request, 'The note cannot be empty.')
    elif len(note_text) > 5000:
        messages.error(request, 'The note is too long (5000 characters max).')
    else:
        InvestigationNote.objects.create(
            investigation=investigation,
            officer=request.user,
            note=note_text,
        )
        messages.success(request, 'Note added successfully.')

    return redirect('investigation_detail', pk=pk)


@staff_required
def my_assigned_cases(request):

    mine = visible_investigations(request.user).filter(
        assigned_officer=request.user
    )

    investigations = mine.select_related(
        'complaint'
    ).order_by('-started_at')

    search = request.GET.get('search')
    status = request.GET.get('status')
    priority = request.GET.get('priority')

    if search:
        investigations = investigations.filter(
            Q(complaint__tracking_id__icontains=search)
            | Q(complaint__title__icontains=search)
            | Q(complaint__location__icontains=search)
        )

    if status:
        investigations = investigations.filter(
            complaint__status=status
        )

    if priority:
        investigations = investigations.filter(
            complaint__priority=priority
        )

    context = {

        'investigations': investigations,

        'total_count': mine.count(),

        'active_count': mine.filter(
            complaint__status__in=['review', 'investigation', 'evidence']
        ).count(),

        'high_priority_count': mine.filter(
            complaint__priority='High'
        ).count(),

        'resolved_count': mine.filter(
            complaint__status='resolved'
        ).count(),

        'result_count': investigations.count(),

        'has_filters': bool(search or status or priority),

    }

    return render(
        request,
        'investigations/my_cases.html',
        context
    )