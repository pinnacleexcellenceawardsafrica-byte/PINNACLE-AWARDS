import json
import csv
import requests
import datetime
import re
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count, Sum, Q
from django.utils import timezone
from django.conf import settings
from .models import *

def is_admin_user(user):
    return user.is_authenticated and user.is_staff

# ============================================================
# ADMIN LOGIN / LOGOUT
# ============================================================

def admin_login_view(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('admin_dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None and user.is_staff:
            login(request, user)
            return JsonResponse({
                'success': True, 
                'redirect_url': '/admin-dashboard/'
            })
        else:
            return JsonResponse({
                'success': False, 
                'message': 'Invalid credentials. Please try again.'
            }, status=401)
    
    return render(request, 'admin_dashboard.html')

def admin_logout_view(request):
    logout(request)
    return redirect('admin_login')

# ============================================================
# PUBLIC INDEX
# ============================================================

def index(request):
    categories = Category.objects.filter(is_active=True)
    nominees = Nominee.objects.filter(status='active').order_by('-votes')
    news = NewsArticle.objects.filter(published=True).order_by('-published_date')[:3]
    gallery = GalleryImage.objects.filter(featured=True).order_by('order')[:6]
    partners = Partner.objects.filter(is_active=True).order_by('order')
    hall_of_fame = HallOfFame.objects.all().order_by('-year')[:6]
    
    rankings = Nominee.objects.filter(status='active').order_by('-votes')[:10]
    max_votes = nominees.aggregate(max=Sum('votes'))['max'] or 1
    total_categories = categories.count()
    total_nominees = nominees.count()
    
    paystack_public_key = getattr(settings, 'PAYSTACK_PUBLIC_KEY', '')
    site_settings = SiteSettings.objects.first()
    
    context = {
        'categories': categories,
        'nominees': nominees,
        'news': news,
        'gallery': gallery,
        'partners': partners,
        'hall_of_fame': hall_of_fame,
        'rankings': rankings,
        'max_votes': max_votes,
        'total_categories': total_categories,
        'total_nominees': total_nominees,
        'paystack_public_key': paystack_public_key,
        'site_settings': site_settings,
        'page_title': 'Home',
    }
    return render(request, 'index.html', context)

# ============================================================
# PAYSTACK PAYMENT INITIALIZATION
# ============================================================

@csrf_exempt
def paystack_initialize(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=400)
    
    try:
        data = json.loads(request.body)
        nominee_id = data.get('nominee_id')
        phone = data.get('phone')
        voter_name = data.get('voter_name', '')
        voter_email = data.get('voter_email', '')
        amount = data.get('amount', 10.00)
        quantity = data.get('quantity', 1)
        
        if not nominee_id or not phone:
            return JsonResponse({'success': False, 'message': 'Nominee and phone are required'}, status=400)
        
        nominee = get_object_or_404(Nominee, id=nominee_id)
        settings_obj = SiteSettings.objects.first()
        
        if not settings_obj or not settings_obj.voting_open:
            return JsonResponse({'success': False, 'message': 'Voting is currently closed'}, status=400)
        
        if not getattr(settings, 'PAYSTACK_ACTIVE', False):
            return JsonResponse({'success': False, 'message': 'Paystack is not active. Please contact administrator.'}, status=400)
        
        reference = f"PEA-{int(timezone.now().timestamp())}-{nominee.id}-{quantity}"
        amount_in_cents = int(amount * 100)
        email = voter_email or f"voter_{reference}@pinnacleexcellenceawards.com"
        
        payload = {
            "email": email,
            "amount": amount_in_cents,
            "currency": "KES",
            "reference": reference,
            "callback_url": request.build_absolute_uri('/paystack-callback/'),
            "metadata": {
                "nominee_id": nominee.id,
                "nominee_name": nominee.name,
                "phone": phone,
                "voter_name": voter_name,
                "quantity": quantity,
                "custom_fields": [
                    {"display_name": "Nominee", "variable_name": "nominee", "value": nominee.name},
                    {"display_name": "Quantity", "variable_name": "quantity", "value": str(quantity)}
                ]
            }
        }
        
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }
        
        response = requests.post(
            "https://api.paystack.co/transaction/initialize",
            json=payload,
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('status'):
                vote = Vote.objects.create(
                    nominee=nominee,
                    category=nominee.category,
                    voter_phone=phone,
                    voter_name=voter_name,
                    voter_email=email,
                    transaction_id=reference,
                    amount=amount,
                    payment_status='pending',
                    payment_method='Paystack',
                    paystack_reference=reference,
                    ip_address=request.META.get('REMOTE_ADDR')
                )
                
                return JsonResponse({
                    'success': True,
                    'authorization_url': result['data']['authorization_url'],
                    'reference': reference,
                    'access_code': result['data']['access_code'],
                    'vote_id': vote.id,
                    'email': email,
                    'amount': amount
                })
            else:
                return JsonResponse({'success': False, 'message': result.get('message', 'Paystack error')}, status=400)
        else:
            return JsonResponse({'success': False, 'message': 'Payment gateway error'}, status=500)
            
    except Nominee.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Nominee not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

# ============================================================
# PAYSTACK VERIFY
# ============================================================

@csrf_exempt
def paystack_verify(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=400)
    
    try:
        data = json.loads(request.body)
        reference = data.get('reference')
        nominee_id = data.get('nominee_id')
        quantity = data.get('quantity', 1)
        
        if not reference:
            return JsonResponse({'success': False, 'message': 'Reference required'}, status=400)
        
        if not nominee_id:
            return JsonResponse({'success': False, 'message': 'Nominee ID required'}, status=400)
        
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }
        
        response = requests.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('status') and result['data']['status'] == 'success':
                vote = Vote.objects.filter(transaction_id=reference).first()
                nominee = get_object_or_404(Nominee, id=nominee_id)
                
                qty = quantity
                
                if not vote:
                    metadata = result['data'].get('metadata', {})
                    vote = Vote.objects.create(
                        nominee=nominee,
                        category=nominee.category,
                        voter_phone=metadata.get('phone', ''),
                        voter_name=metadata.get('voter_name', ''),
                        voter_email=result['data'].get('customer', {}).get('email', ''),
                        transaction_id=reference,
                        amount=result['data'].get('amount', 0) / 100,
                        payment_status='completed',
                        payment_method='Paystack',
                        paystack_reference=reference,
                        payment_response=result.get('data'),
                        ip_address=request.META.get('REMOTE_ADDR')
                    )
                else:
                    vote.payment_status = 'completed'
                    vote.payment_response = result.get('data')
                    vote.save()
                
                nominee.votes += qty
                nominee.save()
                
                return JsonResponse({
                    'success': True,
                    'message': f'{qty} vote(s) recorded for {nominee.name}!',
                    'nominee_name': nominee.name,
                    'nominee_id': nominee.id,
                    'total_votes': nominee.votes,
                    'quantity': qty,
                    'transaction_id': reference
                })
            else:
                vote = Vote.objects.filter(transaction_id=reference).first()
                if vote:
                    vote.payment_status = 'failed'
                    vote.payment_response = result.get('data')
                    vote.save()
                
                return JsonResponse({
                    'success': False,
                    'message': result.get('message', 'Payment verification failed')
                }, status=400)
        else:
            return JsonResponse({'success': False, 'message': 'Payment verification failed'}, status=500)
            
    except Nominee.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Nominee not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

# ============================================================
# PAYSTACK CALLBACK
# ============================================================

@csrf_exempt
def paystack_callback(request):
    reference = request.GET.get('reference')
    if not reference:
        messages.error(request, 'Invalid payment reference')
        return redirect('index')
    
    try:
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }
        
        response = requests.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('status') and result['data']['status'] == 'success':
                vote = Vote.objects.filter(transaction_id=reference).first()
                if vote:
                    vote.payment_status = 'completed'
                    vote.payment_response = result.get('data')
                    vote.save()
                    
                    qty = result['data'].get('metadata', {}).get('quantity', 1)
                    nominee = vote.nominee
                    nominee.votes += qty
                    nominee.save()
                    
                    messages.success(request, f'✅ Payment successful! {qty} vote(s) for {nominee.name} recorded.')
                else:
                    messages.error(request, 'Vote record not found')
            else:
                vote = Vote.objects.filter(transaction_id=reference).first()
                if vote:
                    vote.payment_status = 'failed'
                    vote.payment_response = result.get('data')
                    vote.save()
                messages.error(request, 'Payment was not successful. Please try again.')
        else:
            messages.error(request, 'Payment verification failed. Please contact support.')
            
    except Exception as e:
        messages.error(request, f'An error occurred: {str(e)}')
    
    return redirect('index')

