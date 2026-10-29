"""
URL Access Matrix & Route Security Classification Registry (Phase 8B).

Walks the production URL resolver (`config.urls`) and enforces that every route
is explicitly classified as one of:
- `public`
- `authenticated`
- `enrolled` (active enrollment)
- `teacher`
- `superuser`
- `test-only`

Expectations per actor come from written class rules (`CLASS_ACTOR_EXPECTATIONS`),
with every actor on every route resolving to ONE exact integer status code (`int`),
and multi-mode endpoints (AJAX vs form POST, query/state variants) represented via
explicit named `CaseVariantSpec` entries with a written `reason`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.urls import URLPattern, URLResolver, get_resolver

VALID_CLASSIFICATIONS = frozenset(
    {
        "public",
        "authenticated",
        "enrolled",
        "teacher",
        "superuser",
        "test-only",
    }
)

ACTORS = (
    "guest",
    "student_unenrolled",
    "student_pending",
    "student_revoked",
    "student_active",
    "student_other_course",
    "teacher",
    "superuser",
)

# Written class rules: ONE expected integer status code for each actor per classification
CLASS_ACTOR_EXPECTATIONS: dict[str, dict[str, dict[str, int]]] = {
    "public": {
        "GET": {
            "guest": 200,
            "student_unenrolled": 200,
            "student_pending": 200,
            "student_revoked": 200,
            "student_active": 200,
            "student_other_course": 200,
            "teacher": 200,
            "superuser": 200,
        },
        "POST": {
            "guest": 302,
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 302,
            "student_other_course": 302,
            "teacher": 302,
            "superuser": 302,
        },
    },
    "authenticated": {
        "GET": {
            "guest": 302,
            "student_unenrolled": 200,
            "student_pending": 200,
            "student_revoked": 200,
            "student_active": 200,
            "student_other_course": 200,
            "teacher": 200,
            "superuser": 200,
        },
        "POST": {
            "guest": 302,
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 302,
            "student_other_course": 302,
            "teacher": 302,
            "superuser": 302,
        },
    },
    "enrolled": {
        "GET": {
            "guest": 302,
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 200,
            "student_other_course": 302,
            "teacher": 200,
            "superuser": 200,
        },
        "POST": {
            "guest": 302,
            "student_unenrolled": 403,
            "student_pending": 403,
            "student_revoked": 403,
            "student_active": 302,
            "student_other_course": 403,
            "teacher": 302,
            "superuser": 302,
        },
    },
    "teacher": {
        "GET": {
            "guest": 302,
            "student_unenrolled": 403,
            "student_pending": 403,
            "student_revoked": 403,
            "student_active": 403,
            "student_other_course": 403,
            "teacher": 200,
            "superuser": 200,
        },
        "POST": {
            "guest": 302,
            "student_unenrolled": 403,
            "student_pending": 403,
            "student_revoked": 403,
            "student_active": 403,
            "student_other_course": 403,
            "teacher": 302,
            "superuser": 302,
        },
    },
    "superuser": {
        "GET": {
            "guest": 302,
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 302,
            "student_other_course": 302,
            "teacher": 302,
            "superuser": 200,
        },
        "POST": {
            "guest": 302,
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 302,
            "student_other_course": 302,
            "teacher": 302,
            "superuser": 302,
        },
    },
    "test-only": {
        "GET": {
            "guest": 404,
            "student_unenrolled": 404,
            "student_pending": 404,
            "student_revoked": 404,
            "student_active": 404,
            "student_other_course": 404,
            "teacher": 404,
            "superuser": 404,
        },
        "POST": {
            "guest": 405,
            "student_unenrolled": 405,
            "student_pending": 405,
            "student_revoked": 405,
            "student_active": 405,
            "student_other_course": 405,
            "teacher": 405,
            "superuser": 405,
        },
    },
}


@dataclass(frozen=True)
class CaseVariantSpec:
    """
    Explicit named case variant for a route (e.g., `ajax_post` with
    `X-Requested-With: XMLHttpRequest`, or `cancelled_oauth` / `valid_query`
    with query parameters) where every actor has ONE exact expected status code.
    """

    name: str
    method: str
    actor_expectations: dict[str, int]
    reason: str
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not self.reason:
            raise ValueError(f"CaseVariantSpec {self.name!r} must include a written reason.")
        for actor, code in self.actor_expectations.items():
            if not isinstance(code, int):
                raise ValueError(
                    f"CaseVariantSpec {self.name!r} actor {actor!r} must have a single int status, got {code!r}."
                )


@dataclass(frozen=True)
class RouteAccessSpec:
    route_key: str
    classification: str
    methods: tuple[str, ...]
    ratelimit: str | None = None
    actor_overrides: dict[str, int] = field(default_factory=dict)
    exception_reason: str = ""
    case_variants: tuple[CaseVariantSpec, ...] = ()
    description: str = ""

    def __post_init__(self):
        if self.classification not in VALID_CLASSIFICATIONS:
            raise ValueError(f"Invalid classification {self.classification!r} for {self.route_key}")
        if self.actor_overrides and not self.exception_reason:
            raise ValueError(
                f"Route {self.route_key} defines actor_overrides without an exception_reason."
            )
        for actor, val in self.actor_overrides.items():
            if not isinstance(val, int):
                raise ValueError(
                    f"Route {self.route_key} actor {actor!r} must have a single int status code, got {val!r}."
                )

    def expected_for_actor(self, actor: str, method: str | None = None) -> int:
        if actor in self.actor_overrides:
            return self.actor_overrides[actor]
        check_method = method or ("GET" if "GET" in self.methods else "POST")
        default_map = CLASS_ACTOR_EXPECTATIONS[self.classification][check_method]
        return default_map[actor]


# Unused or unlinked allauth routes removed from the URLconf (must return 404 and fail reverse())
REMOVED_ALLAUTH_ROUTES: dict[str, str] = {
    "google_login_by_token": "/accounts/google/login/token/",
    "account_confirm_login_code": "/accounts/login/code/confirm/",
    "account_email": "/accounts/email/",
    "account_reauthenticate": "/accounts/reauthenticate/",
    "account_set_password": "/accounts/password/set/",
    "account_inactive": "/accounts/inactive/",
    "socialaccount_login_cancelled": "/accounts/3rdparty/login/cancelled/",
    "socialaccount_login_error": "/accounts/3rdparty/login/error/",
    "socialaccount_signup": "/accounts/3rdparty/signup/",
    "socialaccount_connections": "/accounts/3rdparty/",
    "<unnamed:accounts/social/login/cancelled/>": "/accounts/social/login/cancelled/",
    "<unnamed:accounts/social/login/error/>": "/accounts/social/login/error/",
    "<unnamed:accounts/social/signup/>": "/accounts/social/signup/",
    "<unnamed:accounts/social/connections/>": "/accounts/social/connections/",
}

# Object-state variants for enrolled-class routes:
# Each variant maps route_key -> {method: {actor: expected_int_status}}
ENROLLED_OBJECT_STATE_EXPECTATIONS: dict[str, dict[str, dict[str, dict[str, int]]]] = {
    "draft_lesson": {
        "learn:lesson": {
            "GET": {
                "guest": 404,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "learn:toggle_complete": {
            "POST": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "learn:playback_position": {
            "POST": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
    },
    "assignment_unpublished_lesson": {
        "assignments:detail": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 302,
                "student_pending": 302,
                "student_revoked": 302,
                "student_active": 404,
                "student_other_course": 302,
                "teacher": 200,
                "superuser": 200,
            },
            "POST": {
                "guest": 302,
                "student_unenrolled": 302,
                "student_pending": 302,
                "student_revoked": 302,
                "student_active": 404,
                "student_other_course": 302,
                "teacher": 302,
                "superuser": 302,
            },
        },
        "assignments:download": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 403,
                "student_pending": 403,
                "student_revoked": 403,
                "student_active": 404,
                "student_other_course": 403,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "assignments:attachment_download": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 403,
                "student_pending": 403,
                "student_revoked": 403,
                "student_active": 404,
                "student_other_course": 403,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "assignments:attachment_preview": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 403,
                "student_pending": 403,
                "student_revoked": 403,
                "student_active": 404,
                "student_other_course": 403,
                "teacher": 200,
                "superuser": 200,
            }
        },
    },
    "unpublished_assignment": {
        "assignments:detail": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 302,
                "student_pending": 302,
                "student_revoked": 302,
                "student_active": 404,
                "student_other_course": 302,
                "teacher": 200,
                "superuser": 200,
            },
            "POST": {
                "guest": 302,
                "student_unenrolled": 302,
                "student_pending": 302,
                "student_revoked": 302,
                "student_active": 404,
                "student_other_course": 302,
                "teacher": 302,
                "superuser": 302,
            },
        },
        "assignments:download": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 403,
                "student_pending": 403,
                "student_revoked": 403,
                "student_active": 404,
                "student_other_course": 403,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "assignments:attachment_download": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 403,
                "student_pending": 403,
                "student_revoked": 403,
                "student_active": 404,
                "student_other_course": 403,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "assignments:attachment_preview": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 403,
                "student_pending": 403,
                "student_revoked": 403,
                "student_active": 404,
                "student_other_course": 403,
                "teacher": 200,
                "superuser": 200,
            }
        },
    },
    "assignment_before_opens_at": {
        "assignments:detail": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 302,
                "student_pending": 302,
                "student_revoked": 302,
                "student_active": 200,
                "student_other_course": 302,
                "teacher": 200,
                "superuser": 200,
            },
            "POST": {
                "guest": 302,
                "student_unenrolled": 302,
                "student_pending": 302,
                "student_revoked": 302,
                "student_active": 400,
                "student_other_course": 302,
                "teacher": 400,
                "superuser": 400,
            },
        },
        "assignments:attachment_download": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 403,
                "student_pending": 403,
                "student_revoked": 403,
                "student_active": 404,
                "student_other_course": 403,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "assignments:attachment_preview": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 403,
                "student_pending": 403,
                "student_revoked": 403,
                "student_active": 404,
                "student_other_course": 403,
                "teacher": 200,
                "superuser": 200,
            }
        },
    },
    "unpublished_attachment": {
        "assignments:attachment_download": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 403,
                "student_pending": 403,
                "student_revoked": 403,
                "student_active": 404,
                "student_other_course": 403,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "assignments:attachment_preview": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 403,
                "student_pending": 403,
                "student_revoked": 403,
                "student_active": 404,
                "student_other_course": 403,
                "teacher": 200,
                "superuser": 200,
            }
        },
    },
    "archived_course": {
        "learn:course": {
            "GET": {
                "guest": 404,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 302,
                "student_other_course": 404,
                "teacher": 302,
                "superuser": 302,
            }
        },
        "learn:lesson": {
            "GET": {
                "guest": 404,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 200,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "learn:toggle_complete": {
            "POST": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 200,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "learn:playback_position": {
            "POST": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 200,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "learn:materials": {
            "GET": {
                "guest": 404,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 200,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "learn:material_request": {
            "POST": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 302,
                "student_other_course": 404,
                "teacher": 302,
                "superuser": 302,
            }
        },
        "learn:material_cancel": {
            "POST": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 302,
                "student_other_course": 404,
                "teacher": 302,
                "superuser": 302,
            }
        },
        "learn:material_download": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 200,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "learn:material_preview": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 200,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "assignments:list": {
            "GET": {
                "guest": 404,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 200,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "assignments:detail": {
            "GET": {
                "guest": 404,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 200,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "assignments:download": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 200,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "assignments:attachment_download": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 200,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "assignments:attachment_preview": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 200,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
    },
    "unpublished_course": {
        "learn:course": {
            "GET": {
                "guest": 404,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 302,
                "superuser": 302,
            }
        },
        "learn:lesson": {
            "GET": {
                "guest": 404,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "learn:toggle_complete": {
            "POST": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "learn:playback_position": {
            "POST": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "learn:materials": {
            "GET": {
                "guest": 404,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "learn:material_request": {
            "POST": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 302,
                "superuser": 302,
            }
        },
        "learn:material_cancel": {
            "POST": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 302,
                "superuser": 302,
            }
        },
        "learn:material_download": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "learn:material_preview": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "assignments:list": {
            "GET": {
                "guest": 404,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "assignments:detail": {
            "GET": {
                "guest": 404,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "assignments:download": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "assignments:attachment_download": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
        "assignments:attachment_preview": {
            "GET": {
                "guest": 302,
                "student_unenrolled": 404,
                "student_pending": 404,
                "student_revoked": 404,
                "student_active": 404,
                "student_other_course": 404,
                "teacher": 200,
                "superuser": 200,
            }
        },
    },
}


# Explicit exemptions for POST-capable routes that do not use our @track_ratelimit decorator
# (e.g., third-party allauth views enforced via ACCOUNT_RATE_LIMITS or session-authenticated utility endpoints).
POST_RATELIMIT_EXEMPTIONS: dict[str, str] = {
    "account_logout": "Session termination endpoint; no abuse vector and safe to call repeatedly.",
    "account_change_password": "Authenticated password change protected by current password verification.",
    "account_reset_password": "Enforced by allauth ACCOUNT_RATE_LIMITS['reset_password'] (20/m/ip, 5/m/key).",
    "account_confirm_email": "Enforced by allauth ACCOUNT_RATE_LIMITS['confirm_email'] (10/m/ip, 3/180s/key).",
    "account_reset_password_from_key": "Enforced by allauth ACCOUNT_RATE_LIMITS['reset_password_from_key'] (20/m/ip).",
    "admin:login": "Shadowed in config.urls by rate_limited_admin_login_view (admin_login, 20/m/ip).",
    "admin:logout": "Admin session termination endpoint; requires active staff/superuser session.",
    "admin:password_change": "Admin password change protected by current password verification and staff/superuser check.",
    "admin:auth_user_password_change": "Admin user password change form protected by staff/superuser session and change_user permission.",
}

# Explicit exemptions for mutating routes that do not use a payload factory in the generic matrix runner
MUTATING_PAYLOAD_FACTORY_EXEMPTIONS: dict[str, str] = {
    "admin:login": "Shadowed at /admin/login/ by top-level rate_limited_admin_login_view (admin_login), which is tested with a full payload factory.",
}


def _build_admin_model_routes() -> dict[str, RouteAccessSpec]:
    """
    Build explicit RouteAccessSpec entries for all registered Django admin model routes.
    Every actor maps to ONE exact status code:
    - Non-staff (`guest`..`student_other_course`): 302 (redirect to `admin:login`)
    - Non-superuser staff (`teacher`, no model permissions): 403 Forbidden
    - `superuser`: 200 (except disabled singleton/audit actions which return 403)
    """
    specs: dict[str, RouteAccessSpec] = {}
    admin_models = [
        ("auth", "group"),
        ("account", "emailaddress"),
        ("socialaccount", "socialapp"),
        ("socialaccount", "socialtoken"),
        ("socialaccount", "socialaccount"),
        ("core", "sitesettings"),
        ("core", "faqitem"),
        ("accounts", "user"),
        ("courses", "course"),
        ("courses", "lesson"),
        ("courses", "enrollment"),
        ("courses", "enrollmentevent"),
        ("courses", "lessonprogress"),
        ("courses", "coursematerial"),
        ("courses", "materialitem"),
        ("courses", "downloadrequest"),
        ("courses", "downloadlog"),
        ("assignments", "assignment"),
        ("assignments", "submission"),
        ("assignments", "submissionevent"),
    ]
    for app_label, model_name in admin_models:
        prefix = f"admin:{app_label}_{model_name}"
        specs[f"{prefix}_changelist"] = RouteAccessSpec(
            route_key=f"{prefix}_changelist",
            classification="teacher",
            methods=("GET",),
            actor_overrides={
                "student_unenrolled": 302,
                "student_pending": 302,
                "student_revoked": 302,
                "student_active": 302,
                "student_other_course": 302,
                "teacher": 403,
            },
            exception_reason="Django admin redirects non-staff to admin:login (302); non-superuser teacher lacks model view/change permission (403).",
            description=f"Admin {model_name} changelist",
        )
        if (app_label, model_name) in {("courses", "downloadlog"), ("core", "sitesettings")}:
            specs[f"{prefix}_add"] = RouteAccessSpec(
                route_key=f"{prefix}_add",
                classification="teacher",
                methods=("GET",),
                actor_overrides={
                    "student_unenrolled": 302,
                    "student_pending": 302,
                    "student_revoked": 302,
                    "student_active": 302,
                    "student_other_course": 302,
                    "teacher": 403,
                    "superuser": 403,
                },
                exception_reason=(
                    "DownloadLogAdmin disables add (immutable audit log -> 403); "
                    "SiteSettingsAdmin disables add once the singleton row exists (403)."
                ),
                description=f"Admin {model_name} add (disabled)",
            )
        else:
            specs[f"{prefix}_add"] = RouteAccessSpec(
                route_key=f"{prefix}_add",
                classification="teacher",
                methods=("GET",),
                actor_overrides={
                    "student_unenrolled": 302,
                    "student_pending": 302,
                    "student_revoked": 302,
                    "student_active": 302,
                    "student_other_course": 302,
                    "teacher": 403,
                },
                exception_reason="Django admin redirects non-staff to login (302); non-superuser teacher lacks model add permission (403).",
                description=f"Admin {model_name} add",
            )

        specs[f"{prefix}_history"] = RouteAccessSpec(
            route_key=f"{prefix}_history",
            classification="teacher",
            methods=("GET",),
            actor_overrides={
                "student_unenrolled": 302,
                "student_pending": 302,
                "student_revoked": 302,
                "student_active": 302,
                "student_other_course": 302,
                "teacher": 403,
            },
            exception_reason="Django admin redirects non-staff to login (302); non-superuser teacher lacks model view/change permission (403).",
            description=f"Admin {model_name} history",
        )
        if (app_label, model_name) == ("core", "sitesettings"):
            specs[f"{prefix}_delete"] = RouteAccessSpec(
                route_key=f"{prefix}_delete",
                classification="teacher",
                methods=("GET",),
                actor_overrides={
                    "student_unenrolled": 302,
                    "student_pending": 302,
                    "student_revoked": 302,
                    "student_active": 302,
                    "student_other_course": 302,
                    "teacher": 403,
                    "superuser": 403,
                },
                exception_reason="SiteSettingsAdmin disables deletion on the singleton SiteSettings row (has_delete_permission=False -> 403).",
                description="Admin sitesettings delete (disabled)",
            )
        else:
            specs[f"{prefix}_delete"] = RouteAccessSpec(
                route_key=f"{prefix}_delete",
                classification="teacher",
                methods=("GET",),
                actor_overrides={
                    "student_unenrolled": 302,
                    "student_pending": 302,
                    "student_revoked": 302,
                    "student_active": 302,
                    "student_other_course": 302,
                    "teacher": 403,
                },
                exception_reason="Django admin redirects non-staff to login (302); non-superuser teacher lacks model delete permission (403).",
                description=f"Admin {model_name} delete",
            )

        specs[f"{prefix}_change"] = RouteAccessSpec(
            route_key=f"{prefix}_change",
            classification="teacher",
            methods=("GET",),
            actor_overrides={
                "student_unenrolled": 302,
                "student_pending": 302,
                "student_revoked": 302,
                "student_active": 302,
                "student_other_course": 302,
                "teacher": 403,
            },
            exception_reason="Django admin redirects non-staff to login (302); non-superuser teacher lacks model view/change permission (403).",
            description=f"Admin {model_name} change",
        )
        unnamed_key = f"<unnamed:admin/{app_label}/{model_name}/<path:object_id>/>"
        specs[unnamed_key] = RouteAccessSpec(
            route_key=unnamed_key,
            classification="public",
            methods=("GET",),
            actor_overrides=dict.fromkeys(ACTORS, 302),
            exception_reason="Django admin RedirectView redirects <object_id>/ to <object_id>/change/ with HTTP 302.",
            description=f"Admin {model_name} object redirect",
        )

    return specs


ACCESS_MATRIX: dict[str, RouteAccessSpec] = {
    # =========================================================================
    # 1. Core & Public Routes
    # =========================================================================
    "core:home": RouteAccessSpec(
        route_key="core:home",
        classification="public",
        methods=("GET",),
        description="Public landing page",
    ),
    "core:privacy": RouteAccessSpec(
        route_key="core:privacy",
        classification="public",
        methods=("GET",),
        description="Privacy policy page",
    ),
    "core:terms": RouteAccessSpec(
        route_key="core:terms",
        classification="public",
        methods=("GET",),
        description="Terms of service page",
    ),
    "core:healthz": RouteAccessSpec(
        route_key="core:healthz",
        classification="public",
        methods=("GET",),
        description="Health check probe",
    ),
    "core:robots_txt": RouteAccessSpec(
        route_key="core:robots_txt",
        classification="public",
        methods=("GET",),
        description="Robots.txt (core namespace)",
    ),
    "robots_txt": RouteAccessSpec(
        route_key="robots_txt",
        classification="public",
        methods=("GET",),
        description="Robots.txt (root)",
    ),
    "favicon": RouteAccessSpec(
        route_key="favicon",
        classification="public",
        methods=("GET",),
        actor_overrides=dict.fromkeys(ACTORS, 301),
        exception_reason="Permanent RedirectView (301) to /static/favicon.ico.",
        description="Favicon redirect",
    ),
    "django.contrib.sitemaps.views.sitemap": RouteAccessSpec(
        route_key="django.contrib.sitemaps.views.sitemap",
        classification="public",
        methods=("GET",),
        description="XML sitemap",
    ),
    "styleguide": RouteAccessSpec(
        route_key="styleguide",
        classification="test-only",
        methods=("GET",),
        description="Debug-only UI styleguide (raises 404 when DEBUG=False)",
    ),
    # =========================================================================
    # 2. Authentication & Kept Allauth Routes
    # =========================================================================
    "account_login": RouteAccessSpec(
        route_key="account_login",
        classification="public",
        methods=("GET", "POST"),
        ratelimit="get_client_ip:60/m",
        actor_overrides={
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 302,
            "student_other_course": 302,
            "teacher": 302,
            "superuser": 302,
        },
        exception_reason="Already-authenticated users visiting login are redirected to their dashboard (302).",
        description="User login page and form submission",
    ),
    "account_signup": RouteAccessSpec(
        route_key="account_signup",
        classification="public",
        methods=("GET", "POST"),
        ratelimit="get_client_ip:30/m",
        actor_overrides={
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 302,
            "student_other_course": 302,
            "teacher": 302,
            "superuser": 302,
        },
        exception_reason="Already-authenticated users visiting signup are redirected to their dashboard (302).",
        description="Student signup page and form submission",
    ),
    "google_login": RouteAccessSpec(
        route_key="google_login",
        classification="public",
        methods=("GET", "POST"),
        ratelimit="get_client_ip:30/m",
        actor_overrides=dict.fromkeys(ACTORS, 302),
        exception_reason="Initiates OAuth flow or redirects cleanly to account_login (302) if credentials are unset.",
        description="Google OAuth login initiation",
    ),
    "account_logout": RouteAccessSpec(
        route_key="account_logout",
        classification="authenticated",
        methods=("GET", "POST"),
        description="Logout confirmation (GET 200) and session logout (POST 302)",
    ),
    "account_change_password": RouteAccessSpec(
        route_key="account_change_password",
        classification="authenticated",
        methods=("GET", "POST"),
        description="Authenticated password change",
    ),
    "account_reset_password": RouteAccessSpec(
        route_key="account_reset_password",
        classification="public",
        methods=("GET", "POST"),
        description="Password reset request form",
    ),
    "account_reset_password_done": RouteAccessSpec(
        route_key="account_reset_password_done",
        classification="public",
        methods=("GET",),
        description="Password reset email sent confirmation",
    ),
    "account_reset_password_from_key": RouteAccessSpec(
        route_key="account_reset_password_from_key",
        classification="public",
        methods=("GET", "POST"),
        description="Password reset from token link",
    ),
    "account_reset_password_from_key_done": RouteAccessSpec(
        route_key="account_reset_password_from_key_done",
        classification="public",
        methods=("GET",),
        description="Password reset complete page",
    ),
    "account_email_verification_sent": RouteAccessSpec(
        route_key="account_email_verification_sent",
        classification="public",
        methods=("GET",),
        description="Email verification sent notice",
    ),
    "account_confirm_email": RouteAccessSpec(
        route_key="account_confirm_email",
        classification="public",
        methods=("GET", "POST"),
        description="Email confirmation from key",
    ),
    "google_callback": RouteAccessSpec(
        route_key="google_callback",
        classification="public",
        methods=("GET",),
        actor_overrides=dict.fromkeys(ACTORS, 401),
        exception_reason="OAuth2 callback without an active session state/code renders authentication_error.html with HTTP 401.",
        description="Google OAuth2 callback",
    ),
    # =========================================================================
    # 3. Public Courses & Enrollment Request
    # =========================================================================
    "courses:list": RouteAccessSpec(
        route_key="courses:list",
        classification="public",
        methods=("GET",),
        description="Public course catalog",
    ),
    "courses:detail": RouteAccessSpec(
        route_key="courses:detail",
        classification="public",
        methods=("GET",),
        description="Public course detail and syllabus",
    ),
    "courses:enroll": RouteAccessSpec(
        route_key="courses:enroll",
        classification="authenticated",
        methods=("POST",),
        ratelimit="user:20/m",
        description="Request enrollment in a free course",
    ),
    # =========================================================================
    # 4. Student Learning & Course Materials (`learn` namespace)
    # =========================================================================
    "learn:course": RouteAccessSpec(
        route_key="learn:course",
        classification="enrolled",
        methods=("GET",),
        actor_overrides={
            "student_active": 302,
            "teacher": 302,
            "superuser": 302,
        },
        exception_reason="Course learn root is a resume dispatcher that always redirects (302) to the target lesson URL.",
        description="Course resume redirect view",
    ),
    "learn:lesson": RouteAccessSpec(
        route_key="learn:lesson",
        classification="enrolled",
        methods=("GET",),
        description="Lesson video player and syllabus view",
    ),
    "learn:toggle_complete": RouteAccessSpec(
        route_key="learn:toggle_complete",
        classification="enrolled",
        methods=("POST",),
        ratelimit="user:60/m",
        actor_overrides={
            "student_active": 200,
            "teacher": 200,
            "superuser": 200,
        },
        exception_reason="JSON API endpoint returns 200 JSON on success; guests get 302 to login and unauthorized users get 403.",
        description="AJAX toggle lesson completion",
    ),
    "learn:playback_position": RouteAccessSpec(
        route_key="learn:playback_position",
        classification="enrolled",
        methods=("POST",),
        ratelimit="user:120/m",
        actor_overrides={
            "student_active": 200,
            "teacher": 200,
            "superuser": 200,
        },
        exception_reason="JSON API endpoint returns 200 JSON on success; guests get 302 to login and unauthorized users get 403.",
        description="AJAX save video playback position",
    ),
    "learn:materials": RouteAccessSpec(
        route_key="learn:materials",
        classification="enrolled",
        methods=("GET",),
        description="Enrolled course materials list",
    ),
    "learn:material_request": RouteAccessSpec(
        route_key="learn:material_request",
        classification="enrolled",
        methods=("POST",),
        ratelimit="user:15/m",
        description="Student request access to a request_required material item",
    ),
    "learn:material_cancel": RouteAccessSpec(
        route_key="learn:material_cancel",
        classification="enrolled",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Student cancel pending material download request",
    ),
    "learn:material_download": RouteAccessSpec(
        route_key="learn:material_download",
        classification="enrolled",
        methods=("GET",),
        ratelimit="user:60/m",
        actor_overrides={
            "student_unenrolled": 403,
            "student_pending": 403,
            "student_revoked": 403,
            "student_other_course": 403,
        },
        exception_reason="File download endpoint uses API mode (403 Forbidden instead of 302 redirect) when enrollment is missing/inactive.",
        description="Enrolled material file download",
    ),
    "learn:material_preview": RouteAccessSpec(
        route_key="learn:material_preview",
        classification="enrolled",
        methods=("GET",),
        ratelimit="user:60/m",
        actor_overrides={
            "student_unenrolled": 403,
            "student_pending": 403,
            "student_revoked": 403,
            "student_other_course": 403,
        },
        exception_reason="Isolated iframe file preview endpoint uses API mode (403 Forbidden instead of 302 redirect) when enrollment is missing/inactive.",
        description="In-browser PDF/image material preview",
    ),
    # =========================================================================
    # 5. Assignments & Submissions (`assignments` namespace)
    # =========================================================================
    "assignments:list": RouteAccessSpec(
        route_key="assignments:list",
        classification="enrolled",
        methods=("GET",),
        description="Course assignments list for enrolled students",
    ),
    "assignments:detail": RouteAccessSpec(
        route_key="assignments:detail",
        classification="enrolled",
        methods=("GET", "POST"),
        ratelimit="user:30/h,user:10/m",
        description="Assignment detail and submission upload view",
    ),
    "assignments:download": RouteAccessSpec(
        route_key="assignments:download",
        classification="enrolled",
        methods=("GET",),
        ratelimit="user:60/m",
        actor_overrides={
            "student_unenrolled": 403,
            "student_pending": 403,
            "student_revoked": 403,
            "student_other_course": 403,
        },
        exception_reason="Private submission file download returns 403 Forbidden for non-enrolled users or other students.",
        description="Private submission file download (submitting student or teacher)",
    ),
    "assignments:attachment_download": RouteAccessSpec(
        route_key="assignments:attachment_download",
        classification="enrolled",
        methods=("GET",),
        ratelimit="user:60/m",
        actor_overrides={
            "student_unenrolled": 403,
            "student_pending": 403,
            "student_revoked": 403,
            "student_other_course": 403,
        },
        exception_reason="Private assignment attachment download returns 403 Forbidden when enrollment is missing/inactive.",
        description="Assignment attachment download",
    ),
    "assignments:attachment_preview": RouteAccessSpec(
        route_key="assignments:attachment_preview",
        classification="enrolled",
        methods=("GET",),
        ratelimit="user:60/m",
        actor_overrides={
            "student_unenrolled": 403,
            "student_pending": 403,
            "student_revoked": 403,
            "student_other_course": 403,
        },
        exception_reason="Isolated iframe attachment preview returns 403 Forbidden when enrollment is missing/inactive.",
        description="In-browser PDF/image assignment attachment preview",
    ),
    # =========================================================================
    # 6. Notifications (`notifications` namespace)
    # =========================================================================
    "notifications:list": RouteAccessSpec(
        route_key="notifications:list",
        classification="authenticated",
        methods=("GET",),
        description="Authenticated user notification center",
    ),
    "notifications:mark_read": RouteAccessSpec(
        route_key="notifications:mark_read",
        classification="authenticated",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Mark a single user notification as read",
    ),
    "notifications:mark_all_read": RouteAccessSpec(
        route_key="notifications:mark_all_read",
        classification="authenticated",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Mark all unread user notifications as read",
    ),
    # =========================================================================
    # 7. Dashboards (`dashboard` namespace)
    # =========================================================================
    "dashboard:student": RouteAccessSpec(
        route_key="dashboard:student",
        classification="authenticated",
        methods=("GET",),
        description="Student learning dashboard",
    ),
    "dashboard:teacher": RouteAccessSpec(
        route_key="dashboard:teacher",
        classification="teacher",
        methods=("GET",),
        description="Teacher administration portal overview",
    ),
    "dashboard:teacher_permissions": RouteAccessSpec(
        route_key="dashboard:teacher_permissions",
        classification="teacher",
        methods=("GET",),
        description="Teacher download permissions queue",
    ),
    "dashboard:teacher_permission_action": RouteAccessSpec(
        route_key="dashboard:teacher_permission_action",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Approve/deny/revoke single download request",
    ),
    "dashboard:teacher_permissions_bulk_action": RouteAccessSpec(
        route_key="dashboard:teacher_permissions_bulk_action",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Bulk approve/deny download requests",
    ),
    "dashboard:teacher_approve_for_all": RouteAccessSpec(
        route_key="dashboard:teacher_approve_for_all",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Switch material item to open_to_enrolled and approve pending",
    ),
    "dashboard:teacher_download_history": RouteAccessSpec(
        route_key="dashboard:teacher_download_history",
        classification="teacher",
        methods=("GET",),
        description="Per-item download audit log (from permissions queue)",
    ),
    "dashboard:teacher_courses": RouteAccessSpec(
        route_key="dashboard:teacher_courses",
        classification="teacher",
        methods=("GET",),
        description="Teacher course management list",
    ),
    "dashboard:teacher_course_create": RouteAccessSpec(
        route_key="dashboard:teacher_course_create",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher create course",
    ),
    "dashboard:teacher_course_edit": RouteAccessSpec(
        route_key="dashboard:teacher_course_edit",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher edit course",
    ),
    "dashboard:teacher_course_archive": RouteAccessSpec(
        route_key="dashboard:teacher_course_archive",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Teacher archive or restore course",
    ),
    "dashboard:teacher_lessons": RouteAccessSpec(
        route_key="dashboard:teacher_lessons",
        classification="teacher",
        methods=("GET",),
        description="Teacher course lessons list",
    ),
    "dashboard:teacher_course_lessons": RouteAccessSpec(
        route_key="dashboard:teacher_course_lessons",
        classification="teacher",
        methods=("GET",),
        description="Teacher course lessons list (alias)",
    ),
    "dashboard:teacher_lesson_create": RouteAccessSpec(
        route_key="dashboard:teacher_lesson_create",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher create lesson",
    ),
    "dashboard:teacher_course_lesson_create": RouteAccessSpec(
        route_key="dashboard:teacher_course_lesson_create",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher create lesson (alias)",
    ),
    "dashboard:teacher_lesson_edit": RouteAccessSpec(
        route_key="dashboard:teacher_lesson_edit",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher edit lesson",
    ),
    "dashboard:teacher_course_lesson_edit": RouteAccessSpec(
        route_key="dashboard:teacher_course_lesson_edit",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher edit lesson (alias)",
    ),
    "dashboard:teacher_lesson_toggle_publish": RouteAccessSpec(
        route_key="dashboard:teacher_lesson_toggle_publish",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Teacher toggle lesson published state",
    ),
    "dashboard:teacher_course_lesson_toggle_publish": RouteAccessSpec(
        route_key="dashboard:teacher_course_lesson_toggle_publish",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Teacher toggle lesson published state (alias)",
    ),
    "dashboard:teacher_lesson_reorder": RouteAccessSpec(
        route_key="dashboard:teacher_lesson_reorder",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Teacher reorder lesson",
    ),
    "dashboard:teacher_course_lesson_reorder": RouteAccessSpec(
        route_key="dashboard:teacher_course_lesson_reorder",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Teacher reorder lesson (alias)",
    ),
    "dashboard:teacher_lesson_delete": RouteAccessSpec(
        route_key="dashboard:teacher_lesson_delete",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Teacher delete lesson",
    ),
    "dashboard:teacher_course_lesson_delete": RouteAccessSpec(
        route_key="dashboard:teacher_course_lesson_delete",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Teacher delete lesson (alias)",
    ),
    "dashboard:teacher_assignments": RouteAccessSpec(
        route_key="dashboard:teacher_assignments",
        classification="teacher",
        methods=("GET",),
        description="Teacher course assignments list",
    ),
    "dashboard:teacher_course_assignments": RouteAccessSpec(
        route_key="dashboard:teacher_course_assignments",
        classification="teacher",
        methods=("GET",),
        description="Teacher course assignments list (alias)",
    ),
    "dashboard:teacher_assignment_create": RouteAccessSpec(
        route_key="dashboard:teacher_assignment_create",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher create assignment",
    ),
    "dashboard:teacher_course_assignment_create": RouteAccessSpec(
        route_key="dashboard:teacher_course_assignment_create",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher create assignment (alias)",
    ),
    "dashboard:teacher_assignment_edit": RouteAccessSpec(
        route_key="dashboard:teacher_assignment_edit",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher edit assignment",
    ),
    "dashboard:teacher_course_assignment_edit": RouteAccessSpec(
        route_key="dashboard:teacher_course_assignment_edit",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher edit assignment (alias)",
    ),
    "dashboard:teacher_assignment_toggle_publish": RouteAccessSpec(
        route_key="dashboard:teacher_assignment_toggle_publish",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Teacher toggle assignment published state",
    ),
    "dashboard:teacher_course_assignment_toggle_publish": RouteAccessSpec(
        route_key="dashboard:teacher_course_assignment_toggle_publish",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Teacher toggle assignment published state (alias)",
    ),
    "dashboard:teacher_assignment_delete": RouteAccessSpec(
        route_key="dashboard:teacher_assignment_delete",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Teacher delete assignment",
    ),
    "dashboard:teacher_course_assignment_delete": RouteAccessSpec(
        route_key="dashboard:teacher_course_assignment_delete",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Teacher delete assignment (alias)",
    ),
    "dashboard:teacher_assignment_attachment_add": RouteAccessSpec(
        route_key="dashboard:teacher_assignment_attachment_add",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Teacher add assignment attachment",
    ),
    "dashboard:teacher_assignment_attachment_edit": RouteAccessSpec(
        route_key="dashboard:teacher_assignment_attachment_edit",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Teacher edit assignment attachment",
    ),
    "dashboard:teacher_assignment_attachment_toggle_publish": RouteAccessSpec(
        route_key="dashboard:teacher_assignment_attachment_toggle_publish",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Teacher toggle assignment attachment visibility",
    ),
    "dashboard:teacher_assignment_attachment_reorder": RouteAccessSpec(
        route_key="dashboard:teacher_assignment_attachment_reorder",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Teacher reorder assignment attachment",
    ),
    "dashboard:teacher_assignment_attachment_delete": RouteAccessSpec(
        route_key="dashboard:teacher_assignment_attachment_delete",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Teacher delete assignment attachment",
    ),
    "dashboard:teacher_assignment_attachment_downloads": RouteAccessSpec(
        route_key="dashboard:teacher_assignment_attachment_downloads",
        classification="teacher",
        methods=("GET",),
        description="Teacher view assignment attachment download history",
    ),
    "dashboard:teacher_enrollments": RouteAccessSpec(
        route_key="dashboard:teacher_enrollments",
        classification="teacher",
        methods=("GET",),
        description="Teacher enrollments management queue",
    ),
    "dashboard:teacher_enrollment_action": RouteAccessSpec(
        route_key="dashboard:teacher_enrollment_action",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Teacher approve/revoke single enrollment",
    ),
    "dashboard:teacher_enrollments_bulk_action": RouteAccessSpec(
        route_key="dashboard:teacher_enrollments_bulk_action",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Teacher bulk approve/revoke enrollments",
    ),
    "dashboard:teacher_enrollment_manual": RouteAccessSpec(
        route_key="dashboard:teacher_enrollment_manual",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Teacher manual student enrollment",
    ),
    "dashboard:teacher_submissions": RouteAccessSpec(
        route_key="dashboard:teacher_submissions",
        classification="teacher",
        methods=("GET",),
        description="Teacher global submissions queue",
    ),
    "dashboard:teacher_course_assignment_submissions": RouteAccessSpec(
        route_key="dashboard:teacher_course_assignment_submissions",
        classification="teacher",
        methods=("GET",),
        description="Teacher per-assignment submissions queue",
    ),
    "dashboard:teacher_missed_deadlines": RouteAccessSpec(
        route_key="dashboard:teacher_missed_deadlines",
        classification="teacher",
        methods=("GET",),
        description="Teacher missed deadlines report",
    ),
    "dashboard:teacher_submission_grade": RouteAccessSpec(
        route_key="dashboard:teacher_submission_grade",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:60/m",
        description="Teacher grade submission view",
    ),
    "dashboard:teacher_submission_unlock": RouteAccessSpec(
        route_key="dashboard:teacher_submission_unlock",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Teacher unlock graded submission for resubmission",
    ),
    "dashboard:teacher_students": RouteAccessSpec(
        route_key="dashboard:teacher_students",
        classification="teacher",
        methods=("GET",),
        ratelimit="user:60/m",
        description="Teacher student directory",
    ),
    "dashboard:teacher_student_detail": RouteAccessSpec(
        route_key="dashboard:teacher_student_detail",
        classification="teacher",
        methods=("GET",),
        description="Teacher student detail and progress profile",
    ),
    "dashboard:teacher_student_toggle_active": RouteAccessSpec(
        route_key="dashboard:teacher_student_toggle_active",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Teacher activate/deactivate student account",
    ),
    "dashboard:teacher_course_grades_export": RouteAccessSpec(
        route_key="dashboard:teacher_course_grades_export",
        classification="teacher",
        methods=("GET",),
        ratelimit="user:10/m",
        description="Teacher course grades CSV export",
    ),
    "dashboard:teacher_course_progress_export": RouteAccessSpec(
        route_key="dashboard:teacher_course_progress_export",
        classification="teacher",
        methods=("GET",),
        ratelimit="user:10/m",
        description="Teacher course progress CSV export",
    ),
    "dashboard:teacher_materials": RouteAccessSpec(
        route_key="dashboard:teacher_materials",
        classification="teacher",
        methods=("GET",),
        description="Teacher materials course picker",
    ),
    "dashboard:teacher_course_materials": RouteAccessSpec(
        route_key="dashboard:teacher_course_materials",
        classification="teacher",
        methods=("GET",),
        description="Teacher course materials management list",
    ),
    "dashboard:teacher_material_create": RouteAccessSpec(
        route_key="dashboard:teacher_material_create",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher create course material container",
    ),
    "dashboard:teacher_material_edit": RouteAccessSpec(
        route_key="dashboard:teacher_material_edit",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher edit course material container",
    ),
    "dashboard:teacher_material_toggle_publish": RouteAccessSpec(
        route_key="dashboard:teacher_material_toggle_publish",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Teacher toggle course material published state",
    ),
    "dashboard:teacher_material_archive": RouteAccessSpec(
        route_key="dashboard:teacher_material_archive",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Teacher archive/unarchive course material",
    ),
    "dashboard:teacher_material_delete": RouteAccessSpec(
        route_key="dashboard:teacher_material_delete",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Teacher delete course material",
    ),
    "dashboard:teacher_material_item_create": RouteAccessSpec(
        route_key="dashboard:teacher_material_item_create",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher create material item",
    ),
    "dashboard:teacher_material_item_edit": RouteAccessSpec(
        route_key="dashboard:teacher_material_item_edit",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher edit material item",
    ),
    "dashboard:teacher_material_item_toggle_publish": RouteAccessSpec(
        route_key="dashboard:teacher_material_item_toggle_publish",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Teacher toggle material item published state",
    ),
    "dashboard:teacher_material_item_delete": RouteAccessSpec(
        route_key="dashboard:teacher_material_item_delete",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Teacher delete material item",
    ),
    "dashboard:teacher_material_item_reorder": RouteAccessSpec(
        route_key="dashboard:teacher_material_item_reorder",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Teacher reorder material item",
    ),
    "dashboard:teacher_material_item_policy": RouteAccessSpec(
        route_key="dashboard:teacher_material_item_policy",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher material item download policy transition",
    ),
    "dashboard:teacher_material_item_history": RouteAccessSpec(
        route_key="dashboard:teacher_material_item_history",
        classification="teacher",
        methods=("GET",),
        description="Teacher material item download history",
    ),
    "dashboard:teacher_settings": RouteAccessSpec(
        route_key="dashboard:teacher_settings",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher global site settings configuration",
    ),
    "dashboard:teacher_faqs": RouteAccessSpec(
        route_key="dashboard:teacher_faqs",
        classification="teacher",
        methods=("GET",),
        description="Teacher FAQs management list",
    ),
    "dashboard:teacher_faq_create": RouteAccessSpec(
        route_key="dashboard:teacher_faq_create",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher create FAQ item",
    ),
    "dashboard:teacher_faq_edit": RouteAccessSpec(
        route_key="dashboard:teacher_faq_edit",
        classification="teacher",
        methods=("GET", "POST"),
        ratelimit="user:30/m",
        description="Teacher edit FAQ item",
    ),
    "dashboard:teacher_faq_toggle_publish": RouteAccessSpec(
        route_key="dashboard:teacher_faq_toggle_publish",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Teacher toggle FAQ published state",
    ),
    "dashboard:teacher_faq_reorder": RouteAccessSpec(
        route_key="dashboard:teacher_faq_reorder",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:60/m",
        description="Teacher reorder FAQ item",
    ),
    "dashboard:teacher_faq_delete": RouteAccessSpec(
        route_key="dashboard:teacher_faq_delete",
        classification="teacher",
        methods=("POST",),
        ratelimit="user:30/m",
        description="Teacher delete FAQ item",
    ),
    # =========================================================================
    # 8. Django Admin Core Routes
    # =========================================================================
    "admin_login": RouteAccessSpec(
        route_key="admin_login",
        classification="public",
        methods=("GET", "POST"),
        ratelimit="get_client_ip:20/m",
        actor_overrides={
            "teacher": 302,
            "superuser": 302,
        },
        exception_reason="Staff/superuser already logged in are redirected to admin:index (302); guests and non-staff see login page (200).",
        description="Rate-limited Django admin login wrapper",
    ),
    "admin:login": RouteAccessSpec(
        route_key="admin:login",
        classification="public",
        methods=("GET", "POST"),
        ratelimit=None,
        actor_overrides={
            "teacher": 302,
            "superuser": 302,
        },
        exception_reason="Shadowed at /admin/login/ by rate_limited_admin_login_view.",
        description="Django admin built-in login (shadowed)",
    ),
    "admin:index": RouteAccessSpec(
        route_key="admin:index",
        classification="teacher",
        methods=("GET",),
        actor_overrides={
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 302,
            "student_other_course": 302,
        },
        exception_reason="Django admin redirects non-staff users to admin:login (302).",
        description="Django admin index dashboard",
    ),
    "admin:logout": RouteAccessSpec(
        route_key="admin:logout",
        classification="teacher",
        methods=("POST",),
        actor_overrides={
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 302,
            "student_other_course": 302,
            "teacher": 200,
            "superuser": 200,
        },
        exception_reason="Django admin logout accepts POST only (405 on GET), redirects non-staff to login (302), and renders logged_out.html (200) for staff/superuser.",
        description="Django admin logout",
    ),
    "admin:password_change": RouteAccessSpec(
        route_key="admin:password_change",
        classification="teacher",
        methods=("GET", "POST"),
        actor_overrides={
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 302,
            "student_other_course": 302,
        },
        exception_reason="Django admin redirects non-staff users to admin:login (302).",
        description="Django admin password change",
    ),
    "admin:password_change_done": RouteAccessSpec(
        route_key="admin:password_change_done",
        classification="teacher",
        methods=("GET",),
        actor_overrides={
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 302,
            "student_other_course": 302,
        },
        exception_reason="Django admin redirects non-staff users to admin:login (302).",
        description="Django admin password change done",
    ),
    "admin:autocomplete": RouteAccessSpec(
        route_key="admin:autocomplete",
        classification="teacher",
        methods=("GET",),
        actor_overrides={
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 302,
            "student_other_course": 302,
            "teacher": 403,
            "superuser": 403,
        },
        exception_reason="Django admin autocomplete without query params raises PermissionDenied (403) for staff/superuser; non-staff redirects to admin:login (302).",
        case_variants=(
            CaseVariantSpec(
                name="valid_query",
                method="GET",
                query_params={
                    "app_label": "courses",
                    "model_name": "lesson",
                    "field_name": "course",
                },
                actor_expectations={
                    "guest": 302,
                    "student_unenrolled": 302,
                    "student_pending": 302,
                    "student_revoked": 302,
                    "student_active": 302,
                    "student_other_course": 302,
                    "teacher": 403,
                    "superuser": 200,
                },
                reason="With valid app_label/model_name/field_name query parameters, non-superuser teacher lacks model view permission (403) and superuser receives 200 JSON.",
            ),
        ),
        description="Django admin Select2 autocomplete endpoint",
    ),
    "admin:jsi18n": RouteAccessSpec(
        route_key="admin:jsi18n",
        classification="teacher",
        methods=("GET",),
        actor_overrides={
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 302,
            "student_other_course": 302,
        },
        exception_reason="Django admin redirects non-staff users to admin:login (302).",
        description="Django admin JavaScript i18n catalog",
    ),
    "admin:view_on_site": RouteAccessSpec(
        route_key="admin:view_on_site",
        classification="teacher",
        methods=("GET",),
        actor_overrides={
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 302,
            "student_other_course": 302,
            "teacher": 404,
            "superuser": 404,
        },
        exception_reason="Django admin view_on_site raises 404 when the target model does not define get_absolute_url.",
        description="Django admin view-on-site shortcut",
    ),
    "admin:app_list": RouteAccessSpec(
        route_key="admin:app_list",
        classification="teacher",
        methods=("GET",),
        actor_overrides={
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 302,
            "student_other_course": 302,
            "teacher": 404,
        },
        exception_reason="Django admin app_list raises 404 for staff users who do not have model permissions in that app_label.",
        description="Django admin per-app index",
    ),
    "<unnamed:admin/(?P<url>.*)$>": RouteAccessSpec(
        route_key="<unnamed:admin/(?P<url>.*)$>",
        classification="teacher",
        methods=("GET",),
        actor_overrides={
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 302,
            "student_other_course": 302,
            "teacher": 404,
            "superuser": 404,
        },
        exception_reason="Django admin catch-all pattern raises 404 for unknown admin paths once authenticated as staff.",
        description="Django admin final catch-all 404 handler",
    ),
    "admin:auth_user_password_change": RouteAccessSpec(
        route_key="admin:auth_user_password_change",
        classification="teacher",
        methods=("GET", "POST"),
        actor_overrides={
            "student_unenrolled": 302,
            "student_pending": 302,
            "student_revoked": 302,
            "student_active": 302,
            "student_other_course": 302,
            "teacher": 403,
        },
        exception_reason="Django admin user password change requires change_user permission (403 for non-superuser teacher).",
        description="Django admin change user password form",
    ),
    **_build_admin_model_routes(),
}


def walk_urlconf(urlconf: str = "config.urls") -> list[dict[str, Any]]:
    """
    Walks the full URL resolver (including included apps, allauth, admin, and dashboard;
    skipping static/media and debug_toolbar) and returns all discovered routes in order.
    """
    resolver = get_resolver(urlconf)
    discovered: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    def _walk(
        patterns: list[Any],
        prefix: str = "",
        namespace_parts: tuple[str, ...] = (),
    ) -> None:
        for item in patterns:
            if isinstance(item, URLResolver):
                sub_prefix = prefix + str(item.pattern)
                if item.namespace == "djdt" or sub_prefix.startswith("__debug__"):
                    continue
                if sub_prefix.startswith("static/") or sub_prefix.startswith("media/"):
                    continue
                next_ns = (*namespace_parts, item.namespace) if item.namespace else namespace_parts
                _walk(item.url_patterns, sub_prefix, next_ns)
            elif isinstance(item, URLPattern):
                full_pattern = prefix + str(item.pattern)
                if full_pattern.startswith("static/") or full_pattern.startswith("media/"):
                    continue
                ns_str = ":".join(namespace_parts)
                if item.name:
                    route_key = f"{ns_str}:{item.name}" if ns_str else item.name
                else:
                    route_key = f"<unnamed:{full_pattern}>"

                if route_key in seen_keys:
                    continue
                seen_keys.add(route_key)
                discovered.append(
                    {
                        "route_key": route_key,
                        "url_name": f"{ns_str}:{item.name}"
                        if (ns_str and item.name)
                        else item.name,
                        "namespace": ns_str,
                        "pattern": full_pattern,
                        "callback": item.callback,
                    }
                )

    _walk(resolver.url_patterns)
    return discovered


def format_access_matrix_markdown() -> str:
    """
    Formats the entire URL Access Matrix as a readable Markdown table:
    (route name, class, methods, rate limit, tested actors & named variants).
    """
    lines = [
        "| Route Name | Class | Methods | Rate Limit | Tested Actors (G / U / P / R / A / O / T / S) |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    actor_short = [
        ("guest", "G"),
        ("student_unenrolled", "U"),
        ("student_pending", "P"),
        ("student_revoked", "R"),
        ("student_active", "A"),
        ("student_other_course", "O"),
        ("teacher", "T"),
        ("superuser", "S"),
    ]
    for route_key, spec in ACCESS_MATRIX.items():
        methods_str = ", ".join(spec.methods)
        rl_str = spec.ratelimit or (
            f"Exempt ({POST_RATELIMIT_EXEMPTIONS[route_key][:28]}...)"
            if route_key in POST_RATELIMIT_EXEMPTIONS
            else "-"
        )
        actor_summary_parts = []
        for actor_key, short_label in actor_short:
            code = spec.expected_for_actor(actor_key)
            actor_summary_parts.append(f"{short_label}:{code}")
        actors_str = " ".join(actor_summary_parts)
        lines.append(
            f"| `{route_key}` | `{spec.classification}` | `{methods_str}` | `{rl_str}` | {actors_str} |"
        )
        for variant in spec.case_variants:
            v_parts = [
                f"{short_label}:{variant.actor_expectations[actor_key]}"
                for actor_key, short_label in actor_short
            ]
            v_str = " ".join(v_parts)
            lines.append(
                f"| `{route_key} [{variant.name}]` | `{spec.classification}` | `{variant.method}` | `{rl_str}` | {v_str} |"
            )
    return "\n".join(lines)
