import csv
import io
import re
import urllib.parse
from decimal import Decimal

from django.http import StreamingHttpResponse
from django.utils import timezone

from apps.assignments.models import Assignment, Submission
from apps.courses.models import Course, Enrollment, Lesson, LessonProgress


def sanitize_csv_cell(val) -> str:
    """
    Prevents CSV / Formula injection (CWE-1236 / OWASP).
    If a string cell starts with '=', '+', '-', '@', '\t', or '\r',
    it is prepended with a single quote (').
    """
    if val is None:
        return ""
    s = str(val)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{s}"
    return s


def build_content_disposition_header(filename: str) -> str:
    """
    Formats RFC 5987 / RFC 6266 Content-Disposition header with safe ASCII fallback
    and UTF-8 encoded filename*.
    """
    # ASCII fallback with non-ascii and unsafe chars removed
    ascii_clean = re.sub(r"[^\w\-.]", "_", filename.encode("ascii", "ignore").decode("ascii"))
    if not ascii_clean:
        ascii_clean = "export.csv"
    utf8_encoded = urllib.parse.quote(filename)
    return f"attachment; filename=\"{ascii_clean}\"; filename*=UTF-8''{utf8_encoded}"


def stream_course_grades_csv(course: Course) -> StreamingHttpResponse:
    """
    Streams a per-course student grades CSV.
    Columns:
    - Student Name
    - Student Email
    - [One column per published assignment]: Title (Max Pts)
    - Total Points Earned
    - Graded Max Points
    - Score (%)
    """
    published_assignments = list(
        Assignment.objects.filter(course=course, is_published=True).order_by("due_at", "id")
    )

    header = ["Student Name", "Email"]
    for assign in published_assignments:
        header.append(f"{assign.title} (Max: {assign.max_score})")
    header.extend(["Total Points Earned", "Graded Max Points", "Total Score (%)"])

    def row_generator():
        # Iterate over active and pending enrollments for this course
        enrollments = (
            Enrollment.objects.filter(course=course)
            .select_related("student")
            .order_by("student__first_name", "student__last_name", "student__email")
            .iterator(chunk_size=100)
        )

        for enrollment in enrollments:
            student = enrollment.student
            # Map submissions for this student across published assignments
            submissions = {
                sub.assignment_id: sub
                for sub in Submission.objects.filter(
                    assignment__course=course,
                    assignment__is_published=True,
                    student=student,
                )
            }

            points_earned = Decimal("0")
            graded_max = Decimal("0")

            row = [
                student.get_full_name() or student.email.split("@")[0],
                student.email,
            ]

            for assign in published_assignments:
                sub = submissions.get(assign.id)
                if sub and sub.grade is not None:
                    row.append(str(sub.grade))
                    points_earned += sub.grade
                    graded_max += assign.max_score
                else:
                    row.append("—")

            row.append(str(points_earned) if graded_max > 0 else "0")
            row.append(str(graded_max))

            if graded_max > 0:
                pct = round((float(points_earned) / float(graded_max)) * 100, 1)
                row.append(f"{pct}%")
            else:
                row.append("N/A")

            yield row

    def csv_generator():
        # Output UTF-8 BOM first for proper Excel display
        yield "\ufeff"
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([sanitize_csv_cell(c) for c in header])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        for row in row_generator():
            writer.writerow([sanitize_csv_cell(c) for c in row])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    filename = f"grades_{course.slug}_{timezone.now().strftime('%Y%m%d_%H%M')}.csv"
    response = StreamingHttpResponse(csv_generator(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = build_content_disposition_header(filename)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def stream_course_progress_csv(course: Course) -> StreamingHttpResponse:
    """
    Streams a per-course student syllabus progress CSV.
    Only counts published lessons toward total and completion.
    Columns:
    - Student Name
    - Student Email
    - Enrollment Status
    - Enrolled Date
    - Completed Lessons
    - Total Published Lessons
    - Progress (%)
    """
    published_lessons = list(
        Lesson.objects.filter(course=course, is_published=True).order_by("order", "id")
    )
    total_published = len(published_lessons)
    published_lesson_ids = {lesson.id for lesson in published_lessons}

    header = [
        "Student Name",
        "Email",
        "Enrollment Status",
        "Enrolled Date",
        "Completed Lessons",
        "Total Published Lessons",
        "Progress (%)",
    ]

    def row_generator():
        enrollments = (
            Enrollment.objects.filter(course=course)
            .select_related("student")
            .order_by("student__first_name", "student__last_name", "student__email")
            .iterator(chunk_size=100)
        )

        for enrollment in enrollments:
            student = enrollment.student
            completed_count = LessonProgress.objects.filter(
                student=student,
                lesson_id__in=published_lesson_ids,
                completed_at__isnull=False,
            ).count()

            pct = (
                round((completed_count / total_published) * 100, 1) if total_published > 0 else 0.0
            )

            row = [
                student.get_full_name() or student.email.split("@")[0],
                student.email,
                enrollment.get_status_display(),
                enrollment.created_at.strftime("%Y-%m-%d %H:%M"),
                completed_count,
                total_published,
                f"{pct}%",
            ]
            yield row

    def csv_generator():
        yield "\ufeff"
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([sanitize_csv_cell(c) for c in header])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        for row in row_generator():
            writer.writerow([sanitize_csv_cell(c) for c in row])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    filename = f"progress_{course.slug}_{timezone.now().strftime('%Y%m%d_%H%M')}.csv"
    response = StreamingHttpResponse(csv_generator(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = build_content_disposition_header(filename)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
