"""
Management command to scan private media storage for orphaned submission and material files.
Defaults to dry-run mode unless --delete is explicitly passed.
"""

from django.core.files.storage import storages
from django.core.management.base import BaseCommand

from apps.assignments.models import Submission
from apps.courses.models import MaterialItem


def walk_storage_files(storage, base_path):
    """
    Recursively yield relative file paths inside a storage directory.
    """
    try:
        dirs, files = storage.listdir(base_path)
    except (FileNotFoundError, OSError):
        return

    for f in files:
        yield f"{base_path}/{f}".lstrip("/")

    for d in dirs:
        sub_dir = f"{base_path}/{d}".lstrip("/")
        yield from walk_storage_files(storage, sub_dir)


class Command(BaseCommand):
    help = "Scan and clean up orphaned files in private submission and course material storage (defaults to dry-run)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Perform actual deletion of orphaned files. Defaults to False (dry-run).",
        )

    def handle(self, *args, **options):
        is_delete = options.get("delete", False)
        storage = storages["private"]

        self.stdout.write(self.style.NOTICE("Scanning private storage for submission and material files..."))

        storage_files = set()
        for root_dir in ("submissions", "materials"):
            for path in walk_storage_files(storage, root_dir):
                storage_files.add(path)

        # Collect referenced files from database
        referenced_submissions = set(Submission.objects.exclude(file="").values_list("file", flat=True))
        referenced_materials = set(MaterialItem.objects.exclude(file="").values_list("file", flat=True))
        referenced_files = referenced_submissions | referenced_materials

        orphaned = storage_files - referenced_files

        if not orphaned:
            self.stdout.write(self.style.SUCCESS("No orphaned submission or material files found."))
            return

        total_bytes = 0
        for path in orphaned:
            try:
                total_bytes += storage.size(path)
            except (FileNotFoundError, OSError):
                pass

        total_mb = total_bytes / (1024 * 1024)

        if not is_delete:
            self.stdout.write(
                self.style.WARNING(
                    f"[DRY-RUN] Found {len(orphaned)} orphaned file(s) ({total_mb:.2f} MB):\n"
                    + "\n".join(f" - {p}" for p in sorted(orphaned))
                    + "\n\nDry-run complete. Run with '--delete' to permanently remove these files."
                )
            )
        else:
            deleted_count = 0
            for path in orphaned:
                try:
                    storage.delete(path)
                    deleted_count += 1
                except (FileNotFoundError, OSError) as exc:
                    self.stdout.write(self.style.ERROR(f"Failed to delete {path}: {exc}"))

            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully deleted {deleted_count} orphaned file(s) ({total_mb:.2f} MB freed)."
                )
            )
