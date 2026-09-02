import os
import uuid
from datetime import datetime, timezone

from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import text

app = Flask(__name__)
app.secret_key = 'change-this-to-any-random-words'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['AVATAR_FOLDER'] = 'static/avatars'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['AVATAR_FOLDER'], exist_ok=True)
db = SQLAlchemy(app)

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
    avatar_filename = db.Column(db.String(255), nullable=True)
    joined_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    posts = db.relationship('Post', backref='author', lazy=True)


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    caption = db.Column(db.Text, nullable=True)
    image_filename = db.Column(db.String(255), nullable=True)
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


def run_migrations():
    """Lightweight, additive migration so an existing site.db (from the
    old single-feed schema) keeps its users and posts instead of being
    wiped out by the new columns."""
    with db.engine.connect() as conn:
        user_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(user)"))}
        post_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(post)"))}

        if 'bio' not in user_cols:
            conn.execute(text("ALTER TABLE user ADD COLUMN bio TEXT DEFAULT ''"))
        if 'avatar_filename' not in user_cols:
            conn.execute(text("ALTER TABLE user ADD COLUMN avatar_filename VARCHAR(255)"))
        if 'joined_at' not in user_cols:
            conn.execute(text("ALTER TABLE user ADD COLUMN joined_at DATETIME"))

        if 'category' not in post_cols:
            conn.execute(text("ALTER TABLE post ADD COLUMN category VARCHAR(20) DEFAULT 'general'"))
        if 'created_at' not in post_cols:
            conn.execute(text("ALTER TABLE post ADD COLUMN created_at DATETIME"))

        conn.commit()


with app.app_context():
    db.create_all()
    run_migrations()


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
            ext = os.path.splitext(secure_filename(file.filename))[1].lower()
            if ext in {'.png', '.jpg', '.jpeg', '.gif', '.webp'}:
                filename = f"{uuid.uuid4().hex}{ext}"
                file.save(os.path.join(app.config['AVATAR_FOLDER'], filename))
                if user.avatar_filename:
                    old_path = os.path.join(app.config['AVATAR_FOLDER'], user.avatar_filename)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                user.avatar_filename = filename
            else:
                flash('Avatar must be an image file (png, jpg, gif, or webp).')

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
    filename = None

    # Images are only allowed on general (Home) posts — Opinion and
    # Creative Writing are text-only sections.
    if category == 'general':
        file = request.files.get('image')
        if file and file.filename != '':
            ext = os.path.splitext(secure_filename(file.filename))[1]
            filename = f"{uuid.uuid4().hex}{ext}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    if caption or filename:
        new_post = Post(caption=caption, image_filename=filename,
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
    if post.image_filename:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], post.image_filename)
        if os.path.exists(filepath):
            os.remove(filepath)

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
