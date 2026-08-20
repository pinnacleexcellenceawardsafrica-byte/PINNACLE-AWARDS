from django.urls import path
from . import views

urlpatterns = [
    # Public
    path('', views.index, name='index'),
    path('api/vote/', views.api_vote, name='api_vote'),
    path('api/standings/', views.api_standings, name='api_standings'),
    path('api/nominate/', views.api_nominate, name='api_nominate'),
    
    # Paystack Routes
    path('paystack/initialize/', views.paystack_initialize, name='paystack_initialize'),
    path('paystack/verify/', views.paystack_verify, name='paystack_verify'),
    path('paystack-callback/', views.paystack_callback, name='paystack_callback'),
    path('paystack-webhook/', views.paystack_webhook, name='paystack_webhook'),
    
    # Admin Auth
    path('admin/', views.admin_login_view, name='admin'),
    path('admin-login/', views.admin_login_view, name='admin_login'),
    path('admin-logout/', views.admin_logout_view, name='admin_logout'),
    
    # Admin Pages
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin-partners/', views.admin_partners, name='admin_partners'),
    path('admin-nominees/', views.admin_nominees, name='admin_nominees'),
    path('admin-categories/', views.admin_categories, name='admin_categories'),
    path('admin-gallery/', views.admin_gallery, name='admin_gallery'),
    path('admin-news/', views.admin_news, name='admin_news'),
    path('admin-hall-of-fame/', views.admin_hall_of_fame, name='admin_hall_of_fame'),
    path('admin-votes/', views.admin_votes, name='admin_votes'),
    path('admin-settings/', views.admin_settings, name='admin_settings'),
    path('admin-countdown/', views.admin_countdown, name='admin_countdown'),
    path('admin-revenue/', views.admin_revenue, name='admin_revenue'),
    path('admin-user-nominations/', views.admin_user_nominations, name='admin_user_nominations'),
    
    # Admin APIs
    path('api/partners/', views.api_partners, name='api_partners'),
    path('api/nominees/', views.api_nominees, name='api_nominees'),
    path('api/categories/', views.api_categories, name='api_categories'),
    path('api/gallery/', views.api_gallery, name='api_gallery'),
    path('api/gallery/upload/', views.api_gallery_upload, name='api_gallery_upload'),
    path('api/news/', views.api_news, name='api_news'),
    path('api/hall-of-fame/', views.api_hall_of_fame, name='api_hall_of_fame'),
    path('api/votes/', views.api_votes_admin, name='api_votes_admin'),
    path('api/settings/', views.api_settings, name='api_settings'),
    path('api/countdown/', views.api_countdown, name='api_countdown'),
    path('api/user-nominations/', views.api_user_nominations, name='api_user_nominations'),
    
    # Revenue APIs
    path('api/revenue-stats/', views.api_revenue_stats, name='api_revenue_stats'),
    path('api/transactions/', views.api_transactions, name='api_transactions'),
    path('api/transactions/export/', views.api_transactions_export, name='api_transactions_export'),
]