from django.contrib.auth.decorators import login_required
from datetime import date,timedelta
from django.db.models import Sum
from django.shortcuts import render , redirect, get_object_or_404
from .models import *
from .utils import get_member_status
from django.http import JsonResponse
from django.contrib import messages
from datetime import datetime
from django.views.decorators.http import require_POST
from django.utils import timezone
from accounts.models import User
from accounts.decorators import owner_required, owner_or_trainer
from frontend.invoice_utils import generate_invoice_number
import calendar
from django.db.models.functions import ExtractMonth
from calendar import month_name
from django.core.files.base import ContentFile
import base64
from django.conf import settings
from django.db.models import Sum, Max, OuterRef, Subquery, DecimalField, Value ,Q
from django.db.models.functions import Coalesce
from django.db.models import F, Value, DecimalField, ExpressionWrapper, Q
from django.db.models.functions import Coalesce, Greatest
from . import backup
from django.contrib.auth import get_user_model
from django.contrib.auth import update_session_auth_hash
from django.utils.dateparse import parse_date

from io import BytesIO
from decimal import Decimal
import os

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.db.models import Sum, Max
from django.db.models.functions import Coalesce

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont



import pandas as pd
from decimal import Decimal
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone

User = get_user_model()

# Checker
def can_use_whatsapp(gym):
    return gym.subscription_type in ["pro"]

@login_required
@require_POST
def owner_reset_password(request):
    if getattr(request.user, "role", "") not in ["ADMIN", "OWNER"]:
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    new_password = (request.POST.get("password") or "").strip()
    confirm_password = (request.POST.get("confirm_password") or "").strip()

    if len(new_password) < 6:
        return JsonResponse({"success": False, "error": "Password must be at least 6 characters"}, status=400)

    if new_password != confirm_password:
        return JsonResponse({"success": False, "error": "Passwords do not match"}, status=400)

    request.user.set_password(new_password)
    request.user.save(update_fields=["password"])

    # ✅ IMPORTANT: prevents auto logout after password change
    update_session_auth_hash(request, request.user)

    return JsonResponse({"success": True})




@login_required
def reset_user_password(request, user_id):

    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid request"}, status=400)

    # Only owner/admin allowed
    if request.user.role != "ADMIN":
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    gym = request.user.gym
    user = User.objects.filter(id=user_id, gym=gym).first()

    if not user:
        return JsonResponse({"success": False, "error": "User not found"})

    new_password = request.POST.get("password")

    if not new_password:
        return JsonResponse({"success": False, "error": "Password required"})

    user.set_password(new_password)
    user.save(update_fields=["password"])

    return JsonResponse({"success": True})

from django.db.models.functions import Cast, Substr
from django.db.models import Max, IntegerField

def generate_admission_number(gym):
    start_number = gym.admission_start_number or 1

    max_number = (
        Member.objects
        .filter(gym=gym, admission_number__startswith="ADM-")
        .annotate(
            num=Cast(Substr("admission_number", 5), IntegerField())
        )
        .aggregate(max_num=Max("num"))["max_num"]
    )

    # If no members exist → use gym start number
    if max_number is None:
        new_number = start_number
    else:
        # ALWAYS continue from actual DB max
        new_number = max(max_number + 1, start_number)

    return f"ADM-{new_number:04d}"

def update_admission_settings(request):
    if request.method == "POST":
        gym = request.user.gym
        start_number = request.POST.get("admission_start_number")

        if not start_number:
            messages.error(request, "Please enter a starting number")
            return redirect("settings_page")

        try:
            start_number = int(start_number)
        except ValueError:
            messages.error(request, "Invalid number")
            return redirect("settings_page")

        if start_number < 1:
            messages.error(request, "Start number must be greater than 0")
            return redirect("settings_page")

        # 🔥 NO BLOCKING (Advanced system allows change)
        gym.admission_start_number = start_number
        gym.save()

        messages.success(
            request,
            "Admission start number updated. System will auto-adjust next numbers safely."
        )
        return redirect("gym_profile")

    return redirect("gym_profile")

def update_member_statuses(gym):
    today = timezone.localdate()
    days = gym.expiry_reminder_days_before or 7
    alert_limit = today + timedelta(days=7)
    expiring_limit = today + timedelta(days=days)

    # Expired
    Member.objects.filter(
        gym=gym,
        expiry_date__lt=today
    ).exclude(status="expired").update(status="expired")

    # Expiring Soon
    Member.objects.filter(
        gym=gym,
        expiry_date__gte=today,
        expiry_date__lte=expiring_limit
    ).exclude(status="expiring").update(status="expiring")

    # Active
    Member.objects.filter(
        gym=gym,
        expiry_date__gt=expiring_limit
    ).exclude(status="active").update(status="active")


def _month_range(any_day: date):
    """Return (start_date, end_date) inclusive for that month."""
    start = any_day.replace(day=1)
    last_day = calendar.monthrange(any_day.year, any_day.month)[1]
    end = any_day.replace(day=last_day)
    return start, end


def _last_month_any_day(today: date):
    """Return a date inside last month."""
    if today.month == 1:
        return date(today.year - 1, 12, 1)
    return date(today.year, today.month - 1, 1)

def dashboard_stats(request):
    gym = request.user.gym
    today = timezone.localdate()
    days = gym.expiry_reminder_days_before or 7
    expiring_limit_days = days
    expiring_to = today + timedelta(days=expiring_limit_days)

    range_key = (request.GET.get("range") or "current").lower()  # current/last/all
    branch_id = (request.GET.get("branch") or "").strip()
    chart_year = int(request.GET.get("year") or today.year)      # ✅ for charts

    # -----------------------------
    # Base querysets (always gym-scoped)
    # -----------------------------
    members_qs = Member.objects.filter(gym=gym,is_deleted=False).select_related("branch", "plan")
    payments_qs = Payment.objects.filter(gym=gym).select_related("member", "member__branch", "plan")

    # Branch filter (optional)
    if branch_id:
        members_qs = members_qs.filter(branch_id=branch_id)
        payments_qs = payments_qs.filter(member__branch_id=branch_id)

    # -----------------------------
    # Range filter for revenue + "new members" + "renewals count"
    # -----------------------------
    if range_key == "current":
        start, end = _month_range(today)
        payments_range = payments_qs.filter(payment_date__gte=start, payment_date__lte=end)
        new_members_qs = members_qs.filter(join_date__gte=start, join_date__lte=end)

    elif range_key == "last":
        last_month_day = _last_month_any_day(today)
        start, end = _month_range(last_month_day)
        payments_range = payments_qs.filter(payment_date__gte=start, payment_date__lte=end)
        new_members_qs = members_qs.filter(join_date__gte=start, join_date__lte=end)

    else:  # all
        payments_range = payments_qs
        new_members_qs = members_qs

    # -----------------------------
    # Member status counts (ALWAYS based on today)
    # -----------------------------
    total_members = members_qs.count()

    expired_qs = members_qs.filter(expiry_date__lt=today)
    expiring_qs = members_qs.filter(expiry_date__gte=today, expiry_date__lte=expiring_to)
    active_qs = members_qs.filter(expiry_date__gt=expiring_to)

    expired_count = expired_qs.count()
    expiring_count = expiring_qs.count()
    active_count = active_qs.count()

    # -----------------------------
    # Revenue + payment mode split (range based)
    # -----------------------------
    revenue = payments_range.aggregate(total=Sum("amount"))["total"] or 0
    cash_total = payments_range.filter(payment_mode="cash").aggregate(total=Sum("amount"))["total"] or 0
    upi_total = payments_range.filter(payment_mode="upi").aggregate(total=Sum("amount"))["total"] or 0

    renewals_count = payments_range.count()
    new_members_count = new_members_qs.count()

    # -----------------------------
    # Tables (Top 10)
    # -----------------------------
    expiring_list = []
    for m in expiring_qs.order_by("expiry_date")[:10]:
        days_left = (m.expiry_date - today).days
        expiring_list.append({
            "id": m.id,
            "name": m.name,
            "phone": m.phone,
            "branch": m.branch.name if m.branch else "",
            "expiry": m.expiry_date.strftime("%Y-%m-%d"),
            "days_left": days_left,
        })

    expired_list = []
    for m in expired_qs.order_by("-expiry_date")[:10]:
        days_over = (today - m.expiry_date).days
        expired_list.append({
            "id": m.id,
            "name": m.name,
            "phone": m.phone,
            "branch": m.branch.name if m.branch else "",
            "expiry": m.expiry_date.strftime("%Y-%m-%d"),
            "days_over": days_over,
        })

    recent_renewals = []
    for p in payments_range.order_by("-payment_date", "-id")[:10]:
        recent_renewals.append({
            "payment_id": p.id,
            "member_id": p.member_id,
            "name": p.member.name if p.member else "",
            "phone": p.member.phone if p.member else "",
            "branch": p.member.branch.name if (p.member and p.member.branch) else "",
            "amount": float(p.amount or 0),
            "mode": p.payment_mode,
            "date": p.payment_date.strftime("%Y-%m-%d") if p.payment_date else "",
            "invoice_no": getattr(p, "invoice_no", "") or "",
        })

    branches = list(Branch.objects.filter(gym=gym).values("id", "name").order_by("name"))

    # -----------------------------
    # ✅ CHARTS (Jan-Dec) + Cash/UPI (year based)
    # -----------------------------
    payments_year = payments_qs.filter(payment_date__year=chart_year)

    month_rows = (
        payments_year
        .annotate(m=ExtractMonth("payment_date"))
        .values("m")
        .annotate(total=Sum("amount"))
        .order_by("m")
    )

    month_map = {r["m"]: float(r["total"] or 0) for r in month_rows}
    chart_labels = [month_name[i][:3] for i in range(1, 13)]
    chart_totals = [month_map.get(i, 0) for i in range(1, 13)]

    chart_cash = payments_year.filter(payment_mode="cash").aggregate(t=Sum("amount"))["t"] or 0
    chart_upi  = payments_year.filter(payment_mode="upi").aggregate(t=Sum("amount"))["t"] or 0
        # -----------------------------
# ✅ Security Deposit totals (range based)
# -----------------------------
    security_deposit_total = new_members_qs.aggregate(
        t=Coalesce(
            Sum("security_deposit"),
            Value(0),
            output_field=DecimalField(max_digits=10, decimal_places=2),
        )
    )["t"]
    
    # ✅ Total income = plan payments + deposits (range based)
    total_income = (revenue or 0) + (security_deposit_total or 0)


    return JsonResponse({
        "success": True,
        "range": range_key,
        "branch_id": branch_id,
        "expiring_limit_days": expiring_limit_days,

        "cards": {
            "total_members": total_members,
            "active_members": active_count,
            "expiring_members": expiring_count,
            "expired_members": expired_count,
            "revenue": float(revenue),
            "security_deposit_total": float(security_deposit_total),   # ✅ separate
            "total_income": float(total_income),
            "cash_total": float(cash_total),
            "upi_total": float(upi_total),
            "new_members": new_members_count,
            "renewals": renewals_count,
            # "pending_total": float(pending_total),
            # "pending_members": pending_members_count,
        },

        "tables": {
            "expiring_list": expiring_list,
            "expired_list": expired_list,
            "recent_renewals": recent_renewals,
        },

        # ✅ charts included
        "charts": {
            "year": chart_year,
            "labels": chart_labels,
            "month_totals": chart_totals,
            "cash": float(chart_cash),
            "upi": float(chart_upi),
        },

        "branches": branches,
        
    })
    
