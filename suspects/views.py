from django.shortcuts import( render, redirect, get_object_or_404)
from django.contrib.auth.decorators import login_required
from .models import Suspect
from .forms import SuspectForm



@login_required
def suspect_list(request):
    suspects = Suspect.objects.all()

    search = request.GET.get('search')
    status_filter = request.GET.get('status')

    if search:
        suspects = suspects.filter(full_name__icontains=search)

    if status_filter in ('wanted', 'clear'):
        wanted = status_filter == 'wanted'
        suspects = suspects.filter(wanted=wanted)

    total_count = Suspect.objects.count()
    wanted_count = Suspect.objects.filter(wanted=True).count()
    clear_count = Suspect.objects.filter(wanted=False).count()
    linked_case_count = Suspect.objects.exclude(complaint__isnull=True).count()

    result_count = suspects.count()
    has_filters = bool(search or status_filter)

    return render(request, 'suspects/suspect_list.html', {
        'suspects': suspects,
        'total_count': total_count,
        'wanted_count': wanted_count,
        'clear_count': clear_count,
        'linked_case_count': linked_case_count,
        'result_count': result_count,
        'has_filters': has_filters,
        'search': search or '',
        'status': status_filter or '',
    })

@login_required
def suspect_detail(request, pk):
    suspect = get_object_or_404(Suspect, pk=pk)
    return render(request, 'suspects/suspect_detail.html', {
        'suspect': suspect
    })

@login_required
def suspect_create(request):
    form = SuspectForm()
    if request.method == 'POST':
        form = SuspectForm(request.POST, request.FILES)

        if form.is_valid():
            form.save()
            return redirect('suspect_list')

    return render(
        request, 'suspects/suspect_form.html', {
            'form': form
        }
    )