# ============================================================
# PAYSTACK WEBHOOK
# ============================================================

@csrf_exempt
def paystack_webhook(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        event = data.get('event')
        
        if event == 'charge.success':
            transaction_data = data.get('data', {})
            reference = transaction_data.get('reference')
            
            if reference:
                vote = Vote.objects.filter(transaction_id=reference).first()
                if vote and vote.payment_status == 'pending':
                    vote.payment_status = 'completed'
                    vote.payment_response = transaction_data
                    vote.save()
                    
                    qty = transaction_data.get('metadata', {}).get('quantity', 1)
                    nominee = vote.nominee
                    nominee.votes += qty
                    nominee.save()
                    
                    return JsonResponse({'status': 'success'})
        
        return JsonResponse({'status': 'ignored'})
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

# ============================================================
# VOTING API
# ============================================================

@csrf_exempt
def api_vote(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=400)
    
    try:
        data = json.loads(request.body)
        nominee_id = data.get('nominee_id')
        phone = data.get('phone')
        voter_name = data.get('voter_name', '')
        voter_email = data.get('voter_email', '')
        amount = data.get('amount', 10.00)
        payment_method = data.get('payment_method', 'M-Pesa')
        transaction_id = data.get('transaction_id', f"VOTE-{int(timezone.now().timestamp())}")
        quantity = data.get('quantity', 1)
        
        if not nominee_id or not phone:
            return JsonResponse({'success': False, 'message': 'Nominee and phone are required'}, status=400)
        
        nominee = get_object_or_404(Nominee, id=nominee_id)
        settings_obj = SiteSettings.objects.first()
        
        if not settings_obj or not settings_obj.voting_open:
            return JsonResponse({'success': False, 'message': 'Voting is currently closed'}, status=400)
        
        vote = Vote.objects.create(
            nominee=nominee,
            category=nominee.category,
            voter_phone=phone,
            voter_name=voter_name,
            voter_email=voter_email,
            transaction_id=transaction_id,
            amount=amount * quantity,
            payment_status='completed',
            payment_method=payment_method,
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        nominee.votes += quantity
        nominee.save()
        
        return JsonResponse({
            'success': True,
            'message': f'{quantity} vote(s) recorded successfully!',
            'vote_id': vote.id,
            'transaction_id': transaction_id,
            'new_vote_count': nominee.votes,
            'nominee_id': nominee.id,
            'amount': float(vote.amount),
            'quantity': quantity
        })
        
    except Nominee.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Nominee not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

# ============================================================
# API: STANDINGS
# ============================================================

def api_standings(request):
    standings = []
    for cat in Category.objects.filter(is_active=True):
        top = cat.nominees.order_by('-votes').first()
        standings.append({
            'category': cat.name,
            'category_id': cat.id,
            'leader': top.name if top else None,
            'leader_votes': top.votes if top else 0,
            'total_votes': cat.nominees.aggregate(total=Sum('votes'))['total'] or 0,
            'nominee_count': cat.nominees.count()
        })
    
    return JsonResponse({
        'success': True,
        'standings': standings
    })

# ============================================================
# USER NOMINATION API
# ============================================================

@csrf_exempt
def api_nominate(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=400)
    
    try:
        data = json.loads(request.body)
        
        nominee_name = data.get('nominee_name', '').strip()
        category_id = data.get('category_id')
        description = data.get('description', '').strip()
        nominator_name = data.get('nominator_name', '').strip()
        nominator_email = data.get('nominator_email', '').strip()
        nominator_phone = data.get('nominator_phone', '').strip()
        
        if not nominee_name:
            return JsonResponse({'success': False, 'message': 'Nominee name is required'}, status=400)
        if not category_id:
            return JsonResponse({'success': False, 'message': 'Category is required'}, status=400)
        if not description:
            return JsonResponse({'success': False, 'message': 'Description is required'}, status=400)
        if not nominator_name:
            return JsonResponse({'success': False, 'message': 'Your name is required'}, status=400)
        if not nominator_email:
            return JsonResponse({'success': False, 'message': 'Your email is required'}, status=400)
        
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, nominator_email):
            return JsonResponse({'success': False, 'message': 'Invalid email address'}, status=400)
        
        try:
            category = Category.objects.get(id=category_id)
        except Category.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Category not found'}, status=400)
        
        existing = UserNomination.objects.filter(
            nominee_name__iexact=nominee_name,
            category=category,
            nominator_email__iexact=nominator_email,
            status='pending'
        ).first()
        
        if existing:
            return JsonResponse({
                'success': False, 
                'message': f'You have already nominated "{nominee_name}" for this category. Please wait for review.'
            }, status=400)
        
        nomination = UserNomination.objects.create(
            nominee_name=nominee_name,
            category=category,
            description=description,
            nominator_name=nominator_name,
            nominator_email=nominator_email,
            nominator_phone=nominator_phone,
            status='pending'
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Thank you for nominating {nominee_name}! Your nomination has been submitted for review.',
            'nomination_id': nomination.id
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

# ============================================================
# ADMIN: USER NOMINATIONS
# ============================================================

@login_required
@user_passes_test(is_admin_user)
def admin_user_nominations(request):
    return render(request, 'admin_dashboard.html', {
        'page_title': 'User Nominations', 
        'admin_page': 'user-nominations'
    })

@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
def api_user_nominations(request):
    if request.method == 'GET':
        nominations = UserNomination.objects.select_related('category', 'approved_nominee').all()
        
        status = request.GET.get('status')
        if status:
            nominations = nominations.filter(status=status)
        
        data = []
        for n in nominations:
            data.append({
                'id': n.id,
                'nominee_name': n.nominee_name,
                'category': n.category.name,
                'category_id': n.category.id,
                'description': n.description,
                'nominator_name': n.nominator_name,
                'nominator_email': n.nominator_email,
                'nominator_phone': n.nominator_phone,
                'status': n.status,
                'admin_notes': n.admin_notes,
                'created_at': n.created_at.strftime('%Y-%m-%d %H:%M'),
                'approved_nominee_id': n.approved_nominee.id if n.approved_nominee else None,
                'approved_nominee_name': n.approved_nominee.name if n.approved_nominee else None,
            })
        
        return JsonResponse({'success': True, 'nominations': data})
    
    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            action = data.get('action')
            nomination_id = data.get('id')
            
            if not nomination_id:
                return JsonResponse({'success': False, 'message': 'Nomination ID required'}, status=400)
            
            nomination = get_object_or_404(UserNomination, id=nomination_id)
            
            if action == 'approve':
                nominee = Nominee.objects.create(
                    name=nomination.nominee_name,
                    category=nomination.category,
                    group=nomination.category.group,
                    description=nomination.description,
                    status='active',
                    votes=0
                )
                
                nomination.status = 'approved'
                nomination.approved_nominee = nominee
                nomination.admin_notes = data.get('admin_notes', '')
                nomination.save()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Nominee "{nomination.nominee_name}" has been approved and added!',
                    'nominee_id': nominee.id
                })
            
            elif action == 'reject':
                nomination.status = 'rejected'
                nomination.admin_notes = data.get('admin_notes', '')
                nomination.save()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Nomination for "{nomination.nominee_name}" has been rejected.'
                })
            
            elif action == 'delete':
                nomination.delete()
                return JsonResponse({
                    'success': True,
                    'message': 'Nomination deleted.'
                })
            
            return JsonResponse({'success': False, 'message': 'Invalid action'}, status=400)
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)

