from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

from accounts.permissions import staff_required
from .models import Witness
from .forms import WitnessForm


@staff_required
def witness_list(request):
    """Was `@login_required` only: any citizen could read every witness's
    name, phone, address and full statement.

    Root cause of the audit finding: the Protected / Standard KPI cards and the
    status dropdown submitted ``?status=...`` but the view only ever read
    ``search``, so the filter silently did nothing.
    """

    witnesses = Witness.objects.all()

    search = request.GET.get('search')
    status = request.GET.get('status')

    if search:
        witnesses = witnesses.filter(full_name__icontains=search)

    if status in ('protected', 'standard'):
        witnesses = witnesses.filter(
            protected_witness=(status == 'protected')
        )

    return render(
        request,
        'witnesses/witness_list.html',
        {
            'witnesses': witnesses,
            'total_count': Witness.objects.count(),
            'protected_count': Witness.objects.filter(
                protected_witness=True).count(),
            'standard_count': Witness.objects.filter(
                protected_witness=False).count(),
            'result_count': witnesses.count(),
            'has_filters': bool(search or status),
            'search': search or '',
            'status': status or '',
        },
    )


@staff_required
def witness_detail(request, pk):
    witness = get_object_or_404(Witness, pk=pk)
    return render(request, 'witnesses/witness_detail.html',
                  {'witness': witness})


@staff_required
def witness_create(request):
    """Was `@login_required` only, and the submit button sat outside the
    `<form>` element so it could never be submitted."""
    form = WitnessForm()
    if request.method == 'POST':
        form = WitnessForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Witness added.')
            return redirect('witness_list')
    else:
        form = WitnessForm()

    return render(request, 'witnesses/witness_form.html', {'form': form})


@staff_required
@require_POST
def toggle_protection(request, pk):
    """Backs the "Change Protection" control on the witness detail page.

    Root cause of the audit finding: it was a ``<a href="...?status=standard">``
    link and no view read it, so protected status could never be changed.
    """
    witness = get_object_or_404(Witness, pk=pk)
    witness.protected_witness = not witness.protected_witness
    witness.save(update_fields=['protected_witness'])
    messages.success(
        request,
        '{} is now a {} witness.'.format(
            witness.full_name,
            'protected' if witness.protected_witness else 'standard',
        ),
    )
    return redirect('witness_detail', pk=pk)
