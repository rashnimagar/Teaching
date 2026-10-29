import logging

from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from apps.accounts.permissions import teacher_required
from apps.core.models import FAQItem, SiteSettings
from apps.core.ratelimit import track_ratelimit as ratelimit
from apps.dashboard.forms_teacher import TeacherFAQForm, TeacherSiteSettingsForm

logger = logging.getLogger(__name__)


@teacher_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="30/m", block=True, method=["POST"])
def teacher_settings_view(request):
    """
    Teacher Portal: Global Site Settings configuration view.
    Manages brand name, hero banners, instructor narrative, photo, and validated social links.
    Invalidates shared cache immediately upon saving.
    """
    settings_obj = SiteSettings.get_solo()

    if request.method == "POST":
        form = TeacherSiteSettingsForm(request.POST, request.FILES, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, _("Site settings updated successfully."))
            return redirect("dashboard:teacher_settings")
    else:
        form = TeacherSiteSettingsForm(instance=settings_obj)

    context = {
        "form": form,
        "site_settings": settings_obj,
    }
    return render(request, "dashboard/settings/site_settings.html", context)


@teacher_required
@require_http_methods(["GET"])
def teacher_faqs_list_view(request):
    """
    Teacher Portal: FAQ management list view.
    """
    faqs = FAQItem.objects.all().order_by("order", "id")

    context = {
        "faqs": faqs,
        "total_count": faqs.count(),
        "published_count": faqs.filter(is_published=True).count(),
    }
    return render(request, "dashboard/settings/faq_list.html", context)


@teacher_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="30/m", block=True, method=["POST"])
def teacher_faq_create_view(request):
    """Create a new FAQ item. Order defaults to max(order) + 1."""
    if request.method == "POST":
        form = TeacherFAQForm(request.POST)
        if form.is_valid():
            faq = form.save()
            messages.success(
                request,
                _("FAQ question '%(q)s' created.") % {"q": faq.question},
            )
            return redirect("dashboard:teacher_faqs")
    else:
        form = TeacherFAQForm()

    context = {
        "faq": None,
        "form": form,
        "is_create": True,
    }
    return render(request, "dashboard/settings/faq_form.html", context)


@teacher_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="30/m", block=True, method=["POST"])
def teacher_faq_edit_view(request, faq_id):
    """Edit an existing FAQ item."""
    faq = get_object_or_404(FAQItem, pk=faq_id)

    if request.method == "POST":
        form = TeacherFAQForm(request.POST, instance=faq)
        if form.is_valid():
            faq = form.save()
            messages.success(
                request,
                _("FAQ question '%(q)s' updated.") % {"q": faq.question},
            )
            return redirect("dashboard:teacher_faqs")
    else:
        form = TeacherFAQForm(instance=faq)

    context = {
        "faq": faq,
        "form": form,
        "is_create": False,
    }
    return render(request, "dashboard/settings/faq_form.html", context)


@require_http_methods(["POST"])
@teacher_required
@ratelimit(key="user", rate="60/m", block=True)
def teacher_faq_toggle_publish_view(request, faq_id):
    """Toggle the published state of an FAQ item."""
    faq = get_object_or_404(FAQItem, pk=faq_id)
    faq.is_published = not faq.is_published
    faq.save(update_fields=["is_published", "updated_at"])

    status_str = _("published") if faq.is_published else _("hidden as draft")
    messages.success(
        request,
        _("FAQ '%(q)s' is now %(status)s.") % {"q": faq.question, "status": status_str},
    )
    return redirect("dashboard:teacher_faqs")


@require_http_methods(["POST"])
@teacher_required
@ratelimit(key="user", rate="60/m", block=True)
def teacher_faq_reorder_view(request, faq_id):
    """
    Reorder FAQ items up or down with select_for_update() inside transaction.atomic().
    """
    direction = request.POST.get("direction", "up")

    with transaction.atomic():
        faqs = list(FAQItem.objects.select_for_update().order_by("order", "id"))

        target_idx = None
        for idx, f in enumerate(faqs):
            if f.id == faq_id:
                target_idx = idx
                break

        if target_idx is None:
            raise Http404(_("FAQ item does not exist."))

        if direction == "up" and target_idx > 0:
            swap_idx = target_idx - 1
            faqs[target_idx], faqs[swap_idx] = faqs[swap_idx], faqs[target_idx]
        elif direction == "down" and target_idx < len(faqs) - 1:
            swap_idx = target_idx + 1
            faqs[target_idx], faqs[swap_idx] = faqs[swap_idx], faqs[target_idx]

        for new_order, f in enumerate(faqs, start=1):
            if f.order != new_order:
                f.order = new_order
                f.save(update_fields=["order", "updated_at"])

    messages.success(request, _("FAQ order updated."))
    return redirect("dashboard:teacher_faqs")


@require_http_methods(["POST"])
@teacher_required
@ratelimit(key="user", rate="30/m", block=True)
def teacher_faq_delete_view(request, faq_id):
    """Delete an FAQ item."""
    faq = get_object_or_404(FAQItem, pk=faq_id)
    question = faq.question
    faq.delete()

    messages.success(request, _("FAQ '%(q)s' deleted.") % {"q": question})
    return redirect("dashboard:teacher_faqs")
