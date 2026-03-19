from django.db import models


class Staff(models.Model):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('manager', 'Manager'),
        ('staff', 'Staff'),
    ]
    
    name = models.CharField(max_length=255)
    username = models.CharField(max_length=150, unique=True, null=True)
    password = models.CharField(max_length=128, null=True)
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='staff')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.role})"
