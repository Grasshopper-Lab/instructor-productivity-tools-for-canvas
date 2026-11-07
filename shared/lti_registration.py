"""
Canvas LTI 1.3 registration JSON (/lti.json).

All tools in this repo share one LTI Developer Key, so there is a single
/lti.json. Each tool contributes its own Canvas placements by calling
register_placements() with a function that takes the tool's base URL and
returns a list of placement dicts.
"""
import os
import json
from flask import Blueprint, Response, request, render_template, current_app

lti_registration = Blueprint('lti_registration', __name__)

# Functions of base_url -> list of Canvas placement dicts, one per tool
_placement_providers = []


def register_placements(provider):
    """Register a tool's placements. Usable as a decorator."""
    _placement_providers.append(provider)
    return provider


def build_lti_config(base_url):
    """Build the LTI 1.3 configuration for the shared Developer Key"""
    placements = []
    for provider in _placement_providers:
        placements.extend(provider(base_url))

    return {
        "title": "Assignment Extension Manager",
        "scopes": [
            "https://purl.imsglobal.org/spec/lti-ags/scope/lineitem",
            "https://purl.imsglobal.org/spec/lti-ags/scope/lineitem.readonly",
            "https://purl.imsglobal.org/spec/lti-ags/scope/result.readonly",
            "https://purl.imsglobal.org/spec/lti-ags/scope/score",
            "https://purl.imsglobal.org/spec/lti-nrps/scope/contextmembership.readonly",
            "https://canvas.instructure.com/lti/account_lookup/scope/show"
        ],
        "extensions": [
            {
                "platform": "canvas.instructure.com",
                "settings": {
                    "platform": "canvas.instructure.com",
                    "placements": placements
                },
                "privacy_level": "public"
            }
        ],
        "public_jwk": {},
        "description": "A tool for managing assignment deadline extensions in Canvas courses. Students can request extensions with supporting documentation, and instructors can review and approve/deny requests.",
        "custom_fields": {
            "canvas_course_id": "$Canvas.course.id",
            "canvas_user_id": "$Canvas.user.id",
            "canvas_user_name": "$Person.name.full"
        },
        "public_jwk_url": f"{base_url}/lti/jwks",
        "target_link_uri": f"{base_url}/lti/launch",
        "oidc_initiation_url": f"{base_url}/lti/login"
    }


@lti_registration.route('/lti.json', methods=['GET'])
def lti_json():
    """Returns the LTI 1.3 configuration JSON for Canvas integration"""
    try:
        # Use TOOL_BASE_URL env var
        base_url = os.environ.get('TOOL_BASE_URL', request.url_root.rstrip('/')).rstrip('/')
        config = build_lti_config(base_url)
        return Response(json.dumps(config, indent=2), mimetype='application/json')
    except Exception as e:
        current_app.logger.error(f"Error with LTI JSON: {e}")
        return render_template('error.html', msg='Error with LTI JSON configuration.')