# ============================================================
# REVENUE APIs
# ============================================================

def api_revenue_stats(request):
    total_revenue = Vote.objects.filter(payment_status='completed').aggregate(total=Sum('amount'))['total'] or 0
    today = timezone.now().date()
    today_revenue = Vote.objects.filter(created_at__date=today, payment_status='completed').aggregate(total=Sum('amount'))['total'] or 0
    total_transactions = Vote.objects.filter(payment_status='completed').count()
    today_transactions = Vote.objects.filter(created_at__date=today, payment_status='completed').count()
    completed_transactions = Vote.objects.filter(payment_status='completed').count()
    pending_transactions = Vote.objects.filter(payment_status='pending').count()
    
    return JsonResponse({
        'success': True,
        'total_revenue': float(total_revenue),
        'today_revenue': float(today_revenue),
        'total_transactions': total_transactions,
        'today_transactions': today_transactions,
        'completed_transactions': completed_transactions,
        'pending_transactions': pending_transactions,
        'average_amount': float(total_revenue / total_transactions) if total_transactions > 0 else 0,
    })

def api_transactions(request):
    transactions = Vote.objects.select_related('nominee', 'category').all().order_by('-created_at')
    
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    status = request.GET.get('status')
    
    if from_date:
        transactions = transactions.filter(created_at__date__gte=from_date)
    if to_date:
        transactions = transactions.filter(created_at__date__lte=to_date)
    if status:
        transactions = transactions.filter(payment_status=status)
    
    data = []
    for v in transactions:
        data.append({
            'id': v.id,
            'transaction_id': v.transaction_id or f"VOTE-{v.id}",
            'nominee': v.nominee.name,
            'category': v.category.name,
            'phone': v.voter_phone,
            'amount': float(v.amount),
            'status': v.payment_status,
            'payment_method': v.payment_method,
            'date': v.created_at.strftime('%Y-%m-%d %H:%M'),
        })
    
    return JsonResponse({'success': True, 'transactions': data})