@login_required
@owner_or_trainer
def dashboard_charts(request):
    gym = request.user.gym
    year = int(request.GET.get("year", date.today().year))
    branch_id = request.GET.get("branch", "")

    payments = Payment.objects.filter(gym=gym, payment_date__year=year)

    if branch_id:
        payments = payments.filter(member__branch_id=branch_id)

    # --------- Month wise collection ----------
    month_rows = (
        payments
        .annotate(m=ExtractMonth("payment_date"))
        .values("m")
        .annotate(total=Sum("amount"))
        .order_by("m")
    )

    month_map = {r["m"]: float(r["total"] or 0) for r in month_rows}

    labels = [month_name[i][:3] for i in range(1, 13)]
    month_totals = [month_map.get(i, 0) for i in range(1, 13)]

    # --------- Cash vs UPI split ----------
    cash_total = payments.filter(payment_mode="cash").aggregate(t=Sum("amount"))["t"] or 0
    upi_total  = payments.filter(payment_mode="upi").aggregate(t=Sum("amount"))["t"] or 0

    return JsonResponse({
        "labels": labels,
        "month_totals": month_totals,
        "cash": float(cash_total),
        "upi": float(upi_total),
        "year": year,
    })    
    
    
    
    

@login_required
@owner_required
def dashboard(request):
    today = date.today()
    gym = request.user.gym
    update_member_statuses(gym)
    members = Member.objects.filter(gym=gym)

    active_count = 0
    expiring_count = 0
    expired_count = 0

    for m in members:
        status = get_member_status(m.expiry_date)
        if status == 'active':
            active_count += 1
        elif status == 'expired':
            expired_count += 1
        elif status == 'expiring':
            expiring_count += 1
        else:
            expired_count += 1

    today_expiring = members.filter(expiry_date=today)

    monthly_collection = Payment.objects.filter(
        gym=gym,
        payment_date__month=today.month,
        payment_date__year=today.year
    ).aggregate(total=Sum('amount'))['total'] or 0

    context = {
        'total_members': members.count(),
        'active_count': active_count,
        'expiring_count': expiring_count,
        'expired_count': expired_count,
        'today_expiring': today_expiring,
        'monthly_collection': monthly_collection,
    }
    print(context)
    return render(request, 'dashboard.html', context)

from decimal import Decimal

def _to_decimal(value, default="0"):
    try:
        return Decimal(str(value).strip())
    except Exception:
        return Decimal(default)
@login_required
@owner_or_trainer
def Add_members(request):
    gym = request.user.gym

    if request.method == "GET":
        branches = Branch.objects.filter(gym=gym).values("name", "id")
        return render(request, "Add_members.html", {"branches": branches})
    # -------------------------
    # POST DATA
    # -------------------------
    name = (request.POST.get("name") or "").strip()
    phone = (request.POST.get("phone") or "").strip()
    branch_id = request.POST.get("branch")
    plan_id = request.POST.get("plan")

    dob = request.POST.get("date_of_birth")  # safer naming
    join_date_str = request.POST.get("join_date")
    start_date_str = request.POST.get("Start_date")

    payment_method = (request.POST.get("Payment_method") or "").strip()

    paid_amount_raw = request.POST.get("paid_amount")
    paid_amount = _to_decimal(paid_amount_raw, default="0")

    discount_amount = _to_decimal(request.POST.get("discount_amount"), default="0")
    discount_reason = (request.POST.get("discount_reason") or "").strip()
    referral_name = (request.POST.get("referral_name") or "").strip()

    advance_amount = _to_decimal(request.POST.get("security_deposit"), default="0")

    # -------------------------
    # VALIDATIONS
    # -------------------------
    branch = get_object_or_404(Branch, id=branch_id, gym=gym)
    plan = get_object_or_404(MembershipPlan, id=plan_id, branch=branch, is_active=True)

    # Dates
    try:
        join_date = datetime.strptime(join_date_str, "%Y-%m-%d").date()
    except Exception:
        messages.error(request, "Invalid Join Date")
        return redirect("Add_members")

    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else join_date
    except Exception:
        messages.error(request, "Invalid Start Date")
        return redirect("Add_members")

    expiry_date = start_date + timedelta(days=plan.duration_days - 1)

    # Duplicate phone
    if Member.objects.filter(gym=gym, phone=phone).exists():
        messages.error(request, "Phone number already exists!")
        return redirect("Add_members")

    # -------------------------
    # PHOTO HANDLING (UPDATED)
    # -------------------------
    photo_file = None
    photo = request.FILES.get("photo")   # ✅ direct file
    photo_base64 = request.POST.get("captured_photo")
    
    if photo:
        # ✅ BEST: use file directly (fast + small size)
        photo_file = photo
    
    elif photo_base64:
        try:
            format, imgstr = photo_base64.split(";base64,")
            ext = format.split("/")[-1]
    
            photo_file = ContentFile(
                base64.b64decode(imgstr),
                name=f"member_{phone}.{ext}"
            )
        except Exception:
            messages.error(request, "Invalid captured image")
            return redirect("Add_members")

    # -------------------------
    # FINANCIAL LOGIC
    # -------------------------
    plan_price = Decimal(plan.price)

    if discount_amount < 0:
        messages.error(request, "Discount cannot be negative")
        return redirect("Add_members")

    if discount_amount > plan_price:
        messages.error(request, "Discount exceeds plan price")
        return redirect("Add_members")

    final_amount = plan_price - discount_amount

    # If empty → full payment
    if paid_amount_raw in (None, "", "None"):
        paid_amount = final_amount

    if paid_amount < 0:
        messages.error(request, "Paid amount cannot be negative")
        return redirect("Add_members")

    if paid_amount > final_amount:
        messages.error(request, "Paid exceeds final amount")
        return redirect("Add_members")

    pending = final_amount - paid_amount
    
    
    # ------------------------
    # admission_number 
    # ------------------------

    admission_number = request.POST.get("admission_number")

    if not admission_number:
        admission_number = generate_admission_number(gym)

    # -------------------------
    # CREATE MEMBER
    # -------------------------
    member = Member.objects.create(
        gym=gym,
        admission_number=admission_number,
        branch=branch,
        name=name.capitalize(),
        phone=phone,
        join_date=join_date,
        plan=plan,
        start_date=start_date,
        expiry_date=expiry_date,
        photo=photo_file,
        security_deposit=advance_amount,
        DOB=dob if dob else None
    )

    # -------------------------
    # CREATE PAYMENT
    # -------------------------
    inv = generate_invoice_number(gym)

    if paid_amount > 0:
        Payment.objects.create(
            gym=gym,
            member=member,
            plan=plan,
            amount=paid_amount,
            payment_mode=payment_method,
            payment_date=timezone.localdate(),
            coverage_start=start_date,
            coverage_end=expiry_date,
            invoice_no=inv,
            plan_price=plan_price,
            discount_amount=discount_amount,
            discount_reason=discount_reason,
            referral_name=referral_name,
            final_amount=final_amount,
            created_by=request.user,
        )

    # -------------------------
    # WHATSAPP MESSAGE
    # -------------------------
    msg = (
        f"Thank You for choosing {gym} 💪\n\n"
        f"Hello {member.name} 👋\n"
        f"✅ Member Added Successfully!\n\n"
        f"🧾 Receipt No: {inv}\n"
        f"📦 Plan: {plan.name}\n"
        f"💰 Plan Amount: ₹{plan_price}\n"
        f"🏷️ Discount: ₹{discount_amount}\n"
        f"✅ Final Amount: ₹{final_amount}\n"
        f"💵 Paid Now: ₹{paid_amount}\n"
        f"⚠️ Pending: ₹{pending}\n"
        f"💳 Method: {payment_method}\n"
        f"📅 Validity: {start_date} → {expiry_date}\n"
        f"💼 Security Deposit: ₹{advance_amount}"
    )

    whatsapp_url = f"https://wa.me/91{member.phone}?text={quote(msg)}"

    request.session["whatsapp_url"] = whatsapp_url
    request.session["invoice_id"] = inv

    messages.success(request, "Member added successfully ✅")
    return redirect("member_list")

# For Getting the Baranch based Planes and Price.
@login_required
@owner_or_trainer
def get_plan(request):
    gym = request.user.gym
    branch_id = request.GET.get("branch_id")

    plans = MembershipPlan.objects.filter(
        branch_id=branch_id,
        branch__gym=gym,
        is_active=True
    ).values("id", "name", "price", "duration_days")

    return JsonResponse(list(plans), safe=False)

# Members List
@login_required
@owner_or_trainer
def member_list(request):
    
    whatsapp_url = request.session.pop("whatsapp_url", None)
    invoice_id = request.session.pop("invoice_id", None)

    gym = request.user.gym
    update_member_statuses(gym)

    # 🔍 Get filters from request
    search = request.GET.get("q", "")
    branch = request.GET.get("branch", "")
    status = request.GET.get("status", "")

    members = Member.objects.select_related(
        "branch", "plan"
    ).filter(
        gym=gym,
        is_deleted=False
    )

    # 🔍 Search filter
    if search:
        members = members.filter(
            Q(name__icontains=search) |
            Q(phone__icontains=search) |
            Q(admission_number__icontains=search)
        )

    # 🏢 Branch filter
    if branch:
        members = members.filter(branch__id=branch)

    # 📊 Status filter
    if status:
        members = members.filter(status__iexact=status)

    members = members.only(
        "id", "name", "phone", "join_date",
        "expiry_date", "status", "photo",
        "branch__name", "plan__name","admission_number"
    ).order_by("-id")

    # 🔽 Send branches for dropdown
    branches = gym.branches.all()
    
    return render(request, "List_members.html", {
        "members": members,
        "branches": branches,
        "q": search,
        "branch": branch,
        "status": status,
        "whatsapp_url": whatsapp_url,
        "invoice_id": invoice_id
    })
    

@login_required
@owner_or_trainer
def plans(request):
    gym = request.user.gym

    search = request.GET.get("q")
    branch = request.GET.get("branch")
    status = request.GET.get("status")
    duration = request.GET.get("duration")

    plans = MembershipPlan.objects.filter(
        branch__gym=gym
    ).select_related("branch")

    # Filters
    if search:
        plans = plans.filter(
            Q(name__icontains=search) |
            Q(branch__name__icontains=search)
        )

    if branch:
        plans = plans.filter(branch_id=branch)

    if status:
        plans = plans.filter(is_active=(status == "Active"))

    if duration:
        plans = plans.filter(duration_days=duration)  # ✅ FIX FIELD NAME

    # ✅ FIX: unique + ordered durations
    durations = (
        MembershipPlan.objects
        .filter(branch__gym=gym)
        .values_list("duration_days", flat=True)
        .distinct()
        .order_by("duration_days")
    )
    branches = gym.branches.all()
    return render(request, "Planes.html", {
        "plans": plans,
        "durations": durations,
        "branches":branches
    })
    
    
@login_required
@owner_required
def Add_plan(request):
    gym = request.user.gym
    if request.method == "GET":
        add_new = Branch.objects.filter(gym__name=gym).values("id","name")
        return render(request, "Add_plan.html",{"add_new":add_new})
    
    if request.method == "POST":
        branch_id = request.POST.get("branch")
        name = (request.POST.get("Plan_name") or "").strip()
        duration = request.POST.get("Plan_duration")
        price = request.POST.get("Plan_amount")

        # ✅ validate branch belongs to this gym
        branch = get_object_or_404(Branch, id=branch_id, gym=gym)

        # ✅ basic validations
        if not name:
            messages.error(request, "Plan name is required.")
            return redirect("Add_plan")

        # try:
        #     start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        #     end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        # except Exception:
        #     messages.error(request, "Please select valid start and end dates.")
        #     return redirect("Add_plan")

        # if end_date < start_date:
        #     messages.error(request, "End date must be after start date.")
        #     return redirect("Add_plan")

        # duration_days = (end_date - start_date).days + 1  # inclusive

        # ✅ prevent duplicate plan name in same branch
        if MembershipPlan.objects.filter(branch=branch, name__iexact=name).exists():
            messages.error(request, "This plan name already exists for the selected branch.")
            return redirect("Add_plan")

        # ✅ create plan
        MembershipPlan.objects.create(
            branch=branch,
            name=name,
            duration_days=duration,
            price=price,
            is_active=True,
        )

        messages.success(request, "Plan created successfully!")
        return redirect("Add_plan")
    

    return render(request, "add_plan.html", {"add_new": add_new})
        
        
