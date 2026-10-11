import os
import click
from flask import Flask, render_template, session, request, Response, jsonify, redirect, send_from_directory
from flask_migrate import Migrate
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
import logging
from logging.handlers import RotatingFileHandler

from shared import config
from shared.models import db
from shared.lti13_service import LTI13Service
from shared.lti_registration import lti_registration, register_placements
from apps.autoextend.extension_views import init_extension_routes

# Templates and static files live at the repo root, not next to this module
app = Flask(__name__, template_folder=config.TEMPLATES_DIR, static_folder=config.STATIC_DIR)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = config.secret_key
app.config['DEBUG'] = os.environ.get('FLASK_ENV') != 'production'
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = config.SQLALCHEMY_TRACK_MODIFICATIONS
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH

# Canvas API Configuration
app.config['CANVAS_API_URL'] = config.CANVAS_API_URL
app.config['CANVAS_API_TOKEN'] = config.CANVAS_API_TOKEN

app._session_tokens = {}

# Session configuration for LTI 1.3
app.config['SESSION_COOKIE_SAMESITE'] = None  
app.config['SESSION_COOKIE_SECURE'] = False  
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access for security
app.config['SESSION_COOKIE_DOMAIN'] = None  
app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # 30 minutes


_allowed_origins = [o.strip() for o in os.environ.get('ALLOWED_ORIGINS', 'http://localhost:3008').split(',')]
CORS(app, resources={
    r"/api/*": {
        "origins": _allowed_origins,
        "supports_credentials": True,
        "allow_headers": ["Content-Type", "Authorization", "X-Session-Token"],
        "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    }
})

# Production configuration
if os.environ.get('DYNO') or os.environ.get('FLASK_ENV') == 'production':
    app.config['DEBUG'] = False
    app.config['TESTING'] = False

# Configure upload folder for documentation files
app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize database
db.init_app(app)
migrate = Migrate(app, db, directory=config.MIGRATIONS_DIR)

# Initialize LTI service
lti_service = LTI13Service(app)

# Shared /lti.json route
app.register_blueprint(lti_registration)

# Initialize extension routes
init_extension_routes(app)


# ============================================
# Logging

formatter = logging.Formatter(config.LOG_FORMAT)
if os.environ.get('FLASK_ENV') == 'production':
    import sys
    handler = logging.StreamHandler(sys.stdout)
else:
    handler = RotatingFileHandler(
        config.LOG_FILE,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT
    )
handler.setLevel(logging.getLevelName(config.LOG_LEVEL))
handler.setFormatter(formatter)
app.logger.addHandler(handler)



# Utility Functions


def return_error(msg):
    return render_template('error.html', msg=msg)


# ============================================
# LTI 1.3 Routes
# ============================================

@app.route('/lti/login', methods=['GET', 'POST'])
def lti_login():
    """Handle LTI 1.3 OIDC login initiation"""
    try:
        app.logger.info(f"LTI login - method: {request.method}, args: {dict(request.args)}, form: {dict(request.form)}")
        return lti_service.handle_oidc_login()
    except Exception as e:
        app.logger.error(f"LTI login error: {e}")
        import traceback
        app.logger.error(traceback.format_exc())
        return return_error(f"LTI login failed: {str(e)}")


@app.route('/lti/launch', methods=['POST'])
def lti_launch():
    """Handle LTI 1.3 launch with JWT token validation"""
    try:
        app.logger.info("LTI 1.3 launch initiated")

        # Handle launch and get LTI claims
        lti_claims = lti_service.handle_launch()

        # Determine user role — course-level Learner takes priority over institution-level Admin
        learner_role = 'http://purl.imsglobal.org/vocab/lis/v2/membership#Learner'
        if learner_role in lti_claims['roles']:
            role = 'student'
        elif any(r in lti_claims['roles'] for r in config.INSTRUCTOR_ROLES):
            role = 'instructor'
        else:
            role = 'student'

        # Get course ID (prefer canvas_course_id from custom params, fall back to context ID)
        course_id = session.get('canvas_course_id') or session.get('lti_context_id') or '12345'

        # Initialize user and course in database if they don't exist
        from apps.autoextend.models import User, Course

        # Get or create user
        canvas_user_id = session.get('canvas_user_id')
        user = User.query.filter_by(canvas_id=str(canvas_user_id)).first()
        if not user:
            user = User(
                canvas_id=str(canvas_user_id),
                sortable_name=session.get('lti_user_name', ''),
                email=session.get('lti_user_email', '')
            )
            db.session.add(user)
            app.logger.info(f"Created new user record for Canvas ID: {canvas_user_id}")
        else:
            # Update user info in case it changed
            user.sortable_name = session.get('lti_user_name', user.sortable_name)
            user.email = session.get('lti_user_email', user.email)

        # get or create course
        course = Course.query.filter_by(canvas_id=str(course_id)).first()
        if not course:
            course = Course(
                canvas_id=str(course_id),
                name=session.get('lti_context_title', f'Course {course_id}')
            )
            db.session.add(course)
            app.logger.info(f"Created new course record for Canvas ID: {course_id}")
        else:
            # Update course name in case it changed
            course.name = session.get('lti_context_title', course.name)

        db.session.commit()

        # Make session permanent so it persists across requests
        session.permanent = True

        # Generate a temporary session token for cross-origin communication
        import secrets
        session_token = secrets.token_urlsafe(32)
        session['session_token'] = session_token

        # Store token mapping (in production, use Redis)
        app._session_tokens[session_token] = {
            'lti_authenticated': True,
            'lti_user_id': session.get('lti_user_id'),
            'canvas_user_id': session.get('canvas_user_id'),
            'lti_user_name': session.get('lti_user_name'),
            'lti_user_email': session.get('lti_user_email'),
            'lti_roles': session.get('lti_roles'),
            'lti_context_id': session.get('lti_context_id'),
            'canvas_course_id': session.get('canvas_course_id'),
        }

        # Log successful launch
        app.logger.info(f"LTI launch successful for user: {session.get('lti_user_name')}")
        app.logger.info(f"Role: {role}, Course: {course_id}")
        app.logger.info(f"Session token: {session_token[:10]}...")

        # Redirect to React app with parameters including session token
        redirect_url = f"/client/?course_id={course_id}&role={role}&session_token={session_token}"
        return render_template('launch.html', redirect_url=redirect_url)

    except Exception as e:
        app.logger.error(f"LTI launch error: {e}")
        return return_error(f"LTI launch failed: {str(e)}")


@app.route('/lti/jwks', methods=['GET'])
def lti_jwks():
    """Provide public keys for JWT signature verification"""
    try:
        from shared.lti13_config import lti_config
        jwks = lti_config.get_jwks()
        return jsonify(jwks)
    except Exception as e:
        app.logger.error(f"JWKS error: {e}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({'error': 'Failed to get public keys'}), 500



# Canvas placements for this tool, served by the shared /lti.json route

@register_placements
def autoextend_placements(base_url):
    return [
        {
            "placement": "course_navigation",
            "message_type": "LtiResourceLinkRequest",
            "text": "Assignment Extensions",
            "icon_url": f"{base_url}/static/img/icon.png",
            "selection_width": 800,
            "selection_height": 600
        },
        {
            "placement": "assignment_menu",
            "message_type": "LtiResourceLinkRequest",
            "text": "Request Extension",
            "icon_url": f"{base_url}/static/img/icon.png"
        }
    ]

# ============================================
# Static Routes
# ============================================

@app.route('/', methods=['GET'])
def index():
    """Home page"""
    return render_template('index.html')


@app.route('/client/')
@app.route('/client/<path:path>')
def serve_client(path=''):
    if os.environ.get('FLASK_ENV') == 'production':
        dist_dir = config.CLIENT_DIST_DIR
        target = os.path.join(dist_dir, path) if path else None
        if path and os.path.isfile(target):
            return send_from_directory(dist_dir, path)
        return send_from_directory(dist_dir, 'index.html')
    else:
        import requests

        query_string = request.query_string.decode('utf-8')
        vite_base = os.environ.get('VITE_DEV_SERVER_URL', 'http://localhost:3008')
        vite_url = f'{vite_base}/client/{path}'
        if query_string:
            vite_url += f'?{query_string}'

        try:
            resp = requests.get(vite_url, stream=True)
            response = Response(resp.content, status=resp.status_code)
            excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
            for key, value in resp.headers.items():
                if key.lower() not in excluded_headers:
                    response.headers[key] = value
            return response
        except Exception as e:
            app.logger.error(f"Error proxying to Vite dev server: {e}")
            return jsonify({'error': 'Failed to load client application'}), 500


# Error Handlers

@app.errorhandler(404)
def not_found(error):
    return return_error("Page not found"), 404


@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Internal error: {error}")
    return return_error("Internal server error"), 500


# ============================================
# Admin CLI Commands
# ============================================

@app.cli.command('approve-client')
@click.argument('client_id')
@click.argument('issuer')
@click.option('--org-name', default='', help='Organization name (e.g. University of Florida)')
@click.option('--approved-by', default='admin', help='Name of person approving')
def approve_client(client_id, issuer, org_name, approved_by):
    """Approve a new LTI client ID for use with this tool."""
    from shared.models import ApprovedClient
    existing = ApprovedClient.query.filter_by(client_id=client_id).first()
    if existing:
        if existing.is_active:
            click.echo(f"Client ID {client_id} is already approved.")
        else:
            existing.is_active = True
            existing.approved_by = approved_by
            db.session.commit()
            click.echo(f"Client ID {client_id} reactivated.")
        return
    record = ApprovedClient(
        client_id=client_id,
        issuer=issuer,
        org_name=org_name,
        approved_by=approved_by
    )
    db.session.add(record)
    db.session.commit()
    click.echo(f"Approved client ID {client_id} for {org_name or issuer}.")


@app.cli.command('revoke-client')
@click.argument('client_id')
def revoke_client(client_id):
    """Revoke an approved LTI client ID."""
    from shared.models import ApprovedClient
    record = ApprovedClient.query.filter_by(client_id=client_id).first()
    if not record:
        click.echo(f"Client ID {client_id} not found.")
        return
    record.is_active = False
    db.session.commit()
    click.echo(f"Revoked client ID {client_id}.")


@app.cli.command('list-clients')
def list_clients():
    """List all approved LTI client IDs."""
    from shared.models import ApprovedClient
    records = ApprovedClient.query.order_by(ApprovedClient.approved_at).all()
    if not records:
        click.echo("No approved clients found.")
        return
    click.echo(f"{'CLIENT ID':<25} {'STATUS':<10} {'ORG':<30} {'ISSUER'}")
    click.echo("-" * 90)
    for r in records:
        status = 'active' if r.is_active else 'revoked'
        click.echo(f"{r.client_id:<25} {status:<10} {(r.org_name or ''):<30} {r.issuer}")
