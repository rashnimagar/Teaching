from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.assignments.models import Assignment, Submission
from apps.core.models import FAQItem, SiteSettings
from apps.courses.models import Course, Enrollment, Lesson, LessonProgress

User = get_user_model()


class Command(BaseCommand):
    help = "Seeds the database with representative demo courses, lessons, enrollments, and submissions."

    def handle(self, *args, **options):
        # Refuse to run if DEBUG is False
        if not settings.DEBUG:
            raise CommandError(
                "Refusing to run seed_demo: DEBUG is False. Demo seed data is strictly restricted to development environments."
            )

        self.stdout.write(self.style.NOTICE("Seeding demo data for development..."))

        # 1. Users
        teacher, _ = User.objects.get_or_create(
            email="teacher@example.com",
            defaults={
                "first_name": "Roshan",
                "last_name": "Adhikari",
                "role": User.Role.TEACHER,
                "is_staff": True,
            },
        )
        teacher.set_unusable_password()
        teacher.save()

        student1, _ = User.objects.get_or_create(
            email="student1@example.com",
            defaults={
                "first_name": "Aayush",
                "last_name": "Sharma",
                "role": User.Role.STUDENT,
            },
        )
        student1.set_unusable_password()
        student1.save()

        student2, _ = User.objects.get_or_create(
            email="student2@example.com",
            defaults={
                "first_name": "Pooja",
                "last_name": "Thapa",
                "role": User.Role.STUDENT,
            },
        )
        student2.set_unusable_password()
        student2.save()

        # Ensure verified EmailAddress records for seeded users
        from allauth.account.models import EmailAddress

        for u in [teacher, student1, student2]:
            EmailAddress.objects.update_or_create(
                user=u,
                email=u.email,
                defaults={"verified": True, "primary": True},
            )

        self.stdout.write(
            "  [OK] Users created (teacher@example.com, student1@example.com, student2@example.com)"
        )

        # 2. Courses
        course_free, _ = Course.objects.update_or_create(
            slug="python-fullstack-fundamentals",
            defaults={
                "title": "Python & Django Full-Stack Fundamentals",
                "short_description": "Build modern web applications from scratch using Python, Django 5.2, and Tailwind CSS.",
                "description": (
                    "A complete end-to-end foundation covering Python fundamentals, relational database design, "
                    "server-side rendering, authentication, and responsive user interfaces."
                ),
                "is_published": True,
                "is_featured": True,
                "is_free": True,
                "price": None,
                "currency": "NPR",
            },
        )

        course_paid, _ = Course.objects.update_or_create(
            slug="advanced-microservices-django",
            defaults={
                "title": "Advanced Backend Engineering & Microservices",
                "short_description": "Master distributed task processing, caching strategies, and robust payment integrations.",
                "description": (
                    "Deep dive into high-throughput Django backends: database connection pooling, asynchronous jobs, "
                    "server-side payment gateway verification, and rate limiting."
                ),
                "is_published": True,
                "is_featured": False,
                "is_free": False,
                "price": Decimal("3500.00"),
                "currency": "NPR",
            },
        )

        self.stdout.write("  [OK] Courses created (Free and Paid)")

        # 3. Lessons for Free Course
        lessons_free = [
            {
                "order": 1,
                "title": "Introduction & Workspace Setup",
                "video_provider": Lesson.VideoProvider.YOUTUBE,
                "video_id": "dQw4w9WgXcQ",
                "duration": timedelta(minutes=12, seconds=30),
                "is_preview": True,
                "is_published": True,
            },
            {
                "order": 2,
                "title": "Configuring Virtual Environments and Split Settings",
                "video_provider": Lesson.VideoProvider.BUNNY,
                "video_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
                "duration": timedelta(minutes=24, seconds=15),
                "is_preview": False,
                "is_published": True,
            },
            {
                "order": 3,
                "title": "Modeling Data with Django ORM",
                "video_provider": Lesson.VideoProvider.VIMEO,
                "video_id": "76979871",
                "duration": timedelta(minutes=31, seconds=45),
                "is_preview": False,
                "is_published": True,
            },
        ]

        for lesson_data in lessons_free:
            Lesson.objects.update_or_create(
                course=course_free,
                order=lesson_data["order"],
                defaults=lesson_data,
            )

        # Lessons for Paid Course
        lessons_paid = [
            {
                "order": 1,
                "title": "Architecture Overview: Monolith to Services",
                "video_provider": Lesson.VideoProvider.YOUTUBE,
                "video_id": "dQw4w9WgXcQ",
                "duration": timedelta(minutes=18, seconds=10),
                "is_preview": True,
                "is_published": True,
            },
            {
                "order": 2,
                "title": "Integrating Redis Caching & Throttling",
                "video_provider": Lesson.VideoProvider.BUNNY,
                "video_id": "f9e8d7c6-b5a4-3210-9876-543210fedcba",
                "duration": timedelta(minutes=28, seconds=50),
                "is_preview": False,
                "is_published": True,
            },
        ]

        for lesson_data in lessons_paid:
            Lesson.objects.update_or_create(
                course=course_paid,
                order=lesson_data["order"],
                defaults=lesson_data,
            )

        self.stdout.write("  [OK] Lessons created for both courses")

        # 4. Enrollments
        Enrollment.objects.update_or_create(
            student=student1,
            course=course_free,
            defaults={
                "status": Enrollment.Status.ACTIVE,
                "source": Enrollment.Source.FREE,
            },
        )

        Enrollment.objects.update_or_create(
            student=student2,
            course=course_paid,
            defaults={
                "status": Enrollment.Status.PENDING,
                "source": Enrollment.Source.PAYMENT,
            },
        )

        self.stdout.write("  [OK] Enrollments created (student1 active, student2 pending)")

        # 5. Lesson Progress
        lesson_1 = Lesson.objects.get(course=course_free, order=1)
        LessonProgress.objects.update_or_create(
            student=student1,
            lesson=lesson_1,
            defaults={
                "last_position_seconds": 450,
                "completed_at": timezone.now() - timedelta(days=2),
            },
        )
        self.stdout.write("  [OK] Lesson progress tracked for student1")

        # 6. Assignments
        now = timezone.now()

        # Assignment 1: Currently active assignment
        assignment_active, _ = Assignment.objects.update_or_create(
            course=course_free,
            title="Assignment 1: Build a Normalized Django Model Schema",
            defaults={
                "lesson": lesson_1,
                "instructions": "Design a relational schema with constraints, write migrations, and verify in the Django admin.",
                "opens_at": now - timedelta(days=1),
                "due_at": now + timedelta(days=6),
                "max_score": 100,
                "allow_late": False,
            },
        )

        # Assignment 2: Past assignment with submissions
        assignment_past, _ = Assignment.objects.update_or_create(
            course=course_free,
            title="Assignment 0: Environment Setup and Smoke Testing",
            defaults={
                "instructions": "Set up a clean virtual environment and run the smoke test suite.",
                "opens_at": now - timedelta(days=14),
                "due_at": now - timedelta(days=2),
                "max_score": 50,
                "allow_late": True,
            },
        )

        self.stdout.write("  [OK] Assignments created (active and past due)")

        # 7. Submissions
        # Student 1: on-time submission (submitted before due date), graded
        sub1_time = assignment_past.due_at - timedelta(days=1)
        sub1, _ = Submission.objects.update_or_create(
            assignment=assignment_past,
            student=student1,
            defaults={
                "content_text": "Completed the setup checklist, virtual environment active and all smoke tests pass.",
                "submitted_at": sub1_time,
                "is_late": False,
                "grade": Decimal("48.00"),
                "feedback": "Flawless configuration. Well done!",
                "graded_by": teacher,
                "graded_at": now - timedelta(hours=12),
            },
        )

        # Student 2: late submission (submitted after due date, accepted because allow_late=True)
        sub2_time = assignment_past.due_at + timedelta(hours=8)
        sub2, _ = Submission.objects.update_or_create(
            assignment=assignment_past,
            student=student2,
            defaults={
                "content_text": "Attached my summary of test outputs. Apologies for submitting after the deadline.",
                "submitted_at": sub2_time,
                "is_late": True,
                "grade": None,
                "feedback": "",
                "graded_by": None,
                "graded_at": None,
            },
        )

        self.stdout.write("  [OK] Submissions recorded (1 on-time & graded, 1 late & pending)")

        # 6. Site Settings (neutral placeholders)
        SiteSettings.get_solo()
        self.stdout.write("  [OK] Site settings ensured")

        # 7. FAQ Items
        faqs = [
            (
                "How do I access course videos and lessons?",
                "Once enrolled in a course, all published lessons become available in your student dashboard. You can stream high-definition videos anytime at your own pace.",
                1,
            ),
            (
                "How do timed assignments and submissions work?",
                "Courses may include assignments with clear start times and submission deadlines. You can submit your work directly through the platform and receive feedback once graded.",
                2,
            ),
            (
                "What are the prerequisites to enroll in courses?",
                "Prerequisites vary by course and are detailed on each course's overview page. All you need to get started is a Google account.",
                3,
            ),
            (
                "Can I learn on mobile devices?",
                "Yes, the platform is designed to be fully responsive and works smoothly across mobile phones, tablets, and desktop computers.",
                4,
            ),
        ]
        for q, a, order in faqs:
            FAQItem.objects.update_or_create(
                question=q,
                defaults={"answer": a, "order": order, "is_published": True},
            )
        self.stdout.write("  [OK] Frequently Asked Questions seeded")

        self.stdout.write(self.style.SUCCESS("Successfully seeded demo data!"))
