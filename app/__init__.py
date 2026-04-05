from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from .config import Config
from flask_migrate import Migrate
# import flask migrate here

app = Flask(__name__)
app.config.from_object(Config)

db = SQLAlchemy(app)
migrate = Migrate(app, db)
# Instantiate Flask-Migrate library here

# Flask-Login login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

from app import views

# Create any tables that don't exist yet (safe — won't touch existing tables)
with app.app_context():
    db.create_all()
    # Seed default clinic hours if the table is empty
    from app.models import ClinicHours
    if ClinicHours.query.count() == 0:
        defaults = [
            (0, True,  '09:00', '17:00'),
            (1, True,  '09:00', '17:00'),
            (2, True,  '09:00', '17:00'),
            (3, True,  '09:00', '17:00'),
            (4, True,  '09:00', '17:00'),
            (5, False, None,    None),
            (6, False, None,    None),
        ]
        for day, is_open, open_t, close_t in defaults:
            db.session.add(ClinicHours(day_of_week=day, is_open=is_open, open_time=open_t, close_time=close_t))
        db.session.commit()
