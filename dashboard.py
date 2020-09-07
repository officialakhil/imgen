import hashlib
import json
from random import randint
from datetime import datetime
import secrets

from flask import render_template, request, Blueprint, url_for, session, redirect

from utils.db import get_db
from utils.make_session import make_session

config = json.load(open('config.json'))

dash = Blueprint('dashboard', __name__, template_folder='views', static_folder='views/assets')

API_BASE_URL = 'https://discordapp.com/api'
AUTHORIZATION_BASE_URL = API_BASE_URL + '/oauth2/authorize'
TOKEN_URL = API_BASE_URL + '/oauth2/token'


def limited_access(func):
    def wrapper(*args, **kwargs):
        if 'user' not in session:
            discord = make_session(token=session.get('oauth2_token'))
            user = discord.get(API_BASE_URL + '/users/@me').json()

            if 'id' not in user:
                return redirect(url_for('.login'))

            session['user'] = user  # TODO: Expiry

        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


@dash.route('/login')
def login():
    discord = make_session(scope='identify email', redirect_uri=request.host_url + 'callback')
    authorization_url, state = discord.authorization_url(AUTHORIZATION_BASE_URL)
    return redirect(authorization_url)


@dash.route('/logout')
def logout():
    session.clear()
    return redirect(request.host_url)


@dash.route('/callback')
def callback():
    if request.values.get('error'):
        return request.values['error']

    discord = make_session(state=session.get('oauth2_state'), redirect_uri=request.host_url + 'callback')
    token = discord.fetch_token(
        TOKEN_URL,
        client_secret=config['client_secret'],
        authorization_response=request.url)
    session['oauth2_token'] = token
    return redirect(url_for('.dashboard'))


@dash.route('/dashboard')
@limited_access
def dashboard():
    user = session['user']
    is_admin = user['id'] in config['admins']
    db = get_db().imgen
    keys = db.keys.find({'owner': user['id']})
    return render_template('dashboard.html', name=user['username'], keys=keys, admin=is_admin, active_dash='nav-active')


@dash.route('/request', methods=['GET', 'POST'])
@limited_access
def request_key():
    user = session['user']

    if request.method == 'GET':
        return render_template('request.html')

    elif request.method == 'POST':
        name = request.form.get('name', None)
        servers = request.form.get('servers', None)
        reason = request.form.get('reason', None)
        app_type = request.form.get('type', None)
        link = request.form.get('link', None)
        description = request.form.get('description', None)
        tos = request.form.get('tos', False)
        consent = request.form.get('consent', False)

        if not reason or not name or not link or not app_type or not description or not tos:
            result = 'Please make sure you have entered a name, description, type, server count, link, description and have accepted our TOS before submitting your application'
            return render_template('result.html', result=result, success=False)
        if not link.startswith('http'):
            return render_template('result.html', result='URL must use HTTP(S) scheme!', success=False)
        data = {
            "_id": secrets.token_hex(10),
            "owner": user['id'],
            "email": user['email'],
            "name": name,
            "servers": servers,
            "description": description,
            "link": link,
            "type": app_type,
            "email_consent": consent,
            "owner_name": f'{user["username"]}#{user["discriminator"]}',
            "reason": reason,
            "time": datetime.now()
        }
        db = get_db().imgen
        db.applications.insert_one(data)
        result = 'Application Submitted 👌'
        return render_template('result.html', result=result, success=True)


@dash.route('/createkey', methods=['GET', 'POST'])
@limited_access
def create_key():
    user = session['user']

    if user['id'] not in config['admins']:
        return render_template('gitout.html')

    if request.method == 'GET':
        return render_template('create.html')
    elif request.method == 'POST':
        name = request.form.get('name', None)
        token = request.form.get('token', None)
        owner = request.form.get('owner', None)
        owner_name = request.form.get('owner_name', None)
        email = request.form.get('email', None)

        if not token or not name or not owner or not owner_name or not email:
            result = 'Please fill in all required inputs'
            return render_template('result.html', result=result, success=False)
        data = {
            "_id": token,
            "name": name,
            "owner": owner,
            "owner_name": owner_name,
            "email": email,
            "total_usage": 0,
            "usages": {},
            "unlimited": False,
            "ratelimit_reached": 0
        }
        db = get_db().imgen
        db.keys.insert_one(data)
        result = 'Key Created 👌'
        return render_template('result.html', result=result, success=True)


