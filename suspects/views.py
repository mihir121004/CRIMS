from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

from accounts.permissions import staff_required
from .models import Suspect
from .forms import SuspectForm


@staff_required
def suspect_list(request):
    """Was `@login_required` only: any citizen could enumerate every suspect
    including criminal history and Aadhaar numbers."""

    suspects = Suspect.objects.select_related('complaint')

    search = request.GET.get('search')
    status_filter = request.GET.get('status')

    if search:
        suspects = suspects.filter(full_name__icontains=search)

    if status_filter in ('wanted', 'clear'):
        suspects = suspects.filter(wanted=(status_filter == 'wanted'))

    return render(
        request,
        'suspects/suspect_list.html',
        {
            'suspects': suspects,
            'total_count': Suspect.objects.count(),
            'wanted_count': Suspect.objects.filter(wanted=True).count(),
            'clear_count': Suspect.objects.filter(wanted=False).count(),
            'linked_case_count': Suspect.objects.exclude(
                complaint__isnull=True
            ).count(),
            'result_count': suspects.count(),
            'has_filters': bool(search or status_filter),
            'search': search or '',
            'status': status_filter or '',
        },
    )


@staff_required
def suspect_detail(request, pk):
    suspect = get_object_or_404(Suspect.objects.select_related('complaint'),
                                pk=pk)
    return render(request, 'suspects/suspect_detail.html',
                  {'suspect': suspect})


@staff_required
def suspect_create(request):
    """Was `@login_required` only, and the form’s submit button sat outside the
    `<form>` element so it could never be submitted."""
    form = SuspectForm(user=request.user)
    if request.method == 'POST':
        form = SuspectForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Suspect added.')
            return redirect('suspect_list')
    else:
        form = SuspectForm(user=request.user)

    return render(request, 'suspects/suspect_form.html', {'form': form})


@staff_required
@require_POST
def clear_suspect(request, pk):
    """Backs the "Mark Cleared" control on the suspect detail page.

    Root cause of the audit finding: that control was a plain
    ``<a href="...?clear">`` and no view ever read the query parameter, so it
    re-rendered the page with the WANTED badge still showing. This is now a
    real POST-only action that persists the change.
    """
    suspect = get_object_or_404(Suspect, pk=pk)
    if suspect.wanted:
        suspect.wanted = False
        suspect.save(update_fields=['wanted'])
        messages.success(
            request, '{} has been marked as cleared.'.format(suspect.full_name)
        )
    else:
        messages.info(request, 'That suspect is already cleared.')
    return redirect('suspect_detail', pk=pk)


@staff_required
@require_POST
def toggle_wanted(request, pk):
    """Restore the "wanted" flag - previously there was no way to re-set it."""
    suspect = get_object_or_404(Suspect, pk=pk)
    suspect.wanted = not suspect.wanted
    suspect.save(update_fields=['wanted'])
    messages.success(
        request,
        '{} is now {}. '.format(
            suspect.full_name, 'WANTED' if suspect.wanted else 'cleared'
        ),
    )
    return redirect('suspect_detail', pk=pk)
