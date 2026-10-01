from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Q
from django.core.mail import send_mail

from .models import Complaint
from .forms import ComplaintForm

from reports.models import ActivityLog
from notifications.utils import create_notification
from accounts.models import User
from accounts.permissions import (
    can_access_complaint,
    can_modify_complaint,
    staff_required,
    visible_complaints,
)
from investigations.models import Investigation

from ai_engine.utils import detect_priority


@login_required
def create_complaint(request):
    if request.method == 'POST':
        form = ComplaintForm(request.POST)
        if form.is_valid():
            complaint = form.save(commit=False)
            complaint.citizen = request.user

            # Category is normalised inside Complaint.save(); priority is
            # derived there too (see complaints/models.py). Calling the model
            # here as well meant AI ran twice per submission.
            with transaction.atomic():
                complaint.save()

                ActivityLog.objects.create(
                    user=request.user,
                    action='Complaint Submitted: {}'.format(
                        complaint.tracking_id
                    ),
                )

                _assign_least_loaded_officer(complaint)

            messages.success(
                request,
                'Complaint submitted. Tracking ID: {}'.format(
                    complaint.tracking_id
                ),
            )
            return redirect('my_complaints')
    else:
        form = ComplaintForm()

    return render(request, 'complaints/create.html', {'form': form})


def _assign_least_loaded_officer(complaint):
    """Assign the least-loaded approved officer.

    Root cause of the audit's race-condition finding
    -----------------------------------------------
    The original code read ``current_case_count``, added one, and saved, with
    no lock. Two complaints filed in the same instant both read the same
    count, so one increment was lost and officer workload drifted from reality.
    ``select_for_update()`` serialises the read-modify-write inside the
    surrounding atomic block.
    """
    officer = (
        User.objects.filter(role='officer', is_approved=True, is_active=True)
        .order_by('current_case_count', 'id')
        .select_for_update()
        .first()
    )
    if not officer:
        return None

    investigation, _created = Investigation.objects.get_or_create(
        complaint=complaint,
        defaults={'assigned_officer': officer},
    )

    if investigation.assigned_officer_id != officer.id:
        investigation.assigned_officer = officer
        investigation.save(update_fields=['assigned_officer'])

    User.objects.filter(id=officer.id).update(
        current_case_count=officer.current_case_count + 1
    )
    return officer


@login_required
def my_complaints(request):
    """Scoped to the requesting citizen's own complaints."""
    complaints = visible_complaints(request.user).filter(
        citizen=request.user
    ).order_by('-created_at')

    search = request.GET.get('search')
    status = request.GET.get('status')
    category = request.GET.get('category')
    priority = request.GET.get('priority')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if search:
        complaints = complaints.filter(
            Q(tracking_id__icontains=search) | Q(title__icontains=search)
        )
    if status:
        complaints = complaints.filter(status=status)
    if category:
        complaints = complaints.filter(category=category)
    if priority:
        complaints = complaints.filter(priority=priority)
    if start_date:
        complaints = complaints.filter(created_at__date__gte=start_date)
    if end_date:
        complaints = complaints.filter(created_at__date__lte=end_date)

    return render(
        request,
        'complaints/my_complaints.html',
        {'complaints': complaints},
    )


@login_required
def complaint_detail(request, pk):
    """Root cause of the audit's IDOR finding
    ---------------------------------------
    This was ``get_object_or_404(Complaint, id=pk)`` with no ownership filter,
    so any authenticated user could read any case by iterating ids. The object
    is now resolved through ``visible_complaints``, which restricts citizens
    to their own reports and 404s otherwise (404 rather than 403 so the
    response does not confirm that another user's record exists).
    """
    complaint = get_object_or_404(visible_complaints(request.user), id=pk)

    if not can_access_complaint(request.user, complaint):
        raise Http404()

    investigation = (
        Investigation.objects.filter(complaint=complaint)
        .select_related('assigned_officer')
        .first()
    )

    suspects = [complaint.suspects] if complaint.suspects_id else []
    witnesses = complaint.witnesses.all()

    return render(
        request,
        'complaints/detail.html',
        {
            'complaint': complaint,
            'investigation': investigation,
            'evidence': complaint.evidence.all(),
            'suspects': suspects,
            'witnesses': witnesses,
        },
    )


