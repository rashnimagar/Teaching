import logging

from django.db import migrations, models

logger = logging.getLogger(__name__)


def backfill_file_sizes(apps, schema_editor):
    Submission = apps.get_model("assignments", "Submission")
    for sub in Submission.objects.exclude(file="").exclude(file__isnull=True):
        if sub.file:
            try:
                sub.file_size = sub.file.size
                sub.save(update_fields=["file_size"])
            except (FileNotFoundError, OSError, ValueError) as err:
                logger.warning(
                    "Skipping file_size backfill for submission id=%s (missing or inaccessible file %s): %s",
                    sub.id,
                    getattr(sub.file, "name", ""),
                    err,
                )
            except Exception as err:
                logger.warning(
                    "Unexpected error reading file for submission id=%s: %s",
                    sub.id,
                    err,
                )


class Migration(migrations.Migration):

    dependencies = [
        ('assignments', '0004_submission_is_unlocked_submissionevent'),
    ]

    operations = [
        migrations.AddField(
            model_name='submission',
            name='file_size',
            field=models.BigIntegerField(blank=True, help_text='Stored file size in bytes to prevent remote storage requests on list views.', null=True, verbose_name='file size in bytes'),
        ),
        migrations.RunPython(backfill_file_sizes, reverse_code=migrations.RunPython.noop),
    ]
