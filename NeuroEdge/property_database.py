# property_database.py - COMPLETE VERSION
import sqlite3
import json
import hashlib
from datetime import datetime

class PropertyDatabase:
    def __init__(self, db_path, agency_name):
        self.db_path = db_path
        self.agency_name = agency_name
        self.init_database()
        self.init_users_table()

    def init_database(self):
        """Initialize the database with all required tables"""
        conn = sqlite3.connect(self.db_path)
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
                listing_url TEXT,  -- NEW: Link to external listing (Property24, etc.)
                images TEXT,       -- NEW: JSON array of image URLs
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
        
        # Insert sample agents if they don't exist
        sample_agents = [
            ('NE001', 'Sergej-AI', 'sergejwitbooi@gmail.com', '+264 85 749 4061', 
             'Smart Homes & Technology', 'Specialized in eco-friendly smart homes.'),
            ('NE002', 'Obert Nortje-AI', 'obert@remaxnam.com', '+264 81 867 5501',
             'Luxury Apartments', 'Expert in luxury apartment investments.'),
            ('NE003', 'Wilne Van Wyk-AI', 'wilnevanwyk@gmail.com', '+264 81 715 1644',
             'Commercial Properties', 'Focused on commercial real estate.'),
            ('NE005', 'Christopher Grant Van Wyk-AI', 'christopher@neuroedge.properties', '+264 81 234 5678',
             'Residential Properties', 'Expert in residential property sales.')
        ]
        
        for agent in sample_agents:
            cursor.execute('''
                INSERT OR IGNORE INTO agents (id, name, email, phone, specialty, bio)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', agent)
        
        conn.commit()
        conn.close()
        print(f"✅ Database initialized for {self.agency_name}")
    
    def init_users_table(self):
        """Initialize users table for admin authentication"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'admin',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create default admin user if not exists
        cursor.execute('SELECT * FROM users WHERE username = ?', ('admin',))
        if not cursor.fetchone():
            default_password = "admin123"
            password_hash = hashlib.sha256(default_password.encode()).hexdigest()
            cursor.execute('''
                INSERT INTO users (username, password_hash, role)
                VALUES (?, ?, ?)
            ''', ('admin', password_hash, 'admin'))
            print(f"✅ Default admin user created for {self.agency_name}")
        
        conn.commit()
        conn.close()
    
    def verify_user(self, username, password):
        """Verify user credentials"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT password_hash FROM users WHERE username = ?', (username,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            stored_hash = result[0]
            input_hash = hashlib.sha256(password.encode()).hexdigest()
            return stored_hash == input_hash
        
        return False
    
    
    
    def create_user(self, username, password, role='admin'):
        """Create a new admin user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        try:
            cursor.execute('''
                INSERT INTO users (username, password_hash, role)
                VALUES (?, ?, ?)
            ''', (username, password_hash, role))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # Username already exists
        finally:
            conn.close()

    def change_user_password(self, username, new_password):
        """Change user password"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
    
        try:
            password_hash = hashlib.sha256(new_password.encode()).hexdigest()
            cursor.execute('''
                UPDATE users 
                SET password_hash = ?
                WHERE username = ?
            ''', (password_hash, username))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error changing password: {e}")
            return False
        finally:
            conn.close()

    # AGENT MANAGEMENT METHODS
    def get_agents(self):
        """Get list of all agents"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM agents ORDER BY name')
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]

    def delete_agent(self, agent_id):
        """Delete an agent from the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
    
        try:
            # First check if the agent has any properties
            cursor.execute('SELECT COUNT(*) FROM properties WHERE agent_id = ?', (agent_id,))
            property_count = cursor.fetchone()[0]
            
            if property_count > 0:
                return False, f"Cannot delete agent. {property_count} properties are assigned to this agent."
            
            # Delete the agent
            cursor.execute('DELETE FROM agents WHERE id = ?', (agent_id,))
            conn.commit()
            return True, "Agent deleted successfully"
        
        except Exception as e:
            print(f"Error deleting agent: {e}")
            return False, str(e)
        finally:
            conn.close()

    def add_agent(self, agent_data):
        """Add a new agent to the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
    
        try:
            cursor.execute('''
                INSERT INTO agents (id, name, email, phone, specialty, bio)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                agent_data['id'],
                agent_data['name'],
                agent_data['email'],
                agent_data['phone'],
                agent_data['specialty'],
                agent_data.get('bio', '')
            ))
            conn.commit()
            return True, "Agent added successfully"
        except sqlite3.IntegrityError:
            return False, "Agent ID already exists"
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()

    def update_agent(self, agent_id, updates):
        """Update an existing agent"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
    
        try:
            set_clause = ", ".join([f"{key} = ?" for key in updates.keys()])
            values = list(updates.values())
            values.append(agent_id)
        
            cursor.execute(f'''
                UPDATE agents 
                SET {set_clause}
                WHERE id = ?
            ''', values)
            conn.commit()
            return True, "Agent updated successfully"
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()
    
    # PROPERTY MANAGEMENT METHODS
    def add_property(self, property_data):
        """Add a new property to the database with enhanced features"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO properties 
                (id, title, description, price, property_type, bedrooms, bathrooms, 
                 size_sqft, location, features, agent_id, listing_url, images)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                property_data['id'],
                property_data['title'],
                property_data['description'],
                property_data['price'],
                property_data['property_type'],
                property_data['bedrooms'],
                property_data['bathrooms'],
                property_data['size_sqft'],
                property_data['location'],
                json.dumps(property_data.get('features', [])),
                property_data['agent_id'],
                property_data.get('listing_url', ''),  # External listing link
                json.dumps(property_data.get('images', []))  # Image URLs
            ))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            print(f"Property ID {property_data['id']} already exists")
            return False
        except Exception as e:
            print(f"Error adding property: {e}")
            return False
        finally:
            conn.close()

    def get_property_with_links(self, property_id):
        """Get property with enhanced link information"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
    
        cursor.execute('''
            SELECT p.*, a.name as agent_name, a.phone as agent_phone, 
                   a.specialty as agent_specialty, a.email as agent_email
            FROM properties p
            JOIN agents a ON p.agent_id = a.id
            WHERE p.id = ?
        ''', (property_id,))
    
        result = cursor.fetchone()
        conn.close()
    
        if result:
            property_dict = dict(result)
            # Generate chat link based on agent
            property_dict['chat_link'] = self.generate_chat_link(property_dict['agent_name'])
            return property_dict
        return None

    def generate_chat_link(self, agent_name):
        """Generate chat link for the agent"""
        # Map agent names to chat routes
        agent_chat_map = {
            'AI Agent Sergej': '/chat/AI Agent Sergej',
            'AI Agent Obert': '/chat/AI Agent Obert', 
            'AI Agent Wilne': '/chat/AI Agent Wilne',
            'AI Agent Christopher': '/chat/AI Agent Christopher'
        }
        return agent_chat_map.get(agent_name, '/chat/General Inquiry')
    
    def get_all_properties(self, include_deleted=False):
        """Get all properties with option to include deleted ones"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
    
        if include_deleted:
            cursor.execute('''
                SELECT p.*, a.name as agent_name, a.phone as agent_phone, a.specialty as agent_specialty
                FROM properties p
                JOIN agents a ON p.agent_id = a.id
                ORDER BY p.created_at DESC
            ''')
        else:
            cursor.execute('''
                SELECT p.*, a.name as agent_name, a.phone as agent_phone, a.specialty as agent_specialty
                FROM properties p
                JOIN agents a ON p.agent_id = a.id
                WHERE p.status = 'available' OR p.status IS NULL
                ORDER BY p.created_at DESC
            ''')
    
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]

    def get_property_by_id(self, property_id):
        """Get a specific property by ID"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT p.*, a.name as agent_name, a.phone as agent_phone, a.specialty as agent_specialty
            FROM properties p
            JOIN agents a ON p.agent_id = a.id
            WHERE p.id = ?
        ''', (property_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return dict(result)
        return None

    def add_property(self, property_data):
        """Add a new property to the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO properties 
                (id, title, description, price, property_type, bedrooms, bathrooms, 
                 size_sqft, location, features, agent_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                property_data['id'],
                property_data['title'],
                property_data['description'],
                property_data['price'],
                property_data['property_type'],
                property_data['bedrooms'],
                property_data['bathrooms'],
                property_data['size_sqft'],
                property_data['location'],
                json.dumps(property_data.get('features', [])),
                property_data['agent_id']
            ))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            print(f"Property ID {property_data['id']} already exists")
            return False
        except Exception as e:
            print(f"Error adding property: {e}")
            return False
        finally:
            conn.close()
    
    def update_property(self, property_id, updates):
        """Update an existing property"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            set_clause = ", ".join([f"{key} = ?" for key in updates.keys()])
            values = list(updates.values())
            values.append(property_id)
            
            cursor.execute(f'''
                UPDATE properties 
                SET {set_clause}
                WHERE id = ?
            ''', values)
            conn.commit()
            return True
        except Exception as e:
            print(f"Error updating property: {e}")
            return False
        finally:
            conn.close()

    def soft_delete_property(self, property_id):
        """Soft delete by setting status to 'deleted'"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE properties 
                SET status = 'deleted'
                WHERE id = ?
            ''', (property_id,))
            conn.commit()
            return True, "Property archived successfully"
        except Exception as e:
            print(f"Error archiving property: {e}")
            return False, str(e)
        finally:
            conn.close()

    def permanently_delete_property(self, property_id):
        """Permanently delete a property from the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # First, get property info for confirmation message
            cursor.execute('SELECT title FROM properties WHERE id = ?', (property_id,))
            property_info = cursor.fetchone()
            property_title = property_info[0] if property_info else "Unknown Property"
            
            # Permanently delete the property
            cursor.execute('DELETE FROM properties WHERE id = ?', (property_id,))
            conn.commit()
            return True, f"Property '{property_title}' permanently deleted"
        except Exception as e:
            print(f"Error permanently deleting property: {e}")
            return False, str(e)
        finally:
            conn.close()

    def get_deleted_properties(self):
        """Get all soft-deleted properties"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT p.*, a.name as agent_name, a.phone as agent_phone, a.specialty as agent_specialty
                FROM properties p
                JOIN agents a ON p.agent_id = a.id
                WHERE p.status IN ('deleted', 'sold', 'archived')
                ORDER BY p.created_at DESC
            ''')
            results = cursor.fetchall()
            return [dict(row) for row in results]
        except Exception as e:
            print(f"Error getting deleted properties: {e}")
            return []
        finally:
            conn.close()

    def restore_property(self, property_id):
        """Restore a soft-deleted property"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE properties 
                SET status = 'available'
                WHERE id = ?
            ''', (property_id,))
            conn.commit()
            return True, "Property restored successfully"
        except Exception as e:
            print(f"Error restoring property: {e}")
            return False, str(e)
        finally:
            conn.close()

    def permanently_delete_all_deleted(self):
        """Permanently delete all soft-deleted properties"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Count how many will be deleted
            cursor.execute('SELECT COUNT(*) FROM properties WHERE status IN ("deleted", "sold", "archived")')
            count = cursor.fetchone()[0]
            
            if count == 0:
                return True, "No deleted properties found to remove"
            
            # Permanently delete them
            cursor.execute('DELETE FROM properties WHERE status IN ("deleted", "sold", "archived")')
            deleted_count = cursor.changes
            conn.commit()
            return True, f"Permanently deleted {deleted_count} properties"
        except Exception as e:
            print(f"Error deleting all soft-deleted properties: {e}")
            return False, str(e)
        finally:
            conn.close()

    def empty_trash(self):
        """Alias for permanently_delete_all_deleted"""
        return self.permanently_delete_all_deleted()
    
    def search_properties(self, query, max_results=10):
        """Balanced property search - matches query terms with weighted relevance scoring."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if not query or query.strip() == "":
            # Return recent properties for empty search
            sql = '''
                SELECT p.*, a.name as agent_name, a.phone as agent_phone, 
                       a.specialty as agent_specialty, a.email as agent_email
                FROM properties p
                JOIN agents a ON p.agent_id = a.id
                WHERE (p.status = 'available' OR p.status IS NULL)
                ORDER BY p.created_at DESC
                LIMIT ?
            '''
            cursor.execute(sql, [max_results])
            results = cursor.fetchall()
            conn.close()
            return [dict(row) for row in results]

        # Break query into terms (ignore very short ones)
        search_terms = [term.strip().lower() for term in query.split() if len(term.strip()) > 2]
        if not search_terms:
            search_terms = [query.lower()]

        # --- Build WHERE clause ---
        # Conditions only for search terms
        search_conditions = []

        # Exact phrase condition
        exact_phrase_condition = """
            (p.title LIKE ? OR p.description LIKE ? OR p.location LIKE ? 
             OR p.property_type LIKE ? OR p.features LIKE ?)
        """
        exact_pattern = f'%{query}%'
        search_conditions.append(exact_phrase_condition)
        params = [exact_pattern] * 5

        # Individual term matching
        for term in search_terms:
            term_pattern = f'%{term}%'
            search_conditions.append("""
                (p.title LIKE ? OR p.description LIKE ? OR p.location LIKE ? 
                 OR p.property_type LIKE ? OR p.features LIKE ?)
            """)
            params.extend([term_pattern] * 5)

        # Final WHERE clause: always enforce availability
        where_clause = f"(p.status = 'available' OR p.status IS NULL) AND ({' OR '.join(search_conditions)})"

        # --- Build SQL with scoring ---
        sql = f'''
            SELECT p.*, a.name as agent_name, a.phone as agent_phone, 
                   a.specialty as agent_specialty, a.email as agent_email,
                   (
                       (CASE WHEN p.title LIKE ? THEN 10 ELSE 0 END) +
                       (CASE WHEN p.description LIKE ? THEN 6 ELSE 0 END) +
                       (CASE WHEN p.location LIKE ? THEN 8 ELSE 0 END) +
                       (CASE WHEN p.property_type LIKE ? THEN 7 ELSE 0 END) +
                       (CASE WHEN p.features LIKE ? THEN 5 ELSE 0 END)
                   ) as relevance_score
            FROM properties p
            JOIN agents a ON p.agent_id = a.id
            WHERE {where_clause}
            ORDER BY relevance_score DESC, p.price ASC
            LIMIT ?
        '''

        # Add scoring params (based on full query)
        scoring_pattern = f'%{query}%'
        params.extend([
            scoring_pattern, scoring_pattern, scoring_pattern,
            scoring_pattern, scoring_pattern,  # scoring weights
            max_results
        ])

        cursor.execute(sql, params)
        results = cursor.fetchall()
        conn.close()

        return [dict(row) for row in results]
