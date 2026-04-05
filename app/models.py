from . import db
from werkzeug.security import generate_password_hash


class UserProfile(db.Model):
    # You can use this to change the table name. The default convention is to use
    # the class name. In this case a class name of UserProfile would create a
    # user_profile (singular) table, but if we specify __tablename__ we can change it
    # to `user_profiles` (plural) or some other name.
    __tablename__ = 'user_profiles'

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(80))
    last_name = db.Column(db.String(80))
    username = db.Column(db.String(80), unique=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password = db.Column(db.String(128))
    role = db.Column(db.String(80), nullable=False, default='patient')
    phone = db.Column(db.String(20), nullable=True)
    
    appointments = db.relationship('Appointment', backref='user', lazy=True)


    def __init__(self, first_name, last_name, username, email, password, role='patient', phone=None):
        self.first_name = first_name
        self.last_name = last_name
        self.username = username
        self.email = email
        self.password = generate_password_hash(password, method='pbkdf2:sha256')
        self.role = role
        self.phone = phone

    def is_authenticated(self):
        return True

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        try:
            return unicode(self.id)  # python 2 support
        except NameError:
            return str(self.id)  # python 3 support

    def __repr__(self):
        return '<User %r>' % (self.username)
    
    
class Appointment(db.Model):
    __tablename__ = 'appointments'

    id = db.Column(db.Integer, primary_key=True)
    patient_name = db.Column(db.String(100), nullable=False)
    patient_email = db.Column(db.String(120), nullable=False)
    appointment_date = db.Column(db.String(20), nullable=False)
    time_slot = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    when = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='booked')

    user_id = db.Column(db.Integer, db.ForeignKey('user_profiles.id'), nullable=False)

    def __init__(self, patient_name, patient_email, appointment_date, time_slot, reason, notes, when, user_id):
        self.patient_name = patient_name
        self.patient_email = patient_email
        self.appointment_date = appointment_date
        self.time_slot = time_slot
        self.reason = reason
        self.notes = notes
        self.when = when
        self.user_id = user_id
        self.status = 'booked'


class ClinicHours(db.Model):
    __tablename__ = 'clinic_hours'

    id = db.Column(db.Integer, primary_key=True)
    day_of_week = db.Column(db.Integer, nullable=False, unique=True)
    is_open = db.Column(db.Boolean, nullable=False, default=True)
    open_time = db.Column(db.String(8), nullable=True)   
    close_time = db.Column(db.String(8), nullable=True)  

    DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

    @property
    def day_name(self):
        return self.DAY_NAMES[self.day_of_week]