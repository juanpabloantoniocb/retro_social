import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'change-this-to-any-random-words'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    posts = db.relationship('Post', backref='author', lazy=True)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    caption = db.Column(db.Text, nullable=True)
    image_filename = db.Column(db.String(255), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

with app.app_context():
    db.create_all()

@app.route('/')
def feed():
    posts = Post.query.order_by(Post.id.desc()).all()
    return render_template('feed.html', posts=posts)

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
            return redirect(url_for('feed'))
        else:
            flash('Invalid credentials.')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('feed'))

@app.route('/post', methods=['POST'])
def create_post():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    caption = request.form.get('caption', '')
    file = request.files.get('image')
    filename = None
    
    if file and file.filename != '':
        ext = os.path.splitext(secure_filename(file.filename))[1]
        filename = f"{uuid.uuid4().hex}{ext}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
    if caption or filename:
        new_post = Post(caption=caption, image_filename=filename, user_id=session['user_id'])
        db.session.add(new_post)
        db.session.commit()
        
    return redirect(url_for('feed'))

@app.route('/admin/delete/<int:post_id>', methods=['POST'])
def admin_delete_post(post_id):
    if not session.get('is_admin'):
        flash('Unauthorized: Admin access required.')
        return redirect(url_for('feed'))
        
    post = Post.query.get_or_404(post_id)
    if post.image_filename:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], post.image_filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            
    db.session.delete(post)
    db.session.commit()
    flash('Post deleted by Admin.')
    return redirect(url_for('feed'))

if __name__ == '__main__':
    app.run(debug=True)