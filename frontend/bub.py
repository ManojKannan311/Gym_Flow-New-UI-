
def dashboard_stats(request):
    gym = request.user.gym
    today = timezone.localdate()
    expiring_limit_days = 3
    expiring_to = today + timedelta(days=expiring_limit_days)

    range_key = (request.GET.get("range") or "current").lower()  # current/last/all
    branch_id = (request.GET.get("branch") or "").strip()

    # -----------------------------
    # Base querysets (always gym-scoped)
    # -----------------------------
    members_qs = Member.objects.filter(gym=gym).select_related("branch", "plan")
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

    # Renewals count (range based)
    # If you have a way to identify renewals vs join payments, this can be improved.
    # For now: count payments in range
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

    # Branches for dropdown
    branches = list(Branch.objects.filter(gym=gym).values("id", "name").order_by("name"))

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
            "cash_total": float(cash_total),
            "upi_total": float(upi_total),
            "new_members": new_members_count,
            "renewals": renewals_count,
        },

        "tables": {
            "expiring_list": expiring_list,
            "expired_list": expired_list,
            "recent_renewals": recent_renewals,
        },

        "branches": branches,
    })
