from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    help = "Promote a user to teacher status (role=teacher, is_staff=True), creating the account if it does not exist."

    def add_arguments(self, parser):
        parser.add_argument("email", type=str, help="The email address of the user to promote.")

    def handle(self, *args, **options):
        raw_email = options["email"]
        if not raw_email or not raw_email.strip():
            raise CommandError("A valid email address must be provided.")

        email = raw_email.strip().lower()

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "role": User.Role.TEACHER,
                "is_staff": True,
            },
        )

        user.role = User.Role.TEACHER
        user.is_staff = True
        if created:
            user.set_unusable_password()
        user.save()

        action = "Created new teacher account" if created else "Updated existing user to teacher"
        self.stdout.write(self.style.SUCCESS(f"{action}: {email} (role=teacher, is_staff=True)"))
