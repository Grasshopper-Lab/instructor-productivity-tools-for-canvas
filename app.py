#!/usr/bin/env python3
"""
Main entry point for the Canvas LTI tools Flask application.
Used by Docker, Procfile, Render and Heroku (flask --app app / gunicorn app:app).
Currently serves the autoextend tool from apps/autoextend/views.py.
"""

from apps.autoextend.views import app

if __name__ == '__main__':
    # Run the Flask development server
    app.run(host='0.0.0.0', port=5001, debug=True)
