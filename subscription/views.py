from django.shortcuts import render

def subscription_page(request):
    return render(request, 'subscription.html') 