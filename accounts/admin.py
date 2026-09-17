from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Gym Info", {
            "fields": ("gym", "role"),
        }),
    )
    list_display = ("username", "email", "gym", "role", "is_staff")
    list_filter = ("gym", "role")
