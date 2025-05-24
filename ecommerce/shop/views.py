from django.shortcuts import render, redirect, reverse, get_object_or_404
import stripe
from django.conf import settings
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from django.db.models import Q
from django.core.paginator import Paginator
from .models import *
from .utils import *
from .cart import Cart
from .forms import *
import json

stripe.api_key = settings.STRIPE_SECRET_KEY

def shop_view(request):
    products_list = stripe.Product.list()
    products = []
    
    for product in products_list['data']:
        if product.get('metadata', {}).get('category') == "shop":
            products.append(get_product_details(product)) 
        
    return render(request, 'a_stripe/shop.html', {'products': products})


def product_view(request, product_id):
    product = stripe.Product.retrieve(product_id)
    product_details = get_product_details(product)
    
    cart = Cart(request)
    product_details['in_cart'] = product_id in cart.cart_session
    
    return render(request, 'a_stripe/product.html', {'product': product_details})


def add_to_cart(request, product_id):
    cart = Cart(request)
    cart.add(product_id)
    
    product = stripe.Product.retrieve(product_id)
    product_details = get_product_details(product)
    product_details['in_cart'] = product_id in cart.cart_session

    response = render(request, 'a_stripe/partials/cart-button.html', {'product': product_details})
    response['HX-Trigger'] = 'hx_menu_cart'
    return response


def hx_menu_cart(request):
    return render(request, 'a_stripe/partials/menu-cart.html' )


def cart_view(request):
    quantity_range = list(range(1, 11)) 
    return render(request, 'a_stripe/cart.html', {'quantity_range': quantity_range})


def update_checkout(request, product_id):
    quantity = int(request.POST.get('quantity', 1))
    cart = Cart(request)
    cart.add(product_id, quantity)
    
    product = stripe.Product.retrieve(product_id)
    product_details = get_product_details(product)
    product_details['total_price'] = product_details['price'] * quantity

    response = render(request, 'a_stripe/partials/checkout-total.html', {'product' : product_details}) 
    response['HX-Trigger'] = 'hx_menu_cart'
    return response


def remove_from_cart(request, product_id):
    cart = Cart(request)
    cart.remove(product_id)
    return redirect('cart')


@login_required
def checkout_view(request):
    shipping_info = ShippingInfo.objects.filter(user=request.user).first()
    
    if shipping_info:
        form = ShippingForm(instance=shipping_info)
    else:
        form = ShippingForm(initial={'email': request.user.email})
    
    if request.method == 'POST':
        form = ShippingForm(request.POST, instance=shipping_info)
        if form.is_valid():
            shipping_info = form.save(commit=False)
            shipping_info.user = request.user
            shipping_info.email = form.cleaned_data['email'].lower()
            shipping_info.save()
            
            cart = Cart(request)
            checkout_session = create_checkout_session(cart, shipping_info.email)
            
            CheckoutSession.objects.create(
                checkout_id = checkout_session.id,
                shipping_info = shipping_info,
                total_cost = cart.get_total_cost()
            )
            
            return redirect(checkout_session.url, code=303)
    
    return render(request, 'a_stripe/checkout.html', {'form': form})



def payment_successful(request):
    checkout_session_id = request.GET.get('session_id', None)
    
    if checkout_session_id:
        session = stripe.checkout.Session.retrieve(checkout_session_id)
        customer_id = session.customer
        customer = stripe.Customer.retrieve(customer_id)
        
        if settings.CART_SESSION_ID in request.session:
            del request.session[settings.CART_SESSION_ID]
            
        if settings.DEBUG:
            checkout = CheckoutSession.objects.get(checkout_id=checkout_session_id)
            checkout.has_paid = True
            checkout.save()
    
    return render(request, 'a_stripe/payment_successful.html', {'customer': customer})


def payment_cancelled(request):
    return render(request, 'a_stripe/payment_cancelled.html')


@require_POST
@csrf_exempt
def stripe_webhook(request):
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET
    payload = request.body
    signature_header = request.META['HTTP_STRIPE_SIGNATURE']
    event = None
    
    try:
        event = stripe.Webhook.construct_event(
            payload, signature_header, endpoint_secret
        )
    except:
        return HttpResponse(status=400)
    
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        checkout_session_id = session.get('id')
        checkout = CheckoutSession.objects.get(checkout_id=checkout_session_id)
        checkout.has_paid = True
        checkout.save()
        
    return HttpResponse(status=200)

def home(request):
    featured_products = Product.objects.filter(is_featured=True, is_active=True)[:8]
    categories = Category.objects.filter(parent=None)
    latest_products = Product.objects.filter(is_active=True).order_by('-created_at')[:8]
    context = {
        'featured_products': featured_products,
        'categories': categories,
        'latest_products': latest_products,
    }
    return render(request, 'home.html', context)

