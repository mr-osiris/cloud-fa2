from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
import requests
import base64
import os
import uuid
from datetime import datetime
import json
import boto3
from botocore.exceptions import ClientError
from werkzeug.utils import secure_filename
import time

from config import Config
from models import db, User, Image, UserStats

app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions
db.init_app(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

# Ensure media folder exists
os.makedirs(Config.MEDIA_FOLDER, exist_ok=True)

# Initialize AWS clients
try:
    if Config.USE_IAM_ROLE:
        s3_client = boto3.client('s3', region_name=Config.AWS_REGION)
    else:
        s3_client = boto3.client('s3', region_name=Config.AWS_REGION)
    print(f"AWS clients initialized successfully")
except Exception as e:
    print(f"Error initializing AWS clients: {str(e)}")
    s3_client = None


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==================== Helper Functions ====================

def upload_to_s3(file_data, filename, content_type='image/png'):
    """Upload file to S3"""
    if not s3_client or not Config.S3_BUCKET_NAME:
        return None, None

    try:
        s3_key = f"images/{filename}"
        s3_client.put_object(
            Bucket=Config.S3_BUCKET_NAME,
            Key=s3_key,
            Body=file_data,
            ContentType=content_type
        )
        print(f"Image uploaded to S3: {s3_key}")
        # Return S3 key and direct URL
        return s3_key, f"https://{Config.S3_BUCKET_NAME}.s3.{Config.AWS_REGION}.amazonaws.com/{s3_key}"
    except Exception as e:
        print(f"Error uploading to S3: {str(e)}")
        return None, None


def save_image_from_url(image_url, filename):
    """Download and save image"""
    try:
        response = requests.get(image_url)
        if response.status_code == 200:
            if Config.USE_S3:
                s3_key, s3_url = upload_to_s3(response.content, filename)
                if s3_key:
                    return s3_key, s3_url

            # Fallback to local storage
            filepath = os.path.join(Config.MEDIA_FOLDER, filename)
            with open(filepath, 'wb') as f:
                f.write(response.content)
            return filename, f'/media/{filename}'
        return None, None
    except Exception as e:
        print(f"Error saving image: {str(e)}")
        return None, None


def save_base64_image(base64_data, filename):
    """Save base64 encoded image"""
    try:
        if base64_data.startswith('data:image'):
            base64_data = base64_data.split(',')[1]

        image_data = base64.b64decode(base64_data)

        if Config.USE_S3:
            s3_key, s3_url = upload_to_s3(image_data, filename)
            if s3_key:
                return s3_key, s3_url

        # Fallback to local storage
        filepath = os.path.join(Config.MEDIA_FOLDER, filename)
        with open(filepath, 'wb') as f:
            f.write(image_data)
        return filename, f'/media/{filename}'
    except Exception as e:
        print(f"Error saving base64 image: {str(e)}")
        return None, None


def get_available_models():
    """Fetch available models from API"""
    try:
        headers = {
            "Authorization": f"Bearer {Config.API_KEY}",
            "Content-Type": "application/json"
        }
        response = requests.get(f"{Config.API_BASE_URL}/v1/models", headers=headers)
        if response.status_code == 200:
            return response.json()
        return {"data": []}
    except Exception as e:
        print(f"Error fetching models: {str(e)}")
        return {"data": []}


def generate_image(prompt, model_id, size="1024x1024", quality="standard", n=1):
    """Generate image using Infip API"""
    try:
        headers = {
            "Authorization": f"Bearer {Config.API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model_id,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": n
        }

        response = requests.post(
            f"{Config.API_BASE_URL}/v1/images/generations",
            headers=headers,
            json=payload
        )

        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        print(f"Error generating image: {str(e)}")
        return None


# ==================== Routes ====================

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('generate'))
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        try:
            username = request.form.get('username')
            email = request.form.get('email')
            password = request.form.get('password')

            # Validate input
            if not username or not email or not password:
                flash('All fields are required', 'error')
                return render_template('register.html')

            # Check if user exists
            if User.query.filter_by(username=username).first():
                flash('Username already exists', 'error')
                return render_template('register.html')

            if User.query.filter_by(email=email).first():
                flash('Email already registered', 'error')
                return render_template('register.html')

            # Create new user
            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
            new_user = User(
                username=username,
                email=email,
                password_hash=hashed_password
            )

            db.session.add(new_user)
            db.session.commit()

            # Create user stats
            user_stats = UserStats(user_id=new_user.id)
            db.session.add(user_stats)
            db.session.commit()

            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))

        except Exception as e:
            db.session.rollback()
            print(f"Registration error: {str(e)}")
            flash('An error occurred. Please try again.', 'error')

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and bcrypt.check_password_hash(user.password_hash, password):
            login_user(user)
            flash('Login successful!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    stats = UserStats.query.filter_by(user_id=current_user.id).first()
    recent_images = Image.query.filter_by(user_id=current_user.id).order_by(Image.created_at.desc()).limit(6).all()
    return render_template('dashboard.html', stats=stats, recent_images=recent_images)


@app.route('/generate')
@login_required
def generate():
    return render_template('index.html')


@app.route('/gallery')
@login_required
def gallery():
    try:
        images = Image.query.filter_by(user_id=current_user.id).order_by(Image.created_at.desc()).all()

        storage_info = {
            'storage_type': 'AWS S3' if Config.USE_S3 else 'Local Storage',
            'bucket_name': Config.S3_BUCKET_NAME if Config.USE_S3 else None,
            'total_images': len(images)
        }

        return render_template('gallery.html', images=images, storage_info=storage_info)
    except Exception as e:
        print(f"Gallery error: {str(e)}")
        return render_template('gallery.html', images=[], storage_info={}, error=str(e))


@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('dashboard'))

    total_users = User.query.count()
    total_images = Image.query.count()
    total_generations = db.session.query(db.func.sum(UserStats.total_generations)).scalar() or 0

    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
    recent_images = Image.query.order_by(Image.created_at.desc()).limit(10).all()

    return render_template('admin.html',
                         total_users=total_users,
                         total_images=total_images,
                         total_generations=total_generations,
                         recent_users=recent_users,
                         recent_images=recent_images)


