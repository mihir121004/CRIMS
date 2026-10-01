import json

from datetime import timedelta

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from accounts.models import User
from accounts.permissions import admin_required, staff_required
from complaints.models import Complaint
from investigations.models import Investigation

from django.db.models import Count
from django.db.models.functions import TruncMonth

from ai_engine.utils import predict_confidence

ACTIVE_STATUSES = ['review', 'investigation', 'evidence']

@admin_required
def admin_dashboard(request):
    total_users = User.objects.count()

    total_citizens = User.objects.filter(
        role='citizen'
    ).count()

    total_officers = User.objects.filter(
        role='officer'
    ).count()

    total_complaints = Complaint.objects.count()

    pending_cases = Complaint.objects.filter(
        status='pending'
    ).count()

    investigating_cases = Complaint.objects.filter(
        status__in=ACTIVE_STATUSES
    ).count()

    resolved_cases = Complaint.objects.filter(
        status='resolved'
    ).count()

    high_priority_cases = Complaint.objects.filter(
        priority='High'
    ).count()

    recent_complaints = Complaint.objects.order_by('-created_at')[:5]

    status_data = Complaint.objects.values(
        'status'
    ).annotate(total=Count('id'))

    category_data = Complaint.objects.values(
        'category'
    ).annotate(total=Count('id'))

    priority_data = Complaint.objects.values(
        'priority'
    ).annotate(total=Count('id'))

    monthly_data = Complaint.objects.annotate(
        month=TruncMonth('created_at')
    ).values('month').annotate(total=Count('id')).order_by('month')

    monthly_labels = [
        data['month'].strftime('%b') for data in monthly_data
    ]
    monthly_totals = [
        data['total'] for data in monthly_data
    ]

    active_investigations = Complaint.objects.filter(
        status__in=ACTIVE_STATUSES
    ).count()

    ai_fraud_cases = Complaint.objects.filter(
        ai_category__icontains='fraud'
    ).count()

    ai_theft_cases = Complaint.objects.filter(
        ai_category__icontains='theft'
    ).count()

    ai_cyber_cases = Complaint.objects.filter(
        ai_category__icontains='cyber'
    ).count()

    officers = User.objects.filter(role='officer')
    top_officers = []
    for officer in officers:
        assigned = officer.assigned_cases.count()
        solved = officer.assigned_cases.filter(
            complaint__status='resolved'
        ).count()
        performance = round((solved / assigned * 100)) if assigned else 0
        top_officers.append({
            'username': officer.username,
            'assigned': assigned,
            'solved': solved,
            'performance': performance,
        })
    top_officers = sorted(top_officers, key=lambda x: x['performance'], reverse=True)[:5]

    context = {
        'total_users': total_users,
        'total_citizens': total_citizens,
        'total_officers': total_officers,
        'total_complaints': total_complaints,
        'pending_cases': pending_cases,
        'investigating_cases': investigating_cases,
        'resolved_cases': resolved_cases,
        'high_priority_cases': high_priority_cases,
        'active_investigations': active_investigations,
        'latest_complaints': recent_complaints,
        'status_data': status_data,
        'category_data': category_data,
        'priority_data': priority_data,
        'monthly_data': monthly_data,
        'monthly_labels_json': json.dumps(monthly_labels),
        'monthly_totals_json': json.dumps(monthly_totals),
        'ai_fraud_cases': ai_fraud_cases,
        'ai_theft_cases': ai_theft_cases,
        'ai_cyber_cases': ai_cyber_cases,
        'top_officers': top_officers,
    }

    return render(request, 'admin_panel/dashboard.html', context)

