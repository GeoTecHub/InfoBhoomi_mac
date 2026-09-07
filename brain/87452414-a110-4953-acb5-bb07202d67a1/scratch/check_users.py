import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'infobhoomi.settings')
django.setup()

from django.contrib.auth import get_user_model
User = get_user_model()

print("Users in database:")
for u in User.objects.all():
    print(f"  - {u.username} (active: {u.is_active}, superuser: {u.is_superuser})")