def api_transactions_export(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="transactions.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['ID', 'Transaction ID', 'Nominee', 'Category', 'Phone', 'Amount (KES)', 'Status', 'Payment Method', 'Date'])
    
    votes = Vote.objects.select_related('nominee', 'category').all().order_by('-created_at')
    for v in votes:
        writer.writerow([
            v.id,
            v.transaction_id or f"VOTE-{v.id}",
            v.nominee.name,
            v.category.name,
            v.voter_phone,
            float(v.amount),
            v.payment_status,
            v.payment_method,
            v.created_at.strftime('%Y-%m-%d %H:%M')
        ])
    
    return response

# ============================================================
# ADMIN DASHBOARD
# ============================================================

@login_required
@user_passes_test(is_admin_user)
def admin_dashboard(request):
    stats = {
        'total_votes': Vote.objects.filter(payment_status='completed').count(),
        'total_nominees': Nominee.objects.count(),
        'total_categories': Category.objects.count(),
        'total_news': NewsArticle.objects.count(),
        'total_gallery': GalleryImage.objects.count(),
        'total_partners': Partner.objects.count(),
        'total_hall_of_fame': HallOfFame.objects.count(),
        'votes_today': Vote.objects.filter(created_at__date=timezone.now().date(), payment_status='completed').count(),
        'pending_nominations': UserNomination.objects.filter(status='pending').count(),
    }
    
    revenue_stats = {
        'total_revenue': Vote.objects.filter(payment_status='completed').aggregate(total=Sum('amount'))['total'] or 0,
        'today_revenue': Vote.objects.filter(created_at__date=timezone.now().date(), payment_status='completed').aggregate(total=Sum('amount'))['total'] or 0,
        'total_transactions': Vote.objects.filter(payment_status='completed').count(),
        'today_transactions': Vote.objects.filter(created_at__date=timezone.now().date(), payment_status='completed').count(),
    }
    
    top_nominees = Nominee.objects.filter(status='active').order_by('-votes')[:5]
    
    context = {
        'stats': stats,
        'revenue_stats': revenue_stats,
        'top_nominees': top_nominees,
        'page_title': 'Dashboard',
    }
    return render(request, 'admin_dashboard.html', context)

# ============================================================
# ADMIN: PARTNERS
# ============================================================

@login_required
@user_passes_test(is_admin_user)
def admin_partners(request):
    return render(request, 'admin_dashboard.html', {'page_title': 'Partners', 'admin_page': 'partners'})

@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
def api_partners(request):
    if request.method == 'GET':
        partners = Partner.objects.all().order_by('order')
        data = []
        for p in partners:
            data.append({
                'id': p.id,
                'name': p.name,
                'type': p.type,
                'type_display': p.get_type_display(),
                'logo_url': p.logo.url if p.logo else None,
                'website': p.website,
                'description': p.description,
                'is_active': p.is_active,
                'order': p.order
            })
        return JsonResponse({'success': True, 'partners': data})
    
    elif request.method == 'POST':
        try:
            if request.content_type and 'multipart' in request.content_type:
                action = request.POST.get('action')
                name = request.POST.get('name')
                type_ = request.POST.get('type')
                website = request.POST.get('website', '')
                description = request.POST.get('description', '')
            else:
                data = json.loads(request.body)
                action = data.get('action')
                name = data.get('name')
                type_ = data.get('type')
                website = data.get('website', '')
                description = data.get('description', '')
            
            if action == 'add':
                partner = Partner.objects.create(
                    name=name,
                    type=type_,
                    website=website,
                    description=description,
                    is_active=True
                )
                if request.FILES and 'logo' in request.FILES:
                    partner.logo = request.FILES['logo']
                    partner.save()
                return JsonResponse({'success': True, 'message': 'Partner added!', 'id': partner.id})
            
            elif action == 'edit':
                partner_id = request.POST.get('id') if request.content_type and 'multipart' in request.content_type else data.get('id')
                partner = get_object_or_404(Partner, id=partner_id)
                partner.name = name
                partner.type = type_
                partner.website = website
                partner.description = description
                if request.FILES and 'logo' in request.FILES:
                    partner.logo = request.FILES['logo']
                partner.save()
                return JsonResponse({'success': True, 'message': 'Partner updated!'})
            
            elif action == 'delete':
                partner_id = request.POST.get('id') if request.content_type and 'multipart' in request.content_type else data.get('id')
                partner = get_object_or_404(Partner, id=partner_id)
                partner.delete()
                return JsonResponse({'success': True, 'message': 'Partner deleted!'})
            
            elif action == 'toggle':
                partner_id = request.POST.get('id') if request.content_type and 'multipart' in request.content_type else data.get('id')
                partner = get_object_or_404(Partner, id=partner_id)
                partner.is_active = not partner.is_active
                partner.save()
                return JsonResponse({'success': True, 'message': 'Partner toggled!', 'is_active': partner.is_active})
            
            return JsonResponse({'success': False, 'message': 'Invalid action'}, status=400)
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)

