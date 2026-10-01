from django.urls import path
from .views import (
    home,
    health_check,
    run_migrations,
    register_view,
    login_view,
    logout_view,
    dashboard,
    verify_email,
    forgot_password,
    reset_password,
    pending_officers,
    approve_officer,
    reject_officer,
)

urlpatterns = [
    path('health/', health_check, name='health_check'),
    path('internal/migrate/', run_migrations, name='run_migrations'),
    path('', home, name='home'),
    path('register/', register_view, name='register'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('dashboard/', dashboard, name='dashboard'),
    path('verify-email/', verify_email, name='verify_email'),
    path('forgot-password/', forgot_password, name='forgot_password'),
    path('reset-password/', reset_password, name='reset_password'),
    path('pending-officers/', pending_officers, name='pending_officers'),
    path('approve-officer/<int:user_id>/', approve_officer, name='approve_officer'),
    path('reject-officer/<int:user_id>/', reject_officer, name='reject_officer'),
]