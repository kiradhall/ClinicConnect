from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import InputRequired, Email, Regexp, Optional
from .models import UserProfile
from flask_wtf.file import FileField, FileAllowed


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[InputRequired()])
    password = PasswordField('Password', validators=[InputRequired()])


class RegistrationForm(FlaskForm):
    first_name = StringField('First Name', validators=[InputRequired()])
    last_name = StringField('Last Name', validators=[InputRequired()])
    username = StringField('Username', validators=[InputRequired()])
    email = StringField('Email', validators=[InputRequired(), Email()])
    password = PasswordField('Password', validators=[InputRequired()])
    phone = StringField('Phone Number (optional)', validators=[Optional(), Regexp(r'^\+?1?\d{9,15}$', message="Invalid phone number.")])
    submit = SubmitField('Register')


class EditProfileForm(FlaskForm):
    username = StringField('Username', validators=[InputRequired()])
    email = StringField('Email', validators=[InputRequired(), Email()])
    phone = StringField('Phone Number', validators=[Optional(), Regexp(r'^\+?1?\d{9,15}$', message="Invalid phone number.")])
    submit = SubmitField('Save Changes')


class UploadForm(FlaskForm):
    file = FileField('File', validators=[FileAllowed(['jpg', 'png', 'jpeg'], 'Images only!')])
    submit = SubmitField('Upload')