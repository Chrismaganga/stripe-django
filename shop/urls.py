from django.urls import path
from . import views

app_name = 'shop'

urlpatterns = [
    path('', views.shop_view, name='product'),
    path('checkout/', views.checkout_view, name='checkout'),
    path('payment-successful/', views.payment_successful, name='payment_successful'),
    path('payment-cancelled/', views.payment_cancelled, name='payment_cancelled'),
] 