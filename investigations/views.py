from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q

from .models import (
    Investigation,
    InvestigationNote
)

from complaints.models import Complaint
from accounts.models import User
from accounts.utils import admin_required
from notifications.utils import create_notification


@login_required
def investigation_list(request):

    investigations = Investigation.objects.select_related(
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

        'total_count': Investigation.objects.count(),

        'active_count': Investigation.objects.filter(
            complaint__status__in=['review', 'investigation', 'evidence']
        ).count(),

        'assigned_count': Investigation.objects.filter(
            assigned_officer__isnull=False
        ).count(),

        'unassigned_count': Investigation.objects.filter(
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


@login_required
def investigation_detail(request, pk):

    investigation = get_object_or_404(
        Investigation,
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

        previous_officer = investigation.assigned_officer
        investigation.assigned_officer = officer
        investigation.save()

        if previous_officer != officer:
            if previous_officer and previous_officer.current_case_count > 0:
                previous_officer.current_case_count -= 1
                previous_officer.save(update_fields=['current_case_count'])

            officer.current_case_count += 1
            officer.save(update_fields=['current_case_count'])

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


@login_required
def add_note(request, pk):

    investigation = get_object_or_404(
        Investigation,
        pk=pk
    )

    if request.method == 'POST':

        note_text = request.POST.get(
            'note'
        )

        if note_text:

            InvestigationNote.objects.create(

                investigation=investigation,

                officer=request.user,

                note=note_text

            )

            messages.success(
                request,
                "Note added successfully."
            )

        return redirect(
            'investigation_detail',
            pk=pk
        )

    return redirect(
        'investigation_detail',
        pk=pk
    )


@login_required
def my_assigned_cases(request):

    mine = Investigation.objects.filter(
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