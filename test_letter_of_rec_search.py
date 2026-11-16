"""
Tests for GET /api/letter-of-rec/students/search and the CanvasService
methods behind it.

Uses DATABASE_URL if set (rows the tests create are deleted afterwards);
otherwise an in-memory SQLite database.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ.setdefault('SECRET_FLASK', 'test-secret')

from canvasapi.exceptions import Unauthorized, Forbidden, ResourceDoesNotExist  # noqa: E402

from app import app  # noqa: E402
from shared.models import db  # noqa: E402
from shared.canvas_service import CanvasService  # noqa: E402
from apps.autoextend.models import User  # noqa: E402

INSTRUCTOR_ROLE = 'http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor'
LEARNER_ROLE = 'http://purl.imsglobal.org/vocab/lis/v2/membership#Learner'

# Canvas ids chosen to be unlikely to collide with real data
INSTRUCTOR = 99_000_900
OTHER_INSTRUCTOR = 99_000_950
ALEX = 99_000_001     # student in an active and a completed course of INSTRUCTOR
JORDAN = 99_000_002   # TA in one of INSTRUCTOR's courses, student in another
CASEY = 99_000_003    # student only in a course INSTRUCTOR never taught
SAM = 99_000_004      # student only in a course where INSTRUCTOR's enrollment is deleted
PAT = 99_000_005      # student only in a course where INSTRUCTOR's enrollment is rejected
QUINN = 99_000_006    # student only in a course where INSTRUCTOR is only invited
ROBIN = 99_000_007    # rejected student enrollment in INSTRUCTOR's active course
AVERY = 99_000_008    # invited student enrollment in INSTRUCTOR's active course
TEST_CANVAS_IDS = [str(i) for i in (
    INSTRUCTOR, OTHER_INSTRUCTOR, ALEX, JORDAN, CASEY, SAM, PAT, QUINN, ROBIN, AVERY
)]

NAMES = {
    INSTRUCTOR: ('Dana Whitfield', 'Whitfield, Dana'),
    OTHER_INSTRUCTOR: ('Morgan Hale', 'Hale, Morgan'),
    ALEX: ('Alex Rivera', 'Rivera, Alex'),
    JORDAN: ('Jordan Kim', 'Kim, Jordan'),
    CASEY: ('Casey Rivera', 'Rivera, Casey'),
    SAM: ('Sam Ortiz', 'Ortiz, Sam'),
    PAT: ('Pat Lee', 'Lee, Pat'),
    QUINN: ('Quinn Bell', 'Bell, Quinn'),
    ROBIN: ('Robin Ash', 'Ash, Robin'),
    AVERY: ('Avery Stone', 'Stone, Avery'),
}

# course id -> course info + full roster as Canvas stores it:
# (canvas user id, enrollment type, enrollment state), teachers included
COURSES = {
    101: {'name': 'Intro to Biology', 'term': 'Fall 2026', 'status': 'active',
          'roster': [(INSTRUCTOR, 'TeacherEnrollment', 'active'),
                     (ALEX, 'StudentEnrollment', 'active'),
                     (JORDAN, 'TaEnrollment', 'active'),
                     (ROBIN, 'StudentEnrollment', 'rejected'),
                     (AVERY, 'StudentEnrollment', 'invited')]},
    102: {'name': 'Genetics', 'term': 'Spring 2025', 'status': 'completed',
          'roster': [(INSTRUCTOR, 'TeacherEnrollment', 'completed'),
                     (ALEX, 'StudentEnrollment', 'completed')]},
    103: {'name': 'Ecology', 'term': None, 'status': 'completed',
          'roster': [(INSTRUCTOR, 'TeacherEnrollment', 'completed'),
                     (JORDAN, 'StudentEnrollment', 'completed')]},
    105: {'name': 'Marine Biology', 'term': 'Fall 2024', 'status': 'completed',
          'roster': [(INSTRUCTOR, 'TeacherEnrollment', 'deleted'),
                     (SAM, 'StudentEnrollment', 'completed')]},
    106: {'name': 'Botany', 'term': 'Spring 2026', 'status': 'active',
          'roster': [(INSTRUCTOR, 'TeacherEnrollment', 'rejected'),
                     (PAT, 'StudentEnrollment', 'active'),
                     (ALEX, 'StudentEnrollment', 'active')]},
    107: {'name': 'Zoology', 'term': 'Fall 2026', 'status': 'active',
          'roster': [(INSTRUCTOR, 'TeacherEnrollment', 'invited'),
                     (QUINN, 'StudentEnrollment', 'active')]},
    301: {'name': 'Organic Chemistry', 'term': 'Fall 2026', 'status': 'active',
          'roster': [(OTHER_INSTRUCTOR, 'TeacherEnrollment', 'active'),
                     (CASEY, 'StudentEnrollment', 'active'),
                     (INSTRUCTOR, 'StudentEnrollment', 'active')]},
}
ROLE_TO_TYPE = {'student': 'StudentEnrollment', 'ta': 'TaEnrollment'}


class FakeCanvasService:
    """Stands in for CanvasService, answering the way Canvas would when given
    the enrollment states the real CanvasService requests"""

    def __init__(self, error=None):
        self.error = error
        self.teacher_course_calls = []
        self.search_calls = []

    def get_user_teacher_courses(self, user_id):
        self.teacher_course_calls.append(user_id)
        if self.error:
            raise self.error
        states = CanvasService.TEACHER_ENROLLMENT_STATES
        return [
            {'id': cid, 'name': c['name'], 'term': c['term'], 'status': c['status']}
            for cid, c in COURSES.items()
            if any(uid == user_id and etype == 'TeacherEnrollment' and state in states
                   for uid, etype, state in c['roster'])
        ]

    def search_course_users_by_role(self, course_id, search_term, role):
        self.search_calls.append((course_id, search_term, role))
        wanted = ROLE_TO_TYPE[role]
        states = CanvasService.COURSE_USER_ENROLLMENT_STATES
        results = []
        for uid, etype, state in COURSES[course_id]['roster']:
            name, sortable = NAMES[uid]
            if etype == wanted and state in states and search_term.casefold() in name.casefold():
                results.append({'id': uid, 'name': name, 'sortable_name': sortable,
                                'short_name': name, 'email': f'user{uid}@example.edu'})
        return results


class StudentSearchRouteTests(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()
        if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
            db.create_all()
        # Refuse to run (and later delete) if these Canvas ids already exist
        existing = User.query.filter(User.canvas_id.in_(TEST_CANVAS_IDS)).count()
        self.assertEqual(existing, 0, 'test Canvas ids already present in users table')

        self.client = app.test_client()
        self.login(INSTRUCTOR, [INSTRUCTOR_ROLE])
        self.fake = FakeCanvasService()
        patcher = mock.patch('apps.letter_of_rec.views.get_canvas_service',
                             side_effect=lambda: self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        db.session.rollback()
        deleted = User.query.filter(
            User.canvas_id.in_(TEST_CANVAS_IDS)
        ).delete(synchronize_session=False)
        db.session.commit()
        remaining = User.query.filter(User.canvas_id.in_(TEST_CANVAS_IDS)).count()
        print(f"cleanup [{self._testMethodName}]: deleted {deleted} test user row(s), "
              f"{remaining} remaining")
        db.session.remove()
        self.ctx.pop()
        self.assertEqual(remaining, 0)

    def login(self, canvas_user_id, roles):
        with self.client.session_transaction() as sess:
            sess['lti_authenticated'] = True
            sess['lti_user_id'] = f'lti-{canvas_user_id}'
            sess['canvas_user_id'] = str(canvas_user_id)
            sess['lti_roles'] = roles

    def search(self, q, **extra):
        params = {'q': q} if q is not None else {}
        params.update(extra)
        return self.client.get('/api/letter-of-rec/students/search', query_string=params)

    def by_canvas_id(self, results):
        return {r['canvasId']: r for r in results}

    def searched_course_ids(self):
        return {c for c, _, _ in self.fake.search_calls}

    # --- input / auth ------------------------------------------------------

    def test_missing_or_short_q_returns_400(self):
        for q in (None, '', 'a', ' a '):
            resp = self.search(q)
            self.assertEqual(resp.status_code, 400, q)
        self.assertEqual(self.fake.teacher_course_calls, [])

    def test_non_instructor_gets_403(self):
        self.login(ALEX, [LEARNER_ROLE])
        self.assertEqual(self.search('Rivera').status_code, 403)

    def test_unauthenticated_gets_401(self):
        with self.client.session_transaction() as sess:
            sess.clear()
        self.assertEqual(self.search('Rivera').status_code, 401)

    def test_instructor_id_comes_from_session_not_request(self):
        resp = self.search('Rivera', canvas_user_id=OTHER_INSTRUCTOR, user_id=OTHER_INSTRUCTOR)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.fake.teacher_course_calls, [INSTRUCTOR])
        # Casey is only in OTHER_INSTRUCTOR's course, so must not leak in
        self.assertNotIn(str(CASEY), self.by_canvas_id(resp.get_json()))

    # --- matching ----------------------------------------------------------

    def test_student_in_active_and_completed_course_both_listed(self):
        resp = self.search('alex')  # lower-case: matching is case-insensitive
        self.assertEqual(resp.status_code, 200)
        results = resp.get_json()
        self.assertEqual(len(results), 1)
        alex = results[0]
        self.assertEqual(alex['canvasId'], str(ALEX))
        self.assertEqual(alex['name'], 'Alex Rivera')
        # Not 106: Alex is a student there, but INSTRUCTOR's enrollment is rejected
        self.assertEqual(alex['courses'], [
            {'courseId': '101', 'name': 'Intro to Biology', 'term': 'Fall 2026',
             'status': 'active', 'role': 'student'},
            {'courseId': '102', 'name': 'Genetics', 'term': 'Spring 2025',
             'status': 'completed', 'role': 'student'},
        ])

    def test_ta_in_one_course_and_student_in_another_has_right_roles(self):
        results = self.search('JORDAN').get_json()
        self.assertEqual(len(results), 1)
        roles = {c['courseId']: (c['role'], c['status']) for c in results[0]['courses']}
        self.assertEqual(roles, {'101': ('ta', 'active'), '103': ('student', 'completed')})

    def test_student_only_in_untaught_course_does_not_appear(self):
        # "Rivera" matches Alex (taught) and Casey (only in course 301)
        results = self.by_canvas_id(self.search('Rivera').get_json())
        self.assertIn(str(ALEX), results)
        self.assertNotIn(str(CASEY), results)
        self.assertEqual(self.search('Casey').get_json(), [])
        # Course 301 is never even searched
        self.assertNotIn(301, self.searched_course_ids())

    def test_instructor_searching_own_name_does_not_match(self):
        resp = self.search('Whitfield')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), [])
        # Only student and TA rosters were queried, never teachers
        self.assertEqual({r for _, _, r in self.fake.search_calls}, {'student', 'ta'})

    # --- enrollment states -------------------------------------------------

    def test_courses_with_deleted_rejected_or_invited_teacher_enrollment_not_listed(self):
        cases = [('Sam', 105, 'deleted'), ('Pat', 106, 'rejected'), ('Quinn', 107, 'invited')]
        for q, course_id, state in cases:
            with self.subTest(teacher_enrollment=state):
                resp = self.search(q)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.get_json(), [], f'{q} leaked via {state} course {course_id}')
        # Those courses never reach the roster search at all
        self.assertTrue(self.searched_course_ids().isdisjoint({105, 106, 107}))
        self.assertEqual(self.searched_course_ids(), {101, 102, 103})

    def test_rejected_or_invited_student_not_listed(self):
        for q, state in (('Robin', 'rejected'), ('Avery', 'invited')):
            with self.subTest(student_enrollment=state):
                resp = self.search(q)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.get_json(), [], f'{state} student {q} was listed')
        # Course 101 (where they're enrolled) was searched; they were filtered out
        self.assertIn(101, self.searched_course_ids())

    # --- users table -------------------------------------------------------

    def test_creates_missing_user_rows_and_reuses_existing(self):
        existing = User(canvas_id=str(ALEX), sortable_name='Alex Rivera', email='old@example.edu')
        db.session.add(existing)
        db.session.commit()
        existing_id = existing.id

        results = self.by_canvas_id(self.search('ri').get_json())
        # "ri" matches Alex Rivera only among the taught courses' students/TAs
        self.assertEqual(set(results), {str(ALEX)})
        self.assertEqual(results[str(ALEX)]['userId'], existing_id)

        jordan = self.search('Jordan').get_json()[0]
        row = User.query.filter_by(canvas_id=str(JORDAN)).one()
        self.assertEqual(jordan['userId'], row.id)
        self.assertEqual(row.sortable_name, 'Jordan Kim')
        self.assertEqual(row.email, f'user{JORDAN}@example.edu')

        # A repeat search reuses the row instead of creating another
        again = self.search('Jordan').get_json()[0]
        self.assertEqual(again['userId'], row.id)
        self.assertEqual(User.query.filter_by(canvas_id=str(JORDAN)).count(), 1)

    # --- Canvas permission errors -----------------------------------------

    def test_canvas_401_and_403_return_clear_permission_error(self):
        for error in (Unauthorized({'errors': [{'message': 'unauthorized'}]}),
                      Forbidden('forbidden')):
            self.fake = FakeCanvasService(error=error)
            resp = self.search('Rivera')
            self.assertEqual(resp.status_code, 502, type(error).__name__)
            self.assertIn("Canvas API token lacks permission", resp.get_json()['error'])


class FakeResponse:
    def __init__(self, data, next_url=None):
        self._data = data
        self.links = {'next': {'url': next_url, 'rel': 'next'}} if next_url else {}

    def json(self):
        return self._data


def param_values(kwargs, key):
    return [v for k, v in kwargs if k == key]


class CanvasServiceMethodTests(unittest.TestCase):
    """Exercise the real new methods against fake Canvas HTTP responses that
    apply state filters the way Canvas does"""

    BASE = 'https://canvas.test'

    # INSTRUCTOR's teacher enrollments as Canvas stores them
    TEACHER_ENROLLMENTS = [
        {'id': 1, 'type': 'TeacherEnrollment', 'course_id': 101, 'enrollment_state': 'active'},
        {'id': 2, 'type': 'TeacherEnrollment', 'course_id': 102, 'enrollment_state': 'completed'},
        {'id': 3, 'type': 'TeacherEnrollment', 'course_id': 101, 'enrollment_state': 'active'},
        {'id': 4, 'type': 'TeacherEnrollment', 'course_id': 104, 'enrollment_state': 'active'},
        {'id': 5, 'type': 'TeacherEnrollment', 'course_id': 105, 'enrollment_state': 'deleted'},
        {'id': 6, 'type': 'TeacherEnrollment', 'course_id': 106, 'enrollment_state': 'rejected'},
        {'id': 7, 'type': 'TeacherEnrollment', 'course_id': 107, 'enrollment_state': 'invited'},
    ]
    COURSE_JSON = {
        101: {'id': 101, 'name': 'Intro to Biology', 'concluded': False,
              'workflow_state': 'available', 'term': {'name': 'Fall 2026'}},
        102: {'id': 102, 'name': 'Genetics', 'concluded': True,
              'workflow_state': 'available', 'term': {'name': 'Spring 2025'}},
        105: {'id': 105, 'name': 'Marine Biology', 'concluded': True,
              'workflow_state': 'completed', 'term': {'name': 'Fall 2024'}},
        106: {'id': 106, 'name': 'Botany', 'concluded': False,
              'workflow_state': 'available', 'term': {'name': 'Spring 2026'}},
        107: {'id': 107, 'name': 'Zoology', 'concluded': False,
              'workflow_state': 'available', 'term': {'name': 'Fall 2026'}},
    }
    EXPECTED_TAUGHT = [
        {'id': 101, 'name': 'Intro to Biology', 'term': 'Fall 2026', 'status': 'active'},
        {'id': 102, 'name': 'Genetics', 'term': 'Spring 2025', 'status': 'completed'},
    ]

    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        self.svc = CanvasService(api_url=self.BASE, api_token='fake-token')
        self.calls = []

    def patch_requests(self, handler):
        requester = self.svc.canvas._Canvas__requester

        def fake_request(method, endpoint=None, _kwargs=None, **kwargs):
            self.calls.append((method, endpoint, list(_kwargs or [])))
            return handler(endpoint, _kwargs or [])

        patcher = mock.patch.object(requester, 'request', side_effect=fake_request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def enrollments_handler(self, honor_state_filter):
        """Serve TEACHER_ENROLLMENTS over two pages, filtered by state[] like
        Canvas (or unfiltered, to test the method's own re-check)"""
        enroll_path = f'users/{INSTRUCTOR}/enrollments'
        page2 = f'{self.BASE}/api/v1/{enroll_path}?page=2'
        state = {}

        def handler(endpoint, kwargs):
            if endpoint == enroll_path:
                rows = self.TEACHER_ENROLLMENTS
                if honor_state_filter:
                    states = param_values(kwargs, 'state[]')
                    rows = [e for e in rows if e['enrollment_state'] in states]
                state['rows'] = rows
                half = len(rows) // 2
                return FakeResponse(rows[:half], next_url=page2)
            if endpoint == f'{enroll_path}?page=2':
                rows = state['rows']
                return FakeResponse(rows[len(rows) // 2:])
            if endpoint.startswith('courses/'):
                course_id = int(endpoint.split('/')[1])
                if course_id not in self.COURSE_JSON:
                    raise ResourceDoesNotExist('Not Found')  # e.g. deleted course 104
                return FakeResponse(self.COURSE_JSON[course_id])
            raise AssertionError(f'unexpected endpoint {endpoint}')

        return handler

    def test_get_user_teacher_courses_active_and_completed_only(self):
        self.patch_requests(self.enrollments_handler(honor_state_filter=True))
        courses = self.svc.get_user_teacher_courses(INSTRUCTOR)

        self.assertEqual(courses, self.EXPECTED_TAUGHT)
        first_kwargs = self.calls[0][2]
        self.assertEqual(param_values(first_kwargs, 'type[]'), ['TeacherEnrollment'])
        self.assertEqual(param_values(first_kwargs, 'state[]'), ['active', 'completed'])
        # Followed pagination; fetched each remaining course once with term + concluded
        self.assertEqual([c[1] for c in self.calls], [
            f'users/{INSTRUCTOR}/enrollments', f'users/{INSTRUCTOR}/enrollments?page=2',
            'courses/101', 'courses/102', 'courses/104',
        ])
        self.assertIn(('include[]', 'concluded'), self.calls[2][2])
        self.assertIn(('include[]', 'term'), self.calls[2][2])

    def test_get_user_teacher_courses_drops_other_states_even_if_canvas_returns_them(self):
        self.patch_requests(self.enrollments_handler(honor_state_filter=False))
        courses = self.svc.get_user_teacher_courses(INSTRUCTOR)

        self.assertEqual(courses, self.EXPECTED_TAUGHT)
        fetched = {c[1] for c in self.calls if c[1].startswith('courses/')}
        self.assertTrue(fetched.isdisjoint({'courses/105', 'courses/106', 'courses/107'}))

    def test_search_course_users_by_role_active_and_completed_only(self):
        # Course 101's student roster as Canvas stores it
        roster = [
            {'id': ALEX, 'name': 'Alex Rivera', 'state': 'active'},
            {'id': ROBIN, 'name': 'Robin Rivera', 'state': 'rejected'},
            {'id': AVERY, 'name': 'Avery Rivera', 'state': 'invited'},
            {'id': CASEY, 'name': 'Casey Rivera', 'state': 'completed',
             'email': 'c@example.edu'},
        ]
        page2 = f'{self.BASE}/api/v1/courses/101/search_users?page=2'
        state = {}

        def handler(endpoint, kwargs):
            if endpoint == 'courses/101/search_users':
                states = param_values(kwargs, 'enrollment_state[]')
                rows = [{k: v for k, v in u.items() if k != 'state'}
                        for u in roster if u['state'] in states]
                state['rows'] = rows
                return FakeResponse(rows[:1], next_url=page2)
            if endpoint == 'courses/101/search_users?page=2':
                return FakeResponse(state['rows'][1:])
            raise AssertionError(f'unexpected endpoint {endpoint}')

        self.patch_requests(handler)
        users = self.svc.search_course_users_by_role(101, 'Rivera', 'student')

        self.assertEqual([u['id'] for u in users], [ALEX, CASEY])
        self.assertEqual(users[1]['email'], 'c@example.edu')
        kwargs = self.calls[0][2]
        self.assertIn(('search_term', 'Rivera'), kwargs)
        self.assertEqual(param_values(kwargs, 'enrollment_type[]'), ['student'])
        self.assertEqual(param_values(kwargs, 'enrollment_state[]'), ['active', 'completed'])
        self.assertEqual(len(self.calls), 2)  # both pages fetched

        # Teachers can never be requested
        with self.assertRaises(ValueError):
            self.svc.search_course_users_by_role(101, 'Rivera', 'teacher')


if __name__ == '__main__':
    unittest.main()
