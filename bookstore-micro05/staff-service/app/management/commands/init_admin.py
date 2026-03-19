import os
from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password
from app.models import Staff

class Command(BaseCommand):
    """
    Custom command to create or update an admin staff account from environment variables.
    This account is used by staff-service auth endpoint (/api/auth/token/).
    """
    help = 'Creates/updates an admin Staff account from environment variables.'

    def handle(self, *args, **options):
        username = os.environ.get('ADMIN_USER', 'admin')
        email = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
        password = os.environ.get('ADMIN_PASSWORD')
        name = os.environ.get('ADMIN_NAME', 'System Admin')

        if not password:
            self.stdout.write(self.style.ERROR('ADMIN_PASSWORD environment variable not set.'))
            return

        staff, created = Staff.objects.get_or_create(
            username=username,
            defaults={
                'name': name,
                'email': email,
                'password': make_password(password),
                'role': 'admin',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f'Successfully created admin staff account: {username}'))
        else:
            staff.name = name
            staff.email = email
            staff.password = make_password(password)
            staff.role = 'admin'
            staff.is_active = True
            staff.save(update_fields=['name', 'email', 'password', 'role', 'is_active'])
            self.stdout.write(self.style.WARNING(f'Admin staff account {username} already existed. Credentials were updated.'))
