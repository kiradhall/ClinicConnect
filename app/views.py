"""
Flask Documentation:     https://flask.palletsprojects.com/
Jinja2 Documentation:    https://jinja.palletsprojects.com/
Werkzeug Documentation:  https://werkzeug.palletsprojects.com/
This file contains the routes for your application.
"""

import os
from uuid import uuid4
from datetime import datetime
from urllib.parse import urlparse, urljoin
from app import app, db, login_manager
from flask import render_template, request, redirect, url_for, flash, session, abort, send_from_directory
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
from app.models import UserProfile
from app.forms import LoginForm, UploadForm, RegistrationForm

# In-memory stores (no database)
APPOINTMENTS = [
    {
        'id': uuid4().hex,
        'title': 'Orientation Call',
        'when': datetime.now(),
        'notes': 'Discuss onboarding next steps.',
    },
]


def _get_appointment(appointment_id):
    for a in APPOINTMENTS:
        if a['id'] == appointment_id:
            return a
    return None


###
# Routing for your application.
###

@app.route('/')
def home():
    """Render website home page with greeting."""
    return render_template('home.html')


@app.route('/manage-appointments')
@login_required
def manage_appointments():
    """Render manage appointments page (requires login)."""
    sorted_appointments = sorted(APPOINTMENTS, key=lambda a: a['when'])
    return render_template('ManageAppointment.html', appointments=sorted_appointments)


@app.route('/appointments/book', methods=['GET', 'POST'])
@login_required
def book_appointment():
    """Render and handle booking an appointment."""
    if request.method == 'GET':
        return render_template('book_appointment.html')

    title = request.form.get('title', '').strip()
    when_raw = request.form.get('when', '').strip()
    notes = request.form.get('notes', '').strip()

    if not title or not when_raw:
        flash('Title and date/time are required to book an appointment.', 'warning')
        return redirect(url_for('book_appointment'))

    try:
        when = datetime.fromisoformat(when_raw)
    except ValueError:
        flash('Invalid date/time format.', 'danger')
        return redirect(url_for('book_appointment'))

    APPOINTMENTS.append({
        'id': uuid4().hex,
        'title': title,
        'when': when,
        'notes': notes,
    })

    flash('Appointment booked successfully.', 'success')
    return redirect(url_for('manage_appointments'))


@app.route('/appointments/cancel/<appointment_id>', methods=['POST'])
@login_required
def cancel_appointment(appointment_id):
    """Handle cancelling an appointment."""
    appointment = _get_appointment(appointment_id)
    if appointment:
        APPOINTMENTS.remove(appointment)
        flash('Appointment canceled.', 'success')
    else:
        flash('Appointment not found.', 'warning')
    return redirect(url_for('manage_appointments'))


@app.route('/logout')
@login_required
def logout():
    """Handle user logout."""
    logout_user()
    flash('You have successfully logged out.', 'success')
    return redirect(url_for('home'))


def is_safe_url(target):
    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))
    return redirect_url.scheme in ('http', 'https') and host_url.netloc == redirect_url.netloc


@app.route('/login', methods=['POST', 'GET'])
def login():
    form = LoginForm()
    
    if form.validate_on_submit():
        
        user = UserProfile.query.filter_by(username=form.username.data).first()

        if user and check_password_hash(user.password, form.password.data):
            login_user(user)
            flash('You have successfully logged in.', 'success')

            next_page = request.form.get('next') or request.args.get('next')
            if next_page and is_safe_url(next_page):
                return redirect(next_page)

            return redirect(url_for('manage_appointments'))
        else:
            flash('Invalid username or password.', 'danger')

        return redirect(url_for('home'))

    return render_template('login.html', form=form)

@app.route('/register', methods=['POST', 'GET'])
def register():
    form = RegistrationForm()
    
    if form.validate_on_submit():
        # Check if username already exists
        existing_user = UserProfile.query.filter_by(username=form.username.data).first()
        if existing_user:
            flash('Username already exists. Please choose a different one.', 'danger')
            return redirect(url_for('register'))
        
        # Create new user
        user = UserProfile(
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            username=form.username.data,
            password=form.password.data
        )
        db.session.add(user)
        db.session.commit()
        
        flash('Account created successfully! You can now log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template("register.html", form=form)

@login_manager.user_loader
def load_user(id):
    return db.session.execute(db.select(UserProfile).filter_by(id=id)).scalar()

###
# The functions below should be applicable to all Flask apps.
###

# Display Flask WTF errors as Flash messages
def flash_errors(form):
    for field, errors in form.errors.items():
        for error in errors:
            flash(u"Error in the %s field - %s" % (
                getattr(form, field).label.text,
                error
            ), 'danger')


@app.route('/<file_name>.txt')
def send_text_file(file_name):
    """Send your static text file."""
    file_dot_text = file_name + '.txt'
    return app.send_static_file(file_dot_text)


@app.after_request
def add_header(response):
    """
    Add headers to both force latest IE rendering engine or Chrome Frame,
    and also tell the browser not to cache the rendered page. If we wanted
    to we could change max-age to 600 seconds which would be 10 minutes.
    """
    response.headers['X-UA-Compatible'] = 'IE=Edge,chrome=1'
    response.headers['Cache-Control'] = 'public, max-age=0'
    return response


@app.errorhandler(404)
def page_not_found(error):
    """Custom 404 page."""
    return render_template('404.html'), 404
