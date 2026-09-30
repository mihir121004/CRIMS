from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Complaint
from .forms import ComplaintForm
from django.core.mail import send_mail
from reports.models import ActivityLog

from notifications.utils import create_notification
from accounts.models import User
from investigations.models import Investigation, InvestigationNote

from ai_engine.utils import ( predict_category, detect_priority )
from django.db.models import Q

@login_required
def create_complaint(request):
    if request.method == 'POST':
        form = ComplaintForm(request.POST)
        if form.is_valid():
            Complaint = form.save(commit=False)
            Complaint.citizen = request.user
            predicted_category = predict_category(Complaint.description)
            Complaint.ai_category = (
                predicted_category
            )
            Complaint.priority = (
                detect_priority(
                    Complaint.description
                )
            )
            Complaint.save()
            ActivityLog.objects.create(
                user=request.user,
                action = f"Complaint Submitted: {Complaint.tracking_id}"
            )
            officer = User.objects.filter(role='officer').order_by('current_case_count').first()
            if officer:
                Investigation.objects.create(complaint=Complaint, assigned_officer=officer)
                officer.current_case_count += 1
                officer.save()
            return redirect('my_complaints')
    else:
        form = ComplaintForm()
    return render(request, 'complaints/create.html', {'form': form})

@login_required
def my_complaints(request):
    complaints = Complaint.objects.filter(
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
            Q(tracking_id__icontains=search)
            |
            Q(title__icontains=search)
        )
    if status:
        complaints = complaints.filter(status=status)
    if category:
        complaints = complaints.filter(category=category)
    if priority:
        complaints = complaints.filter(priority=priority)
    if start_date:
        complaints = complaints.filter(
            created_at__date__gte=start_date
        )
    if end_date:
        complaints = complaints.filter(
            created_at__date__lte=end_date
        )

    return render(request, 'complaints/my_complaints.html', {'complaints':complaints})

@login_required
def complaint_detail(request, pk):
    complaint = get_object_or_404(Complaint, id=pk)

    investigation = Investigation.objects.filter(
        complaint=complaint
    ).select_related('assigned_officer').first()

    evidence = complaint.evidence.all()

    suspects = (
        [complaint.suspects] if complaint.suspects else []
    )

    witnesses = complaint.witnesses.all()

    return render(
        request,
        'complaints/detail.html',
        {
            'complaint': complaint,
            'investigation': investigation,
            'evidence': evidence,
            'suspects': suspects,
            'witnesses': witnesses
        }
    )

@login_required
def officer_complaints(request):
    complaints = Complaint.objects.all().order_by('-created_at')

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
        'total_count': Complaint.objects.count(),
        'pending_count': Complaint.objects.filter(status='pending').count(),
        'investigating_count': Complaint.objects.filter(status='investigation').count(),
        'resolved_count': Complaint.objects.filter(status='resolved').count(),
        'high_priority_count': Complaint.objects.filter(priority='High').count(),
        'result_count': complaints.count(),
        'has_filters': bool(search or status or priority or category),
    }

    return render(request, 'officer/complaints.html', context)

@login_required
def update_status(request, pk):
    complaint = Complaint.objects.get(id=pk)

    if request.method == 'POST':
        complaint.status = request.POST.get('status')
        complaint.save()

        investigation = Investigation.objects.filter(
            complaint=complaint
        ).select_related('assigned_officer').first()

        create_notification(
            request.user,
            'Complaint Status Updated',
            f'Complaint {complaint.tracking_id} status changed to {complaint.status}.'
        )
        create_notification(
            complaint.citizen,
            'Complaint Status Updated',
            f'Your complaint {complaint.tracking_id} status changed to {complaint.status}.'
        )
        if investigation and investigation.assigned_officer:
            create_notification(
                investigation.assigned_officer,
                'Case Status Updated',
                f'Case {complaint.tracking_id} status changed to {complaint.status}.'
            )
        ActivityLog.objects.create(
            user=request.user,
            action=f"Status changed to {complaint.status}"
        )
        send_mail(
            'Complaint Status Updated',
            f'Your complaint {complaint.tracking_id} status has been updated to {complaint.status}.',
            'noreply@crims.com',
            [complaint.citizen.email],
            fail_silently=True
        )
        return redirect('officer_complaints')
    return render(request, 'officer/update_status.html', 
                  {
                      'complaint': complaint
                  })

@login_required
def citizen_dashboard(request):

    complaints = Complaint.objects.filter(
        citizen=request.user
    ).order_by('-created_at')

    total_complaints = complaints.count()

    pending_count = complaints.filter(
        status='pending'
    ).count()

    investigating_count = complaints.filter(
        status__in=['review', 'investigation', 'evidence']
    ).count()

    resolved_count = complaints.filter(
        status='resolved'
    ).count()

    context = {
        'total_complaints': total_complaints,
        'pending_complaints': pending_count,
        'investigating_complaints': investigating_count,
        'resolved_complaints': resolved_count,
        'complaints': complaints[:10],
    }

    return render(request,'citizen/dashboard.html',context)

@login_required
def officer_dashboard(request):
    assigned_investigations = Investigation.objects.filter(
        assigned_officer=request.user
    ).select_related('complaint')

    assigned_complaints = Complaint.objects.filter(
        investigation__assigned_officer=request.user
    ).order_by('-created_at')

    total_cases = assigned_investigations.count()

    pending_cases = assigned_complaints.filter(
        status='pending'
    ).count()

    active_investigations = assigned_complaints.filter(
        status__in=['review', 'investigation', 'evidence']
    ).count()

    solved_cases = assigned_complaints.filter(
        status='resolved'
    ).count()

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
        return f'{round((count / total_priority) * 100)}%'

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