@login_required
@require_POST
@owner_required
def toggle_plan(request, pk):
    gym = request.user.gym

    # ✅ only allow toggling plans under logged-in user's gym
    plan = get_object_or_404(
        MembershipPlan,
        id=pk,
        branch__gym=gym
    )
    
    is_active_str = request.POST.get("is_active", "").lower()
    print(is_active_str,f"{pk}")
    plan.is_active = is_active_str in ["true", "1", "on", "yes"]
    plan.save(update_fields=["is_active"])

    return JsonResponse({"success": True, "is_active": plan.is_active})
        

@login_required
def plan_data(request, pk):
    gym = request.user.gym

    plan = get_object_or_404(
        MembershipPlan,
        id=pk,
        branch__gym=gym
    )

    data = {
        "branch_id": plan.branch.id,
        "name": plan.name,
        "duration_days":plan.duration_days,
        "start_date": plan.start_date.strftime("%Y-%m-%d") if plan.start_date else "",
        "end_date": plan.end_date.strftime("%Y-%m-%d") if plan.end_date else "",
        "price": str(plan.price),
    }
    print(pk)
    return JsonResponse(data)

@owner_required
def update_plan(request, pk):
    gym = request.user.gym

    plan = get_object_or_404(
        MembershipPlan,
        id=pk,
        branch__gym=gym
    )

    if request.method == "POST":
        branch_id = request.POST.get("branch")
        name = request.POST.get("Plan_name")
        start = request.POST.get("Start_date")
        end = request.POST.get("End_date")
        price = request.POST.get("Plan_amount")
        duration = request.POST.get("Plan_duration")
        branch = get_object_or_404(Branch, id=branch_id, gym=gym)

        plan.branch = branch
        plan.name = name
        plan.duration_days=duration
        plan.price = price
        plan.save()

        return JsonResponse({"success": True})
        

@owner_required
def delete_plan(request, pk):
    gym = request.user.gym

    plan = get_object_or_404(
        MembershipPlan,
        id=pk,
        branch__gym=gym
    )
    plan.delete()
    return JsonResponse({"success": True})

@login_required
@owner_required
def delete_member(request, pk):
    gym = request.user.gym

    member = get_object_or_404(
        Member,
        id=pk,
        gym=gym
    )
    member.is_deleted = True
    member.save()
    print("save")
    return JsonResponse({"success": True})


@login_required
@owner_or_trainer
def Member_data(request, pk):
    gym = request.user.gym

    member = get_object_or_404(Member, id=pk, gym=gym)

    data = {
        "ids": member.id,
        "name": member.name,
        "phone": member.phone,
        "dob": member.DOB.strftime("%Y-%m-%d") if member.DOB else "",
        "photo": member.photo.url if member.photo else ""
    }

    return JsonResponse(data)
@owner_or_trainer
def update_member(request, pk):
    gym = request.user.gym
    member = get_object_or_404(Member, id=pk, gym=gym)

    if request.method == "POST":

        name = (request.POST.get("member_name") or "").strip().capitalize()
        phone = (request.POST.get("Phone_number") or "").strip()
        dob = request.POST.get("date_of_birth")

        if not name or not phone:
            return JsonResponse({"success": False, "error": "Name and phone required"})

        if Member.objects.filter(phone=phone, gym=gym).exclude(id=member.id).exists():
            return JsonResponse({"success": False, "error": "Phone already exists"})

        # -------------------------
        # PHOTO UPDATE (NEW)
        # -------------------------
        photo = request.FILES.get("photo")
        photo_base64 = request.POST.get("captured_photo")

        if photo:
            # ✅ BEST (fast + safe)
            member.photo = photo

        elif photo_base64:
            try:
                fmt, imgstr = photo_base64.split(";base64,")
                ext = fmt.split("/")[-1]

                member.photo = ContentFile(
                    base64.b64decode(imgstr),
                    name=f"member_{member.id}.{ext}"
                )
            except:
                return JsonResponse({"success": False, "error": "Invalid image"})

        # -------------------------
        # UPDATE FIELDS
        # -------------------------
        member.name = name
        member.phone = phone
        member.DOB = dob if dob else None

        member.save()

        return JsonResponse({"success": True})

    return JsonResponse({"success": False})

# @owner_or_trainer
# def member_full_details(request, pk):
#     gym = request.user.gym

#     member = get_object_or_404(
#         Member.objects.select_related("branch", "plan", "gym"),
#         id=pk,
#         gym=gym
#     )

#     payments_qs = (
#         Payment.objects
#         .filter(gym=gym, member=member)
#         .select_related("plan", "created_by")  # ✅ include created_by if you want to display
#         .order_by("-payment_date", "-id")
#     )

#     money = DecimalField(max_digits=12, decimal_places=2)

#     # ✅ Summary aggregation (safe for decimals)
#     agg = payments_qs.aggregate(
#         total_paid=Coalesce(Sum("amount"), Value(Decimal("0.00")), output_field=money),
#         total_discount=Coalesce(Sum("discount_amount"), Value(Decimal("0.00")), output_field=money),
#         total_final=Coalesce(Sum("final_amount"), Value(Decimal("0.00")), output_field=money),
#     )

#     total_paid = agg["total_paid"] or Decimal("0.00")
#     total_discount = agg["total_discount"] or Decimal("0.00")
#     total_final = agg["total_final"] or Decimal("0.00")

#     payments = []
#     last_payment_date = None

#     for p in payments_qs:
#         if last_payment_date is None and p.payment_date:
#             last_payment_date = p.payment_date

#         payments.append({
#             "id": p.id,
#             "amount": float(p.amount or 0),
#             "invoice_no": p.invoice_no,
#             "payment_mode": p.payment_mode,
#             "payment_mode_label": p.get_payment_mode_display(),
#             "payment_date": p.payment_date.strftime("%Y-%m-%d") if p.payment_date else None,

#             "coverage_start": p.coverage_start.strftime("%Y-%m-%d") if p.coverage_start else None,
#             "coverage_end": p.coverage_end.strftime("%Y-%m-%d") if p.coverage_end else None,

#             "plan_id": p.plan_id,
#             "plan_name": p.plan.name if p.plan else None,
#             "plan_price": float(p.plan_price or (p.plan.price if p.plan else 0) or 0),

#             # ✅ NEW: Discount details
#             "discount_amount": float(p.discount_amount or 0),
#             "final_amount": float(p.final_amount or 0),
#             "discount_reason": p.discount_reason,
#             "referral_name": p.referral_name,

#             # ✅ NEW: who gave discount/payment
#             "created_by_id": p.created_by_id,
#             "created_by_name": (
#                 (p.created_by.first_name or p.created_by.username)
#                 if p.created_by else None
#             ),
#             "created_by_role": (getattr(p.created_by, "role", None) if p.created_by else None),
#         })

#     data = {
#         "member": {
#             "id": member.id,
#             "name": member.name,
#             "phone": member.phone,
#             "join_date": member.join_date.strftime("%Y-%m-%d") if member.join_date else None,

#             "status": member.status,
#             "status_label": member.get_status_display(),

#             "gym_id": member.gym_id,
#             "gym_name": member.gym.name if member.gym else None,

#             "branch_id": member.branch_id,
#             "branch_name": member.branch.name if member.branch else None,

#             "plan_id": member.plan_id,
#             "plan_name": member.plan.name if member.plan else None,
#             "plan_duration_days": member.plan.duration_days if member.plan else None,
#             "plan_price": float(member.plan.price) if member.plan else None,

#             "start_date": member.start_date.strftime("%Y-%m-%d") if member.start_date else None,
#             "expiry_date": member.expiry_date.strftime("%Y-%m-%d") if member.expiry_date else None,
#         },
#         "payments": payments,
#         "summary": {
#             "payments_count": payments_qs.count(),
#             "total_paid": float(total_paid),
#             "total_discount": float(total_discount),         # ✅ NEW
#             "total_final_amount": float(total_final),       # ✅ NEW (after discount)
#             "last_payment_date": last_payment_date.strftime("%Y-%m-%d") if last_payment_date else None,
#         }
#     }

#     return JsonResponse(data)


@owner_or_trainer
def member_full_details(request, pk):
    gym = request.user.gym

    member = get_object_or_404(
        Member.objects.select_related("branch", "plan", "gym"),
        id=pk,
        gym=gym
    )

    payments_qs = (
        Payment.objects
        .filter(
            gym=gym,
            member=member,

        )
        .select_related("plan", "created_by")
        .order_by("-payment_date", "-id")
    )

    money = DecimalField(max_digits=12, decimal_places=2)

    agg = payments_qs.aggregate(
        total_paid=Coalesce(Sum("amount"), Value(Decimal("0.00")), output_field=money),
        total_discount=Coalesce(Max("discount_amount"), Value(Decimal("0.00")), output_field=money),
        total_final=Coalesce(Max("final_amount"), Value(Decimal("0.00")), output_field=money),
    )

    total_paid = agg["total_paid"] or Decimal("0.00")
    total_discount = agg["total_discount"] or Decimal("0.00")
    total_final = agg["total_final"] or Decimal("0.00")

    total_pending = total_final - total_paid
    if total_pending < 0:
        total_pending = Decimal("0.00")

    first_payment = payments_qs.first()
    last_payment_date = first_payment.payment_date if first_payment and first_payment.payment_date else None

    payments = []
    for p in payments_qs:
        payments.append({
            "id": p.id,
            "amount": float(p.amount or 0),
            "invoice_no": p.invoice_no,
            "payment_mode": p.payment_mode,
            "payment_mode_label": p.get_payment_mode_display(),
            "payment_date": p.payment_date.strftime("%Y-%m-%d") if p.payment_date else None,

            "coverage_start": p.coverage_start.strftime("%Y-%m-%d") if p.coverage_start else None,
            "coverage_end": p.coverage_end.strftime("%Y-%m-%d") if p.coverage_end else None,

            "plan_id": p.plan_id,
            "plan_name": p.plan.name if p.plan else None,
            "plan_price": float(p.plan_price or (p.plan.price if p.plan else 0) or 0),

            "discount_amount": float(p.discount_amount or 0),
            "final_amount": float(p.final_amount or 0),
            "discount_reason": p.discount_reason,
            "referral_name": p.referral_name,

            "created_by_id": p.created_by_id,
            "created_by_name": (
                (p.created_by.first_name or p.created_by.username)
                if p.created_by else None
            ),
            "created_by_role": (getattr(p.created_by, "role", None) if p.created_by else None),
        })

    data = {
        "member": {
            "id": member.id,
            "name": member.name,
            "phone": member.phone,
            "join_date": member.join_date.strftime("%Y-%m-%d") if member.join_date else None,

            "status": member.status,
            "status_label": member.get_status_display(),

            "gym_id": member.gym_id,
            "gym_name": member.gym.name if member.gym else None,

            "branch_id": member.branch_id,
            "branch_name": member.branch.name if member.branch else None,

            "plan_id": member.plan_id,
            "plan_name": member.plan.name if member.plan else None,
            "plan_duration_days": member.plan.duration_days if member.plan else None,
            "plan_price": float(member.plan.price) if member.plan else None,

            "start_date": member.start_date.strftime("%Y-%m-%d") if member.start_date else None,
            "expiry_date": member.expiry_date.strftime("%Y-%m-%d") if member.expiry_date else None,
        },
        "payments": payments,
        "summary": {
            "payments_count": payments_qs.count(),
            "total_paid": float(total_paid),
            "total_discount": float(total_discount),
            "total_final_amount": float(total_final),
            "total_pending": float(total_pending),
            "last_payment_date": last_payment_date.strftime("%Y-%m-%d") if last_payment_date else None,
        }
    }
    print(data)

    return JsonResponse(data)

