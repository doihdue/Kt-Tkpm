import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    """
    Custom command to create a superuser from environment variables.
    This is useful for initializing an admin account in a Docker environment.
    """
    help = 'Creates a superuser from environment variables if one does not exist.'

    def handle(self, *args, **options):
        User = get_user_model()
        username = os.environ.get('ADMIN_USER', 'admin')
        email = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
        password = os.environ.get('ADMIN_PASSWORD')

        if not password:
            self.stdout.write(self.style.ERROR('ADMIN_PASSWORD environment variable not set.'))
            return

        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f'Successfully created superuser: {username}'))
        else:
            self.stdout.write(self.style.WARNING(f'Superuser {username} already exists.'))