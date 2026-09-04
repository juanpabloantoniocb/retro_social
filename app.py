import os
import uuid
from datetime import datetime, timezone
import cloudinary
import cloudinary.uploader

from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-to-any-random-words')

# Database Config: Cleans URL and handles Supabase/PgBouncer for SQLAlchemy 2.0
db_url = os.environ.get('DATABASE_URL', 'sqlite:///site.db')

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# Strip out query parameters from the string to prevent driver conflicts
if "?" in db_url:
    db_url = db_url.split("?")[0]

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Pass connection parameters explicitly via engine options to fix Supabase e3q8 error
if db_url.startswith("postgresql://"):
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        "connect_args": {
            "sslmode": "require",
            "prepare_threshold": None  # Disables prepared statements for PgBouncer compatibility
        }
    }

db = SQLAlchemy(app)

# Cloudinary Setup
cloudinary.config(
    cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key = os.environ.get('CLOUDINARY_API_KEY'),
    api_secret = os.environ.get('CLOUDINARY_API_SECRET')
)

CATEGORIES = {
    'general':  {'label': 'Dispatch',        'endpoint': 'home'},
    'opinion':  {'label': 'Opinion',         'endpoint': 'opinion'},
    'creative': {'label': 'Creative Writing', 'endpoint': 'creative'},
}


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    bio = db.Column(db.Text, nullable=True, default='')
    avatar_url = db.Column(db.String(500), nullable=True)
    joined_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    posts = db.relationship('Post', backref='author', lazy=True)


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    caption = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    category = db.Column(db.String(20), nullable=False, default='general')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comments = db.relationship('Comment', backref='post', lazy=True,
                                order_by='Comment.created_at',
                                cascade='all, delete-orphan')


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    author = db.relationship('User')


with app.app_context():
    db.create_all()


def current_user():
    if 'user_id' not in session:
        return None
    return User.query.get(session['user_id'])


@app.context_processor
def inject_globals():
    return {
        'CATEGORIES': CATEGORIES,
        'current_user': current_user(),
        'issue_label': datetime.now(timezone.utc).strftime('%B %Y'),
    }


def render_feed(category, template):
    posts = (Post.query.filter_by(category=category)
             .order_by(Post.created_at.desc(), Post.id.desc()).all())
    return render_template(template, posts=posts, active_category=category)


@app.route('/')
def home():
    return render_feed('general', 'home.html')


@app.route('/opinion')
def opinion():
    return render_feed('opinion', 'opinion.html')


@app.route('/creative')
def creative():
    return render_feed('creative', 'creative.html')


@app.route('/profile/<username>')
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    posts = (Post.query.filter_by(user_id=user.id)
             .order_by(Post.created_at.desc(), Post.id.desc()).all())
    return render_template('profile.html', profile_user=user, posts=posts)


@app.route('/profile/edit', methods=['GET', 'POST'])
def edit_profile():
    user = current_user()
    if not user:
        return redirect(url_for('login'))

    if request.method == 'POST':
        user.bio = request.form.get('bio', '').strip()

        file = request.files.get('avatar')
        if file and file.filename != '':
            upload_result = cloudinary.uploader.upload(file)
            user.avatar_url = upload_result.get('secure_url')

        db.session.commit()
        flash('Profile updated.')
        return redirect(url_for('profile', username=user.username))

    return render_template('edit_profile.html', profile_user=user)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        if User.query.filter_by(username=username).first():
            flash('Username already exists!')
            return redirect(url_for('register'))

        hashed = generate_password_hash(password)
        is_first_user = User.query.count() == 0

        new_user = User(username=username, password_hash=hashed, is_admin=is_first_user)
        db.session.add(new_user)
        db.session.commit()

        flash('Account created! Please log in.')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_admin'] = user.is_admin
            return redirect(url_for('home'))
        else:
            flash('Invalid credentials.')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))


@app.route('/post', methods=['POST'])
def create_post():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    category = request.form.get('category', 'general')
    if category not in CATEGORIES:
        category = 'general'

    caption = request.form.get('caption', '').strip()
    image_url = None

    if category == 'general':
        file = request.files.get('image')
        if file and file.filename != '':
            upload_result = cloudinary.uploader.upload(file)
            image_url = upload_result.get('secure_url')

    if caption or image_url:
        new_post = Post(caption=caption, image_url=image_url,
                         category=category, user_id=session['user_id'])
        db.session.add(new_post)
        db.session.commit()
    else:
        flash('Write something before posting.')

    return redirect(url_for(CATEGORIES[category]['endpoint']))


@app.route('/manifesto')
def manifesto():
    return render_template('manifesto.html')


@app.route('/post/<int:post_id>/comment', methods=['POST'])
def create_comment(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    post = Post.query.get_or_404(post_id)
    body = request.form.get('body', '').strip()
    next_url = request.form.get('next')

    if body:
        comment = Comment(body=body, user_id=session['user_id'], post_id=post.id)
        db.session.add(comment)
        db.session.commit()
    else:
        flash('Write something before commenting.')

    if next_url:
        return redirect(next_url)
    endpoint = CATEGORIES.get(post.category, CATEGORIES['general'])['endpoint']
    return redirect(url_for(endpoint))


@app.route('/comment/delete/<int:comment_id>', methods=['POST'])
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    is_owner = session.get('user_id') == comment.user_id
    if not (session.get('is_admin') or is_owner):
        flash('Unauthorized.')
        return redirect(request.referrer or url_for('home'))

    next_url = request.form.get('next')
    db.session.delete(comment)
    db.session.commit()

    if next_url:
        return redirect(next_url)
    return redirect(request.referrer or url_for('home'))


@app.route('/admin/delete/<int:post_id>', methods=['POST'])
def admin_delete_post(post_id):
    if not session.get('is_admin'):
        flash('Unauthorized: Admin access required.')
        return redirect(url_for('home'))

    post = Post.query.get_or_404(post_id)
    endpoint = CATEGORIES.get(post.category, CATEGORIES['general'])['endpoint']

    db.session.delete(post)
    db.session.commit()
    flash('Post deleted by Admin.')

    next_url = request.form.get('next')
    if next_url:
        return redirect(next_url)
    return redirect(url_for(endpoint))


if __name__ == '__main__':
    app.run(debug=True)