# Renewval Payment:
from urllib.parse import quote

@login_required
@owner_or_trainer
def renew_member_plan(request, pk):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Method not allowed"}, status=405)

    gym = request.user.gym
    member = get_object_or_404(Member, id=pk, gym=gym)

    plan_id = (request.POST.get("plan_id") or "").strip()
    payment_mode = (request.POST.get("payment_mode") or "").strip()  # 'cash'/'upi'

    # manual start date for renewal
    manual_select_raw = (request.POST.get("renew_Plane_current_expiry") or "").strip()
    try:
        manual_select = datetime.strptime(manual_select_raw, "%Y-%m-%d").date()
    except Exception:
        return JsonResponse({"success": False, "message": "Invalid start date"}, status=400)

    selected_plan = get_object_or_404(MembershipPlan, id=plan_id, branch=member.branch)

    # ---- Discount inputs ----
    discount_amount = _to_decimal(request.POST.get("discount_amount"), default="0")
    discount_reason = (request.POST.get("discount_reason") or "").strip()
    referral_name = (request.POST.get("referral_name") or "").strip()

    # ---- Paid input (keep raw to detect empty) ----
    paid_amount_raw = request.POST.get("paid_amount")
    paid_amount = _to_decimal(paid_amount_raw, default="0")

    # ---- Plan price + expiry ----
    plan_price = Decimal(selected_plan.price)
    coverage_start = manual_select
    coverage_end = coverage_start + timedelta(days=selected_plan.duration_days - 1)

    # ---- Validations ----
    if payment_mode not in ["cash", "upi"]:
        return JsonResponse({"success": False, "message": "Invalid payment mode"}, status=400)

    if discount_amount < 0:
        return JsonResponse({"success": False, "message": "Discount cannot be negative"}, status=400)

    if discount_amount > plan_price:
        return JsonResponse({"success": False, "message": "Discount cannot exceed plan amount"}, status=400)

    final_amount = plan_price - discount_amount  # payable after discount

    # ✅ If paid_amount left EMPTY => full final amount
    if paid_amount_raw in (None, "", "None"):
        paid_amount = final_amount

    if paid_amount < 0:
        return JsonResponse({"success": False, "message": "Paid amount cannot be negative"}, status=400)

    if paid_amount > final_amount:
        return JsonResponse({"success": False, "message": "Paid amount cannot exceed final amount"}, status=400)

    pending = final_amount - paid_amount

    inv = generate_invoice_number(gym)

    # ✅ Save payment (even if 0 you can skip; I keep only if >0)
    if paid_amount > 0:
        Payment.objects.create(
            gym=gym,
            member=member,
            plan=selected_plan,
            amount=paid_amount,
            payment_mode=payment_mode,
            payment_date=timezone.localdate(),
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            invoice_no=inv,

            # ✅ Discount fields (important)
            plan_price=plan_price,
            discount_amount=discount_amount,
            discount_reason=discount_reason,
            referral_name=referral_name,
            final_amount=final_amount,   # payable after discount
            created_by=request.user,
        )
    else:
        # optional: if you want a record even when paid=0, remove this else
        pass

    # ✅ Update member plan cycle
    member.plan = selected_plan
    member.start_date = coverage_start
    member.expiry_date = coverage_end
    member.status = "active"
    member.save()

    # WhatsApp message
    msg = (
        f"Thank You for choosing {gym} 💪\n\n"
        f"Hello {member.name} 👋\n"
        f"✅ Plan Renewed Successfully!\n\n"
        f"🧾 Receipt No: {inv}\n"
        f"📦 Plan: {selected_plan.name}\n"
        f"💰 Plan Amount: ₹{plan_price}\n"
        f"🏷️ Discount: ₹{discount_amount}\n"
        f"✅ Final Amount: ₹{final_amount}\n"
        f"💵 Paid Now: ₹{paid_amount}\n"
        f"⚠️ Pending: ₹{pending}\n"
        f"💳 Method: {payment_mode}\n"
        f"📅 Validity: {coverage_start} → {coverage_end}\n"
        f"Thank you 💪"
    )

    whatsapp_url = f"https://wa.me/91{member.phone}?text={quote(msg)}"

    return JsonResponse({
        "success": True,
        "invoice_no": inv,
        "coverage_start": str(coverage_start),
        "coverage_end": str(coverage_end),
        "plan_name": selected_plan.name,
        "final_amount": str(final_amount),
        "discount_amount": str(discount_amount),
        "pending": str(pending),
        "whatsapp_url": whatsapp_url,
        
    })
    
    
@login_required
@owner_or_trainer
def branch_plans(request, pk):
    gym = request.user.gym

    branch = get_object_or_404(Branch, id=pk, gym=gym)

    plans = MembershipPlan.objects.filter(
        branch=branch,
        is_active=True
    ).order_by("duration_days")

    data = [
        {
            "id": p.id,
            "name": p.name,
            "duration_days": p.duration_days,
            "price": float(p.price),
        }
        for p in plans
    ]

    return JsonResponse(data, safe=False)


@login_required
@owner_or_trainer
def renewals_page(request):
    gym = request.user.gym
    update_member_statuses(gym)
    today = timezone.localdate()

    # filters
    q = request.GET.get("q", "").strip()
    branch_id = request.GET.get("branch", "").strip()

    # dropdown value should be: active / expiring / expired / all
    status = request.GET.get("status", "expiring").strip()

    # base queryset
    members = Member.objects.filter(gym=gym , is_deleted=False).select_related("branch", "plan")

    # search by name OR phone
    if q:
        members = members.filter(
            Q(name__icontains=q) |
            Q(phone__icontains=q) |
            Q(admission_number__icontains=q)
        )

    # branch filter
    if branch_id:
        members = members.filter(branch_id=branch_id)

    # expiring window
    days = gym.expiry_reminder_days_before or 7
    expiring_limit = today + timedelta(days=days)

    # filter by status (based on expiry_date = source of truth)
    if status == "expired":
        members = members.filter(expiry_date__lt=today)
    elif status == "expiring":
        members = members.filter(expiry_date__gte=today, expiry_date__lte=expiring_limit)
    elif status == "active":
        members = members.filter(expiry_date__gt=expiring_limit)
    elif status == "all":
        pass

    branches = Branch.objects.filter(gym=gym).order_by("name")

    context = {
        "members": members.order_by("expiry_date"),
        "branches": branches,
        "q": q,
        "branch_id": branch_id,
        "status": status,
        "today": today,
        "expiring_limit": expiring_limit,
    }
    print(context)

    return render(request, "renewals.html", context)



@login_required
@owner_or_trainer
def paid_members_page(request):
    gym = request.user.gym

    today = date.today()
    month = int(request.GET.get("month", today.month))
    year = int(request.GET.get("year", today.year))

    q = request.GET.get("q", "").strip()
    branch_id = request.GET.get("branch", "").strip()

    # Base payments for month/year
    payments = (
        Payment.objects
        .filter(gym=gym, payment_date__year=year, payment_date__month=month)
        .select_related("member", "member__branch")
    )

    if branch_id:
        payments = payments.filter(member__branch_id=branch_id)

    if q:
        payments = payments.filter(
            Q(member__name__icontains=q) |
            Q(member__phone__icontains=q) |
            Q(member__admission_number__icontains=q)  # ✅ NEW
        )

    # ✅ Aggregate by member (one row per member)
    member_totals = (
    payments
    .values("member_id")
    .annotate(
        total_paid=Coalesce(
            Sum("amount"),
            Value(0),
            output_field=DecimalField(max_digits=8, decimal_places=2)
        ),
        last_payment=Max("payment_date"),
    )
)

    # Subquery to attach totals to each member
    total_paid_sq = Subquery(
        member_totals.filter(member_id=OuterRef("pk")).values("total_paid")[:1]
    )
    last_payment_sq = Subquery(
        member_totals.filter(member_id=OuterRef("pk")).values("last_payment")[:1]
    )

    # ✅ Get members list with photo.url available
    members_qs = (
        Member.objects
        .filter(gym=gym, payments__in=payments, is_deleted=False)
        .select_related("branch", "plan")
        .distinct()
        .annotate(
            total_paid=total_paid_sq,
            last_payment=last_payment_sq,
        )
        .order_by("-total_paid", "name")
    )

    total_collection = payments.aggregate(total=Sum("amount"))["total"] or 0
    branches = Branch.objects.filter(gym=gym).order_by("name")

    context = {
        "paid_members": members_qs,   # ✅ now each item is a Member object
        "branches": branches,
        "q": q,
        "branch_id": branch_id,
        "month": month,
        "year": year,
        "total_collection": total_collection,
    }
    return render(request, "paid_members.html", context)

@login_required
@owner_or_trainer
def unpaid_members_page(request):
    gym = request.user.gym
    today = timezone.localdate()
    days = gym.expiry_reminder_days_before or 7
    alert_limit = today + timedelta(days=days)

    q = request.GET.get("q", "").strip()
    branch_id = request.GET.get("branch", "").strip()
    status = request.GET.get("status", "all").strip()   # expired / expiring / all

    members = Member.objects.filter(
        gym=gym,
        expiry_date__lte=alert_limit,  # includes expiring + expired
        is_deleted=False
    ).select_related("branch", "plan")

    if q:
        members = members.filter(
            Q(name__icontains=q) |
            Q(phone__icontains=q) |
            Q(admission_number__icontains=q)
        )

    if branch_id:
        members = members.filter(branch_id=branch_id)

    # status filter inside unpaid window
    if status == "expired":
        members = members.filter(expiry_date__lt=today)
    elif status == "expiring":
        members = members.filter(expiry_date__gte=today, expiry_date__lte=alert_limit)

    branches = Branch.objects.filter(gym=gym).order_by("name")

    context = {
        "members": members.order_by("expiry_date"),
        "branches": branches,
        "q": q,
        "branch_id": branch_id,
        "status": status,
        "today": today,
        "alert_limit": alert_limit,
    }
    return render(request, "unpaid_members.html", context)

@login_required
@owner_required
def gym_profile(request):
    gym = request.user.gym

    branches = Branch.objects.filter(gym=gym).order_by("name")
    trainers = User.objects.filter(gym=gym, role="TRAINER").select_related("branch").order_by("first_name", "username")
    invoice_setting, _ = InvoiceSettings.objects.get_or_create(
        gym=gym,
        defaults={"prefix": "INV", "next_number": 1001, "padding": 4}
    )
    return render(request, "gym_profile.html", {
        "gym": gym,
        "branches": branches,
        "trainers": trainers,
         "invoice_setting": invoice_setting
    })


@require_POST
@owner_required
@login_required
def create_branch(request):
    if request.user.gym.plan_type == "single":
        return JsonResponse({"Error": "Upgrade the Plan"})
    
    if request.user.role != "ADMIN":
        return JsonResponse({"success": False, "message": "Not allowed"})
    gym = request.user.gym
    name = request.POST.get("name", "").strip()
    address = request.POST.get("address", "").strip()
    phone = request.POST.get("phone", "").strip()

    if not name:
        return JsonResponse({"success": False, "message": "Branch name is required"})

    Branch.objects.create(gym=gym, name=name, address=address, phone=phone)
    return JsonResponse({"success": True})


@require_POST
@login_required
@owner_required
def create_trainer(request):
    if request.user.role != "ADMIN":
        return JsonResponse({"success": False, "message": "Not allowed"})

    gym = request.user.gym

    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "").strip()
    full_name = request.POST.get("name", "").strip()
    phone = request.POST.get("phone", "").strip()
    branch_id = request.POST.get("branch_id", "").strip()

    if not username or not password:
        return JsonResponse({"success": False, "message": "Username & Password required"})

    if User.objects.filter(username=username).exists():
        return JsonResponse({"success": False, "message": "Username already exists"})

    first_name = full_name
    branch = None
    if branch_id:
        branch = get_object_or_404(Branch, id=branch_id, gym=gym)

    trainer = User.objects.create_user(
        username=username,
        password=password,
        first_name=first_name,
    )
    trainer.gym = gym
    trainer.role = "TRAINER"
    trainer.branch = branch
    trainer.save()

    return JsonResponse({"success": True})


