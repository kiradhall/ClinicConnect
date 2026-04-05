"""
Flask Documentation:     https://flask.palletsprojects.com/
Jinja2 Documentation:    https://jinja.palletsprojects.com/
Werkzeug Documentation:  https://werkzeug.palletsprojects.com/
This file contains the routes for your application.
"""

import os
from functools import wraps
from uuid import uuid4
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin
from app import app, db, login_manager
from flask import render_template, request, redirect, url_for, flash, session, abort, send_from_directory
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
from app.models import UserProfile, Appointment, ClinicHours
from app.forms import LoginForm, UploadForm, RegistrationForm, EditProfileForm


def role_required(*roles):
    """Restrict a route to users with one of the specified roles."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def _get_appointment(appointment_id):
    return Appointment.query.get(appointment_id)


###
# Routing for your application.
###

@app.route('/')
def home():
    """Render website home page with greeting."""
    return render_template('home.html')


@app.route('/my-appointments')
@login_required
def my_appointments():
    """Render my appointments page (requires login)."""
    now = datetime.now()
    if current_user.role == 'patient':
        my = Appointment.query.filter_by(user_id=current_user.id)
    else:
        my = Appointment.query
    # Only show non-cancelled appointments in upcoming
    upcoming = my.filter(Appointment.when >= now, Appointment.status != 'cancelled').order_by(Appointment.when.asc()).all()
    past = my.filter(Appointment.when < now).order_by(Appointment.when.desc()).all()
    return render_template('my_appointments.html', upcoming=upcoming, past=past)


@app.route('/appointments/book', methods=['GET', 'POST'])
@login_required
def book_appointment():
    from datetime import time as dtime

    def get_slots_for_date(date_str):
        """Return hourly time slots for a given date based on clinic hours."""
        if not date_str:
            return []
        try:
            sel_dt = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return []

        ch = ClinicHours.query.filter_by(day_of_week=sel_dt.weekday()).first()
        if ch is None or not ch.is_open or not ch.open_time or not ch.close_time:
            return []

        open_h  = int(ch.open_time.split(':')[0])
        close_h = int(ch.close_time.split(':')[0])
        slots = []
        for h in range(open_h, close_h):
            t = dtime(h, 0)
            slots.append(datetime.combine(sel_dt.date(), t).strftime('%I:%M %p'))
        return slots

    selected_date = request.args.get('appointment_date', '').strip()
    all_slots = get_slots_for_date(selected_date)

    available_slots = all_slots.copy()
    if selected_date:
        booked_slots = [
            a.time_slot for a in Appointment.query.filter(Appointment.when >= datetime.now()).all()
            if a.when.strftime('%Y-%m-%d') == selected_date
        ]
        available_slots = [slot for slot in all_slots if slot not in booked_slots]

    is_patient = current_user.role == 'patient'
    is_receptionist = current_user.role == 'receptionist'

    if request.method == 'GET':
        return render_template(
            'book_appointment.html',
            available_slots=available_slots,
            today_date=datetime.now().strftime('%Y-%m-%d'),
            selected_date=selected_date,
            is_patient=is_patient,
            patient_name=f"{current_user.first_name} {current_user.last_name}" if is_patient else '',
            patient_email=current_user.email if is_patient else ''
        )

    appointment_date = request.form.get('appointment_date', '').strip()
    time_slot = request.form.get('time_slot', '').strip()
    reason = request.form.get('reason', '').strip()
    notes = request.form.get('notes', '').strip()

    if is_patient:
        patient_name = f"{current_user.first_name} {current_user.last_name}"
        patient_email = current_user.email
    else:
        patient_name = request.form.get('patient_name', '').strip()
        patient_email = request.form.get('patient_email', '').strip()

    if not appointment_date or not time_slot or not reason or not patient_name or not patient_email:
        flash('All required fields must be filled in.', 'warning')
        return redirect(url_for('book_appointment', appointment_date=appointment_date))

    try:
        when = datetime.strptime(f"{appointment_date} {time_slot}", "%Y-%m-%d %I:%M %p")
    except ValueError:
        flash('Invalid appointment details.', 'danger')
        return redirect(url_for('book_appointment', appointment_date=appointment_date))

    if when <= datetime.now():
        flash('You cannot book an appointment in the past.', 'danger')
        return redirect(url_for('book_appointment', appointment_date=appointment_date))


    conflict = Appointment.query.filter_by(when=when).first()
    if conflict:
        flash('That date and time is already booked.', 'danger')
        return redirect(url_for('book_appointment', appointment_date=appointment_date))


    appt = Appointment(
        patient_name=patient_name,
        patient_email=patient_email,
        appointment_date=appointment_date,
        time_slot=time_slot,
        reason=reason,
        notes=notes,
        when=when,
        user_id=current_user.id
    )

    # If a receptionist/admin books using an email that belongs to a patient,
    # link the appointment to that patient so they can see it.
    if not is_patient:
        matched_user = UserProfile.query.filter_by(email=patient_email).first()
        if matched_user:
            appt.user_id = matched_user.id

    db.session.add(appt)
    db.session.commit()

    flash('Appointment booked successfully.', 'success')
    if is_receptionist:
        return redirect(url_for('manage_appointments')) 
    else:
        return redirect(url_for('my_appointments'))

@app.route('/appointments/reschedule/<appointment_id>', methods=['GET', 'POST'])
@login_required
def reschedule_appointment(appointment_id):
    """Allow a user to move an existing appointment to a new date/time slot."""
    appointment = _get_appointment(appointment_id)
    if not appointment:
        flash('Appointment not found.', 'warning')
        return redirect(url_for('my_appointments'))

    from datetime import time as dtime

    def get_slots_for_date(date_str):
        default_slots = ["09:00 AM", "10:00 AM", "11:00 AM", "01:00 PM", "02:00 PM"]
        if not date_str:
            return default_slots
        try:
            sel_dt = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return default_slots
        ch = ClinicHours.query.filter_by(day_of_week=sel_dt.weekday()).first()
        if ch is None or not ch.is_open or not ch.open_time or not ch.close_time:
            return []

        open_h  = int(ch.open_time.split(':')[0])
        close_h = int(ch.close_time.split(':')[0])
        slots = []
        for h in range(open_h, close_h):
            t = dtime(h, 0)
            slots.append(datetime.combine(sel_dt.date(), t).strftime('%I:%M %p'))
        return slots

    selected_date = request.args.get('appointment_date', '').strip()
    all_slots = get_slots_for_date(selected_date)
    available_slots = all_slots.copy()

    if selected_date:
        booked_slots = [
            a.time_slot for a in Appointment.query.filter(Appointment.when >= datetime.now()).all()
            if a.id != appointment.id and a.when.strftime('%Y-%m-%d') == selected_date
        ]
        available_slots = [slot for slot in all_slots if slot not in booked_slots]

    if request.method == 'GET':
        return render_template(
            'reschedule_appointment.html',
            appointment=appointment,
            available_slots=available_slots,
            today_date=datetime.now().strftime('%Y-%m-%d'),
            selected_date=selected_date
        )

    new_date = request.form.get('appointment_date', '').strip()
    new_slot = request.form.get('time_slot', '').strip()

    if not new_date or not new_slot:
        flash('Please select a new date and time slot.', 'warning')
        return redirect(url_for('reschedule_appointment', appointment_id=appointment_id, appointment_date=new_date))

    try:
        new_when = datetime.strptime(f"{new_date} {new_slot}", "%Y-%m-%d %I:%M %p")
    except ValueError:
        flash('Invalid date or time slot.', 'danger')
        return redirect(url_for('reschedule_appointment', appointment_id=appointment_id))

    if new_when <= datetime.now():
        flash('You cannot reschedule to a time in the past.', 'danger')
        return redirect(url_for('reschedule_appointment', appointment_id=appointment_id, appointment_date=new_date))


    conflict = Appointment.query.filter(Appointment.id != appointment.id, Appointment.when == new_when).first()
    if conflict:
        flash('That time slot is already booked. Please choose another.', 'danger')
        return redirect(url_for('reschedule_appointment', appointment_id=appointment_id, appointment_date=new_date))


    # Update the appointment
    appointment.appointment_date = new_date
    appointment.time_slot = new_slot
    appointment.when = new_when
    db.session.commit()

    flash('Appointment rescheduled successfully.', 'success')
    return redirect(url_for('my_appointments'))


@app.route('/appointments/cancel/<appointment_id>', methods=['POST'])
@login_required
def cancel_appointment(appointment_id):
    """Handle cancelling an appointment."""
    appointment = _get_appointment(appointment_id)
    if appointment:
        db.session.delete(appointment)
        db.session.commit()
        flash('Appointment canceled.', 'success')
    else:
        flash('Appointment not found.', 'warning')
    return redirect(url_for('my_appointments'))


@app.route('/manage-appointments')
@login_required
@role_required('receptionist')
def manage_appointments():
    """Receptionist appointment management dashboard."""
    sort = request.args.get('sort', 'when')
    direction = request.args.get('direction', 'asc')
    status_filter = request.args.get('status', '')
    search = request.args.get('search', '').strip()

    allowed_sorts = {'when', 'patient_name', 'patient_email', 'reason', 'status'}
    if sort not in allowed_sorts:
        sort = 'when'

    query = Appointment.query
    if status_filter in ('booked', 'cancelled', 'no-show'):
        query = query.filter(Appointment.status == status_filter)
    if search:
        like = f'%{search}%'
        query = query.filter(
            db.or_(
                Appointment.patient_name.ilike(like),
                Appointment.patient_email.ilike(like),
                Appointment.reason.ilike(like)
            )
        )

    sort_col = getattr(Appointment, sort)
    if direction == 'desc':
        query = query.order_by(sort_col.desc())
    else:
        query = query.order_by(sort_col.asc())

    appointments = query.all()
    return render_template(
        'manage_appointments.html',
        appointments=appointments,
        sort=sort,
        direction=direction,
        status_filter=status_filter,
        search=search,
        now=datetime.now(),
        timedelta=timedelta
    )


@app.route('/appointments/noshow/<int:appointment_id>', methods=['POST'])
@login_required
@role_required('receptionist')
def mark_no_show(appointment_id):
    """Mark an appointment as no-show."""
    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        flash('Appointment not found.', 'warning')
    elif datetime.now() < appointment.when + timedelta(minutes=10):
        flash('Cannot mark as No-Show until 10 minutes after the appointment time.', 'warning')
    else:
        appointment.status = 'no-show'
        db.session.commit()
        flash('Appointment marked as No-Show.', 'info')
    return redirect(url_for('manage_appointments'))


@app.route('/appointments/dashboard-cancel/<int:appointment_id>', methods=['POST'])
@login_required
@role_required('receptionist')
def dashboard_cancel(appointment_id):
    """Cancel an appointment from the receptionist dashboard (marks status)."""
    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        flash('Appointment not found.', 'warning')
    else:
        appointment.status = 'cancelled'
        db.session.commit()
        flash('Appointment cancelled.', 'success')
    return redirect(url_for('manage_appointments'))


@app.route('/admin/users')
@login_required
@role_required('admin')
def admin_users():
    """Admin page to view and change user roles."""
    search = request.args.get('search', '').strip()
    sort = request.args.get('sort', 'username')
    direction = request.args.get('direction', 'asc')

    allowed_sort = {'username', 'first_name', 'last_name', 'role'}
    if sort not in allowed_sort:
        sort = 'username'

    query = UserProfile.query
    if search:
        like = f'%{search}%'
        query = query.filter(
            UserProfile.username.ilike(like) |
            UserProfile.first_name.ilike(like) |
            UserProfile.last_name.ilike(like) |
            UserProfile.email.ilike(like)
        )

    sort_col = getattr(UserProfile, sort)
    if direction == 'desc':
        sort_col = sort_col.desc()
    users = query.order_by(sort_col).all()

    return render_template('admin_users.html', users=users, search=search, sort=sort, direction=direction)


@app.route('/admin/users/<int:user_id>/role', methods=['POST'])
@login_required
@role_required('admin')
def admin_change_role(user_id):
    """Admin action to update a user's role."""
    if user_id == current_user.id:
        flash('You cannot change your own role.', 'warning')
        return redirect(url_for('admin_users'))

    user = db.session.get(UserProfile, user_id)
    if not user:
        flash('User not found.', 'warning')
        return redirect(url_for('admin_users'))

    new_role = request.form.get('role', '').strip()
    if new_role not in ('patient', 'receptionist', 'admin'):
        flash('Invalid role specified.', 'danger')
        return redirect(url_for('admin_users'))

    user.role = new_role
    db.session.commit()
    flash(f"Role for '{user.username}' updated to '{new_role}'.", 'success')
    return redirect(url_for('admin_users'))


