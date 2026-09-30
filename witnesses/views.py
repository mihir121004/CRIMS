from django.shortcuts import (render, redirect, get_object_or_404)
from django.contrib.auth.decorators import login_required
from .models import Witness
from .forms import WitnessForm


@login_required
def witness_list(request):

    witnesses = Witness.objects.all()

    search = request.GET.get('search')
    if search:
        witnesses = witnesses.filter(
            full_name__icontains=search
        )

    total_count = Witness.objects.count()
    protected_count = Witness.objects.filter(protected_witness=True).count()
    standard_count = Witness.objects.filter(protected_witness=False).count()
    result_count = witnesses.count()
    has_filters = bool(search)

    return render(request, 'witnesses/witness_list.html', {
        'witnesses': witnesses,
        'total_count': total_count,
        'protected_count': protected_count,
        'standard_count': standard_count,
        'result_count': result_count,
        'has_filters': has_filters,
        'search': search or '',
    })


@login_required
def witness_detail(request, pk):

    witness = get_object_or_404(Witness, pk=pk)

    return render(request, 'witnesses/witness_detail.html', {
        'witness': witness
    })


@login_required
def witness_create(request):
    form = WitnessForm()
    if request.method == 'POST':
        form = WitnessForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('witness_list')

    return render(request, 'witnesses/witness_form.html', {
        'form': form
    })
