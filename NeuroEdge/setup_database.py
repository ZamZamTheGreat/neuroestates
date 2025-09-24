# setup_database.py
import sqlite3
import os

def create_database_schema(db_path):
    """Create the database schema for an agency"""
    
    # Ensure the directory exists
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else '.', exist_ok=True)
    
    # Connect to SQLite database (creates it if it doesn't exist)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create properties table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS properties (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            currency TEXT DEFAULT 'NAD',
            property_type TEXT NOT NULL,
            bedrooms INTEGER,
            bathrooms INTEGER,
            size_sqft INTEGER,
            location TEXT NOT NULL,
            city TEXT DEFAULT 'Windhoek',
            features TEXT,
            status TEXT DEFAULT 'available',
            agent_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create agents table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            specialty TEXT,
            bio TEXT
        )
    ''')
    
    print(f"✅ Database schema created successfully at: {db_path}")
    
    # Close the connection
    conn.close()

def insert_sample_data(db_path, agency_name):
    """Insert sample data for testing"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Sample agents data
    agents_data = {
        "NeuroEdge Properties": [
            ('NE001', 'AI Agent Mike', 'mike@neuroedge.properties', '+264 81 345 6789', 
             'Smart Homes & Technology', 'Specialized in eco-friendly smart homes.'),
            ('NE002', 'AI Agent Sarah', 'sarah@neuroedge.properties', '+264 81 456 7890',
             'Luxury Apartments', 'Expert in luxury apartment investments.')
        ],
        "Windhoek Property Brokers": [
            ('WPB001', 'John Doe', 'john@windhoekbrokers.com', '+264 81 123 4567', 
             'Family Homes', 'Experienced in family home sales.'),
            ('WPB002', 'Sarah Smith', 'sarah@windhoekbrokers.com', '+264 81 234 5678',
             'Luxury Properties', 'Specialized in luxury real estate.')
        ]
    }
    
    # Sample properties data
    properties_data = {
        "NeuroEdge Properties": [
            ('NE-P001', 'Smart Eco-Home in Pioneers Park', 
             'Beautiful eco-friendly smart home with modern technology.', 2800000.00, 
             'house', 3, 2, 3200, 'Pioneers Park, Windhoek', '["Solar Panels", "Smart Home"]', 'NE001'),
            ('NE-P002', 'Luxury Apartment in CBD', 'Stunning luxury apartment with city views.', 
             1500000.00, 'apartment', 2, 2, 950, 'CBD, Windhoek', '["Pool", "Gym"]', 'NE002')
        ],
        "Windhoek Property Brokers": [
            ('WPB-P001', 'Luxury Villa in Klein Windhoek', 'Magnificent luxury villa with amenities.', 
             3500000.00, 'house', 4, 3, 4500, 'Klein Windhoek, Windhoek', '["Pool", "Garden"]', 'WPB001'),
            ('WPB-P002', 'Modern Townhouse in Olympia', 'Contemporary townhouse in secure complex.', 
             1200000.00, 'townhouse', 3, 2, 1800, 'Olympia, Windhoek', '["Secure Complex"]', 'WPB002')
        ]
    }
    
    # Insert agents
    agents = agents_data.get(agency_name, [])
    cursor.executemany('''
        INSERT OR IGNORE INTO agents (id, name, email, phone, specialty, bio)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', agents)
    
    # Insert properties
    properties = properties_data.get(agency_name, [])
    cursor.executemany('''
        INSERT OR IGNORE INTO properties 
        (id, title, description, price, property_type, bedrooms, bathrooms, size_sqft, location, features, agent_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', properties)
    
    conn.commit()
    conn.close()
    print(f"✅ Sample data inserted for {agency_name}")

if __name__ == "__main__":
    # Create database for NeuroEdge Properties
    create_database_schema('neuroedge_properties.db')
    insert_sample_data('neuroedge_properties.db', 'NeuroEdge Properties')
    
    # Create database for Windhoek Property Brokers
    create_database_schema('windhoek_brokers.db')
    insert_sample_data('windhoek_brokers.db', 'Windhoek Property Brokers')
    
    print("🎉 All databases created successfully!")