from shared.models import db, utc_now
from apps.autoextend.models import User, Course

class LetterRequest(db.Model):
    __tablename__ = 'letter_requests'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    instructor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'))
    status = db.Column(db.String(20), default='requested')  # requested, drafted, sent
    s3_bucket = db.Column(db.String(255))
    s3_key = db.Column(db.String(1024))
    notes = db.Column(db.Text)
    requested_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    completed_at = db.Column(db.DateTime(timezone=True))

    student = db.relationship(User, foreign_keys=[student_id], backref='letter_requests_as_student')
    instructor = db.relationship(User, foreign_keys=[instructor_id], backref='letter_requests_as_instructor')
    course = db.relationship(Course, backref='letter_requests')
