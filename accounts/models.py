from django.contrib.auth.models import AbstractUser
from django.db import models
from frontend.models import  *  # import your Gym model

class User(AbstractUser):
    ROLE_CHOICES = (
        ('ADMIN', 'Owner'),
        ('TRAINER', 'Trainer'),
    )

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, null=True, blank=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='TRAINER')
    phone = models.CharField(max_length=15, blank=True, null=True)

    # ✅ new field (trainer assigned branch)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.username