# ============================================================
# ADMIN: NOMINEES
# ============================================================

@login_required
@user_passes_test(is_admin_user)
def admin_nominees(request):
    return render(request, 'admin_dashboard.html', {'page_title': 'Nominees', 'admin_page': 'nominees'})

@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
def api_nominees(request):
    if request.method == 'GET':
        nominees = Nominee.objects.select_related('category').all().order_by('-votes')
        data = []
        for n in nominees:
            data.append({
                'id': n.id,
                'name': n.name,
                'category': n.category.name,
                'category_id': n.category.id,
                'group': n.group,
                'description': n.description,
                'gender': n.gender,
                'photo_url': n.photo.url if n.photo else None,
                'votes': n.votes,
                'status': n.status,
                'featured': n.featured
            })
        return JsonResponse({'success': True, 'nominees': data})
    
    elif request.method == 'POST':
        try:
            if request.content_type and 'multipart' in request.content_type:
                action = request.POST.get('action')
                name = request.POST.get('name')
                category_id = request.POST.get('category_id')
                group = request.POST.get('group')
                votes = request.POST.get('votes', 0)
                status = request.POST.get('status', 'active')
                description = request.POST.get('description', '')
            else:
                data = json.loads(request.body)
                action = data.get('action')
                name = data.get('name')
                category_id = data.get('category_id')
                group = data.get('group')
                votes = data.get('votes', 0)
                status = data.get('status', 'active')
                description = data.get('description', '')
            
            if action == 'add':
                category = get_object_or_404(Category, id=category_id)
                nominee = Nominee.objects.create(
                    name=name,
                    category=category,
                    group=group or category.group,
                    description=description,
                    gender='other',
                    status=status or 'active',
                    votes=int(votes) if votes else 0
                )
                if request.FILES and 'photo' in request.FILES:
                    nominee.photo = request.FILES['photo']
                    nominee.save()
                return JsonResponse({'success': True, 'message': 'Nominee added!', 'id': nominee.id})
            
            elif action == 'edit':
                nominee_id = request.POST.get('id') if request.content_type and 'multipart' in request.content_type else data.get('id')
                nominee = get_object_or_404(Nominee, id=nominee_id)
                nominee.name = name
                if category_id:
                    category = get_object_or_404(Category, id=category_id)
                    nominee.category = category
                    nominee.group = category.group
                nominee.description = description
                nominee.status = status or 'active'
                nominee.votes = int(votes) if votes else 0
                if request.FILES and 'photo' in request.FILES:
                    nominee.photo = request.FILES['photo']
                nominee.save()
                return JsonResponse({'success': True, 'message': 'Nominee updated!'})
            
            elif action == 'delete':
                nominee_id = request.POST.get('id') if request.content_type and 'multipart' in request.content_type else data.get('id')
                nominee = get_object_or_404(Nominee, id=nominee_id)
                nominee.delete()
                return JsonResponse({'success': True, 'message': 'Nominee deleted!'})
            
            return JsonResponse({'success': False, 'message': 'Invalid action'}, status=400)
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)

