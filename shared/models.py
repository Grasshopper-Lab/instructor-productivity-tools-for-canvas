from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

# Single SQLAlchemy instance shared by every tool in the repo
db = SQLAlchemy()

def utc_now():
    """Helper function to get current UTC time with timezone awareness"""
    return datetime.now(timezone.utc)

class ApprovedClient(db.Model):
    """Approved LTI client IDs — one row per registered Canvas organization"""
    __tablename__ = 'approved_clients'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.String(255), unique=True, nullable=False, index=True)
    issuer = db.Column(db.String(255), nullable=False)
    org_name = db.Column(db.String(255))
    approved_by = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    approved_at = db.Column(db.DateTime(timezone=True), default=utc_now)

    @classmethod
    def is_approved(cls, client_id):
        """Check if a client ID is approved and active"""
        record = cls.query.filter_by(client_id=client_id, is_active=True).first()
        return record is not None