@dash.route('/admin')
@limited_access
def admin():
    user = session['user']

    if user['id'] not in config['admins']:
        return render_template('gitout.html')
    sort = request.args.get('sort', 'age')
    db = get_db().imgen
    if sort == 'age_asc':
        keys = db.keys.find().sort("creation_time")
    elif sort == 'age_desc':
        keys = keys = db.keys.find().sort("creation_time",-1)
    elif sort == 'usage_asc':
        keys = db.keys.find().sort("total_usage")
    elif sort == 'usage_desc':
        keys = db.keys.find().sort("total_usage",-1)
    elif sort == 'accept_asc':
        keys = db.keys.find().sort("acceptance_time")
    elif sort == 'accept_desc':
        keys = db.keys.find().sort("acceptance_time", -1)
    else:
        keys = db.keys.find().sort("creation_time")
    apps = db.applications.find().sort("time")
    return render_template('admin.html', name=user['username'], apps=apps, keys=keys, sort=sort)


@dash.route('/view/<key_id>')
@limited_access
def view(key_id):
    user = session['user']
    print(key_id)
    if user['id'] in config['admins']:
        admin = True
    else:
        admin = False
    db = get_db().imgen
    key = db.applications.find_one({"_id": key_id})
    key_type = 'app'
    if not key:
        key = db.keys.find_one({"_id": key_id})
        key_type = 'key'
    if key['owner'] == user['id'] or admin:
        return render_template('app.html', key=key, key_type=key_type, admin=admin)
    else:
        return render_template('gitout.html')


@dash.route('/approve/<key_id>')
@limited_access
def approve(key_id):
    user = session['user']

    if user['id'] not in config['admins']:
        return render_template('gitout.html')
    db = get_db().imgen
    key = db.applications.find_one({"_id": key_id})
    m = hashlib.sha256()
    m.update(str(key['_id']).encode())
    m.update(str(randint(10000, 99999)).encode())
    token = m.hexdigest()
    data = {
        "_id": token,
        "name": key['name'],
        "owner": key['owner'],
        "owner_name": key['owner_name'],
        "email": key['email'],
        "email_consent": key.get('email_consent', 'Not Available'),
        "description": key.get('description', 'Not Available'),
        "reason": key['reason'],
        "link": key.get('link', 'Not Available'),
        "type": key.get('type', 'Unknown'),
        "creation_time": key.get('time', 0),
        "acceptance_time": datetime.now(),
        "total_usage": 0,
        "usages": {},
        "unlimited": False,
        "ratelimit_reached": 0
    }
    db.keys.insert_one(data)
    db.applications.delete_one({"_id": key_id})
    return redirect(url_for('.admin'))


@dash.route('/decline/<key_id>')
@limited_access
def decline(key_id):
    user = session['user']

    if user['id'] not in config['admins']:
        return render_template('gitout.html')
    db = get_db().imgen
    db.applications.delete_one({"_id": key_id})
    return redirect(url_for('.admin'))


@dash.route('/delete/<key_id>')
@limited_access
def delete(key_id):
    user = session['user']
    db = get_db().imgen
    k = db.keys.find_one({"_id": key_id})
    if user['id'] in config['admins']:
        db.keys.delete_one({"_id": key_id})
        return redirect(url_for('.admin'))
    elif user['id'] == k['owner']:
        db.keys.delete_one({"_id": key_id})
        return redirect(url_for('.dashboard'))
    else:
        return render_template('gitout.html')


@dash.route('/unlimited/<key_id>')
@limited_access
def unlimited(key_id):
    user = session['user']

    if user['id'] not in config['admins']:
        return render_template('gitout.html')
    db = get_db().imgen
    key = db.keys.find_one({"_id": key_id})
    unlimited = not key['unlimited']
    db.keys.update_one({"_id": key_id},{"$set": {"unlimited": unlimited}})
    return redirect(url_for('.admin'))