# ============================================================
# ADMIN: CATEGORIES
# ============================================================

@login_required
@user_passes_test(is_admin_user)
def admin_categories(request):
    return render(request, 'admin_dashboard.html', {'page_title': 'Categories', 'admin_page': 'categories'})

@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
def api_categories(request):
    if request.method == 'GET':
        categories = Category.objects.all().order_by('order')
        data = []
        for c in categories:
            data.append({
                'id': c.id,
                'name': c.name,
                'group': c.group,
                'description': c.description,
                'slug': c.slug,
                'is_active': c.is_active,
                'order': c.order,
                'nominee_count': c.nominees.count()
            })
        return JsonResponse({'success': True, 'categories': data})
    
    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            action = data.get('action')
            
            if action == 'add':
                category = Category.objects.create(
                    name=data.get('name'),
                    group=data.get('group'),
                    description=data.get('description', ''),
                    is_active=True
                )
                return JsonResponse({'success': True, 'message': 'Category added!', 'id': category.id})
            
            elif action == 'edit':
                category = get_object_or_404(Category, id=data.get('id'))
                category.name = data.get('name')
                category.group = data.get('group')
                category.description = data.get('description', '')
                category.is_active = data.get('is_active', True)
                category.save()
                return JsonResponse({'success': True, 'message': 'Category updated!'})
            
            elif action == 'delete':
                category = get_object_or_404(Category, id=data.get('id'))
                category.delete()
                return JsonResponse({'success': True, 'message': 'Category deleted!'})
            
            return JsonResponse({'success': False, 'message': 'Invalid action'}, status=400)
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)

# ============================================================
# ADMIN: GALLERY
# ============================================================

@login_required
@user_passes_test(is_admin_user)
def admin_gallery(request):
    return render(request, 'admin_dashboard.html', {'page_title': 'Gallery', 'admin_page': 'gallery'})

@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
def api_gallery(request):
    if request.method == 'GET':
        images = GalleryImage.objects.all().order_by('order')
        data = []
        for img in images:
            data.append({
                'id': img.id,
                'title': img.title,
                'image_url': img.image.url,
                'description': img.description,
                'featured': img.featured,
                'order': img.order
            })
        return JsonResponse({'success': True, 'images': data})
    
    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            action = data.get('action')
            
            if action == 'delete':
                image = get_object_or_404(GalleryImage, id=data.get('id'))
                image.delete()
                return JsonResponse({'success': True, 'message': 'Image deleted!'})
            
            return JsonResponse({'success': False, 'message': 'Invalid action'}, status=400)
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)

