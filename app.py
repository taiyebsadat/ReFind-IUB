import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from datetime import datetime
import requests
from bs4 import BeautifulSoup
app = Flask(__name__)
app.secret_key = "university_secret_key"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///campus.db'

# --- IMAGE CONFIGURATION ---
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

db = SQLAlchemy(app)

# --- MODELS ---

# MISSING CLASS ADDED HERE:
class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100)) # Add this line to store the name
    items = db.relationship('Item', backref='reporter', lazy=True)

class Item(db.Model):
    __tablename__ = 'item'
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(10))        
    item_name = db.Column(db.String(100))
    owner_name = db.Column(db.String(100)) 
    target_id = db.Column(db.String(50))   
    location = db.Column(db.String(100))   
    description = db.Column(db.Text)       
    security_question = db.Column(db.String(200)) 

    posted_by = db.Column(db.String(20), db.ForeignKey('user.user_id'), nullable=False)

    image_file = db.Column(db.String(100), default='default.jpg')
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)    
    resolved = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='Active') # 'Active' or 'Resolved'
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow) # Automatically updates when status changes

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.String(50), nullable=False)
    sender_id = db.Column(db.String(50), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    
    # NEW: Store specific contact details separately for easy access
    contact_info = db.Column(db.String(255), nullable=True) 
    
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class InfoRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    sender_id = db.Column(db.String(20), nullable=False)  # The person asking
    receiver_id = db.Column(db.String(20), nullable=False) # The reporter
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=True) # The response
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# --- ROUTES ---

@app.route('/')
def index():
    if 'user_id' in session:
        # If YOU are logged in, go to admin. If OTHERS are logged in, go to dashboard.
        if session['user_id'].lower() == 'taiyebsadat':
            return redirect(url_for('admin_panel'))
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login')
def login():
    # The external URL where IRAS sends the data back
    callback_url = url_for('auth_callback', _external=True)
    
    # Redirecting the user to the secure login proxy
    auth_url = f"https://iras-auth.pages.dev/login?redirect_uri={callback_url}"
    return redirect(auth_url)

@app.route('/callback')
def auth_callback():
    # Fetching the student info returned by the proxy
    student_id = request.args.get('studentId')
    student_name = request.args.get('studentName')
    
    if student_id:
        # 1. Start the Session
        session['user_id'] = student_id
        session['user_name'] = student_name
        
        # 2. Database Sync
        user = User.query.filter_by(user_id=student_id).first()
        if not user:
            new_user = User(user_id=student_id, name=student_name)
            db.session.add(new_user)
            db.session.commit()
            
        flash(f"Logged in as {student_name}", "success")

        # 3. ADMIN LOGIN LOGIC
        # Replace '2412517' with your actual IUB ID
        if student_id == '2412517':
            session['is_admin'] = True  # Useful for protecting admin routes
            return redirect(url_for('admin_panel'))
            
        # Regular user goes to dashboard
        return redirect(url_for('dashboard'))
    
    flash("Authentication failed. Please use valid IUB credentials.", "danger")
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear() # Removes user_id, user_name, and is_admin
    flash("You have been logged out.", "info")
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    # 1. User's Notifications/Messages
    messages = Notification.query.filter_by(recipient_id=user_id).all()
    
    # 2. My Reports
    my_reports = Item.query.filter_by(posted_by=user_id).all()
    
    # 3. Recent Reports (From other people, excluding current user)
    recent_items = Item.query.filter(Item.posted_by != user_id, Item.status != 'Resolved')\
                             .order_by(Item.date_posted.desc()).limit(5).all()
    
    # 4. Info Requests (Incoming questions for my items)
    incoming_requests = InfoRequest.query.filter_by(receiver_id=user_id).all()
    
    # 5. My Outgoing Requests (Questions I asked others)
    my_questions = InfoRequest.query.filter_by(sender_id=user_id).all()
    
    return render_template('dashboard.html', 
                           messages=messages, 
                           recent_items=recent_items, 
                           my_reports=my_reports,
                           incoming_requests=incoming_requests,
                           my_questions=my_questions)

@app.route('/report/<report_type>')
def report(report_type):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # We pass item=None and edit_mode=False so the template 
    # doesn't crash looking for old data
    return render_template('report.html', 
                           report_type=report_type, 
                           item=None, 
                           edit_mode=False)

