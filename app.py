from flask import Flask, render_template, request, redirect, url_for, session, flash, g
import sqlite3
import click
from werkzeug.security import generate_password_hash, check_password_hash
from models.database import init_db, get_db_connection, DATABASE
import os
import functools
from datetime import datetime, timedelta
import math
import pytz 

# INITIAL CONFIGURATION
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24) 
app.config['SESSION_COOKIE_SECURE'] = False 
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

@app.cli.command('init-db')
def init_db_command():
    """Clear existing data and create new tables."""
    init_db()
    click.echo('Initialized the database.')

@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None 
    else:
        conn = get_db_connection()
        g.user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        conn.close()

def admin_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.user or g.user['role'] != 'admin':
            flash('Admin access required.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.user:
            flash('Login required.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

#ROUTES

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=('GET', 'POST'))
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        error = None

        if not username:
            error = 'Username is required.'
        elif not password:
            error = 'Password is required.'
        elif not email:
            error = 'Email is required.'

        conn = get_db_connection()
        if error is None:
            try:
                existing_user = conn.execute(
                    'SELECT id FROM users WHERE username = ? OR email = ?', (username, email)
                ).fetchone()
                if existing_user:
                    error = f"User '{username}' or email '{email}' already exists."
                else:
                    conn.execute(
                        "INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)",
                        (username, generate_password_hash(password), email, 'user')
                    )
                    conn.commit()
                    flash('Registration successful! Please log in.', 'success')
                    return redirect(url_for('login'))
            except sqlite3.Error as e:
                error = f"Database error: {e}"
                conn.rollback()
            finally:
                conn.close()

        flash(error, 'danger')
    return render_template('register.html')


@app.route('/login', methods=('GET', 'POST'))
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        error = None

        conn = get_db_connection()
        user = conn.execute(
            'SELECT * FROM users WHERE username = ?', (username,)
        ).fetchone()
        conn.close()

        if user is None:
            error = 'Incorrect username.'
        elif not check_password_hash(user['password_hash'], password):
            error = 'Incorrect password.'

        if error is None:
            session.clear()
            session['user_id'] = user['id']
            session['role'] = user['role']
            flash('Logged in successfully!', 'success')
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('user_dashboard'))

        flash(error, 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


@app.route('/admin_dashboard')
@admin_required
def admin_dashboard():
    conn = get_db_connection()
    parking_lots = conn.execute('SELECT * FROM parking_lots ORDER BY prime_location_name').fetchall()
    
    users = conn.execute('SELECT id, username, email, role, created_at FROM users ORDER BY username').fetchall()

    total_lots = len(parking_lots)
    total_max_spots = sum(lot['maximum_number_of_spots'] for lot in parking_lots)
    total_occupied_spots = sum(lot['current_occupied_spots'] for lot in parking_lots)

    conn.close()
    return render_template('admin_dashboard.html',
                           parking_lots=parking_lots,
                           users=users,
                           total_lots=total_lots,
                           total_max_spots=total_max_spots,
                           total_occupied_spots=total_occupied_spots) 

@app.route('/admin/parking_lots/add', methods=('GET', 'POST'))
@admin_required
def add_parking_lot():
    if request.method == 'POST':
        name = request.form['prime_location_name']
        address = request.form['address']
        pin_code = request.form['pin_code']
        price_per_hour = request.form['price_per_hour']
        max_spots = request.form['maximum_number_of_spots']
        error = None

        if not name or not address or not pin_code or not price_per_hour or not max_spots:
            error = 'All fields are required.'

        try:
            price_per_hour = float(price_per_hour)
            max_spots = int(max_spots)
            if max_spots <= 0 or price_per_hour < 0:
                error = 'Maximum spots must be positive and price cannot be negative.'

        except ValueError:
            error = 'Price per hour and maximum spots must be valid numbers.'

        conn = get_db_connection()
        if error is None:
            try:
                # Insert parking lot
                conn.execute(
                    "INSERT INTO parking_lots (prime_location_name, address, pin_code, price_per_hour, maximum_number_of_spots) VALUES (?, ?, ?, ?, ?)",
                    (name, address, pin_code, price_per_hour, max_spots)
                )
                lot_id = conn.execute('SELECT id FROM parking_lots WHERE prime_location_name = ?', (name,)).fetchone()['id']
                # Initialize spots for this lot
                for i in range(1, max_spots + 1):
                    spot_number = f"S{i}"
                    conn.execute(
                        "INSERT INTO parking_spots (lot_id, spot_number, status) VALUES (?, ?, ?)",
                        (lot_id, spot_number, 'Available')
                    )
                conn.commit()
                flash('Parking Lot added successfully!', 'success')
                return redirect(url_for('admin_dashboard'))
            except sqlite3.IntegrityError:
                error = f"A parking lot named '{name}' already exists."
                conn.rollback()
            finally:
                conn.close()

        flash(error, 'danger')
    return render_template('add_parking_lot.html')

@app.route('/admin/parking_lots/edit/<int:lot_id>', methods=('GET', 'POST'))
@admin_required
def edit_parking_lot(lot_id):
    conn = get_db_connection()
    parking_lot = conn.execute('SELECT * FROM parking_lots WHERE id = ?', (lot_id,)).fetchone()

    if parking_lot is None:
        flash('Parking Lot not found.', 'danger')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        name = request.form['prime_location_name']
        address = request.form['address']
        pin_code = request.form['pin_code']
        price_per_hour = request.form['price_per_hour']
        max_spots = request.form['maximum_number_of_spots']
        error = None

        if not name or not address or not pin_code or not price_per_hour or not max_spots:
            error = 'All fields are required.'
        try:
            price_per_hour = float(price_per_hour)
            max_spots = int(max_spots)
            if max_spots <= 0 or price_per_hour < 0:
                error = 'Maximum spots must be positive and price cannot be negative.'
        except ValueError:
            error = 'Price per hour and maximum spots must be valid numbers.'

        if error is None:
            try:
                conn.execute(
                    "UPDATE parking_lots SET prime_location_name = ?, address = ?, pin_code = ?, price_per_hour = ?, maximum_number_of_spots = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (name, address, pin_code, price_per_hour, max_spots, lot_id)
                )
                conn.commit()
                flash('Parking Lot updated successfully!', 'success')
                return redirect(url_for('admin_dashboard'))
            except sqlite3.IntegrityError:
                error = f"A parking lot named '{name}' already exists."
                conn.rollback()
            finally:
                conn.close()
        
        flash(error, 'danger')
    
    conn.close()
    return render_template('edit_parking_lot.html', parking_lot=parking_lot)


@app.route('/admin/parking_lots/delete/<int:lot_id>', methods=('POST',))
@admin_required
def delete_parking_lot(lot_id):
    conn = get_db_connection()
    error = None
    
    active_reservations_count = conn.execute('''
        SELECT COUNT(pr.id)
        FROM parking_reservations pr
        JOIN parking_spots ps ON pr.spot_id = ps.id
        WHERE ps.lot_id = ? AND pr.is_active = 1
    ''', (lot_id,)).fetchone()[0]

    if active_reservations_count > 0:
        error = 'Cannot delete parking lot. There are active parked vehicles in this lot.'

    if error is None:
        try:
            conn.execute('DELETE FROM parking_lots WHERE id = ?', (lot_id,))
            conn.commit()
            flash('Parking Lot deleted successfully!', 'success')
        except sqlite3.Error as e:
            error = f"Database error: {e}"
            conn.rollback()
        finally:
            conn.close()
    
    if error:
        flash(error, 'danger')
        conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/parking_lots/manage_spots/<int:lot_id>')
@admin_required
def manage_spots(lot_id):
    conn = get_db_connection()
    parking_lot = conn.execute('SELECT * FROM parking_lots WHERE id = ?', (lot_id,)).fetchone()
    if parking_lot is None:
        flash('Parking Lot not found.', 'danger')
        conn.close()
        return redirect(url_for('admin_dashboard'))
    
    spots = conn.execute('SELECT * FROM parking_spots WHERE lot_id = ? ORDER BY CAST(SUBSTR(spot_number, 2) AS INTEGER)', (lot_id,)).fetchall()
    
    conn.close()
    flash('This is the "Manage Spots" page. Functionality to add/view/edit individual spots for this lot would go here.', 'info')
    return render_template('manage_spots.html', parking_lot=parking_lot, spots=spots)

@app.route('/admin/parking_spots/edit/<int:spot_id>', methods=('GET', 'POST'))
@admin_required
def edit_spot(spot_id):
    conn = get_db_connection()
    spot = conn.execute('SELECT * FROM parking_spots WHERE id = ?', (spot_id,)).fetchone()

    if spot is None:
        flash('Parking spot not found.', 'danger')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    parking_lot = conn.execute('SELECT prime_location_name FROM parking_lots WHERE id = ?', (spot['lot_id'],)).fetchone()
    if parking_lot is None: 
        flash('Associated parking lot not found.', 'danger')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        new_spot_number = request.form['spot_number'].strip()
        new_status = request.form['status'].strip() 
        error = None

        if not new_spot_number:
            error = 'Spot name/number is required.'
        elif new_status not in ['Available', 'Occupied']: 
            error = 'Invalid status selected.'

        if error is None and new_spot_number != spot['spot_number']:
            existing_spot_with_new_name = conn.execute(
                'SELECT id FROM parking_spots WHERE lot_id = ? AND spot_number = ?',
                (spot['lot_id'], new_spot_number)
            ).fetchone()
            if existing_spot_with_new_name:
                error = f"Spot number '{new_spot_number}' already exists in this parking lot."
        
        
        if error is None and spot['status'] == 'Occupied' and new_status == 'Available':
            active_reservation_check = conn.execute(
                'SELECT id FROM parking_reservations WHERE spot_id = ? AND is_active = 1',
                (spot_id,)
            ).fetchone()
            if active_reservation_check:
                error = "Cannot manually mark 'Occupied' spot as 'Available' because it has an active user reservation. User must release it."


        if error is None:
            try:
                conn.execute(
                    "UPDATE parking_spots SET spot_number = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_spot_number, new_status, spot_id)
                )
                conn.commit()
                flash('Parking spot updated successfully!', 'success')
                return redirect(url_for('manage_spots', lot_id=spot['lot_id']))
            except sqlite3.Error as e:
                error = f"Database error: {e}"
                conn.rollback()
        
        flash(error, 'danger')
        conn = get_db_connection()
        spot = conn.execute('SELECT * FROM parking_spots WHERE id = ?', (spot_id,)).fetchone()
        parking_lot = conn.execute('SELECT prime_location_name FROM parking_lots WHERE id = ?', (spot['lot_id'],)).fetchone()
        conn.close()

    conn.close() 
    return render_template('edit_spot.html', spot=spot, parking_lot=parking_lot)


@app.route('/admin/parking_spots/delete/<int:spot_id>', methods=('POST',))
@admin_required
def delete_spot(spot_id): 
    conn = get_db_connection()
    error = None

    spot = conn.execute('SELECT * FROM parking_spots WHERE id = ?', (spot_id,)).fetchone()
    if spot is None:
        flash('Parking spot not found.', 'danger')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    lot_id = spot['lot_id']

    active_reservation = conn.execute(
        'SELECT id FROM parking_reservations WHERE spot_id = ? AND is_active = 1',
        (spot_id,)
    ).fetchone()

    if active_reservation:
        error = 'Cannot delete spot. It has an active parking reservation. Please ensure the vehicle has departed.'
    else:
        try:
            current_spot_status = spot['status']

            conn.execute('DELETE FROM parking_spots WHERE id = ?', (spot_id,))

            conn.execute(
                "UPDATE parking_lots SET maximum_number_of_spots = maximum_number_of_spots - 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (lot_id,)
            )

            if current_spot_status == 'Occupied':
                conn.execute(
                    "UPDATE parking_lots SET current_occupied_spots = current_occupied_spots - 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (lot_id,)
                )

            conn.commit()
            flash(f'Parking spot "{spot["spot_number"]}" deleted successfully! Parking lot capacity updated.', 'success')

        except sqlite3.Error as e:
            error = f"Database error during spot deletion: {e}"
            conn.rollback()
        finally:
            conn.close()
    
    if error:
        flash(error, 'danger')
    
    return redirect(url_for('manage_spots', lot_id=lot_id))


@app.route('/user_dashboard')
@login_required 
def user_dashboard():
    if not g.user or g.user['role'] != 'user':
        flash('Unauthorized access. Please log in as a user.', 'warning')
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    user_id = g.user['id']

    utc_timezone = pytz.utc
    ist_timezone = pytz.timezone('Asia/Kolkata') 

    available_parking_lots = conn.execute('''
        SELECT id, prime_location_name, address, pin_code, price_per_hour, maximum_number_of_spots, current_occupied_spots
        FROM parking_lots
        WHERE (maximum_number_of_spots - current_occupied_spots) > 0
        ORDER BY prime_location_name
    ''').fetchall()

    active_reservations = conn.execute('''
        SELECT pr.id, pl.prime_location_name, ps.spot_number, pr.parking_timestamp
        FROM parking_reservations pr
        JOIN parking_spots ps ON pr.spot_id = ps.id
        JOIN parking_lots pl ON ps.lot_id = pl.id
        WHERE pr.user_id = ? AND pr.is_active = 1
        ORDER BY pr.parking_timestamp DESC
    ''', (user_id,)).fetchall()

    parking_history = conn.execute('''
        SELECT pr.id, pl.prime_location_name, ps.spot_number, pr.parking_timestamp, pr.leaving_timestamp, pr.total_cost
        FROM parking_reservations pr
        JOIN parking_spots ps ON pr.spot_id = ps.id
        JOIN parking_lots pl ON ps.lot_id = pl.id
        WHERE pr.user_id = ? AND pr.is_active = 0
        ORDER BY pr.leaving_timestamp DESC
    ''', (user_id,)).fetchall()

    processed_active_reservations = []
    for res in active_reservations:
        
        try:
            parking_utc_dt = datetime.strptime(res['parking_timestamp'], '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            parking_utc_dt = datetime.strptime(res['parking_timestamp'], '%Y-%m-%d %H:%M:%S')
        
        parking_utc_dt = utc_timezone.localize(parking_utc_dt)
        parking_ist_dt = parking_utc_dt.astimezone(ist_timezone)
        processed_active_reservations.append({
            'id': res['id'],
            'prime_location_name': res['prime_location_name'],
            'spot_number': res['spot_number'],
            'parking_timestamp': parking_ist_dt.strftime('%Y-%m-%d %H:%M:%S') 
        })

    processed_parking_history = []
    for hist in parking_history:
        try:
            parking_utc_dt = datetime.strptime(hist['parking_timestamp'], '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            parking_utc_dt = datetime.strptime(hist['parking_timestamp'], '%Y-%m-%d %H:%M:%S')
        
        parking_utc_dt = utc_timezone.localize(parking_utc_dt)
        parking_ist_dt = parking_utc_dt.astimezone(ist_timezone)

        leaving_ist_dt_str = 'N/A'
        if hist['leaving_timestamp']:
            try:
                leaving_utc_dt = datetime.strptime(hist['leaving_timestamp'], '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                leaving_utc_dt = datetime.strptime(hist['leaving_timestamp'], '%Y-%m-%d %H:%M:%S')
            
            leaving_utc_dt = utc_timezone.localize(leaving_utc_dt)
            leaving_ist_dt = leaving_utc_dt.astimezone(ist_timezone)
            leaving_ist_dt_str = leaving_ist_dt.strftime('%Y-%m-%d %H:%M:%S')

        processed_parking_history.append({
            'id': hist['id'],
            'prime_location_name': hist['prime_location_name'],
            'spot_number': hist['spot_number'],
            'parking_timestamp': parking_ist_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'leaving_timestamp': leaving_ist_dt_str,
            'total_cost': hist['total_cost']
        })

    total_reservations = conn.execute('SELECT COUNT(*) FROM parking_reservations WHERE user_id = ?', (user_id,)).fetchone()[0]
    completed_parks = conn.execute('SELECT COUNT(*) FROM parking_reservations WHERE user_id = ? AND is_active = 0', (user_id,)).fetchone()[0]
    total_amount_spent = conn.execute('SELECT SUM(total_cost) FROM parking_reservations WHERE user_id = ? AND is_active = 0', (user_id,)).fetchone()[0] or 0.0

    conn.close()
    return render_template('user_dashboard.html',
                           available_parking_lots=available_parking_lots,
                           active_reservations=processed_active_reservations, 
                           parking_history=processed_parking_history,       
                           total_reservations=total_reservations,
                           completed_parks=completed_parks,
                           total_amount_spent=total_amount_spent)


@app.route('/user/book_parking_spot/<int:lot_id>', methods=('POST',))
@login_required
def book_parking_spot(lot_id):
    conn = get_db_connection()
    user_id = g.user['id']
    error = None

    existing_active_reservation = conn.execute('SELECT id FROM parking_reservations WHERE user_id = ? AND is_active = 1', (user_id,)).fetchone()
    if existing_active_reservation:
        error = 'You already have an active parking reservation. Please release it before booking another.'
        flash(error, 'danger')
        conn.close()
        return redirect(url_for('user_dashboard'))

    available_spot = conn.execute(
        'SELECT id, lot_id FROM parking_spots WHERE lot_id = ? AND status = ? LIMIT 1',
        (lot_id, 'Available')
    ).fetchone()

    if available_spot:
        try:
            spot_id = available_spot['id']
            conn.execute(
                "UPDATE parking_spots SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ('Occupied', spot_id)
            )
            
            conn.execute(
                "INSERT INTO parking_reservations (spot_id, user_id, parking_timestamp, is_active) VALUES (?, ?, CURRENT_TIMESTAMP, 1)",
                (spot_id, user_id)
            )
            conn.execute(
                "UPDATE parking_lots SET current_occupied_spots = current_occupied_spots + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (lot_id,)
            )
            conn.commit()
            flash('Parking spot booked successfully! Check your active reservations.', 'success')
        except sqlite3.Error as e:
            error = f"Database error during booking: {e}"
            flash(error, 'danger')
            conn.rollback()
        finally:
            conn.close()
    else:
        flash('No available spots in this parking lot.', 'danger')
        conn.close()
    
    return redirect(url_for('user_dashboard'))


@app.route('/user/release_parking_spot/<int:reservation_id>', methods=('POST',))
@login_required
def release_parking_spot(reservation_id):
    conn = get_db_connection()
    user_id = g.user['id']
    error = None

    reservation = conn.execute(
        'SELECT pr.id, pr.spot_id, pr.parking_timestamp, pl.price_per_hour '
        'FROM parking_reservations pr '
        'JOIN parking_spots ps ON pr.spot_id = ps.id '
        'JOIN parking_lots pl ON ps.lot_id = pl.id '
        'WHERE pr.id = ? AND pr.user_id = ? AND pr.is_active = 1',
        (reservation_id, user_id)
    ).fetchone()

    if reservation is None:
        flash('Active reservation not found or you do not have permission to release it.', 'danger')
        conn.close()
        return redirect(url_for('user_dashboard'))

    try:
        spot_id = reservation['spot_id']
        utc_timezone = pytz.utc
        ist_timezone = pytz.timezone('Asia/Kolkata') 

        parking_timestamp_str = reservation['parking_timestamp']
        try:
            parking_timestamp_utc = datetime.strptime(parking_timestamp_str, '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            parking_timestamp_utc = datetime.strptime(parking_timestamp_str, '%Y-%m-%d %H:%M:%S')
        parking_timestamp_utc = utc_timezone.localize(parking_timestamp_utc) 

        leaving_timestamp_ist = ist_timezone.localize(datetime.now()) 
        leaving_timestamp_utc = leaving_timestamp_ist.astimezone(utc_timezone)

        price_per_hour = reservation['price_per_hour']

        duration_delta = leaving_timestamp_utc - parking_timestamp_utc
        duration_seconds = duration_delta.total_seconds()
        
        billed_hours = 0
        total_cost = 0.0
        if duration_seconds > 0:
            billed_hours = math.ceil(duration_seconds / 3600.0)
            if billed_hours == 0: 
                billed_hours = 1
            total_cost = round(billed_hours * price_per_hour, 2)

        conn.execute(
            "UPDATE parking_spots SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            ('Available', spot_id)
        )

        conn.execute(
            "UPDATE parking_reservations SET leaving_timestamp = ?, total_cost = ?, is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (leaving_timestamp_utc.strftime('%Y-%m-%d %H:%M:%S'), total_cost, reservation_id) 
        )

        lot_id_for_spot = conn.execute('SELECT lot_id FROM parking_spots WHERE id = ?', (spot_id,)).fetchone()['lot_id']
        conn.execute(
            "UPDATE parking_lots SET current_occupied_spots = current_occupied_spots - 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (lot_id_for_spot,)
        )

        conn.commit()
        flash(f'Parking spot released successfully! Total cost: ₹{total_cost:.2f}', 'success')
    except sqlite3.Error as e:
        error = f"Database error during release: {e}"
        flash(error, 'danger')
        conn.rollback()
    finally:
        conn.close()
    
    return redirect(url_for('user_dashboard'))



# MAIN ENTRY POINT
if __name__ == '__main__':
    ist_timezone = pytz.timezone('Asia/Kolkata')
    current_time_ist = datetime.now(ist_timezone).strftime('%Y-%m-%d %H:%M:%S IST')
    print(f"[{current_time_ist}] Starting Flask application...")

    with app.app_context():
        db_exists = os.path.exists(DATABASE)

        force_reinit = os.environ.get('FLASK_REINIT_DB') == '1'

        if not db_exists or force_reinit:
            if not db_exists:
                print(f"[{current_time_ist}] Database file not found at {DATABASE}. Initializing database...")
            elif force_reinit:
                print(f"[{current_time_ist}] FLASK_REINIT_DB is set to 1. Forcing database re-initialization at {DATABASE}...")
            
            init_db(DATABASE) 
            print(f"[{current_time_ist}] Database initialized successfully.")
        else:
            print(f"[{current_time_ist}] Database already exists at {DATABASE}. Skipping initialization. To force re-initialization, set FLASK_REINIT_DB=1 environment variable.")
    
    app.run(debug=True)