@require_POST
@login_required
@owner_required
def assign_trainer_branch(request, pk):
    if request.user.role != "ADMIN":
        return JsonResponse({"success": False, "message": "Not allowed"})

    gym = request.user.gym
    trainer = get_object_or_404(User, id=pk, gym=gym, role="TRAINER")

    branch_id = request.POST.get("branch_id", "").strip()

    if not branch_id:
        trainer.branch = None
        trainer.save()
        return JsonResponse({"success": True})

    branch = get_object_or_404(Branch, id=branch_id, gym=gym)
    trainer.branch = branch
    trainer.save()

    return JsonResponse({"success": True})


@require_POST
@login_required
@owner_required
def toggle_trainer(request, pk):
    if request.user.role != "ADMIN":
        return JsonResponse({"success": False, "message": "Not allowed"})

    gym = request.user.gym
    trainer = get_object_or_404(User, id=pk, gym=gym, role="TRAINER")
    trainer.is_active = not trainer.is_active
    trainer.save()
    return JsonResponse({"success": True, "is_active": trainer.is_active})


@require_POST
@login_required
@owner_required
def update_trainer(request, pk):
    if request.user.role != "ADMIN":
        return JsonResponse({"success": False, "message": "Not allowed"})

    gym = request.user.gym
    trainer = get_object_or_404(User, id=pk, gym=gym, role="TRAINER")

    name = request.POST.get("name", "").strip()
    phone = request.POST.get("phone", "").strip()
    branch_id = request.POST.get("branch_id", "").strip()

    if name:
        trainer.first_name = name

    # only if phone field exists in User model
    if hasattr(trainer, "phone"):
        trainer.phone = phone

    if branch_id:
        branch = get_object_or_404(Branch, id=branch_id, gym=gym)
        trainer.branch = branch
    else:
        trainer.branch = None

    trainer.save()
    return JsonResponse({"success": True})


@require_POST
@login_required
@owner_required
def delete_trainer(request, pk):
    if request.user.role != "ADMIN":
        return JsonResponse({"success": False, "message": "Not allowed"})

    gym = request.user.gym
    trainer = get_object_or_404(User, id=pk, gym=gym, role="TRAINER")

    # safer: don't allow deleting yourself
    if trainer.id == request.user.id:
        return JsonResponse({"success": False, "message": "You cannot delete yourself"})

    trainer.delete()
    return JsonResponse({"success": True})

@require_POST
@login_required
@owner_required
def invoice_settings_view(request):
    gym = request.user.gym
    settings, _ = InvoiceSettings.objects.get_or_create(gym=gym)

    if request.method == "POST":
        prefix = request.POST.get("prefix",settings.prefix).strip()
        next_number = int(request.POST.get("next_number", settings.next_number))
        padding = int(request.POST.get("padding", settings.padding))
        
        settings.prefix = prefix
        settings.next_number = next_number
        settings.padding = padding
        settings.save()
        print(prefix,next_number,padding)
        messages.success(request, "Invoice settings updated ✅")
        return redirect("gym_profile")

    return render(request, "invoice_settings.html", {"settings": settings})

from django.db.models import (
    Sum, Value, F, Q, OuterRef, Subquery,
    DecimalField, ExpressionWrapper
)
from django.db.models.functions import Coalesce, Greatest
@login_required
@owner_or_trainer
def pending_payments_page(request):
    gym = request.user.gym
    q = (request.GET.get("q") or "").strip()
    branch_id = (request.GET.get("branch") or "").strip()

    money = DecimalField(max_digits=10, decimal_places=2)
    zero = Value(Decimal("0.00"))

    # Base queryset
    members_qs = (
        Member.objects
        .filter(gym=gym, plan__isnull=False)
        .select_related("plan", "branch")
    )

    # ✅ SEARCH FILTER
    if q:
        members_qs = members_qs.filter(
            Q(name__icontains=q) |
            Q(phone__icontains=q) |
            Q(admission_number__icontains=q)
        )

    # ✅ BRANCH FILTER
    if branch_id:
        members_qs = members_qs.filter(branch_id=branch_id)

    # ✅ Paid Subquery
    paid_subq = (
        Payment.objects
        .filter(
            gym=gym,
            member_id=OuterRef("pk"),
            coverage_start=OuterRef("start_date"),
            coverage_end=OuterRef("expiry_date"),
        )
        .values("member_id")
        .annotate(s=Coalesce(Sum("amount"), zero))
        .values("s")[:1]
    )

    # ✅ Discount Subquery
    discount_subq = (
        Payment.objects
        .filter(
            gym=gym,
            member_id=OuterRef("pk"),
            coverage_start=OuterRef("start_date"),
            coverage_end=OuterRef("expiry_date"),
        )
        .values("member_id")
        .annotate(d=Coalesce(Max("discount_amount"), zero))
        .values("d")[:1]
    )

    # ✅ Final calculations
    members_qs = (
        members_qs
        .annotate(
            plan_price=Coalesce(F("plan__price"), zero),
            paid_total=Coalesce(Subquery(paid_subq), zero),
            discount_amount=Coalesce(Subquery(discount_subq), zero),
        )
        .annotate(
            final_amount=Greatest(F("plan_price") - F("discount_amount"), zero),
            balance=Greatest(F("final_amount") - F("paid_total"), zero),
        )
        .filter(balance__gt=0)
        .order_by("-balance", "name")
    )

    # Convert to template-friendly list
    pending_list = [
        {
            "member_id": m.id,
            "name": m.name,
            "phone": m.phone,
            "admission": m.admission_number,
            "branch": m.branch.name if m.branch else "",
            "plan": m.plan.name if m.plan else "",
            "plan_price": m.plan_price,
            "paid": m.paid_total,
            "balance": m.balance,
            "photo": m.photo.url if m.photo else "",
        }
        for m in members_qs
    ]

    branches = Branch.objects.filter(gym=gym).order_by("name")

    total_pending = sum((x["balance"] for x in pending_list), Decimal("0.00"))

    return render(request, "pending_payments.html", {
        "pending_list": pending_list,
        "branches": branches,
        "q": q,
        "branch_id": branch_id,
        "total_pending": total_pending,
    })

from django.db import transaction
@login_required
@owner_or_trainer
def pending_payment_data(request, member_id):
    gym = request.user.gym

    member = get_object_or_404(
        Member.objects.select_related("plan"),
        id=member_id,
        gym=gym,
        # is_deleted=False
    )

    if not member.plan:
        return JsonResponse({"success": False, "error": "Member has no plan"}, status=400)

    plan_price = Decimal(member.plan.price or 0)

    cycle_qs = Payment.objects.filter(
        gym=gym,
        member=member,
        plan=member.plan,
        coverage_start=member.start_date,
        coverage_end=member.expiry_date
    )

    agg = cycle_qs.aggregate(
        total_paid=Coalesce(Sum("amount"), Decimal("0.00")),
        discount=Coalesce(Max("discount_amount"), Decimal("0.00")),
    )

    total_paid = Decimal(agg["total_paid"] or 0)
    discount = Decimal(agg["discount"] or 0)

    final_amount = plan_price - discount
    if final_amount < 0:
        final_amount = Decimal("0.00")

    balance = final_amount - total_paid
    if balance < 0:
        balance = Decimal("0.00")

    return JsonResponse({
        "success": True,
        "member": {
            "id": member.id,
            "name": member.name,
            "phone": member.phone,
        },
        "plan": {
            "name": member.plan.name,
            "price": float(plan_price),
            "start_date": member.start_date.strftime("%Y-%m-%d") if member.start_date else None,
            "expiry_date": member.expiry_date.strftime("%Y-%m-%d") if member.expiry_date else None,
        },
        "payments": {
            "total_paid": float(total_paid),
            "discount": float(discount),
            "final_amount": float(final_amount),
            "balance": float(balance),
        }
    })

@login_required
@owner_or_trainer
def pending_payment_pay(request, member_id):

    gym = request.user.gym
    
    member = get_object_or_404(
        Member.objects.select_related("plan"),
        id=member_id,
        gym=gym,
       
    )

    if not member.plan:
        return JsonResponse({"success": False, "error": "Member has no plan"}, status=400)

    amount_str = (request.POST.get("amount") or "").strip()
    payment_mode = (request.POST.get("payment_mode") or "").strip()

    if amount_str == "" or payment_mode not in ["cash", "upi"]:
        return JsonResponse({"success": False, "error": "Invalid amount or payment mode"}, status=400)

    try:
        amount = Decimal(amount_str)
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid amount"}, status=400)

    if amount <= 0:
        return JsonResponse({"success": False, "error": "Amount must be > 0"}, status=400)

    plan_price = Decimal(member.plan.price)

    cycle_qs = Payment.objects.filter(
        gym=gym,
        member=member,
        plan=member.plan,
        coverage_start=member.start_date,
        coverage_end=member.expiry_date
    )

    agg = cycle_qs.aggregate(
        total_paid=Coalesce(Sum("amount"), Decimal("0")),
        discount=Coalesce(Max("discount_amount"), Decimal("0")),
    )

    total_paid = Decimal(agg["total_paid"] or 0)
    discount = Decimal(agg["discount"] or 0)

    final_amount = plan_price - discount
    if final_amount < 0:
        final_amount = Decimal("0")

    balance = final_amount - total_paid
    if balance < 0:
        balance = Decimal("0")

    if amount > balance:
        return JsonResponse(
            {"success": False, "error": f"Amount exceeds balance ₹{balance}"},
            status=400
        )

    inv = generate_invoice_number(gym)

    with transaction.atomic():
        Payment.objects.create(
            gym=gym,
            member=member,
            plan=member.plan,
            amount=amount,
            payment_mode=payment_mode,
            payment_date=timezone.localdate(),
            coverage_start=member.start_date,
            coverage_end=member.expiry_date,
            invoice_no=inv,
            discount_amount=discount,
            final_amount=final_amount,
            created_by=request.user
            
        )

    new_total_paid = total_paid + amount
    new_balance = final_amount - new_total_paid
    if new_balance < 0:
        new_balance = Decimal("0")
        
        
    msg = (
        f"Thank You for choosing {gym.name} 💪\n\n"
        f"Hello {member.name} 👋\n"
        f"✅ Payment Received Successfully!\n\n"
        f"🧾 Receipt No: {inv}\n"
        f"📦 Plan: {member.plan.name}\n"
        f"💰 Plan Amount: ₹{plan_price}\n"
        f"🏷️ Discount: ₹{discount}\n"
        f"✅ Final Amount: ₹{final_amount}\n"
        f"💵 Paid Now: ₹{amount}\n"
        f"⚠️ Pending: ₹{new_balance}\n"
        f"💳 Method: {payment_mode.upper()}\n"
        f"📅 Validity: {member.start_date} → {member.expiry_date}\n\n"
        f"Thank you 💪"
    )

    whatsapp_url = f"https://wa.me/91{member.phone}?text={quote(msg)}"
   
    
    return JsonResponse({
        "success": True,
        "invoice_no": inv,
        "plan_price": float(plan_price),
        "discount": float(discount),
        "final_amount": float(final_amount),
        "total_paid": float(new_total_paid),
        "balance": float(new_balance),
        "whatsapp_url": whatsapp_url,
    })
    
    