def product_list(request):
    products = Product.objects.filter(is_active=True)
    category = request.GET.get('category')
    search_query = request.GET.get('q')
    sort = request.GET.get('sort', '-created_at')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')

    if category:
        products = products.filter(category__slug=category)
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(category__name__icontains=search_query)
        )
    if min_price:
        products = products.filter(price__gte=min_price)
    if max_price:
        products = products.filter(price__lte=max_price)

    products = products.order_by(sort)
    paginator = Paginator(products, 12)
    page = request.GET.get('page')
    products = paginator.get_page(page)

    categories = Category.objects.all()
    context = {
        'products': products,
        'categories': categories,
    }
    return render(request, 'shop/product_list.html', context)

def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    reviews = product.reviews.all()
    related_products = product.related_products.all()[:4]
    
    if request.method == 'POST' and request.user.is_authenticated:
        form = ReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.product = product
            review.user = request.user
            review.save()
            messages.success(request, 'Your review has been added!')
            return redirect('shop:product_detail', slug=slug)
    else:
        form = ReviewForm()

    context = {
        'product': product,
        'reviews': reviews,
        'form': form,
        'related_products': related_products,
    }
    return render(request, 'shop/product_detail.html', context)

def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    products = Product.objects.filter(category=category, is_active=True)
    subcategories = category.children.all()
    
    context = {
        'category': category,
        'products': products,
        'subcategories': subcategories,
    }
    return render(request, 'shop/category_detail.html', context)

@login_required
def add_to_cart(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        product_id = data.get('product_id')
        quantity = int(data.get('quantity', 1))
        product = get_object_or_404(Product, id=product_id)
        cart, created = CartModel.objects.get_or_create(user=request.user)
        cart_item, created = CartItem.objects.get_or_create(
            cart=cart,
            product=product,
            defaults={'quantity': quantity}
        )
        if not created:
            cart_item.quantity += quantity
            cart_item.save()
        return JsonResponse({
            'message': 'Product added to cart',
            'cart_total': cart.get_total_price(),
            'cart_items': cart.get_total_items()
        })
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def cart_detail(request):
    cart, created = CartModel.objects.get_or_create(user=request.user)
    return render(request, 'shop/cart_detail.html', {'cart': cart})

@login_required
def update_cart(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        item_id = data.get('item_id')
        quantity = int(data.get('quantity', 1))
        cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        cart_item.quantity = quantity
        cart_item.save()
        return JsonResponse({
            'message': 'Cart updated',
            'cart_total': cart_item.cart.get_total_price(),
            'cart_items': cart_item.cart.get_total_items()
        })
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def remove_from_cart(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        item_id = data.get('item_id')
        cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        cart = cart_item.cart
        cart_item.delete()
        return JsonResponse({
            'message': 'Item removed from cart',
            'cart_total': cart.get_total_price(),
            'cart_items': cart.get_total_items()
        })
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def checkout(request):
    cart = get_object_or_404(CartModel, user=request.user)
    if not cart.items.exists():
        messages.warning(request, 'Your cart is empty!')
        return redirect('shop:cart_detail')
    if request.method == 'POST':
        order = Order.objects.create(
            user=request.user,
            total_amount=cart.get_total_price(),
            shipping_address=request.POST.get('shipping_address'),
            billing_address=request.POST.get('billing_address'),
            payment_method=request.POST.get('payment_method'),
        )
        for item in cart.items.all():
            OrderItem.objects.create(
                order=order,
                product=item.product,
                quantity=item.quantity,
                price=item.product.sale_price or item.product.price
            )
        cart.items.all().delete()
        messages.success(request, 'Your order has been placed successfully!')
        return redirect('shop:order_detail', order_id=order.id)
    return render(request, 'shop/checkout.html', {'cart': cart})

@login_required
def order_list(request):
    orders = Order.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'shop/order_list.html', {'orders': orders})

@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    return render(request, 'shop/order_detail.html', {'order': order})

@login_required
def add_review(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        form = ReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.product = product
            review.user = request.user
            review.save()
            messages.success(request, 'Your review has been added!')
            return redirect('shop:product_detail', slug=product.slug)
    else:
        form = ReviewForm()
    return render(request, 'shop/add_review.html', {'form': form, 'product': product})

def search(request):
    query = request.GET.get('q', '')
    if query:
        products = Product.objects.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(category__name__icontains=query)
        ).distinct()
    else:
        products = Product.objects.none()
    
    return render(request, 'shop/search_results.html', {
        'products': products,
        'query': query
    })

def pricing(request):
    return render(request, 'pricing.html')

def contact(request):
    if request.method == 'POST':
        # Here you can handle the form submission, e.g., send email or save to DB
        # For now, just render the same page (optionally with a success message)
        pass
    return render(request, 'contact.html')