def _ensure_clinic_hours():
    """Seed default clinic hours (Mon-Fri 09:00-17:00, Sat-Sun closed) if not yet set."""
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


@app.route('/admin/clinic-hours', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def clinic_hours():
    """Admin page to view and update weekly clinic hours."""
    hours = ClinicHours.query.order_by(ClinicHours.day_of_week).all()

    if request.method == 'POST':
        conflicts = []
        updates = []  # (ClinicHours row, new values)

        for ch in hours:
            is_open = request.form.get(f'is_open_{ch.day_of_week}') == '1'
            open_t  = request.form.get(f'open_{ch.day_of_week}',  '').strip() or None
            close_t = request.form.get(f'close_{ch.day_of_week}', '').strip() or None

            # Validate: if closing, check no future appointments on that weekday
            if ch.is_open and not is_open:
                conflicting = [
                    a for a in Appointment.query.filter(
                        Appointment.when >= datetime.now(),
                        Appointment.status == 'booked'
                    ).all()
                    if a.when.weekday() == ch.day_of_week
                ]
                if conflicting:
                    conflicts.append(
                        f"{ch.day_name}: {len(conflicting)} existing appointment(s) conflict."
                    )
                    continue

            # Validate: if changing hours, check existing appointments still fall within new window
            if is_open and open_t and close_t:
                from datetime import time as dtime
                try:
                    new_open  = dtime(*map(int, open_t.split(':')))
                    new_close = dtime(*map(int, close_t.split(':')))
                except ValueError:
                    flash(f"Invalid time format for {ch.day_name}.", 'danger')
                    return redirect(url_for('clinic_hours'))

                conflicting = [
                    a for a in Appointment.query.filter(
                        Appointment.when >= datetime.now(),
                        Appointment.status == 'booked'
                    ).all()
                    if a.when.weekday() == ch.day_of_week
                    and not (new_open <= a.when.time() <= new_close)
                ]
                if conflicting:
                    conflicts.append(
                        f"{ch.day_name}: {len(conflicting)} appointment(s) fall outside the new hours."
                    )
                    continue

            updates.append((ch, is_open, open_t, close_t))

        if conflicts:
            for msg in conflicts:
                flash(msg, 'danger')
            return redirect(url_for('clinic_hours'))

        for ch, is_open, open_t, close_t in updates:
            ch.is_open   = is_open
            ch.open_time  = open_t if is_open else None
            ch.close_time = close_t if is_open else None
        db.session.commit()
        flash('Clinic hours updated successfully.', 'success')
        return redirect(url_for('clinic_hours'))

    return render_template('clinic_hours.html', hours=hours)


@app.route('/receptionist/patients')
@login_required
@role_required('receptionist', 'admin')
def patient_list():
    """Receptionist page to view all patients."""
    search = request.args.get('search', '').strip()
    query = UserProfile.query.filter_by(role='patient')
    if search:
        like = f'%{search}%'
        query = query.filter(
            UserProfile.username.ilike(like) |
            UserProfile.first_name.ilike(like) |
            UserProfile.last_name.ilike(like) |
            UserProfile.email.ilike(like)
        )
    patients = query.order_by(UserProfile.last_name, UserProfile.first_name).all()
    return render_template('patient_list.html', patients=patients, search=search)


@app.route('/receptionist/patients/<int:patient_id>/edit', methods=['POST'])
@login_required
@role_required('receptionist', 'admin')
def edit_patient(patient_id):
    """Receptionist action to update a patient's email or phone."""
    patient = db.session.get(UserProfile, patient_id)
    if not patient or patient.role != 'patient':
        flash('Patient not found.', 'warning')
        return redirect(url_for('patient_list'))

    new_email = request.form.get('email', '').strip()
    new_phone = request.form.get('phone', '').strip()

    if new_email and new_email != patient.email:
        if UserProfile.query.filter(UserProfile.email == new_email, UserProfile.id != patient_id).first():
            flash(f"Email '{new_email}' is already in use.", 'danger')
            return redirect(url_for('patient_list'))
        patient.email = new_email

    patient.phone = new_phone or None
    db.session.commit()
    flash(f"Patient '{patient.first_name} {patient.last_name}' updated.", 'success')
    return redirect(url_for('patient_list'))


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
        
        identifier = form.username.data
        user = UserProfile.query.filter(
            (UserProfile.username == identifier) | (UserProfile.email == identifier)
        ).first()

        if user and check_password_hash(user.password, form.password.data):
            login_user(user)
            flash('You have successfully logged in.', 'success')

            next_page = request.form.get('next') or request.args.get('next')
            if next_page and is_safe_url(next_page):
                return redirect(next_page)

            return redirect(url_for('home'))
        else:
            flash('Invalid username or password.', 'danger')

        return redirect(url_for('login'))

    return render_template('login.html', form=form)

@app.route('/register', methods=['POST', 'GET'])
def register():
    form = RegistrationForm()
    
    if form.validate_on_submit():
        # Check if username already exists
        if UserProfile.query.filter_by(username=form.username.data).first():
            flash('Username already exists. Please choose a different one.', 'danger')
            return redirect(url_for('register'))

        if UserProfile.query.filter_by(email=form.email.data).first():
            flash('An account with that email already exists.', 'danger')
            return redirect(url_for('register'))
        
        # Create new user
        user = UserProfile(
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            username=form.username.data,
            email=form.email.data,
            password=form.password.data,
            role='patient',
            phone=form.phone.data
        )
        db.session.add(user)
        db.session.commit()
        
        flash('Account created successfully! You can now log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template("register.html", form=form)

@app.route('/profile')
@login_required
def user_profile():
    return render_template('user_profile.html')


@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm(obj=current_user)

    if form.validate_on_submit():
        new_username = form.username.data.strip()
        new_email = form.email.data.strip()

        # Check uniqueness (excluding the current user)
        if new_username != current_user.username and UserProfile.query.filter_by(username=new_username).first():
            flash('That username is already taken.', 'danger')
            return redirect(url_for('edit_profile'))
        if new_email != current_user.email and UserProfile.query.filter_by(email=new_email).first():
            flash('An account with that email already exists.', 'danger')
            return redirect(url_for('edit_profile'))

        current_user.username = new_username
        current_user.email = new_email
        current_user.phone = form.phone.data.strip() or None

        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('user_profile'))

    return render_template('edit_profile.html', form=form)


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


@app.errorhandler(403)
def forbidden(error):
    """Custom 403 page."""
    flash('You do not have permission to access that page.', 'danger')
    return redirect(url_for('home'))


@app.errorhandler(404)
def page_not_found(error):
    """Custom 404 page."""
    return render_template('404.html'), 404