@login_required
@owner_or_trainer
def discount_report(request):
    gym = request.user.gym

    q = (request.GET.get("q") or "").strip()
    branch_id = (request.GET.get("branch") or "").strip()
    created_by_id = (request.GET.get("created_by") or "").strip()
    start = (request.GET.get("start") or "").strip()
    end = (request.GET.get("end") or "").strip()

    qs = (
        Payment.objects
        .filter(gym=gym, discount_amount__gt=0)
        .select_related("member", "member__branch", "plan", "created_by")
        .order_by("-payment_date", "-id")
    )

    if q:
        qs = qs.filter(Q(member__name__icontains=q) | Q(member__phone__icontains=q))

    if branch_id:
        qs = qs.filter(member__branch_id=branch_id)

    if created_by_id:
        qs = qs.filter(created_by_id=created_by_id)

    if start:
        qs = qs.filter(payment_date__gte=start)
    if end:
        qs = qs.filter(payment_date__lte=end)

    dec_out = DecimalField(max_digits=12, decimal_places=2)

    summary = qs.aggregate(
        total_discount=Coalesce(Sum("discount_amount"), Value(Decimal("0.00")), output_field=dec_out),
        total_collected=Coalesce(Sum("final_amount"), Value(Decimal("0.00")), output_field=dec_out),
    )

    branches = Branch.objects.filter(gym=gym).order_by("name")
    staff = User.objects.filter(gym=gym).order_by("role", "first_name", "username")

    context = {
        "rows": qs[:800],
        "branches": branches,
        "staff": staff,
        "filters": {
            "q": q,
            "branch": branch_id,
            "created_by": created_by_id,   # ✅ keep dropdown selected
            "start": start,
            "end": end,
        },
        "summary": {
            "total_discount": summary["total_discount"] or Decimal("0.00"),
            "total_collected": summary["total_collected"] or Decimal("0.00"),
            "total_rows": qs.count(),
        }
    }

    return render(request, "discount_report.html", context)



@login_required
def _invoice_filters_qs(request, base_qs):
    gym = request.user.gym

    q = (request.GET.get("q") or "").strip()
    branch_id = (request.GET.get("branch") or "").strip()
    created_by_id = (request.GET.get("created_by") or "").strip()
    start = (request.GET.get("start") or "").strip()
    end = (request.GET.get("end") or "").strip()

    qs = base_qs.filter(gym=gym).select_related("member", "member__branch", "plan", "created_by")

    if q:
        qs = qs.filter(
            Q(member__name__icontains=q) |
            Q(member__phone__icontains=q) |
            Q(invoice_no__icontains=q)
        )

    if branch_id:
        qs = qs.filter(member__branch_id=branch_id)

    if created_by_id:
        qs = qs.filter(created_by_id=created_by_id)

    if start:
        qs = qs.filter(payment_date__gte=start)
    if end:
        qs = qs.filter(payment_date__lte=end)

    return qs, {
        "q": q,
        "branch": branch_id,
        "created_by": created_by_id,
        "start": start,
        "end": end,
    }

@login_required
def invoices_page(request):
    # Base queryset: only invoices that have invoice_no (optional)
    base_qs = Payment.objects.exclude(invoice_no__isnull=True).exclude(invoice_no__exact="")

    qs, filters = _invoice_filters_qs(request, base_qs)
    qs = qs.order_by("-payment_date", "-id")

    branches = Branch.objects.filter(gym=request.user.gym).order_by("name")
    staff = User.objects.filter(gym=request.user.gym).order_by("role", "first_name", "username")

    context = {
        "rows": qs[:1000],  # safety limit
        "branches": branches,
        "staff": staff,
        "filters": filters,
    }
    return render(request, "invoices.html", context)



@login_required
def enquiry_page(request):
    gym = request.user.gym

    # -------- CREATE (POST) ----------
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        phone = (request.POST.get("phone") or "").strip()
        branch_id = (request.POST.get("branch") or "").strip()
        source = (request.POST.get("source") or "").strip()
        interested_plan = (request.POST.get("interested_plan") or "").strip()
        note = (request.POST.get("note") or "").strip()
        next_followup = (request.POST.get("next_followup") or "").strip()

        branch = None
        if branch_id:
            branch = get_object_or_404(Branch, id=branch_id, gym=gym)

        if not name or not phone:
            # simple validation
            return redirect("enquiry_page")

        Enquiry.objects.create(
            gym=gym,
            branch=branch,
            name=name,
            phone=phone,
            source=source or None,
            interested_plan=interested_plan or None,
            note=note or None,
            next_followup=next_followup or None,
            created_by=request.user,
        )
        return redirect("enquiry_page")

    # -------- LIST (GET) ----------
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    branch_id = (request.GET.get("branch") or "").strip()
    followup = (request.GET.get("followup") or "").strip()  # today / overdue / upcoming

    qs = (
        Enquiry.objects
        .filter(gym=gym)
        .select_related("branch", "created_by")
        .order_by("-created_at", "-id")
    )

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q))

    if status:
        qs = qs.filter(status=status)

    if branch_id:
        qs = qs.filter(branch_id=branch_id)

    today = timezone.localdate()
    if followup == "today":
        qs = qs.filter(next_followup=today).exclude(status__in=["won", "lost"])
    elif followup == "overdue":
        qs = qs.filter(next_followup__lt=today).exclude(status__in=["won", "lost"])
    elif followup == "upcoming":
        qs = qs.filter(next_followup__gt=today).exclude(status__in=["won", "lost"])

    branches = Branch.objects.filter(gym=gym).order_by("name")

    return render(request, "enquiries.html", {
        "rows": qs[:1000],
        "branches": branches,
        "filters": {
            "q": q,
            "status": status,
            "branch": branch_id,
            "followup": followup,
        },
        "status_choices": Enquiry.STATUS_CHOICES,
    })


@login_required
@owner_or_trainer
def enquiry_update(request, pk):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)

    gym = request.user.gym
    e = get_object_or_404(Enquiry, id=pk, gym=gym)

    status = (request.POST.get("status") or "").strip()
    next_followup = (request.POST.get("next_followup") or "").strip()
    note = (request.POST.get("last_followup_note") or "").strip()

    valid = {k for k, _ in Enquiry.STATUS_CHOICES}
    if status and status not in valid:
        return JsonResponse({"success": False, "error": "Invalid status"}, status=400)

    if status:
        e.status = status

    # when closed, clear followup
    if status in [Enquiry.STATUS_WON, Enquiry.STATUS_LOST]:
        e.next_followup = None
    else:
        e.next_followup = next_followup or None

    e.last_followup_note = note or None
    e.save(update_fields=["status", "next_followup", "last_followup_note"])

    return JsonResponse({"success": True})




# Whatsapp goes down
from .utils import send_interakt_template, already_sent_today,get_next_birthday

@login_required
@owner_or_trainer
def send_renewal_whatsapp(request):
    gym = request.user.gym
    today = timezone.localdate()
    days = gym.expiry_reminder_days_before or 7
    expiring_limit = today + timedelta(days=days)

    members = Member.objects.filter(
        gym=gym,
        is_deleted=False
    ).select_related("plan", "branch")

    sent_count = 0
    skipped_count = 0
    failed_count = 0

    for member in members:

        if not member.phone:
            skipped_count += 1
            continue

        if not member.plan:
            skipped_count += 1
            continue

        expiry_date = member.expiry_date

        # expired
        if expiry_date < today:

            if not gym.wa_template_expired:
                skipped_count += 1
                continue

            if already_sent_today(member, "expired"):
                skipped_count += 1
                continue

            log = send_interakt_template(
                gym=gym,
                member=member,
                template_name=gym.wa_template_expired,
                body_values=[
                    member.name,
                    gym.name,
                    expiry_date.strftime("%d-%m-%Y"),
                ],
                message_type="expired",
            )

            if log.status in ["queued", "sent", "delivered", "read"]:
                sent_count += 1
            else:
                failed_count += 1

        # expiring soon
        elif today <= expiry_date <= expiring_limit:

            if not gym.wa_template_expiring_soon:
                skipped_count += 1
                continue

            if already_sent_today(member, "expiring_soon"):
                skipped_count += 1
                continue

            log = send_interakt_template(
                gym=gym,
                member=member,
                template_name=gym.wa_template_expiring_soon,
                body_values=[
                    member.name,
                    gym.name,
                    expiry_date.strftime("%d-%m-%Y"),
                ],
                message_type="expiring_soon",
            )

            if log.status in ["queued", "sent", "delivered", "read"]:
                sent_count += 1
            else:
                failed_count += 1

    messages.success(
        request,
        f"WhatsApp done. Sent: {sent_count}, Failed: {failed_count}, Skipped: {skipped_count}"
    )

    return redirect("/renewals/")

# Birthday wish
@login_required
@owner_or_trainer
def send_birthday_whatsapp(request):
    gym = request.user.gym
    today = timezone.localdate()
    reminder_days = gym.birthday_reminder_days_before or 10
    target_date = today + timedelta(days=reminder_days)

    members = Member.objects.filter(
        gym=gym,
        is_deleted=False
    ).select_related("plan", "branch")

    sent_count = 0
    skipped_count = 0
    failed_count = 0

    for member in members:
        if not member.phone:
            skipped_count += 1
            continue

        if not member.DOB:
            skipped_count += 1
            continue

        next_birthday = get_next_birthday(member.DOB, today)

        # Exact birthday
        if next_birthday == today:
            if not gym.wa_template_birthday_today:
                skipped_count += 1
                continue

            if already_sent_today(member, "birthday_today"):
                skipped_count += 1
                continue

            log = send_interakt_template(
                gym=gym,
                member=member,
                template_name=gym.wa_template_birthday_today,
                body_values=[
                    member.name,
                    gym.name,
                ],
                message_type="birthday_today",
            )

            if log.status in ["queued", "sent", "delivered", "read"]:
                sent_count += 1
            else:
                failed_count += 1

        # 10 days before birthday
        elif next_birthday == target_date:
            if not gym.wa_template_birthday:
                skipped_count += 1
                continue

            if already_sent_today(member, "birthday_upcoming"):
                skipped_count += 1
                continue

            log = send_interakt_template(
                gym=gym,
                member=member,
                template_name=gym.wa_template_birthday,
                body_values=[
                    member.name,
                    gym.name,
                    next_birthday.strftime("%d-%m-%Y"),
                ],
                message_type="birthday_upcoming",
            )

            if log.status in ["queued", "sent", "delivered", "read"]:
                sent_count += 1
            else:
                failed_count += 1
        else:
            skipped_count += 1

    messages.success(
        request,
        f"Birthday WhatsApp done. Sent: {sent_count}, Failed: {failed_count}, Skipped: {skipped_count}"
    )
    return redirect("/renewals/")


# Whatsapp Conf
@login_required
@owner_or_trainer
def whatsapp_conf(request):
    gym = request.user.gym
    
    if request.method == "POST":

        interakt_enabled = request.POST.get("interakt_enabled") == "on"
        Auto_archive_enable= request.POST.get("Auto_archive_enable") == "on"
        template_expired = request.POST.get("wa_template_expired", "").strip()
        template_expiring = request.POST.get("wa_template_expiring_soon", "").strip()
        membership_expires_today = request.POST.get("wa_template_expires_today", "").strip()
        reminder_days = request.POST.get("expiry_reminder_days_before", "").strip()
        interakt_api_key = request.POST.get("interakt_api_key", "").strip()
        Auto_archive_In = request.POST.get("Auto_archive_In", "").strip()
        wa_template_birthday=request.POST.get("wa_template_birthday", "").strip()
        birthday_reminder_days_before=request.POST.get("birthday_reminder_days_before", "").strip()
        wa_template_birthday_today=request.POST.get("wa_template_birthday_today", "").strip()
        
        if reminder_days:
            reminder_days = int(reminder_days)
        else:
            reminder_days = 7

        gym.interakt_enabled = interakt_enabled
        gym.wa_template_expired = template_expired
        gym.wa_template_expiring_soon = template_expiring
        gym.expiry_reminder_days_before = reminder_days
        gym.interakt_api_key = interakt_api_key
        gym.wa_template_expires_today=membership_expires_today
        gym.Auto_archive_In=Auto_archive_In
        gym.Auto_archive_enable=Auto_archive_enable
        gym.wa_template_birthday =wa_template_birthday
        gym.wa_template_birthday_today=wa_template_birthday_today
        gym.expiry_reminder_days_before=birthday_reminder_days_before
        
        gym.save(update_fields=[
            "interakt_enabled",
            "wa_template_expired",
            "wa_template_expiring_soon",
            "wa_template_expires_today",
            "expiry_reminder_days_before",
            "interakt_api_key",
            "Auto_archive_In",
            "Auto_archive_enable",
            "wa_template_birthday",
            "wa_template_birthday_today",
            "expiry_reminder_days_before",
        ])

        messages.success(request, "WhatsApp & Archive configuration updated successfully.")
        return redirect("whatsapp_conf")

    context = {
        "gym": gym
    }

    return render(request, "Whatsapp_conf.html", context)