@staff_required
def officer_complaints(request):
    """The departmental queue.

    Root cause of the audit finding: this had only ``@login_required``, so a
    citizen could list every complaint in the system including complainant
    names and locations.
    """
    complaints = visible_complaints(request.user).order_by('-created_at')

    search = request.GET.get('search')
    status = request.GET.get('status')
    priority = request.GET.get('priority')
    category = request.GET.get('category')

    if search:
        complaints = complaints.filter(
            Q(tracking_id__icontains=search)
            | Q(title__icontains=search)
            | Q(location__icontains=search)
            | Q(citizen__username__icontains=search)
            | Q(citizen__first_name__icontains=search)
            | Q(citizen__last_name__icontains=search)
        )
    if status:
        complaints = complaints.filter(status=status)
    if priority:
        complaints = complaints.filter(priority=priority)
    if category:
        complaints = complaints.filter(category=category)

    context = {
        'complaints': complaints,
        'total_count': visible_complaints(request.user).count(),
        'pending_count': visible_complaints(request.user).filter(
            status='pending').count(),
        'investigating_count': visible_complaints(request.user).filter(
            status='investigation').count(),
        'resolved_count': visible_complaints(request.user).filter(
            status='resolved').count(),
        'high_priority_count': visible_complaints(request.user).filter(
            priority='High').count(),
        'result_count': complaints.count(),
        'has_filters': bool(search or status or priority or category),
    }

    return render(request, 'officer/complaints.html', context)


@staff_required
def update_status(request, pk):
    """Case status transitions.

    Root cause of the audit finding
    ------------------------------
    1. Only ``@login_required`` - a citizen POSTed ``status=resolved`` and
       closed another user's open case (verified in the audit).
    2. ``Complaint.objects.get(id=pk)`` - an unfiltered fetch, plus a 500
       instead of a 404 on a bad id.
    3. ``complaint.status = request.POST.get('status')`` wrote an arbitrary
       string straight into the column with no membership check against
       ``STATUS_CHOICES``.
    """
    complaint = get_object_or_404(visible_complaints(request.user), id=pk)

    if request.method == 'POST':
        if not can_modify_complaint(request.user, complaint):
            # Unreachable via the decorator, kept as defence in depth.
            messages.error(request, 'You cannot change this case status.')
            return redirect('complaint_detail', pk=complaint.id)

        requested = request.POST.get('status')
        valid_statuses = {code for code, _label in Complaint.STATUS_CHOICES}
        if requested not in valid_statuses:
            messages.error(
                request, 'Unknown status "{}".'.format(requested or '')
            )
            return redirect('complaint_detail', pk=complaint.id)

        # Save without re-running the AI priority heuristics, which used to
        # fire on every .save() and could silently rewrite the priority.
        complaint.status = requested
        complaint.save(update_fields=['status', 'updated_at'])

        investigation = (
            Investigation.objects.filter(complaint=complaint)
            .select_related('assigned_officer')
            .first()
        )

        label = complaint.get_status_display()
        create_notification(
            request.user,
            'Complaint Status Updated',
            'Complaint {} status changed to {}.'.format(
                complaint.tracking_id, label
            ),
        )
        if complaint.citizen_id and complaint.citizen_id != request.user.id:
            create_notification(
                complaint.citizen,
                'Complaint Status Updated',
                'Your complaint {} status changed to {}.'.format(
                    complaint.tracking_id, label
                ),
            )
        if investigation and investigation.assigned_officer_id:
            if investigation.assigned_officer_id != request.user.id:
                create_notification(
                    investigation.assigned_officer,
                    'Case Status Updated',
                    'Case {} status changed to {}.'.format(
                        complaint.tracking_id, label
                    ),
                )

        ActivityLog.objects.create(
            user=request.user,
            action='Status changed to {}'.format(label),
        )

        if complaint.citizen and complaint.citizen.email:
            send_mail(
                'Complaint Status Updated',
                'Your complaint {} status has been updated to {}.'.format(
                    complaint.tracking_id, label
                ),
                None,
                [complaint.citizen.email],
                fail_silently=True,
            )

        messages.success(
            request,
            'Status updated to {}.'.format(label),
        )
        return redirect('complaint_detail', pk=complaint.id)

    return render(request, 'officer/update_status.html',
                  {'complaint': complaint})


