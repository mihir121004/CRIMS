from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db.models import Q

from complaints.models import Complaint
from accounts.permissions import (
    can_access_complaint,
    can_access_evidence,
    staff_required,
    visible_complaints,
)
from .models import (Evidence, EvidenceCustody)
from .forms import (EvidenceForm, EvidenceCustodyForm)
from reports.models import ActivityLog


@login_required
def upload_evidence(request, complaint_id):
    """A citizen may attach evidence to their own report (crime-scene photos,
    receipts); staff may attach to any case.

    Root cause of the audit finding: the complaint was fetched with an
    unfiltered ``get_object_or_404(Complaint, id=complaint_id)``, so any
    authenticated user could upload files into any case.
    """
    complaint = get_object_or_404(visible_complaints(request.user),
                                  id=complaint_id)

    if not can_access_complaint(request.user, complaint):
        raise Http404()

    if request.method == 'POST':
        form = EvidenceForm(request.POST, request.FILES)
        if form.is_valid():
            with _atomic_guard():
                evidence = form.save(commit=False)
                evidence.complaint = complaint
                evidence.uploaded_by = request.user
                evidence.save()

            ActivityLog.objects.create(
                user=request.user,
                action='Evidence uploaded for {}'.format(
                    complaint.tracking_id
                ),
            )
            messages.success(request, 'Evidence uploaded.')
            return redirect('complaint_detail', pk=complaint.id)
    else:
        form = EvidenceForm()

    evidence_list = complaint.evidence.all().order_by('-uploaded_at')

    search = request.GET.get('search')
    if search:
        # `file` is a FileField, so filter on its stored path, not icontains
        # on a non-text field.
        evidence_list = evidence_list.filter(file__icontains=search)

    return render(
        request,
        'evidence/upload.html',
        {
            'form': form,
            'complaint': complaint,
            'recent_evidence': evidence_list[:8],
            'total_evidence': evidence_list.count(),
            'transfers_count': EvidenceCustody.objects.filter(
                evidence__complaint=complaint
            ).count(),
            'chain_locations': EvidenceCustody.objects.filter(
                evidence__complaint=complaint
            ).values('location').distinct().count(),
        },
    )


def _atomic_guard():
    from django.db import transaction
    return transaction.atomic()


@staff_required
def transfer_evidence(request, pk):
    """Chain-of-custody transfer. Staff only - this reassigns custody of
    evidence, which a citizen must never be able to do."""
    evidence = get_object_or_404(Evidence, pk=pk)

    if not can_access_evidence(request.user, evidence):
        raise Http404()

    if request.method == 'POST':
        form = EvidenceCustodyForm(request.POST)
        if form.is_valid():
            custody = form.save(commit=False)
            custody.evidence = evidence
            custody.transferred_by = request.user
            # Only an active officer/admin may receive custody.
            if not custody.received_by.is_active or not can_access_evidence(
                custody.received_by, evidence
            ):
                messages.error(
                    request, 'That user cannot receive this evidence.'
                )
            else:
                custody.save()
                messages.success(request, 'Custody transferred.')
            return redirect('evidence_detail', pk=evidence.id)
    else:
        form = EvidenceCustodyForm()

    return render(
        request,
        'evidence/transfer.html',
        {
            'form': form,
            'evidence': evidence,
            'custody_logs': evidence.custody_logs.all().order_by(
                '-transferred_at'
            ),
        },
    )


@login_required
def evidence_detail(request, pk):
    """Object-level scoped. Citizens may see evidence on their own cases;
    staff may see any."""
    evidence = get_object_or_404(
        Evidence.objects.select_related('complaint'), pk=pk
    )

    if not can_access_evidence(request.user, evidence):
        raise Http404()

    return render(
        request,
        'evidence/detail.html',
        {
            'evidence': evidence,
            'custody_logs': evidence.custody_logs.all().order_by(
                '-transferred_at'
            ),
        },
    )
