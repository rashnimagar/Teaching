from django.shortcuts import render
from django_ratelimit.exceptions import Ratelimited


class RatelimitMiddleware:
    """
    Middleware that intercepts Ratelimited exceptions and returns an accessible
    HTTP 429 Too Many Requests response page.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, Ratelimited):
            return render(request, "429.html", status=429)
        return None
