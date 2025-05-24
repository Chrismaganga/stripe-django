from django.urls import path
from . import views

app_name = 'subscription'

urlpatterns = [
    path('', views.subscription_page, name='subscription'),
    path('success/', views.subscription_success, name='subscription_success'),
    path('cancel/', views.subscription_cancel, name='subscription_cancel'),
    path('webhook/', views.stripe_webhook, name='webhook'),
] 