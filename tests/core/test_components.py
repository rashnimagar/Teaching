import re
from pathlib import Path

import pytest
from django.conf import settings
from django.template.loader import render_to_string
from django.test import Client, override_settings


@pytest.mark.django_db
class TestComponentTemplates:
    """Automated tests for reusable template partials and styleguide."""

    def test_components_no_dynamic_class_concatenation(self):
        """
        Verify that components in templates/components/ do NOT use dynamically
        concatenated Tailwind class names (e.g. bg-{{ variant }}-500 or class="btn-{{ size }}").
        All classes must be complete literal class strings within variant maps/conditionals
        so that Tailwind scanner does not purge them.
        """
        components_dir = Path(settings.BASE_DIR) / "templates" / "components"
        assert components_dir.exists(), "templates/components/ directory must exist"

        html_files = list(components_dir.glob("*.html"))
        assert len(html_files) >= 15, (
            f"Expected at least 15 component templates, found {len(html_files)}"
        )

        dynamic_class_pattern = re.compile(
            r'class="[^"]*(?:bg|text|border|p|px|py|m|rounded)-{{\s*[\w_]+[^}"]*"',
            re.IGNORECASE,
        )

        for template_file in html_files:
            content = template_file.read_text(encoding="utf-8")
            matches = dynamic_class_pattern.findall(content)
            assert not matches, (
                f"File {template_file.name} contains dynamic class interpolation: {matches}. "
                "Use complete, literal Tailwind class strings via variant maps instead."
            )

    def test_button_component_variants_and_states(self):
        """Test button partial rendering across variants, sizes, and states."""
        # 1. Primary Button
        html_primary = render_to_string(
            "components/button.html",
            {"text": "Submit Work", "variant": "primary", "size": "md"},
        )
        assert "bg-indigo-600" in html_primary
        assert "min-h-[44px]" in html_primary
        assert "Submit Work" in html_primary

        # 2. Secondary Button
        html_secondary = render_to_string(
            "components/button.html",
            {"text": "Cancel", "variant": "secondary", "size": "sm"},
        )
        assert "bg-slate-900" in html_secondary
        assert "min-h-[36px]" in html_secondary

        # 3. Danger Button
        html_danger = render_to_string(
            "components/button.html",
            {"text": "Delete", "variant": "danger", "size": "lg"},
        )
        assert "bg-red-600" in html_danger
        assert "min-h-[48px]" in html_danger

        # 4. Loading State
        html_loading = render_to_string(
            "components/button.html",
            {"text": "Saving", "variant": "primary", "is_loading": True},
        )
        assert 'aria-busy="true"' in html_loading
        assert "animate-spin" in html_loading

        # 5. Disabled State
        html_disabled = render_to_string(
            "components/button.html",
            {"text": "Disabled", "variant": "outline", "disabled": True},
        )
        assert 'aria-disabled="true"' in html_disabled
        assert "disabled" in html_disabled

        # 6. Anchor Tag Variant
        html_link = render_to_string(
            "components/button.html",
            {"text": "Browse Courses", "href": "/courses/", "variant": "primary"},
        )
        assert "<a" in html_link
        assert 'href="/courses/"' in html_link

    def test_form_controls_accessible_attributes(self):
        """Test input, select, textarea, and checkbox accessibility attributes."""
        # Input with error
        html_input = render_to_string(
            "components/input.html",
            {
                "id": "email-input",
                "name": "email",
                "type": "email",
                "error": "Invalid email address",
                "help_text": "Enter your university email",
            },
        )
        assert 'aria-invalid="true"' in html_input
        assert 'aria-describedby="email-input-error email-input-help"' in html_input
        assert "border-red-500" in html_input

        # Checkbox with 44px minimum target
        html_checkbox = render_to_string(
            "components/checkbox.html",
            {
                "id": "agree-terms",
                "name": "terms",
                "label": "I accept terms",
                "required": True,
            },
        )
        assert "min-h-[44px]" in html_checkbox
        assert 'for="agree-terms"' in html_checkbox
        assert 'id="agree-terms"' in html_checkbox

    def test_tabs_wai_aria_attributes(self):
        """Test tabs partial role and roving tabindex markup."""
        tabs_data = [
            {"id": "tab-1", "label": "Lesson Video", "count": None},
            {"id": "tab-2", "label": "Assignments", "count": 2},
        ]
        html_tabs = render_to_string(
            "components/tabs.html",
            {"tabs_id": "lesson-tabs", "tabs": tabs_data, "active_tab_id": "tab-1"},
        )
        assert 'role="tablist"' in html_tabs
        assert 'role="tab"' in html_tabs
        assert 'aria-selected="true"' in html_tabs
        assert 'tabindex="0"' in html_tabs
        assert 'tabindex="-1"' in html_tabs
        assert 'aria-controls="tab-1-panel"' in html_tabs

    def test_modal_and_drawer_wai_aria_attributes(self):
        """Test modal and drawer dialog roles and accessibility."""
        html_modal = render_to_string(
            "components/modal_drawer.html",
            {
                "id": "test-dialog",
                "type": "modal",
                "title": "Assignment Details",
                "body_html": "<p>Content</p>",
            },
        )
        assert 'role="dialog"' in html_modal
        assert 'aria-modal="true"' in html_modal
        assert 'aria-labelledby="test-dialog-title"' in html_modal
        assert "data-dialog-backdrop" in html_modal
        assert "data-dialog-close" in html_modal

    def test_toast_aria_live_notification(self):
        """Test toast component role and polite notification."""
        html_toast = render_to_string(
            "components/toast.html",
            {"id": "toast-1", "message": "Saved successfully", "variant": "success"},
        )
        assert 'role="status"' in html_toast
        assert 'aria-live="polite"' in html_toast

    def test_progress_bar_accessible_attributes(self):
        """Test progress bar accessibility."""
        html_progress = render_to_string(
            "components/progress_bar.html",
            {"value": 75, "label": "Course Progress", "variant": "brand"},
        )
        assert 'role="progressbar"' in html_progress
        assert 'aria-valuenow="75"' in html_progress
        assert 'aria-valuemin="0"' in html_progress
        assert 'aria-valuemax="100"' in html_progress

    def test_devanagari_font_file_exists(self):
        """Verify that the subsetted Noto Sans Devanagari font file exists and is populated."""
        font_path = (
            Path(settings.BASE_DIR) / "static" / "fonts" / "noto-sans-devanagari-variable.woff2"
        )
        assert font_path.exists(), "Noto Sans Devanagari woff2 file must exist in static/fonts/"
        assert font_path.stat().st_size > 50000, "Font file must not be empty"


@pytest.mark.django_db
class TestStyleguideView:
    """Tests for the /styleguide/ view."""

    @override_settings(DEBUG=True)
    def test_styleguide_available_in_debug(self):
        """Styleguide must return 200 and showcase all components and Devanagari in DEBUG=True."""
        client = Client()
        response = client.get("/styleguide/")
        assert response.status_code == 200

        content = response.content.decode("utf-8")
        assert "Design System & Component Styleguide" in content
        # Verify Devanagari conjuncts in headings and text
        assert "दक्ष शिक्षकबाट ज्ञान र प्रविधि शिक्षा" in content
        assert "क्ष" in content
        assert "ज्ञ" in content
        assert "नयाँ खाता सिर्जना गर्नुहोस्" in content
        # Verify contrast table
        assert "WCAG 2.1 AA Contrast Ratios" in content

    @override_settings(DEBUG=False)
    def test_styleguide_returns_404_when_debug_false(self):
        """Styleguide must return 404 when DEBUG=False in production."""
        client = Client()
        response = client.get("/styleguide/")
        assert response.status_code == 404