@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
def api_gallery_upload(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)
    
    try:
        title = request.POST.get('title', 'Untitled')
        description = request.POST.get('description', '')
        featured = request.POST.get('featured') == 'on'
        
        if 'image' not in request.FILES:
            return JsonResponse({'success': False, 'message': 'No image provided'}, status=400)
        
        image = GalleryImage.objects.create(
            title=title,
            image=request.FILES['image'],
            description=description,
            featured=featured
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Image uploaded!',
            'id': image.id,
            'image_url': image.image.url,
            'title': image.title
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

# ============================================================
# ADMIN: NEWS
# ============================================================

@login_required
@user_passes_test(is_admin_user)
def admin_news(request):
    return render(request, 'admin_dashboard.html', {'page_title': 'News', 'admin_page': 'news'})

@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
def api_news(request):
    if request.method == 'GET':
        articles = NewsArticle.objects.all().order_by('-published_date')
        data = []
        for a in articles:
            data.append({
                'id': a.id,
                'title': a.title,
                'slug': a.slug,
                'excerpt': a.excerpt,
                'content': a.content,
                'tag': a.tag,
                'image_url': a.image.url if a.image else None,
                'published': a.published,
                'featured': a.featured,
                'published_date': a.published_date.strftime('%Y-%m-%d')
            })
        return JsonResponse({'success': True, 'articles': data})
    
    elif request.method == 'POST':
        try:
            if request.content_type and 'multipart' in request.content_type:
                action = request.POST.get('action')
                title = request.POST.get('title')
                excerpt = request.POST.get('excerpt', '')
                content = request.POST.get('content', '')
                tag = request.POST.get('tag', 'Announcement')
                published = request.POST.get('published') == 'on'
            else:
                data = json.loads(request.body)
                action = data.get('action')
                title = data.get('title')
                excerpt = data.get('excerpt', '')
                content = data.get('content', '')
                tag = data.get('tag', 'Announcement')
                published = data.get('published', True)
            
            if action == 'add':
                article = NewsArticle.objects.create(
                    title=title,
                    excerpt=excerpt,
                    content=content,
                    tag=tag,
                    published=published
                )
                if request.FILES and 'image' in request.FILES:
                    article.image = request.FILES['image']
                    article.save()
                return JsonResponse({'success': True, 'message': 'Article added!', 'id': article.id})
            
            elif action == 'edit':
                article_id = request.POST.get('id') if request.content_type and 'multipart' in request.content_type else data.get('id')
                article = get_object_or_404(NewsArticle, id=article_id)
                article.title = title
                article.excerpt = excerpt
                article.content = content
                article.tag = tag
                article.published = published
                if request.FILES and 'image' in request.FILES:
                    article.image = request.FILES['image']
                article.save()
                return JsonResponse({'success': True, 'message': 'Article updated!'})
            
            elif action == 'delete':
                article_id = request.POST.get('id') if request.content_type and 'multipart' in request.content_type else data.get('id')
                article = get_object_or_404(NewsArticle, id=article_id)
                article.delete()
                return JsonResponse({'success': True, 'message': 'Article deleted!'})
            
            return JsonResponse({'success': False, 'message': 'Invalid action'}, status=400)
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)

# ============================================================
# ADMIN: HALL OF FAME
# ============================================================

@login_required
@user_passes_test(is_admin_user)
def admin_hall_of_fame(request):
    return render(request, 'admin_dashboard.html', {'page_title': 'Hall of Fame', 'admin_page': 'hall-of-fame'})

@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
def api_hall_of_fame(request):
    if request.method == 'GET':
        entries = HallOfFame.objects.all().order_by('-year')
        data = []
        for e in entries:
            data.append({
                'id': e.id,
                'year': e.year,
                'name': e.name,
                'category': e.category,
                'photo_url': e.photo.url if e.photo else None,
                'description': e.description
            })
        return JsonResponse({'success': True, 'entries': data})
    
    elif request.method == 'POST':
        try:
            if request.content_type and 'multipart' in request.content_type:
                action = request.POST.get('action')
                name = request.POST.get('name')
                year = request.POST.get('year')
                category = request.POST.get('category')
                description = request.POST.get('description', '')
            else:
                data = json.loads(request.body)
                action = data.get('action')
                name = data.get('name')
                year = data.get('year')
                category = data.get('category')
                description = data.get('description', '')
            
            if action == 'add':
                entry = HallOfFame.objects.create(
                    year=year,
                    name=name,
                    category=category,
                    description=description
                )
                if request.FILES and 'photo' in request.FILES:
                    entry.photo = request.FILES['photo']
                    entry.save()
                return JsonResponse({'success': True, 'message': 'Entry added!', 'id': entry.id})
            
            elif action == 'edit':
                entry_id = request.POST.get('id') if request.content_type and 'multipart' in request.content_type else data.get('id')
                entry = get_object_or_404(HallOfFame, id=entry_id)
                entry.year = year
                entry.name = name
                entry.category = category
                entry.description = description
                if request.FILES and 'photo' in request.FILES:
                    entry.photo = request.FILES['photo']
                entry.save()
                return JsonResponse({'success': True, 'message': 'Entry updated!'})
            
            elif action == 'delete':
                entry_id = request.POST.get('id') if request.content_type and 'multipart' in request.content_type else data.get('id')
                entry = get_object_or_404(HallOfFame, id=entry_id)
                entry.delete()
                return JsonResponse({'success': True, 'message': 'Entry deleted!'})
            
            return JsonResponse({'success': False, 'message': 'Invalid action'}, status=400)
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)

# ============================================================
# ADMIN: VOTES
# ============================================================

@login_required
@user_passes_test(is_admin_user)
def admin_votes(request):
    return render(request, 'admin_dashboard.html', {'page_title': 'Votes', 'admin_page': 'votes'})