@app.route('/submit_report', methods=['POST'])
def submit_report():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    report_type = request.form.get('type')
    item_name = request.form.get('item_name')
    
    # Logic for Location + Other
    location = request.form.get('location')
    if location == 'Other':
        location = request.form.get('other_location')

    owner_name = request.form.get('owner_name')
    target_id = request.form.get('target_id')
    description = request.form.get('description')
    security_question = request.form.get('security_question')

    # Image Upload
    image_file = request.files.get('image')
    filename = None
    if image_file:
        filename = secure_filename(image_file.filename)
        image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    new_item = Item(
        type=report_type,
        item_name=item_name,
        location=location, # Uses the processed location
        owner_name=owner_name,
        target_id=target_id,
        description=description,
        security_question=security_question,
        image_file=filename,
        posted_by=session['user_id']
    )
    
    db.session.add(new_item)
    db.session.commit()

    # Auto-Notification
    if report_type == 'Found' and target_id:
        auto_msg = f"System Alert: An item matching your Student ID ({target_id}) has been found at {location}!"
        notification = Notification(
            recipient_id=target_id,
            sender_id="System",
            item_id=new_item.id,
            message=auto_msg
        )
        db.session.add(notification)
        db.session.commit()

    flash(f"Your {report_type} report has been submitted successfully!", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin')
def admin_panel():
    # 1. Update the ID check to match your real IUB Student ID
    # Replace '2412517' with the ID you use to log into IRAS
    if 'user_id' not in session or session['user_id'] != '2412517':
        flash("Unauthorized access. Admin only.", "danger")
        return redirect(url_for('dashboard'))
    
    # 2. Fetch statistics for the Admin Dashboard
    all_items = Item.query.order_by(Item.date_posted.desc()).all()
    total_lost = Item.query.filter_by(type='Lost', status='Active').count()
    total_found = Item.query.filter_by(type='Found', status='Active').count()
    
    # 3. New: Count total university members registered on your site
    total_users = User.query.count()
    
    return render_template('admin.html', 
                           items=all_items, 
                           lost=total_lost, 
                           found=total_found, 
                           total_users=total_users)


@app.route('/search')
def search():
    # Force login check
    if 'user_id' not in session:
        flash("Please log in to search for items.", "warning")
        return redirect(url_for('login'))
    
    query = request.args.get('q', '')
    # Filter for active items matching the query
    items = Item.query.filter(Item.item_name.ilike(f'%{query}%'), Item.resolved == False).all()
    return render_template('search_results.html', items=items, query=query)


@app.route('/delete_item/<int:item_id>', methods=['POST'])
def delete_item(item_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    item = Item.query.get_or_404(item_id)
    if item.posted_by == session['user_id'] or session['user_id'] == 'admin':
        db.session.delete(item)
        db.session.commit()
        flash("Item removed.", "success")
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/delete_message/<int:msg_id>', methods=['POST'])
def delete_message(msg_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Fetch the message
    message = Notification.query.get_or_404(msg_id)
    
    # Security Check: Only the recipient can delete their own messages
    if str(message.recipient_id) == str(session['user_id']):
        db.session.delete(message)
        db.session.commit()
        flash("Message deleted successfully.", "info")
    else:
        flash("Unauthorized action.", "danger")
        
    return redirect(url_for('dashboard'))


@app.route('/resolve_item/<int:item_id>', methods=['POST'])
def resolve_item(item_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    item = Item.query.get_or_404(item_id)
    
    # Only the person who posted the item can resolve it
    if str(item.posted_by) == str(session['user_id']):
        item.status = 'Resolved'
        db.session.commit()
        flash("Item marked as Resolved and Returned!", "success")
    
    return redirect(url_for('dashboard'))

@app.route('/claim_item/<int:item_id>', methods=['POST'])
def claim_item(item_id):
    if 'user_id' not in session:
        flash("You must be logged in to claim an item.", "danger")
        return redirect(url_for('login'))
    
    item = Item.query.get_or_404(item_id)
    
    # Get data from the form
    msg_content = request.form.get('message')
    contact = request.form.get('contact_info') # The new field!
    
    # Create the notification
    new_notif = Notification(
        recipient_id=item.posted_by,
        sender_id=session['user_id'],
        item_id=item.id,
        message=msg_content,
        contact_info=contact
    )
    
    db.session.add(new_notif)
    db.session.commit()
    
    flash("Claim request sent! The owner will contact you if the details match.", "success")
    return redirect(url_for('item_detail', item_id=item.id))

@app.route('/item/<int:item_id>')
def item_detail(item_id):
    item = Item.query.get_or_404(item_id)
    
    # Fetch messages sent to the current user regarding THIS item
    messages = []
    if 'user_id' in session:
        messages = Notification.query.filter_by(
            item_id=item_id, 
            recipient_id=session['user_id']
        ).all()

    return render_template('item_detail.html', item=item, messages=messages)

@app.route('/contact_poster/<int:item_id>', methods=['POST'])
def contact_poster(item_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    item = Item.query.get_or_404(item_id)
    sender = session['user_id']
    recipient = item.posted_by # This is the IUB ID of the person who found/lost it

    # Prevent sending a message to yourself
    if str(sender) == str(recipient):
        flash("You cannot contact yourself!", "warning")
        return redirect(url_for('item_detail', item_id=item.id))

    # Create the notification
    new_notif = Notification(
        recipient_id=recipient,
        sender_id=sender,
        item_id=item.id,
        message=f"User {sender} is interested in your item: {item.item_name}"
    )
    
    db.session.add(new_notif)
    db.session.commit()

    flash(f"Notification sent to {recipient}!", "success")
    return redirect(url_for('item_detail', item_id=item.id))

@app.route('/ask_info/<int:item_id>', methods=['POST'])
def ask_info(item_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    item = Item.query.get_or_404(item_id)
    question_text = request.form.get('question')
    
    new_req = InfoRequest(
        item_id=item.id,
        sender_id=session['user_id'],
        receiver_id=item.posted_by,
        question=question_text
    )
    db.session.add(new_req)
    db.session.commit()
    return redirect(url_for('item_detail', item_id=item_id))

@app.route('/reply_info/<int:req_id>', methods=['POST'])
def reply_info(req_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    req = InfoRequest.query.get_or_404(req_id)
    # Security check: only the receiver can reply
    if req.receiver_id == session['user_id']:
        req.answer = request.form.get('answer')
        db.session.commit()
    
    return redirect(url_for('dashboard'))

@app.route('/contact_item/<int:item_id>')
def contact_item(item_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    item = Item.query.get_or_404(item_id)
    return render_template('contact_page.html', item=item)

@app.route('/send_final_contact/<int:item_id>', methods=['POST'])
def send_final_contact(item_id):
    item = Item.query.get_or_404(item_id)
    phone = request.form.get('phone')
    fb = request.form.get('fb_link')
    
    # Create notification with contact info
    contact_msg = f"User {session['user_id']} wants to claim '{item.item_name}'. Contact: {phone} | {fb}"
    new_notif = Notification(
        recipient_id=item.posted_by,
        sender_id=session['user_id'],
        item_id=item.id,
        message=contact_msg
    )
    db.session.add(new_notif)
    db.session.commit()
    
    flash("Your contact info has been sent to the poster!", "success")
    return redirect(url_for('dashboard'))

@app.route('/edit_item/<int:item_id>', methods=['GET', 'POST'])
def edit_item(item_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    item = Item.query.get_or_404(item_id)
    
    # Security check
    if str(item.posted_by) != str(session['user_id']):
        flash("You are not authorized to edit this report.", "danger")
        return redirect(url_for('item_detail', item_id=item.id))

    if request.method == 'POST':
        # Logic for Location + Other
        location = request.form.get('location')
        if location == 'Other':
            location = request.form.get('other_location')

        item.item_name = request.form.get('item_name')
        item.location = location # Save the correctly processed location
        item.owner_name = request.form.get('owner_name')
        item.target_id = request.form.get('target_id')
        item.description = request.form.get('description')
        item.security_question = request.form.get('security_question')
        
        db.session.commit()
        flash("Report updated successfully!", "success")
        return redirect(url_for('item_detail', item_id=item.id))

    # GET request: Show the form
    return render_template('report.html', item=item, report_type=item.type, edit_mode=True)

@app.route('/view_message/<int:notif_id>')
def view_message(notif_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    msg = Notification.query.get_or_404(notif_id)
    item = Item.query.get(msg.item_id)
    
    return render_template('message_detail.html', msg=msg, item=item)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)