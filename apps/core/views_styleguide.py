from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET"])
def styleguide_view(request):
    """
    DEBUG-only styleguide showcasing all UI/UX components, variants,
    sizes, interactive states, and Nepali Devanagari typography in both
    light and dark themes.
    """
    if not settings.DEBUG:
        raise Http404("Styleguide is only available in DEBUG mode.")

    return render(
        request,
        "styleguide.html",
        {
            "dummy_tabs": [
                {"id": "tab-overview", "label": "Course Overview", "count": None},
                {"id": "tab-curriculum", "label": "Curriculum", "count": 12},
                {"id": "tab-assignments", "label": "Assignments", "count": 3},
                {"id": "tab-discussions", "label": "Community Q&A", "count": 48},
            ],
            "dummy_breadcrumbs": [
                {"name": "Home", "url": "/"},
                {"name": "Course Catalog", "url": "/courses/"},
                {"name": "Python & Django Fundamentals", "url": None},
            ],
            "contrast_matrix": [
                {
                    "pair": "Canvas & Text Main",
                    "bg": "#f8fafc",
                    "fg": "#0f172a",
                    "ratio": "17.06:1",
                    "level": "AAA",
                    "theme": "Light",
                },
                {
                    "pair": "Card Surface & Text Main",
                    "bg": "#ffffff",
                    "fg": "#0f172a",
                    "ratio": "17.85:1",
                    "level": "AAA",
                    "theme": "Light",
                },
                {
                    "pair": "Card Surface & Text Muted",
                    "bg": "#ffffff",
                    "fg": "#475569",
                    "ratio": "7.58:1",
                    "level": "AAA",
                    "theme": "Light",
                },
                {
                    "pair": "Primary Button (indigo-600 & white)",
                    "bg": "#4f46e5",
                    "fg": "#ffffff",
                    "ratio": "6.29:1",
                    "level": "AA",
                    "theme": "Light",
                },
                {
                    "pair": "Secondary Button (slate-900 & white)",
                    "bg": "#0f172a",
                    "fg": "#ffffff",
                    "ratio": "17.85:1",
                    "level": "AAA",
                    "theme": "Light",
                },
                {
                    "pair": "Danger Button (red-600 & white)",
                    "bg": "#dc2626",
                    "fg": "#ffffff",
                    "ratio": "4.83:1",
                    "level": "AA",
                    "theme": "Light",
                },
                {
                    "pair": "Interactive Control Border",
                    "bg": "#ffffff",
                    "fg": "#64748b",
                    "ratio": "4.76:1",
                    "level": "UI 3:1+",
                    "theme": "Light",
                },
                {
                    "pair": "Focus Ring vs Canvas",
                    "bg": "#f8fafc",
                    "fg": "#4f46e5",
                    "ratio": "6.01:1",
                    "level": "UI 3:1+",
                    "theme": "Light",
                },
                {
                    "pair": "Canvas & Text Main",
                    "bg": "#020617",
                    "fg": "#f8fafc",
                    "ratio": "19.28:1",
                    "level": "AAA",
                    "theme": "Dark",
                },
                {
                    "pair": "Card Surface & Text Main",
                    "bg": "#0f172a",
                    "fg": "#f8fafc",
                    "ratio": "17.06:1",
                    "level": "AAA",
                    "theme": "Dark",
                },
                {
                    "pair": "Card Surface & Text Muted",
                    "bg": "#0f172a",
                    "fg": "#94a3b8",
                    "ratio": "6.96:1",
                    "level": "AAA",
                    "theme": "Dark",
                },
                {
                    "pair": "Primary Button (indigo-600 & white)",
                    "bg": "#4f46e5",
                    "fg": "#ffffff",
                    "ratio": "6.29:1",
                    "level": "AA",
                    "theme": "Dark",
                },
                {
                    "pair": "Secondary Button (slate-100 & slate-900)",
                    "bg": "#f1f5f9",
                    "fg": "#0f172a",
                    "ratio": "16.30:1",
                    "level": "AAA",
                    "theme": "Dark",
                },
                {
                    "pair": "Danger Button (red-600 & white)",
                    "bg": "#dc2626",
                    "fg": "#ffffff",
                    "ratio": "4.83:1",
                    "level": "AA",
                    "theme": "Dark",
                },
                {
                    "pair": "Interactive Control Border",
                    "bg": "#0f172a",
                    "fg": "#64748b",
                    "ratio": "3.75:1",
                    "level": "UI 3:1+",
                    "theme": "Dark",
                },
                {
                    "pair": "Focus Ring vs Canvas",
                    "bg": "#020617",
                    "fg": "#818cf8",
                    "ratio": "6.76:1",
                    "level": "UI 3:1+",
                    "theme": "Dark",
                },
            ],
        },
    )