@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
def api_votes_admin(request):
    if request.method == 'GET':
        votes = Vote.objects.select_related('nominee', 'category').all().order_by('-created_at')
        data = []
        for v in votes[:100]:
            data.append({
                'id': v.id,
                'nominee': v.nominee.name,
                'category': v.category.name,
                'voter_phone': v.voter_phone,
                'voter_name': v.voter_name,
                'amount': float(v.amount),
                'status': v.payment_status,
                'created_at': v.created_at.strftime('%Y-%m-%d %H:%M')
            })
        return JsonResponse({'success': True, 'votes': data})
    
    return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)

# ============================================================
# ADMIN: SETTINGS
# ============================================================

@login_required
@user_passes_test(is_admin_user)
def admin_settings(request):
    settings_obj = SiteSettings.objects.first()
    if not settings_obj:
        settings_obj = SiteSettings.objects.create()
    
    if request.method == 'POST':
        settings_obj.site_name = request.POST.get('site_name')
        settings_obj.tagline = request.POST.get('tagline')
        settings_obj.voting_open = request.POST.get('voting_open') == 'on'
        settings_obj.results_live = request.POST.get('results_live') == 'on'
        settings_obj.footer_text = request.POST.get('footer_text')
        settings_obj.save()
        messages.success(request, 'Settings saved!')
        return redirect('admin_settings')
    
    return render(request, 'admin_dashboard.html', {'settings': settings_obj, 'page_title': 'Settings', 'admin_page': 'settings'})

# ============================================================
# ADMIN: SETTINGS API
# ============================================================

@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
def api_settings(request):
    if request.method == 'GET':
        settings_obj = SiteSettings.objects.first()
        if not settings_obj:
            settings_obj = SiteSettings.objects.create()
        return JsonResponse({
            'success': True,
            'site_name': settings_obj.site_name or '',
            'tagline': settings_obj.tagline or '',
            'voting_open': settings_obj.voting_open,
            'results_live': settings_obj.results_live,
            'footer_text': settings_obj.footer_text or '',
        })
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)
    
    try:
        data = json.loads(request.body)
        settings_obj = SiteSettings.objects.first()
        if not settings_obj:
            settings_obj = SiteSettings.objects.create()
        
        if 'site_name' in data:
            settings_obj.site_name = data.get('site_name')
        if 'tagline' in data:
            settings_obj.tagline = data.get('tagline')
        if 'voting_open' in data:
            settings_obj.voting_open = data.get('voting_open')
        if 'results_live' in data:
            settings_obj.results_live = data.get('results_live')
        if 'footer_text' in data:
            settings_obj.footer_text = data.get('footer_text')
        
        settings_obj.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Settings saved!'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

# ============================================================
# ADMIN: COUNTDOWN
# ============================================================

@login_required
@user_passes_test(is_admin_user)
def admin_countdown(request):
    settings_obj = SiteSettings.objects.first()
    if not settings_obj:
        settings_obj = SiteSettings.objects.create()
    return render(request, 'admin_dashboard.html', {'settings': settings_obj, 'page_title': 'Countdown', 'admin_page': 'countdown'})

@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
def api_countdown(request):
    if request.method == 'GET':
        settings_obj = SiteSettings.objects.first()
        if not settings_obj:
            settings_obj = SiteSettings.objects.create()
        return JsonResponse({
            'success': True,
            'countdown_date': settings_obj.countdown_date.isoformat() if settings_obj.countdown_date else None,
            'countdown_label': settings_obj.countdown_label or 'The Night Begins In'
        })
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)
    
    try:
        data = json.loads(request.body)
        settings_obj = SiteSettings.objects.first()
        if not settings_obj:
            settings_obj = SiteSettings.objects.create()
        
        if 'countdown_label' in data:
            settings_obj.countdown_label = data.get('countdown_label', settings_obj.countdown_label)
        
        if 'countdown_date' in data and data.get('countdown_date'):
            try:
                if 'T' in data['countdown_date']:
                    date_str = data['countdown_date'].split('+')[0].split('.')[0]
                    if len(date_str) == 16:
                        settings_obj.countdown_date = datetime.datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
                    else:
                        settings_obj.countdown_date = datetime.datetime.fromisoformat(date_str)
                else:
                    settings_obj.countdown_date = datetime.datetime.strptime(data['countdown_date'], '%Y-%m-%d %H:%M:%S')
            except Exception as e:
                return JsonResponse({'success': False, 'message': f'Invalid date format: {str(e)}'}, status=400)
        
        settings_obj.save()
        
        return JsonResponse({
            'success': True, 
            'message': 'Countdown updated!',
            'countdown_date': settings_obj.countdown_date.isoformat() if settings_obj.countdown_date else None,
            'countdown_label': settings_obj.countdown_label
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

# ============================================================
# ADMIN: REVENUE
# ============================================================

@login_required
@user_passes_test(is_admin_user)
def admin_revenue(request):
    return render(request, 'admin_dashboard.html', {'page_title': 'Revenue', 'admin_page': 'revenue'})