@login_required
def citizen_dashboard(request):
    """Scoped to the requesting user's own complaints.

    Root cause of the audit finding: the context was built with keys
    ``pending_complaints`` / ``investigating_complaints`` / ``resolved_complaints``
    while the template reads ``pending_count`` / ``investigating_count`` /
    ``resolved_count``. Django resolves a missing key to the empty string, so
    three of four KPI cards rendered permanently blank and the doughnut chart
    emitted the sparse literal ``[,,,]``. Both names are now provided.
    """
    complaints = Complaint.objects.filter(
        citizen=request.user
    ).order_by('-created_at')

    pending_count = complaints.filter(status='pending').count()
    investigating_count = complaints.filter(
        status__in=['review', 'investigation', 'evidence']
    ).count()
    resolved_count = complaints.filter(status='resolved').count()

    context = {
        'total_complaints': complaints.count(),
        'pending_count': pending_count,
        'investigating_count': investigating_count,
        'resolved_count': resolved_count,
        # Legacy aliases retained for any template still using them.
        'pending_complaints': pending_count,
        'investigating_complaints': investigating_count,
        'resolved_complaints': resolved_count,
        'complaints': complaints[:10],
    }

    return render(request, 'citizen/dashboard.html', context)


@staff_required
def officer_dashboard(request):
    assigned_investigations = Investigation.objects.filter(
        assigned_officer=request.user
    ).select_related('complaint')

    assigned_complaints = Complaint.objects.filter(
        investigation__assigned_officer=request.user
    ).order_by('-created_at')

    total_cases = assigned_investigations.count()

    pending_cases = assigned_complaints.filter(status='pending').count()
    active_investigations = assigned_complaints.filter(
        status__in=['review', 'investigation', 'evidence']
    ).count()
    solved_cases = assigned_complaints.filter(status='resolved').count()

    recent_notes = InvestigationNote.objects.filter(
        investigation__assigned_officer=request.user
    ).order_by('-created_at')[:5]

    high_count = assigned_complaints.filter(priority='High').count()
    medium_count = assigned_complaints.filter(priority='Medium').count()
    low_count = assigned_complaints.filter(priority='Low').count()

    total_priority = high_count + medium_count + low_count

    def priority_percent(count):
        if total_priority == 0:
            return '0%'
        return '{}%'.format(round((count / total_priority) * 100))

    context = {
        'total_cases': total_cases,
        'assigned_cases': total_cases,
        'pending_cases': pending_cases,
        'active_investigations': active_investigations,
        'solved_cases': solved_cases,
        'assigned_complaints': assigned_complaints[:10],
        'recent_notes': recent_notes,
        'high_count': high_count,
        'medium_count': medium_count,
        'low_count': low_count,
        'high_priority_percent': priority_percent(high_count),
        'medium_priority_percent': priority_percent(medium_count),
        'low_priority_percent': priority_percent(low_count),
    }

    return render(request, 'officer/dashboard.html', context)


# Imported late to avoid a circular import at module load.
from investigations.models import InvestigationNote  # noqa: E402
