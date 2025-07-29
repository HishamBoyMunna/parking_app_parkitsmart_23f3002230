import sqlite3
from werkzeug.security import generate_password_hash 
import os 

DATABASE = 'models/database.db' 

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row 
    return conn

def init_db():
    """Initializes the database schema and creates the default admin user."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS parking_reservations")
    cursor.execute("DROP TABLE IF EXISTS parking_spots")
    cursor.execute("DROP TABLE IF EXISTS parking_lots")
    cursor.execute("DROP TABLE IF EXISTS users")

    cursor.execute('''
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user', -- 'user' or 'admin'
            email TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE parking_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prime_location_name TEXT NOT NULL UNIQUE,
            address TEXT NOT NULL,
            pin_code TEXT NOT NULL,
            price_per_hour REAL NOT NULL,
            maximum_number_of_spots INTEGER NOT NULL,
            current_occupied_spots INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE parking_spots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lot_id INTEGER NOT NULL,
            spot_number TEXT NOT NULL, -- e.g., 'A1', 'B2'
            status TEXT NOT NULL DEFAULT 'Available', -- 'Available' or 'Occupied'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (lot_id) REFERENCES parking_lots (id) ON DELETE CASCADE,
            UNIQUE (lot_id, spot_number) -- Ensure spot numbers are unique within a lot
        )
    ''')

    cursor.execute('''
        CREATE TABLE parking_reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spot_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            parking_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            leaving_timestamp TIMESTAMP, -- Nullable until vehicle leaves
            total_cost REAL, -- Nullable until vehicle leaves
            is_active INTEGER NOT NULL DEFAULT 1, -- 1 for active, 0 for completed/inactive
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (spot_id) REFERENCES parking_spots (id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    ''')

    admin_username = os.environ.get('ADMIN_USERNAME', 'admin') 
    admin_password = os.environ.get('ADMIN_PASSWORD', 'adminpassword') 
    admin_email = os.environ.get('ADMIN_EMAIL', 'admin@example.com') 

    hashed_password = generate_password_hash(admin_password)

    try:
        cursor.execute("INSERT INTO users (username, password_hash, role, email) VALUES (?, ?, ?, ?)",
                       (admin_username, hashed_password, 'admin', admin_email))
        conn.commit()
        print(f"Admin user '{admin_username}' created successfully.")
    except sqlite3.IntegrityError:
        print(f"Admin user '{admin_username}' already exists.")
        conn.rollback() 

    conn.close()

if __name__ == '__main__':
    
    print("Initializing database...")
    init_db()
    print("Database initialized successfully.")
