from django.contrib import admin
from .models import Gym, Branch, MembershipPlan, Member, Payment, WhatsAppLog


# ================= GYM =================
@admin.register(Gym)
class GymAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'created_at')
    search_fields = ('name', 'phone')


# ================= BRANCH =================
@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'gym', 'phone', 'created_at')
    list_filter = ('gym',)
    search_fields = ('name',)


# ================= MEMBERSHIP PLAN =================
@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'branch',
        'get_gym',
        'price',
        'duration_days',
        'is_active',
        'created_at'
    )
    list_filter = ('branch', 'is_active')
    search_fields = ('name',)

    def get_gym(self, obj):
        return obj.branch.gym.name
    get_gym.short_description = "Gym"


# ================= MEMBER =================
@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'gym',
        'branch',
        'phone',
        'plan',
        'start_date',
        'expiry_date',
        'status',
        "DOB"
    )
    list_filter = ('gym', 'branch', 'status')
    search_fields = ('name', 'phone')
    date_hierarchy = 'expiry_date'


# ================= PAYMENT =================
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('member', 'gym', 'amount', 'payment_mode', 'payment_date')
    list_filter = ('gym', 'payment_mode')
    search_fields = ('member__name',)


# ================= WHATSAPP =================
@admin.register(WhatsAppLog)
class WhatsAppLogAdmin(admin.ModelAdmin):
    list_display = ('member', 'gym', 'message_type', 'status', 'sent_at')
    list_filter = ('gym', 'status', 'message_type')