@login_required
@owner_or_trainer
def whatsapp_logs_page(request):
    gym = request.user.gym

    from_date = request.GET.get("from_date", "").strip()
    to_date = request.GET.get("to_date", "").strip()
    message_type = request.GET.get("message_type", "").strip()
    status = request.GET.get("status", "").strip()
    q = request.GET.get("q", "").strip()

    logs = WhatsAppMessageLog.objects.filter(gym=gym).select_related("member").order_by("-created_at")

    # Date filters
    if from_date:
        parsed_from = parse_date(from_date)
        if parsed_from:
            logs = logs.filter(created_at__date__gte=parsed_from)

    if to_date:
        parsed_to = parse_date(to_date)
        if parsed_to:
            logs = logs.filter(created_at__date__lte=parsed_to)

    # Optional filters
    if message_type:
        logs = logs.filter(message_type=message_type)

    if status:
        logs = logs.filter(status=status)

    if q:
        logs = logs.filter(member__name__icontains=q)

    # Summary counts
    total_messages = logs.count()
    sent_count = logs.filter(status__in=["queued", "sent", "delivered", "read"]).count()
    failed_count = logs.filter(status="failed").count()
    delivered_count = logs.filter(status="delivered").count()
    read_count = logs.filter(status="read").count()

    message_type_choices = (
        WhatsAppMessageLog.objects.filter(gym=gym)
        .values_list("message_type", flat=True)
        .distinct()
    )

    status_choices = (
        WhatsAppMessageLog.objects.filter(gym=gym)
        .values_list("status", flat=True)
        .distinct()
    )

    context = {
        "logs": logs,
        "from_date": from_date,
        "to_date": to_date,
        "message_type": message_type,
        "status": status,
        "q": q,
        "total_messages": total_messages,
        "sent_count": sent_count,
        "failed_count": failed_count,
        "delivered_count": delivered_count,
        "read_count": read_count,
        "message_type_choices": message_type_choices,
        "status_choices": status_choices,
    }
    return render(request, "whatsapp_logs.html", context)


# Download Invoice In PDF
@login_required
@owner_or_trainer
def generate_invoice_pdf(request, payment_id):
    gym = request.user.gym

    payment = get_object_or_404(
        Payment.objects.select_related("member", "plan", "gym", "created_by"),
        invoice_no=payment_id,   # keep this if your URL sends invoice_no
        gym=gym
    )

    member = payment.member
    plan = payment.plan

    # -----------------------------
    # Unicode font register
    # -----------------------------
    def register_fonts():
        candidates_regular = [
            os.path.join(settings.BASE_DIR, "static", "fonts", "DejaVuSans.ttf"),
            r"C:\Windows\Fonts\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        candidates_bold = [
            os.path.join(settings.BASE_DIR, "static", "fonts", "DejaVuSans-Bold.ttf"),
            r"C:\Windows\Fonts\arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]

        regular_path = next((p for p in candidates_regular if os.path.exists(p)), None)
        bold_path = next((p for p in candidates_bold if os.path.exists(p)), None)

        if regular_path and "GymFont" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("GymFont", regular_path))

        if bold_path and "GymFont-Bold" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("GymFont-Bold", bold_path))

    register_fonts()

    FONT_REGULAR = "GymFont" if "GymFont" in pdfmetrics.getRegisteredFontNames() else "Helvetica"
    FONT_BOLD = "GymFont-Bold" if "GymFont-Bold" in pdfmetrics.getRegisteredFontNames() else "Helvetica-Bold"

    # -----------------------------
    # Amount calculations
    # -----------------------------
    plan_price = Decimal(
        getattr(payment, "plan_price", None) or (plan.price if plan else 0) or 0
    ).quantize(Decimal("0.00"))

    cycle_qs = Payment.objects.filter(
        gym=gym,
        member=member,
        plan=plan,
        coverage_start=payment.coverage_start,
        coverage_end=payment.coverage_end,
    )

    agg = cycle_qs.aggregate(
    total_paid=Coalesce(Sum("amount"), Decimal("0.00")),
    discount=Coalesce(Max("discount_amount"), Decimal("0.00")),
    )

    total_paid = Decimal(agg["total_paid"] or 0).quantize(Decimal("0.00"))
    discount = Decimal(agg["discount"] or 0).quantize(Decimal("0.00"))

    final_amount = (plan_price - discount).quantize(Decimal("0.00"))
    if final_amount < 0:
        final_amount = Decimal("0.00")

    pending_amount = (final_amount - total_paid).quantize(Decimal("0.00"))
    if pending_amount < 0:
        pending_amount = Decimal("0.00")

    paid_now = Decimal(payment.amount or 0).quantize(Decimal("0.00"))

    # -----------------------------
    # PDF setup
    # -----------------------------
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    primary = HexColor("#0f172a")
    accent = HexColor("#f59e0b")
    accent_soft = HexColor("#fef3c7")
    border = HexColor("#d1d5db")
    muted = HexColor("#64748b")
    light_bg = HexColor("#f8fafc")
    success_bg = HexColor("#dcfce7")
    success_text = HexColor("#166534")
    danger_bg = HexColor("#fee2e2")
    danger_text = HexColor("#991b1b")

    left = 18 * mm
    right = width - 18 * mm

    def money(val):
        return f"₹{Decimal(val).quantize(Decimal('0.00'))}"

    def draw_text(x, y, text, size=10, font=FONT_REGULAR, color=black):
        p.setFont(font, size)
        p.setFillColor(color)
        p.drawString(x, y, str(text))

    def draw_right(x, y, text, size=10, font=FONT_REGULAR, color=black):
        p.setFont(font, size)
        p.setFillColor(color)
        p.drawRightString(x, y, str(text))

    def draw_center(x, y, text, size=10, font=FONT_REGULAR, color=black):
        p.setFont(font, size)
        p.setFillColor(color)
        p.drawCentredString(x, y, str(text))

    def box(x, y, w, h, fill=None, stroke=1, stroke_color=border, radius=6):
        p.setStrokeColor(stroke_color)
        if fill:
            p.setFillColor(fill)
        p.roundRect(x, y, w, h, radius, stroke=stroke, fill=1 if fill else 0)

    # -----------------------------
    # Header
    # -----------------------------
    box(left, height - 42 * mm, right - left, 24 * mm, fill=primary, stroke=0, radius=6)
    draw_text(left + 8 * mm, height - 28 * mm, gym.name or "GYM", size=20, font=FONT_BOLD, color=white)
    draw_text(left + 8 * mm, height - 34 * mm, "Membership Payment Receipt", size=10, font=FONT_REGULAR, color=HexColor("#dbeafe"))

    box(right - 50 * mm, height - 36 * mm, 40 * mm, 10 * mm, fill=accent, stroke=0, radius=4)
    draw_center(right - 30 * mm, height - 32.7 * mm, "RECEIPT", size=10, font=FONT_BOLD, color=white)

    current_y = height - 52 * mm

    # -----------------------------
    # Top info cards
    # -----------------------------
    left_box_w = 84 * mm
    right_box_w = (right - left) - left_box_w - 6 * mm
    right_box_x = left + left_box_w + 6 * mm

    box(left, current_y - 28 * mm, left_box_w, 28 * mm, fill=light_bg, radius=5)
    draw_text(left + 5 * mm, current_y - 7 * mm, "Receipt Details ", size=11, font=FONT_BOLD, color=primary)
    draw_text(left + 5 * mm, current_y - 14 * mm, "Receipt No", size=9, color=muted)
    draw_right(left + left_box_w - 5 * mm, current_y - 14 * mm, payment.invoice_no or "-", size=9, font=FONT_BOLD)
    draw_text(left + 5 * mm, current_y - 20 * mm, "Receipt Date", size=9, color=muted)
    draw_right(
        left + left_box_w - 5 * mm,
        current_y - 20 * mm,
        payment.payment_date.strftime("%d-%m-%Y") if payment.payment_date else "-",
        size=9,
        font=FONT_BOLD
    )
    draw_text(left + 5 * mm, current_y - 26 * mm, "Payment Mode", size=9, color=muted)
    draw_right(
        left + left_box_w - 5 * mm,
        current_y - 26 * mm,
        payment.get_payment_mode_display() if hasattr(payment, "get_payment_mode_display") else (payment.payment_mode or "-"),
        size=9,
        font=FONT_BOLD
    )

    box(right_box_x, current_y - 28 * mm, right_box_w, 28 * mm, fill=light_bg, radius=5)
    draw_text(right_box_x + 5 * mm, current_y - 7 * mm, "Gym Details", size=11, font=FONT_BOLD, color=primary)
    draw_text(right_box_x + 5 * mm, current_y - 14 * mm, gym.name or "-", size=9)
    draw_text(right_box_x + 5 * mm, current_y - 20 * mm, gym.phone or "-", size=9)
    draw_text(right_box_x + 5 * mm, current_y - 26 * mm, gym.address or "-", size=9, color=muted)

    current_y -= 38 * mm

    # -----------------------------
    # Member + membership
    # -----------------------------
    box(left, current_y - 34 * mm, 84 * mm, 34 * mm, fill=white, radius=5)
    draw_text(left + 5 * mm, current_y - 7 * mm, "Member", size=11, font=FONT_BOLD, color=primary)
    draw_text(left + 5 * mm, current_y - 15 * mm, member.name or "-", size=10)
    draw_text(left + 5 * mm, current_y - 22 * mm, member.phone or "-", size=9, color=muted)

    validity_text = "-"
    if payment.coverage_start and payment.coverage_end:
        validity_text = f"{payment.coverage_start.strftime('%d-%m-%Y')} to {payment.coverage_end.strftime('%d-%m-%Y')}"

    box(right_box_x, current_y - 34 * mm, right_box_w, 34 * mm, fill=white, radius=5)
    draw_text(right_box_x + 5 * mm, current_y - 7 * mm, "Membership", size=11, font=FONT_BOLD, color=primary)
    draw_text(right_box_x + 5 * mm, current_y - 15 * mm, plan.name if plan else "Membership", size=10)
    draw_text(
        right_box_x + 5 * mm,
        current_y - 22 * mm,
        f"Duration: {plan.duration_days} Days" if plan and getattr(plan, "duration_days", None) else "Duration: -",
        size=9,
        color=muted
    )
    draw_text(right_box_x + 5 * mm, current_y - 29 * mm, f"Validity: {validity_text}", size=9, color=muted)

    current_y -= 44 * mm

    # -----------------------------
    # Payment summary
    # -----------------------------
    draw_text(left, current_y, "Payment Summary", size=12, font=FONT_BOLD, color=primary)
    current_y -= 6 * mm
    
    table_x = left
    table_y = current_y - 32 * mm
    table_w = right - left
    table_h = 32 * mm
    
    box(table_x, table_y, table_w, table_h, fill=white, radius=5)
    box(table_x, table_y + 24 * mm, table_w, 8 * mm, fill=accent_soft, stroke=0, radius=5)
    
    # Better-spaced column anchors
    col_item = table_x + 8 * mm
    col_desc = table_x + 38 * mm
    col_price_r = table_x + 100 * mm
    col_paid_r = table_x + 130 * mm
    col_balance_r = table_x + table_w - 10 * mm
    
    # Header
    draw_text(col_item, table_y + 27 * mm, "Item", size=9, font=FONT_BOLD, color=primary)
    draw_text(col_desc, table_y + 27 * mm, "Description", size=9, font=FONT_BOLD, color=primary)
    draw_right(col_price_r, table_y + 27 * mm, "Plan Price", size=9, font=FONT_BOLD, color=primary)
    draw_right(col_paid_r, table_y + 27 * mm, "Paid Now", size=9, font=FONT_BOLD, color=primary)
    draw_right(col_balance_r, table_y + 27 * mm, "Balance", size=9, font=FONT_BOLD, color=primary)
    
    # Row
    row_text_y = table_y + 15 * mm
    draw_text(col_item, row_text_y, "1", size=10)
    draw_text(col_desc, row_text_y, plan.name if plan else "Membership", size=10)
    draw_right(col_price_r, row_text_y, money(plan_price), size=10)
    draw_right(col_paid_r, row_text_y, money(paid_now), size=10)
    draw_right(col_balance_r, row_text_y, money(pending_amount), size=10)
    
    current_y = table_y - 10 * mm

    # -----------------------------
    # Notes + amount details
    # -----------------------------
    notes_w = 90 * mm
    totals_w = (right - left) - notes_w - 6 * mm
    totals_x = left + notes_w + 6 * mm

    box(left, current_y - 50 * mm, notes_w, 50 * mm, fill=white, radius=5)
    draw_text(left + 5 * mm, current_y - 7 * mm, "Notes", size=11, font=FONT_BOLD, color=primary)
    draw_text(
        left + 5 * mm,
        current_y - 16 * mm,
        payment.discount_reason or "Thank you for your payment. Keep training strong!",
        size=9,
        color=muted
    )

    collected_by = "-"
    if payment.created_by:
        collected_by = payment.created_by.first_name or payment.created_by.username or "-"

    draw_text(left + 5 * mm, current_y - 28 * mm, f"Collected by: {collected_by}", size=9, color=muted)

    box(totals_x, current_y - 50 * mm, totals_w, 50 * mm, fill=light_bg, radius=5)
    draw_text(totals_x + 5 * mm, current_y - 7 * mm, "Amount Details", size=11, font=FONT_BOLD, color=primary)

    line_y = current_y - 15 * mm
    draw_text(totals_x + 5 * mm, line_y, "Plan Price", size=9, color=muted)
    draw_right(totals_x + totals_w - 5 * mm, line_y, money(plan_price), size=9, font=FONT_BOLD)

    draw_text(totals_x + 5 * mm, line_y - 7 * mm, "Discount", size=9, color=muted)
    draw_right(totals_x + totals_w - 5 * mm, line_y - 7 * mm, money(discount), size=9, font=FONT_BOLD)

    draw_text(totals_x + 5 * mm, line_y - 14 * mm, "Final Amount", size=9, color=muted)
    draw_right(totals_x + totals_w - 5 * mm, line_y - 14 * mm, money(final_amount), size=9, font=FONT_BOLD)

    draw_text(totals_x + 5 * mm, line_y - 21 * mm, "Paid Now", size=9, color=muted)
    draw_right(totals_x + totals_w - 5 * mm, line_y - 21 * mm, money(paid_now), size=9, font=FONT_BOLD)

    draw_text(totals_x + 5 * mm, line_y - 28 * mm, "Pending", size=9, color=muted)
    draw_right(totals_x + totals_w - 5 * mm, line_y - 28 * mm, money(pending_amount), size=9, font=FONT_BOLD)

    current_y -= 60 * mm

    # -----------------------------
    # Status bar
    # -----------------------------
    status_fill = success_bg if pending_amount <= 0 else danger_bg
    status_text_color = success_text if pending_amount <= 0 else danger_text
    status_text = "PAID IN FULL" if pending_amount <= 0 else f"PENDING {money(pending_amount)}"

    box(left, current_y - 10 * mm, right - left, 12 * mm, fill=status_fill, stroke=0, radius=5)
    draw_center((left + right) / 2, current_y - 5.8 * mm, status_text, size=11, font=FONT_BOLD, color=status_text_color)

    # -----------------------------
    # Footer
    # -----------------------------
    sig_y = 34 * mm
    p.setStrokeColor(border)
    p.line(left, sig_y, left + 55 * mm, sig_y)
    p.line(right - 55 * mm, sig_y, right, sig_y)

    draw_text(left, sig_y - 6 * mm, "Authorized By", size=9, color=muted)
    draw_right(right, sig_y - 6 * mm, "Member Signature", size=9, color=muted)
    draw_center(width / 2, 18 * mm, "Thank you for choosing our gym!", size=10, font=FONT_BOLD, color=primary)

    p.showPage()
    p.save()

    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="receipt_{payment.invoice_no or payment.id}.pdf"'
    return response



