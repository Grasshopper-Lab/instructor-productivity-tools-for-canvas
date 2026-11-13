"""
Letter of Recommendation API Views
Handles all API endpoints for letter-of-rec requests
"""
import logging
from functools import wraps

from flask import jsonify, request, current_app, session

from shared.models import db
from apps.autoextend.models import User, Course
from apps.autoextend.extension_views import is_instructor
from apps.letter_of_rec.models import LetterRequest


logger = logging.getLogger(__name__)


def check_logged_in(f):
    """Decorator to check if user is authenticated via LTI.

    Same session/token logic as autoextend's check_valid_user, minus the
    course_id URL requirement, since letter-of-rec routes aren't course-scoped.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        lti_authenticated = session.get('lti_authenticated', False)
        lti_user_id = session.get('lti_user_id')

        if not lti_authenticated or not lti_user_id:
            # Check for session token in Authorization or X-Session-Token header
            auth_header = request.headers.get('Authorization', '')
            token = None

            if auth_header.startswith('Bearer '):
                token = auth_header[7:]
            elif 'X-Session-Token' in request.headers:
                token = request.headers.get('X-Session-Token')

            if token and hasattr(current_app, '_session_tokens'):
                token_data = current_app._session_tokens.get(token)
                if token_data:
                    # Restore session data from token
                    session.update(token_data)
                    lti_authenticated = True
                    lti_user_id = token_data.get('lti_user_id')

        if not lti_authenticated or not lti_user_id:
            logger.warning(f"Unauthenticated access attempt to {request.endpoint}")
            return jsonify({'error': 'LTI authentication required'}), 401

        return f(*args, **kwargs)
    return decorated_function


def serialize_letter_request(r):
    return {
        'id': r.id,
        'studentId': r.student_id,
        'studentName': r.student.sortable_name,
        'instructorId': r.instructor_id,
        'courseId': r.course_id,
        'status': r.status,
        'notes': r.notes,
        'requestedAt': r.requested_at.isoformat() if r.requested_at else None,
        'completedAt': r.completed_at.isoformat() if r.completed_at else None
    }


# API Routes

def init_letter_routes(app):
    """Initialize all letter-of-rec API routes"""

    @app.route('/api/letter-of-rec/requests', methods=['POST'])
    @check_logged_in
    @is_instructor
    def create_letter_request():
        """Create a letter-of-rec request owned by the logged-in instructor"""
        try:
            canvas_user_id = session.get('canvas_user_id')
            instructor = User.query.filter_by(canvas_id=str(canvas_user_id)).first()
            if not instructor:
                logger.error(f"Invalid instructor ({canvas_user_id})")
                return jsonify({'error': 'Invalid user'}), 400

            data = request.get_json(silent=True) or {}

            # student_id and course_id are internal users.id / courses.id
            student_id = data.get('student_id')
            if student_id is None:
                return jsonify({'error': 'student_id is required'}), 400
            try:
                student_id = int(student_id)
            except (TypeError, ValueError):
                return jsonify({'error': 'student_id must be an integer'}), 400
            if not db.session.get(User, student_id):
                return jsonify({'error': 'Student not found'}), 400

            course_id = data.get('course_id')
            if course_id is not None:
                try:
                    course_id = int(course_id)
                except (TypeError, ValueError):
                    return jsonify({'error': 'course_id must be an integer'}), 400
                if not db.session.get(Course, course_id):
                    return jsonify({'error': 'Course not found'}), 400

            notes = data.get('notes')
            if notes is not None:
                notes = str(notes).strip()
                if len(notes) > 5000:
                    return jsonify({'error': 'Notes must be less than 5,000 characters'}), 400
                notes = notes or None

            # instructor_id always comes from the session, never the request body
            letter_request = LetterRequest(
                student_id=student_id,
                instructor_id=instructor.id,
                course_id=course_id,
                notes=notes
            )
            db.session.add(letter_request)
            db.session.commit()

            logger.info(f"Created letter request {letter_request.id} for instructor {instructor.id}")

            return jsonify(serialize_letter_request(letter_request)), 201

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating letter request: {e}", exc_info=True)
            return jsonify({'error': 'Failed to create letter request'}), 500

    @app.route('/api/letter-of-rec/requests', methods=['GET'])
    @check_logged_in
    @is_instructor
    def list_letter_requests():
        """Get the logged-in instructor's letter-of-rec requests, newest first"""
        try:
            canvas_user_id = session.get('canvas_user_id')
            instructor = User.query.filter_by(canvas_id=str(canvas_user_id)).first()
            if not instructor:
                return jsonify({'error': 'Invalid user'}), 400

            requests = LetterRequest.query.filter_by(
                instructor_id=instructor.id
            ).order_by(LetterRequest.requested_at.desc(), LetterRequest.id.desc()).all()

            logger.info(f"Retrieved {len(requests)} letter requests for instructor {instructor.id}")

            return jsonify([serialize_letter_request(r) for r in requests])

        except Exception as e:
            logger.error(f"Error listing letter requests: {e}")
            return jsonify({'error': 'Failed to fetch requests'}), 500
