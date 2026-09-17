from django.db import models
from datetime import date
from django.utils import timezone
from django.conf import settings

class Gym(models.Model):
    
    PLEAN_CHOICES =(
        ("single" , "Single Branch"),
        ("multi" , "Multi Branch")
    )
    Subscripation_CHOICES = (
        ("basic" , "Basic"),
        ("pro" , "Pro")
    )
    subscription_type = models.CharField(
        max_length=20,
        choices=Subscripation_CHOICES,
        default="basic"
    )
    plan_type = models.CharField(choices=PLEAN_CHOICES,default="single" , null=True , blank=True , max_length=10)
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Admission Number:
    admission_start_number = models.IntegerField(default=1)
    
    
    # Whatsapp Settings
    interakt_enabled = models.BooleanField(default=False)
    interakt_api_key = models.CharField(max_length=255, blank=True, null=True)

    wa_template_expiring_soon = models.CharField(max_length=100, blank=True, null=True)
    wa_template_expires_today = models.CharField(max_length=100, blank=True, null=True)
    wa_template_expired = models.CharField(max_length=100, blank=True, null=True)
    
    wa_template_birthday = models.CharField(max_length=100, blank=True, null=True)
    birthday_reminder_days_before = models.PositiveIntegerField(default=10)
    wa_template_birthday_today = models.CharField(max_length=100, blank=True, null=True)
    
    Auto_archive_In = models.PositiveIntegerField(default=30)
    Auto_archive_enable=models.BooleanField(default=False)
    expiry_reminder_days_before = models.PositiveIntegerField(default=3)
    
    

    def __str__(self):
        return self.name


class Branch(models.Model):
    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="branches")
    name = models.CharField(max_length=100)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=15, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    def save(self, *args, **kwargs):
        if self.gym.plan_type == "single":
            if Branch.objects.filter(gym=self.gym).exists():
                raise ValueError("Single plan allows only one branch.")
        super().save(*args, **kwargs)
    class Meta:
        unique_together = ('gym', 'name')  # same gym can't have 2 branches with same name

    def __str__(self):
        return f"{self.name} - {self.gym.name}"


class MembershipPlan(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="plans")
    name = models.CharField(max_length=50)  # Monthly / Quarterly
    duration_days = models.PositiveIntegerField()
    start_date = models.DateField(null=True)
    end_date = models.DateField(null=True)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('branch', 'name')  # same branch can't have same plan name twice

    def __str__(self):
        return f"{self.name} - {self.branch.name}"


class Member(models.Model):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('expiring', 'Expiring Soon'),
        ('expired', 'Expired'),
    )
    is_deleted = models.BooleanField(default=False)
    admission_number = models.CharField(max_length=10,  blank=True, null=True)
    DOB=models.DateField(null=True,blank=True)
    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="members")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="members")
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)
    join_date = models.DateField(default=date.today)
    photo = models.ImageField(upload_to="members/", blank=True, null=True)
    plan = models.ForeignKey(MembershipPlan, on_delete=models.SET_NULL, null=True, blank=True)
    start_date = models.DateField(null=True)
    expiry_date = models.DateField()
    security_deposit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ("gym", "admission_number")

    def __str__(self):
        return f"{self.name} ({self.branch.name})"


class Payment(models.Model):
    PAYMENT_MODE = (
        ('cash', 'Cash'),
        ('upi', 'UPI'),
    )

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="payments")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name='payments')
    plan = models.ForeignKey(MembershipPlan, on_delete=models.SET_NULL, null=True, blank=True)
    invoice_no = models.CharField(max_length=50, blank=True, null=True)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    payment_mode = models.CharField(max_length=10, choices=PAYMENT_MODE)
    payment_date = models.DateField(default=timezone.localdate)
    # payment_date = models.DateField(auto_now_add=True)
    coverage_start = models.DateField(null=True, blank=True)
    coverage_end = models.DateField(null=True, blank=True)
    
    plan_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    final_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    discount_reason = models.CharField(max_length=120, blank=True, null=True)
    referral_name = models.CharField(max_length=120, blank=True, null=True)
    
    created_by = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name="payments_created"
)
    
    
    def __str__(self):
        return f"{self.member.name} - {self.amount}"


class InvoiceSettings(models.Model):
    gym = models.OneToOneField("frontend.Gym", on_delete=models.CASCADE, related_name="invoice_settings")
    prefix = models.CharField(max_length=20, default="INV")   # ex: MFG, INV, MFG-VLR
    next_number = models.PositiveIntegerField(default=1001)   # owner can set this
    padding = models.PositiveIntegerField(default=4)          # 0001 format

    def __str__(self):
        return f"{self.gym} - {self.prefix}-{self.next_number}"

class WhatsAppLog(models.Model):
    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="whatsapp_logs")
    member = models.ForeignKey(Member, on_delete=models.CASCADE)

    message_type = models.CharField(max_length=50)  # expiry_reminder
    status = models.CharField(max_length=20 , null=True)  # sent / failed
    response_id = models.CharField(max_length=100, blank=True, null=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.member.name} - {self.status}"
    
    

class Enquiry(models.Model):
    STATUS_OPEN = "open"
    STATUS_FOLLOWUP = "followup"
    STATUS_WON = "won"
    STATUS_LOST = "lost"

    STATUS_CHOICES = (
        (STATUS_OPEN, "Open"),
        (STATUS_FOLLOWUP, "Follow-up"),
        (STATUS_WON, "Closed - Won"),
        (STATUS_LOST, "Closed - Lost"),
    )

    gym = models.ForeignKey("Gym", on_delete=models.CASCADE, related_name="enquiries")
    branch = models.ForeignKey("Branch", on_delete=models.SET_NULL, null=True, blank=True, related_name="enquiries")

    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, db_index=True)

    source = models.CharField(max_length=80, blank=True, null=True)   # walk-in, instagram, referral...
    interested_plan = models.CharField(max_length=120, blank=True, null=True)

    note = models.TextField(blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)

    next_followup = models.DateField(blank=True, null=True)
    last_followup_note = models.CharField(max_length=200, blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="enquiries_created"
    )
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.name} ({self.phone})"
    
    

class WhatsAppMessageLog(models.Model):
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("sent", "Sent"),
        ("delivered", "Delivered"),
        ("read", "Read"),
        ("failed", "Failed"),
    ]

    MESSAGE_TYPE_CHOICES = [
        ("expiring_soon", "Expiring Soon"),
        ("expires_today", "Expires Today"),
        ("expired", "Expired"),
    ]

    gym = models.ForeignKey("Gym", on_delete=models.CASCADE, related_name="wa_logs")
    member = models.ForeignKey("Member", on_delete=models.SET_NULL, null=True, blank=True, related_name="wa_logs")

    phone = models.CharField(max_length=20)
    template_name = models.CharField(max_length=100)
    message_type = models.CharField(max_length=30, choices=MESSAGE_TYPE_CHOICES)

    interakt_message_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    callback_data = models.CharField(max_length=255, blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    error_message = models.TextField(blank=True, null=True)

    sent_at = models.DateTimeField(blank=True, null=True)
    delivered_at = models.DateTimeField(blank=True, null=True)
    read_at = models.DateTimeField(blank=True, null=True)
    failed_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.phone} - {self.message_type} - {self.status}"

