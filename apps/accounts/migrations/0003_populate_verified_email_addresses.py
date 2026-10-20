from django.db import migrations


def populate_verified_email_addresses(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    EmailAddress = apps.get_model("account", "EmailAddress")

    for user in User.objects.all():
        if user.email:
            email_normalized = user.email.strip().lower()
            email_obj, created = EmailAddress.objects.get_or_create(
                user=user,
                email=email_normalized,
                defaults={
                    "verified": True,
                    "primary": True,
                },
            )
            if not created and not email_obj.verified:
                email_obj.verified = True
                email_obj.primary = True
                email_obj.save(update_fields=["verified", "primary"])


def reverse_populate(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_user_terms_accepted_at"),
        ("account", "0009_emailaddress_unique_primary_email"),
    ]

    operations = [
        migrations.RunPython(populate_verified_email_addresses, reverse_populate),
    ]
