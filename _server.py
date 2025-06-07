from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, IntegerField, TextAreaField
from wtforms.validators import DataRequired
from flask_uploads import UploadSet, configure_uploads, IMAGES
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask import send_from_directory
from werkzeug.utils import secure_filename
from datetime import date
import requests
import base64
import os
import shutil
import json
import psycopg2
import urllib.parse
import os
import qrcode
import string
from datetime import datetime
from dotenv import load_dotenv
import uuid
import secrets

load_dotenv()



app = Flask(__name__, static_folder='static')
app.config['SQLALCHEMY_DATABASE_URI'] = ''
app.config['UPLOADED_PHOTOS_DEST'] = 'static/'
app.secret_key = os.getenv('SECRET_KEY')
app.config['UPLOADED_VIDEOS_DEST'] = 'static/videos'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB


db = SQLAlchemy(app)
ALLOWED_EXTENSIONS = set(['png', 'jpg', 'jpeg', 'gif'])
photos = UploadSet('photos', IMAGES)

configure_uploads(app, (photos))




def generate_random_user_id(length=8):
    characters = string.ascii_letters + string.digits
    random_user_id = ''.join(secrets.choice(characters) for i in range(length))
    return random_user_id


class User(db.Model):

    password_hash = db.Column(db.String(512))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if password is None:
            return False
        return check_password_hash(self.password_hash, password)

    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(20), nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)
    birthday = db.Column(db.Date, nullable=False)
    details = db.Column(db.JSON)
    bio = db.Column(db.Text, nullable=False)
    image_file = db.Column(db.String(64), nullable=False,
                           default='abstract-user-flat-4.png')
    background_image = db.Column(db.String(120), nullable=True, default='background.jpg')
    youtube_links = db.Column(db.String(200), nullable=True)
    death_date = db.Column(db.Date, nullable=True)
    
    videos = db.relationship('Video', backref='user', lazy=True)

    
    @property
    def age(self):
        today = date.today()
        return today.year - self.birthday.year - ((today.month, today.day) < (self.birthday.month, self.birthday.day))

def extract_video_id(url):
    query = urllib.parse.urlparse(url)
    if query.hostname == 'youtu.be':
        return query.path[1:]
    if query.hostname in ('www.youtube.com', 'youtube.com'):
        if query.path == '/watch':
            p = urllib.parse.parse_qs(query.query)
            # Only return the video ID, ignore other parameters
            return p['v'][0].split('&')[0]
        if query.path[:7] == '/embed/':
            return query.path.split('/')[2]
        if query.path[:3] == '/v/':
            return query.path.split('/')[2]
    return None