# Inactive Members
@login_required
@owner_or_trainer
def archived_members(request):
    gym = request.user.gym

    q = request.GET.get("q", "").strip()
    month = request.GET.get("month", "").strip()
    year = request.GET.get("year", "").strip()

    base_qs = Member.objects.filter(
        gym=gym,
        is_deleted=True
    ).select_related("plan", "branch")

    members = base_qs

    # Search by name or phone
    if q:
        members = members.filter(
            Q(name__icontains=q) |
            Q(phone__icontains=q)
        )

    # Filter by month
    if month:
        members = members.filter(created_at__month=month)

    # Filter by year
    if year:
        members = members.filter(created_at__year=year)

    members = members.order_by("-created_at")

    # Get available years for dropdown from archived members
    years = (
        base_qs.exclude(created_at__isnull=True)
        .dates("created_at", "year", order="DESC")
    )

    return render(request, "archived_members.html", {
        "members": members,
        "q": q,
        "month": month,
        "year": year,
        "years": years,
    })

# activate Members
@login_required
@owner_or_trainer
def restore_member(request, member_id):
    gym = request.user.gym
    member = get_object_or_404(Member, id=member_id, gym=gym, is_deleted=True)

    member.is_deleted = False
    member.save(update_fields=["is_deleted"])

    messages.success(request, f"{member.name} restored successfully.")
    return redirect("archived_members")

import numpy as np
def clean_value(val):
    if pd.isna(val):
        return None
    if isinstance(val, (pd.Timestamp, )):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    return str(val).strip()

def safe_date(val):
    val = pd.to_datetime(val, errors="coerce")
    return val.strftime("%Y-%m-%d") if pd.notna(val) else None

# Bulk Importing

@login_required
@login_required
def preview_members_excel(request):
    gym = request.user.gym

    if request.method == "POST":
        excel_file = request.FILES.get("excel_file")

        if not excel_file:
            messages.error(request, "Upload Excel file")
            return redirect("preview_members_excel")

        # Important for phone numbers
        df = pd.read_excel(excel_file, dtype={"phone": str})

        preview_data = []

        for index, row in df.iterrows():

            name = clean_value(row.get("name"))
            Admission = clean_value(row.get("Admission"))
            phone = clean_value(row.get("phone"))
            branch_name = clean_value(row.get("branch"))
            plan_name = clean_value(row.get("plan"))

            plan_price = clean_value(row.get("plan_price"))
            discount = clean_value(row.get("discount"))
            paid_amount = clean_value(row.get("paid_amount"))
            payment_mode = clean_value(row.get("payment_mode"))

            error = None
            date_of_birth = safe_date(row.get("Dob"))
            join_date = safe_date(row.get("join_date"))
            start_date = safe_date(row.get("start_date"))
            expiry_date = safe_date(row.get("expiry_date"))

            # Check duplicate phone
            if Member.objects.filter(gym=gym, phone=phone).exists():
                error = "Phone already exists"

            # Validate branch
            try:
                branch = Branch.objects.get(name=branch_name, gym=gym)
            except Branch.DoesNotExist:
                branch = None
                error = "Invalid Branch"

            # Validate plan
            if branch:
                try:
                    plan = MembershipPlan.objects.get(name=plan_name, branch=branch)
                except MembershipPlan.DoesNotExist:
                    plan = None
            else:
                plan = None

            preview_data.append({
                "row": index + 1,
                "Admission": Admission,
                "name": name,
                "Dob":date_of_birth,
                "phone": phone,
                "branch": branch_name,
                "plan": plan_name,
                "join_date": join_date,
                "start_date": start_date,
                "expiry_date": expiry_date,
                "plan_price": plan_price,
                "discount": discount,
                "paid_amount": paid_amount,
                "payment_mode": payment_mode,
                "error": error
            })

        # Store safe data in session
        request.session["import_data"] = preview_data

        return render(request, "import_preview.html", {"data": preview_data})

    return redirect("gym_profile")


@login_required
def confirm_import_members(request):
    gym = request.user.gym
    data = request.session.get("import_data")

    if not data:
        messages.error(request, "No import data found")
        return redirect("member_list")

    created = 0

    for row in data:

        # 🔥 Normalize keys (VERY IMPORTANT)
        row = {k.strip(): v for k, v in row.items()}

        if row.get("error"):
            continue

        try:
            branch = Branch.objects.get(name=row.get("branch"), gym=gym)
            plan = MembershipPlan.objects.filter(
                name=row.get("plan"),
                branch=branch
            ).first()

            # -------------------------
            # ✅ ADMISSION NUMBER FIX
            # -------------------------
            admission_number = row.get("Admission")

            if not admission_number:
                admission_number = generate_admission_number(gym)

            # ❗ Prevent duplicate crash
            if Member.objects.filter(gym=gym, admission_number=admission_number).exists():
                admission_number = generate_admission_number(gym)

            # -------------------------
            # DATE PARSING
            # -------------------------
            join_date = datetime.strptime(row.get("join_date"), "%Y-%m-%d").date()
            start_date = datetime.strptime(row.get("start_date"), "%Y-%m-%d").date()
            expiry_date = datetime.strptime(row.get("expiry_date"), "%Y-%m-%d").date()
            date_of_birth = datetime.strptime(row.get("Dob"), "%Y-%m-%d").date()
            # -------------------------
            # CREATE MEMBER
            # -------------------------
            member = Member.objects.create(
                gym=gym,
                branch=branch,
                admission_number=admission_number,
                name=(row.get("name") or "").capitalize(),
                phone=row.get("phone"),
                DOB=date_of_birth,
                join_date=join_date,
                start_date=start_date,
                expiry_date=expiry_date,
                plan=plan
            )

            # -------------------------
            # FINANCIALS
            # -------------------------
            plan_price = Decimal(row.get("plan_price") or 0)
            discount = Decimal(row.get("discount") or 0)
            paid_amount = Decimal(row.get("paid_amount") or 0)

            final_amount = plan_price - discount

            # -------------------------
            # PAYMENT
            # -------------------------
            if paid_amount > 0:
                Payment.objects.create(
                    gym=gym,
                    member=member,
                    plan=plan,
                    invoice_no=generate_invoice_number(gym),
                    amount=paid_amount,
                    payment_mode=row.get("payment_mode"),
                    payment_date=start_date,
                    coverage_start=start_date,
                    coverage_end=expiry_date,
                    plan_price=plan_price,
                    discount_amount=discount,
                    final_amount=final_amount,
                    created_by=request.user
                )

            created += 1

        except Exception as e:
            print("Import error:", e)
            continue

    request.session.pop("import_data", None)

    messages.success(request, f"{created} Members Imported Successfully ✅")
    return redirect("member_list")
 