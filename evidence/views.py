from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Q

from complaints.models import Complaint
from .models import (Evidence, EvidenceCustody)
from .forms import (EvidenceForm, EvidenceCustodyForm)
from reports.models import ActivityLog

@login_required
def upload_evidence(request, complaint_id):

    complaint = get_object_or_404(
        Complaint,
        id=complaint_id
    )

    if request.method == 'POST':

        form = EvidenceForm(
            request.POST,
            request.FILES
        )

        if form.is_valid():

            evidence = form.save(
                commit=False
            )

            evidence.complaint = complaint

            evidence.save()
            ActivityLog.objects.create(
                user=request.user,
                action=f"Evidence uploaded for {complaint.tracking_id}"
            )
            return redirect(
                'complaint_detail',
                pk=complaint.id
            )

    else:

        form = EvidenceForm()

    evidence_list = complaint.evidence.all().order_by('-uploaded_at')

    search = request.GET.get('search')
    if search:
        evidence_list = evidence_list.filter(
            Q(file__icontains=search)
        )

    total_evidence = evidence_list.count()
    transfers_count = EvidenceCustody.objects.filter(
        evidence__complaint=complaint
    ).count()
    chain_locations = EvidenceCustody.objects.filter(
        evidence__complaint=complaint
    ).values('location').distinct().count()

    return render(
        request,
        'evidence/upload.html',
        {
            'form': form,
            'complaint': complaint,
            'recent_evidence': evidence_list[:8],
            'total_evidence': total_evidence,
            'transfers_count': transfers_count,
            'chain_locations': chain_locations
        }
    )

@login_required
def transfer_evidence(request, pk):

    evidence = get_object_or_404(Evidence, pk=pk)

    form = EvidenceCustodyForm()
    if request.method == 'POST':
        form = EvidenceCustodyForm(request.POST)

        if form.is_valid():
            custody = form.save(commit=False)
            custody.evidence = evidence
            custody.transferred_by = (request.user)
            custody.save()
            return redirect('evidence_detail', pk=evidence.id)

    custody_logs = evidence.custody_logs.all().order_by('-transferred_at')

    return render(request, 'evidence/transfer.html', {
        'form': form,
        'evidence': evidence,
        'custody_logs': custody_logs
    })

@login_required
def evidence_detail(request, pk):
    evidence = get_object_or_404(Evidence, pk=pk)

    custody_logs = evidence.custody_logs.all().order_by('-transferred_at')
    return render(request, 'evidence/detail.html', {
        'evidence': evidence,
        'custody_logs': custody_logs
    })