# ==================== API Routes ====================

@app.route('/api/models')
@login_required
def api_models():
    models = get_available_models()
    return jsonify(models)


@app.route('/api/generate', methods=['POST'])
@login_required
def api_generate():
    try:
        data = request.get_json()
        prompt = data.get('prompt', '')
        model_id = data.get('model', 'img3')
        size = data.get('size', '1024x1024')
        quality = data.get('quality', 'standard')

        if not prompt:
            return jsonify({'error': 'Prompt is required'}), 400

        # Generate image
        result = generate_image(prompt, model_id, size, quality)

        if not result:
            return jsonify({'error': 'Failed to generate image'}), 500

        # Save images
        saved_images = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        for i, image_data in enumerate(result.get('data', [])):
            filename = f"{timestamp}_{uuid.uuid4().hex[:8]}_{i+1}.png"

            if 'url' in image_data:
                s3_key, image_url = save_image_from_url(image_data['url'], filename)
            elif 'b64_json' in image_data:
                s3_key, image_url = save_base64_image(image_data['b64_json'], filename)
            else:
                continue

            if image_url:
                new_image = Image(
                    user_id=current_user.id,
                    prompt=prompt,
                    model=model_id,
                    filename=filename,
                    s3_key=s3_key if Config.USE_S3 else None,
                    size=size,
                    quality=quality
                )
                db.session.add(new_image)
                saved_images.append(new_image.to_dict())

        stats = UserStats.query.filter_by(user_id=current_user.id).first()
        if stats:
            stats.total_generations += 1
            stats.total_images += len(saved_images)
            stats.last_generation = datetime.utcnow()
        else:
            stats = UserStats(
                user_id=current_user.id,
                total_generations=1,
                total_images=len(saved_images),
                last_generation=datetime.utcnow()
            )
            db.session.add(stats)

        db.session.commit()

        return jsonify({
            'success': True,
            'images': saved_images,
            'message': f'Generated {len(saved_images)} image(s) successfully!'
        })

    except Exception as e:
        db.session.rollback()
        print(f"Generation error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Server error: {str(e)}'}), 500


@app.route('/api/user/stats')
@login_required
def api_user_stats():
    stats = UserStats.query.filter_by(user_id=current_user.id).first()
    if stats:
        return jsonify({
            'total_generations': stats.total_generations,
            'total_images': stats.total_images,
            'last_generation': stats.last_generation.isoformat() if stats.last_generation else None
        })
    return jsonify({'total_generations': 0, 'total_images': 0, 'last_generation': None})


@app.route('/media/<filename>')
@login_required
def serve_media(filename):
    return send_from_directory(Config.MEDIA_FOLDER, filename)


@app.route('/api/storage-info')
@login_required
def api_storage_info():
    return jsonify({
        'storage_type': 'AWS S3' if Config.USE_S3 else 'Local Storage',
        'bucket_name': Config.S3_BUCKET_NAME if Config.USE_S3 else None,
        'region': Config.AWS_REGION if Config.USE_S3 else None,
        's3_configured': bool(s3_client),
        'use_s3': Config.USE_S3
    })


# ==================== Database Creation ====================

@app.cli.command('init-db')
def init_db():
    db.create_all()
    print('Database tables created successfully!')


@app.cli.command('create-admin')
def create_admin():
    username = input('Enter admin username: ')
    email = input('Enter admin email: ')
    password = input('Enter admin password: ')

    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
    admin_user = User(
        username=username,
        email=email,
        password_hash=hashed_password,
        is_admin=True
    )

    db.session.add(admin_user)
    db.session.commit()

    user_stats = UserStats(user_id=admin_user.id)
    db.session.add(user_stats)
    db.session.commit()

    print(f'Admin user {username} created successfully!')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