@app.route('/login', methods=['POST', 'GET'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == os.getenv('ADMIN_PASSWORD'):
            session['logged_in_admin'] = True
            return redirect(url_for('admin'))
    return render_template('login.html')


@app.route('/', methods=['GET', 'POST'])
def home():
    return render_template('index.html')


@app.route('/user', methods=['GET', 'POST'])
def user():
    uid = request.args.get('user_id')
    if uid is None:
        return 'No User Id Provided', 404

    user = User.query.filter_by(uid=uid).first()

    if user is None:
        return 'User not found', 404
    
    if request.method == 'POST':
        entered_password = request.form.get('password')
        if user.check_password(entered_password):
            new_bio = request.form.get('bio')
            new_birthday = request.form.get('birthday')
            new_details = request.form.get('details')  # Get the new details from the form data
            if new_bio is not None:
                user.bio = new_bio
            if new_birthday is not None:
                user.birthday = datetime.strptime(
                    new_birthday, '%Y-%m-%d').date()
            if new_details is not None:
                user.details = json.loads(new_details)  # Update the details field
            db.session.commit()
            return redirect(url_for('user', user_id=uid))

    if user is not None:
        # Split the YouTube links by commas and strip whitespace
        youtube_links = [extract_video_id(link.strip())
                         for link in user.youtube_links.split(',')]
        details_json = json.loads(user.details)
        
    else:
        youtube_links = []
    videos = Video.query.filter_by(user_id=user.id).all()
    

    return render_template('user.html', user=user, details_json=details_json, youtube_links=youtube_links, videos=videos, name=user.name, age=user.age, background_image=user.background_image)


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if not session.get('logged_in_admin'):
        return redirect(url_for('login'))

    password = None
    qr_code_path = None

    if request.method == 'POST':
        uid_gen = generate_random_user_id()
        password = ''.join(secrets.SystemRandom().choices(string.ascii_letters + string.digits, k=10))
        user = User(uid=uid_gen, name="Colocar Nombre", birthday=datetime.now(), death_date=None, details='{"cemeteryName": "None", "cemeteryAddress": "None", "googleMapsLink": "None"}',
            bio='I love this platform!', image_file='abstract-user-flat-4.png', youtube_links='example.com')
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        user_url = url_for('user', user_id=user.uid, _external=True)

        img = qrcode.make(user_url)


        qr_code_path = f'static/{user.uid}.png'
        img.save(qr_code_path)
    # add functionality to delete users from the db

    return render_template('admin.html', password=password, qr_code_path=qr_code_path)


@app.route('/check-password', methods=['POST'])
def check_password():
    data = request.get_json()  # Get the JSON body of the request
    uid = data.get('uid')
    password = data.get('password')

    user = User.query.filter_by(uid=uid).first()

    if user and user.check_password(password):

        return jsonify({'passwordAccepted': True})
    else:
        return jsonify({'passwordAccepted': False})


@app.route('/user-dates/<uid>', methods=['GET'])
def get_user_dates(uid):
    user = User.query.filter_by(uid=uid).first()
    if user:
        return jsonify({'success': True, 'birthday': user.birthday, 'deathday': user.death_date})
    else:
        return jsonify({'success': False, 'message': 'User not found'})



@app.route('/get-user-details', methods=['GET'])
def get_user_details():
    uid = request.args.get('user_id')
    if uid is None:
        return jsonify({'success': False, 'message': 'No User Id Provided'}), 400

    user = User.query.filter_by(uid=uid).first()

    if user is None:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    # Parse the JSON string into a dictionary
    if user.details:
        details = json.loads(user.details)
    else:
        details = {}

    return jsonify({'success': True, 'details': details})

@app.route('/update-details', methods=['POST'])
def update_details():
    data = request.get_json()
    uid = data['uid']
    details = data['details']

    # Fetch the user from the database
    user = User.query.filter_by(uid=uid).first()

    if user:
        # Convert the details dictionary to a JSON string
        details_json = json.dumps(details)

        # Clear the existing details (this line is optional)
        user.details = None

        # Update the user's details
        user.details = details_json
        db.session.commit()

        # Return a success status if the user's details were updated successfully
        return jsonify({'status': 'success'})
    else:
        # Return a failure status if the user was not found
        return jsonify({'status': 'failure', 'message': 'User not found'})

@app.route('/update-birthday', methods=['POST'])
def update_birthday():
    data = request.get_json()  # Get the JSON data from the request body
    uid = data.get('uid')
    birthday = data.get('birthday')

    user = User.query.filter_by(uid=uid).first()
    if user and birthday:
        try:
            user.birthday = datetime.strptime(birthday, '%Y-%m-%d').date()
            db.session.commit()
            return jsonify({'success': True})
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid date format. Expected format: YYYY-MM-DD.'})
    else:
        return jsonify({'success': False, 'message': 'User not found or no birthday provided.'})


@app.route('/delete-image', methods=['POST'])
def delete_image():
    # Get the image ID from the request
    image_id = request.json.get('imageId')
    print('Received image ID:', image_id)

    # Find the image in the database
    image = db.session.get(Image, image_id)
    print('Found image:', image)

    # If the image exists, delete it
    if image:
        # Delete the image file
        image_path = os.path.join(
            app.config['UPLOADED_PHOTOS_DEST'], image.filename)
        print('Image path:', image_path)
        if os.path.exists(image_path):
            os.remove(image_path)
            print('Image file deleted')

        # Delete the image record from the database
        db.session.delete(image)
        db.session.commit()
        print('Image record deleted')

        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': 'Image not found'})

@app.route('/update-deathdate', methods=['POST'])
def update_deathdate():
  data = request.get_json()
  deathdate = data.get('deathdate')
  uid = data.get('uid')
  user = User.query.filter_by(uid=uid).first()
  print("Deatj", deathdate)
  if user:
    if deathdate:
      try:
        user.death_date = datetime.strptime(deathdate, '%Y-%m-%d').date()
      except ValueError:
        return jsonify({'success': False, 'message': 'Invalid date format. Expected format: YYYY-MM-DD.'})
    else:
      user.death_date = None
    db.session.commit()
    return jsonify({'success': True})
  else:
    return jsonify({'success': False, 'message': 'User not found.'})

@app.route('/update-bio', methods=['POST'])
def update_bio():
    data = request.get_json()  # Get the JSON body of the request
    uid = data.get('uid')
    bio = data.get('bio')

    user = User.query.filter_by(uid=uid).first()

    if user:
        print('Received bio:', bio)
        print('Bio before update:', user.bio)
        user.bio = bio
        db.session.commit()
        print('Bio after update:', user.bio)
        return jsonify({'updateAccepted': True})
    else:
        return jsonify({'updateAccepted': False})


@app.route('/upload-image', methods=['POST'])
def upload_image():
    if 'image' not in request.files:
        return jsonify({'success': False, 'message': 'No image file in request'})

    file = request.files['image']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No selected file'})

    if file and allowed_file(file.filename):
        unique_id = uuid.uuid4()
        filename = secure_filename(f"{unique_id}_{file.filename}")

        # Ensure the directory exists
        os.makedirs(app.config['UPLOADED_PHOTOS_DEST'], exist_ok=True)

        # Get the user
        uid = request.form.get('uid')
        user = User.query.filter_by(uid=uid).first()

        # If the user has an old image, delete it
        if user and user.image_file != 'A_black_image.jpg':
            old_image_path = os.path.join(
                app.config['UPLOADED_PHOTOS_DEST'], user.image_file)
            if os.path.exists(old_image_path):
                os.remove(old_image_path)

        # Save the new image
        file.save(os.path.join(app.config['UPLOADED_PHOTOS_DEST'], filename))

        # Save the image to GitHub


        # Update the user's image_file field
        if user:
            user.image_file = filename
            db.session.commit()

        return jsonify({'success': True, 'imageUrl': url_for('uploaded_file', filename=filename)})

    return jsonify({'success': False, 'message': 'Invalid file'})


class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    link = db.Column(db.String(200), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


@app.route('/add-video', methods=['POST'])
def add_video():
    title = request.form.get('title')

    description = request.form.get('description')
    link = request.form.get('link')
 
    uid = request.form.get('uid')  # Get the user ID from the form

    # Extract the video ID from the link
    video_id = extract_video_id(link)
    print(video_id)

    # Get the user
    user = User.query.filter_by(uid=uid).first()

    if user:
        # Create a new Video object
        video = Video(title=title, description=description,
                      link=video_id, user_id=user.id)

        # Add the video to the database
        db.session.add(video)
        db.session.commit()

        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': 'User not found'})


@app.route('/get-user-videos/<uid>', methods=['GET'])
def get_user_videos(uid):
    # Query the User model to get the user
    user = User.query.filter_by(uid=uid).first()
    if user:
        # Use the user's id to query the Video model
        videos = Video.query.filter_by(user_id=user.id).all()
        video_data = [{
            'title': video.title,
            'description': video.description,
            'videoId': video.link
        } for video in videos]
        return jsonify({'success': True, 'videos': video_data})
    else:
        return jsonify({'success': False, 'message': 'User not found'})
@app.route('/save_name', methods=['POST'])
def save_name():
    # Get the new name from the request data
    data = request.get_json()
    new_name = data.get('name')
    print(new_name)

    # Get the user's ID from the session or the request data
    uid = data.get('uid')  # Replace this with your actual code
    print(uid)

    # Query the User model to get the user
    user = User.query.filter_by(uid=uid).first()

    # If the user exists, update the name
    if user:
        user.name = new_name
        db.session.commit()
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': 'User not found'})

@app.route('/remove-video', methods=['POST'])
def remove_video():
    # Get the video link from the request
    data = request.get_json()
    video_link = data['video_id']

    # Find the video in the database using the video link
    video = Video.query.filter_by(link=video_link).first()

    # If the video exists, delete it
    if video:
        db.session.delete(video)
        db.session.commit()
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': 'Video not found'})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOADED_PHOTOS_DEST'], filename)

@app.route('/update-background-image', methods=['POST'])
def update_background_image():
    if 'background_image' not in request.files:
        return jsonify({'success': False, 'message': 'No file part'}), 400
    file = request.files['background_image']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No selected file'}), 400
    if file and allowed_file(file.filename):
        unique_id = uuid.uuid4()
        filename = secure_filename(f"{unique_id}_{file.filename}")
        file_path = os.path.join(app.config['UPLOADED_PHOTOS_DEST'], filename)
        file.save(file_path)

        # Get the user ID from the request
        uid = request.form.get('uid')
        # Query the User model to get the user
        user = User.query.filter_by(uid=uid).first()
        if user:
            # Delete the old image file if it's not the default background
            if user.background_image != 'background.jpg' and user.background_image != 'abstract-user-flat-4.png':
                old_image_path = os.path.join(app.config['UPLOADED_PHOTOS_DEST'], user.background_image)
                if os.path.exists(old_image_path):
                    os.remove(old_image_path)
            
            # Update the user's background_image field with the new image
            user.background_image = filename
            db.session.commit()
            
            # Return the URL of the uploaded image
            image_url = url_for('uploaded_file', filename=filename, _external=True)
            return jsonify({'success': True, 'imageUrl': image_url})
        else:
            return jsonify({'success': False, 'message': 'User not found'}), 404
    else:
        return jsonify({'success': False, 'message': 'Invalid file format'}), 400
    



def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


class Image(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    user_uid = db.Column(db.String, db.ForeignKey('user.uid'))
    user = db.relationship('User', backref=db.backref('images', lazy=True))


@app.route('/upload-user-image', methods=['POST'])
def upload_user_image():
    if 'image' not in request.files:
        return jsonify({'success': False, 'message': 'No image part'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No selected file'}), 400

    if file and allowed_file(file.filename):
        unique_id = uuid.uuid4()
        filename = secure_filename(f"{unique_id}_{file.filename}")
        file.save(os.path.join(app.config['UPLOADED_PHOTOS_DEST'], filename))


        # Get additional form data
        title = request.form.get('title', '')
        description = request.form.get('description', '')
        user_uid = request.form.get('uid')

        # Create a new Image record
        new_image = Image(filename=filename, title=title, description=description, user_uid=user_uid)
        db.session.add(new_image)
        db.session.commit()

        # Return the URL of the uploaded image
        image_url = url_for('uploaded_file', filename=filename, _external=True)
        return jsonify({'success': True, 'imageUrl': image_url})
    else:
        return jsonify({'success': False, 'message': 'Invalid file format'}), 400


@app.route('/user-images/<uid>', methods=['GET'])
def get_user_images(uid):
    user = User.query.filter_by(uid=uid).first()
    if user:
        images = Image.query.filter_by(user_uid=uid).all()
        print(images)
        image_data = [{'id': image.id, 'url': url_for(
            'uploaded_file', filename=image.filename), 'title': image.title, 'description': image.description} for image in images]
        return jsonify({'success': True, 'images': image_data})

    else:
        return jsonify({'success': False, 'message': 'User not found'})

@app.route('/update-profile-image', methods=['POST'])
def update_profile_image():
    uid = request.form.get('uid')
    user = User.query.filter_by(uid=uid).first()
    if user and 'profile_image' in request.files:
        file = request.files['profile_image']
        unique_id = uuid.uuid4()
        filename = secure_filename(f"{unique_id}_{file.filename}")
        file.save(os.path.join(app.config['UPLOADED_PHOTOS_DEST'], filename))

        # Delete the old image file if it's not the default image
        if user.image_file != 'background.jpg' and user.image_file != 'abstract-user-flat-4.png':
            old_image_path = os.path.join(app.config['UPLOADED_PHOTOS_DEST'], user.image_file)
            if os.path.exists(old_image_path):
                os.remove(old_image_path)

        # Update the user's image_file field with the new image
        user.image_file = filename
        db.session.commit()

        return jsonify({'success': True, 'imageUrl': url_for('uploaded_file', filename=filename)})
    else:
        return jsonify({'success': False, 'message': 'User not found or no image file in request'})
    
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    app.run(debug=True)