@staff_required
def crime_map(request):
    complaints = Complaint.objects.exclude(
        latitude__isnull=True
    ).exclude(longitude__isnull=True)

    category = request.GET.get('category')
    priority = request.GET.get('priority')

    if category:
        complaints = complaints.filter(category=category)
    if priority:
        complaints = complaints.filter(priority=priority)

    all_complaints = Complaint.objects.all()

    location_stats = (
        all_complaints.values('location')
        .annotate(total_cases=Count('id'))
        .order_by('-total_cases')
    )

    total_locations = location_stats.count()

    hotspot_count = location_stats.filter(
        total_cases__gte=2
    ).count()

    safe_zones = max(total_locations - hotspot_count, 0)

    now = timezone.now()
    this_month_start = now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    last_month_end = this_month_start - timedelta(seconds=1)
    last_month_start = last_month_end.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )

    this_month_count = all_complaints.filter(
        created_at__gte=this_month_start
    ).count()
    last_month_count = all_complaints.filter(
        created_at__gte=last_month_start,
        created_at__lt=this_month_start
    ).count()

    if last_month_count > 0:
        growth = round(
            (this_month_count - last_month_count)
            / last_month_count * 100
        )
    elif this_month_count:
        growth = 100
    else:
        growth = 0

    crime_growth = f'{growth}%'

    predicted_theft = all_complaints.filter(
        ai_category__icontains='theft'
    ).count()

    predicted_fraud = all_complaints.filter(
        ai_category__icontains='fraud'
    ).count()

    predicted_cyber = all_complaints.filter(
        ai_category__icontains='cyber'
    ).count()

    hotspot_zones = location_stats.filter(total_cases__gte=2)[:5]

    return render(request, 'analytics/crime_map.html', {
        'complaints': complaints,
        'total_locations': total_locations,
        'hotspot_count': hotspot_count,
        'safe_zones': safe_zones,
        'crime_growth': crime_growth,
        'predicted_theft': predicted_theft,
        'predicted_fraud': predicted_fraud,
        'predicted_cyber': predicted_cyber,
        'hotspot_zones': hotspot_zones
    })

@staff_required
def ai_dashboard(request):
    complaints = Complaint.objects.all().order_by('-created_at')
    return render(request, 'analytics/ai_dashboard.html', 
                  {
                      'complaints': complaints,
                      'ai_classified_count': complaints.exclude(ai_category__isnull=True).exclude(ai_category='').count(),
                      'unclassified_count': complaints.filter(ai_category__isnull=True).count() + complaints.filter(ai_category='').count(),
                      'category_count': complaints.values('ai_category').distinct().count(),
                  })

@staff_required
def ai_command_center(request):

    complaints = Complaint.objects.all()

    ai_complaints = complaints.exclude(
        ai_category__isnull=True
    ).exclude(ai_category='')

    ai_processed = ai_complaints.count()

    high_risk_cases = complaints.filter(priority='High').count()

    solved_cases = complaints.filter(status='resolved').count()

    hotspot_locations = complaints.values('location').annotate(
        total=Count('id')
    ).count()

    predictions = []
    top_locations = complaints.values('location').annotate(
        total=Count('id')
    ).order_by('-total')[:5]

    for stat in top_locations:
        location = stat['location']
        top_category = complaints.filter(
            location=location
        ).values('ai_category').annotate(
            total=Count('id')
        ).order_by('-total').first()

        if top_category and top_category['ai_category']:
            category = top_category['ai_category']
            confidence = round(top_category['total'] / stat['total'] * 100)
        else:
            category = 'Unknown'
            confidence = 0

        if stat['total'] >= 3:
            risk = 'High'
        elif stat['total'] == 2:
            risk = 'Medium'
        else:
            risk = 'Low'

        predictions.append({
            'location': location,
            'risk': risk,
            'category': category,
            'confidence': confidence
        })

    recommendations = []
    for officer in User.objects.filter(role='officer'):
        solved = Investigation.objects.filter(
            assigned_officer=officer,
            complaint__status='resolved'
        ).count()
        recommendations.append({
            'name': officer.username,
            'score': solved * 10,
            'active_cases': officer.current_case_count
        })

    recommendations = sorted(
        recommendations,
        key=lambda item: item['score'],
        reverse=True
    )[:5]

    high_priority_cases = complaints.filter(
        priority='High'
    ).order_by('-created_at')[:5]

    ai_results = []
    for complaint in ai_complaints.order_by('-created_at')[:10]:
        ai_results.append({
            'id': complaint.tracking_id,
            'category': complaint.ai_category,
            'confidence': predict_confidence(complaint.description)
        })

    crime_type_data = [
        complaints.filter(category='theft').count(),
        complaints.filter(category='cybercrime').count(),
        complaints.filter(category='fraud').count(),
        complaints.filter(category='assault').count(),
        complaints.filter(category='other').count(),
    ]

    map_complaints = complaints.exclude(
        latitude__isnull=True
    ).exclude(longitude__isnull=True)

    context = {
        "ai_processed": ai_processed,
        "high_risk_cases": high_risk_cases,
        "solved_cases": solved_cases,
        "hotspot_locations": hotspot_locations,
        "predictions": predictions,
        "recommendations": recommendations,
        "high_priority_cases": high_priority_cases,
        "ai_results": ai_results,
        "crime_type_data_json": json.dumps(crime_type_data),
        "map_complaints": map_complaints,
    }

    return render(
        request,
        "analytics/ai_command_center.html",
        context
    )