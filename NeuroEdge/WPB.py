import os
import re
import json
import uuid
import redis
import openai
import sqlite3
import hashlib
from functools import wraps
from property_database import PropertyDatabase
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, session, redirect, url_for, flash, jsonify, abort
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
from flask_session import Session
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from flask import make_response
from openai import OpenAI
import requests
from markupsafe import escape
from functools import wraps

app = Flask(__name__)
app.jinja_env.globals['now'] = datetime.now
app.config['SESSION_COOKIE_SECURE'] = True

# ─── Setup ───────────────────────────────────────────────────────────────────
load_dotenv()

# ─── Paths & Uploads ─────────────────────────────────────────────────────────
BASE_DIR = '/var/data'  # all agent data stored here
UPLOAD_FOLDER = BASE_DIR  # same as /var/data, each agent gets a subfolder
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # ensure folder exists


# ─── Flask app config ───────────────────────────────────────────────────────
app.secret_key = 'super-secret-key'  # or replace with a stronger one
# ─── Paths & Uploads ─────────────────────────────────────────────────────────

# Persistent Disk base path (mounted at /var/data in Render)
PERSISTENT_DISK_PATH = "/var/data"
os.makedirs(PERSISTENT_DISK_PATH, exist_ok=True)
db = PropertyDatabase('neuroedge_properties.db', 'NeuroEdge Properties')

# Flask configuration
app.config['UPLOAD_FOLDER'] = PERSISTENT_DISK_PATH  # base folder for all agent data
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'docx', 'txt', 'md'}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max per file

# --- Load Redis from .env ---

REDIS_URL = os.getenv("SESSION_REDIS_URL")  # e.g. redis://default:<password>@<host>:6379

try:
    # Use decode_responses=False for binary-safe session storage
    r = redis.from_url(REDIS_URL, decode_responses=False)
    r.ping()
    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_REDIS'] = r
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_USE_SIGNER'] = True
    Session(app)
    print("✅ Using Redis for sessions")
except Exception as e:
    print(f"⚠️ Redis connection failed: {e}. Using filesystem sessions")
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_REDIS'] = None
Session(app)

# ─── OpenAI API Key ─────────────────────────────────────────────────────────
openai.api_key = os.getenv('OPENAI_API_KEY')

# ─── Login ───────────────────────────────────────────────────────────────────
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
login_manager = LoginManager()
login_manager.init_app(app)

class User(UserMixin):
    def __init__(self, id_): self.id = id_
    @property
    def is_admin(self): return self.id == os.getenv('ADMIN_USERNAME')
    
@login_manager.user_loader
def load_user(uid):
    return User(uid) if uid == os.getenv('ADMIN_USERNAME') else None

# ─── Utilities ───────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOC_JSON_PATH = '/var/data/global_docs.json'

# ─── Helper Functions ────────────────────────────────────────────────────────

def get_database():
    """Helper function to get database instance with correct arguments"""
    return PropertyDatabase(db_path='neuroedge_properties.db', agency_name=session.get('admin_agency', 'NeuroEdge Properties'))

def load_prompt(name):
    """Load system prompt text for a given agent."""
    prompt_path = os.path.join(BASE_DIR, 'prompts', f'{name}.txt')
    if os.path.exists(prompt_path):
        with open(prompt_path, encoding='utf-8') as f:
            return f.read()
    return ""

def allowed_file(filename):
    """Check if the file type is allowed."""
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'md', 'csv'}  # adjust as needed
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_user_upload_dir(agent_id):
    """Return the agent-specific folder under /var/data and ensure it exists."""
    path = os.path.join(UPLOAD_FOLDER, agent_id)
    os.makedirs(path, exist_ok=True)
    return path

def load_global_docs():
    """Load JSON registry of uploaded files."""
    if os.path.exists(DOC_JSON_PATH):
        with open(DOC_JSON_PATH, 'r', encoding='utf-8') as f:
            docs = json.load(f)
            # Normalize paths to just filenames
            for agent_id, paths in docs.items():
                if not isinstance(paths, list):
                    paths = [paths]
                docs[agent_id] = [os.path.basename(p) for p in paths]
            return docs
    return {}

def save_global_docs(docs):
    """Save the JSON registry."""
    with open(DOC_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(docs, f, indent=2)

def preload_documents():
    """
    Loads all agent documents from disk (deprecated; use load_agent_documents()).
    Returns a dict of {agent_id: [file_contents]}.
    """
    all_docs = {}
    if not os.path.exists(UPLOAD_FOLDER):
        return all_docs

    for agent_id in os.listdir(UPLOAD_FOLDER):
        agent_dir = os.path.join(UPLOAD_FOLDER, agent_id)
        if not os.path.isdir(agent_dir):
            continue

        for filename in os.listdir(agent_dir):
            if not allowed_file(filename):
                continue
            file_path = os.path.join(agent_dir, filename)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                all_docs.setdefault(agent_id, []).append(content)
            except Exception as e:
                print(f"Error reading {file_path}: {e}")

    return all_docs

# Global dictionary to hold loaded docs content
AGENT_DOCUMENTS = {}

def load_agent_documents():
    """
    Load all agent documents from /var/data/<agent_id>/ into AGENT_DOCUMENTS.
    Works with files manually placed or uploaded via the app.
    """
    global AGENT_DOCUMENTS
    AGENT_DOCUMENTS = {}

    base_dir = '/var/data'
    global_docs = load_global_docs()

    if not os.path.exists(base_dir):
        print("Persistent disk not found at /var/data")
        return

    for agent_id in os.listdir(base_dir):
        agent_folder = os.path.join(base_dir, agent_id)
        if not os.path.isdir(agent_folder):
            continue

        contents = []

        # First, load all files in the agent folder
        for filename in os.listdir(agent_folder):
            file_path = os.path.join(agent_folder, filename)
            if not allowed_file(filename):
                continue
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    contents.append(f.read())
            except UnicodeDecodeError:
                print(f"Skipping non-text file for agent '{agent_id}': {file_path}")
            except Exception as e:
                print(f"Failed to load document for agent '{agent_id}' at {file_path}: {e}")

        # Update the global JSON registry if missing
        existing_files = global_docs.get(agent_id, [])
        for filename in os.listdir(agent_folder):
            if filename not in existing_files:
                global_docs.setdefault(agent_id, []).append(filename)
        save_global_docs(global_docs)

        AGENT_DOCUMENTS[agent_id] = contents

    print("All agent documents loaded from /var/data")

def format_search_results(properties, query):
    """Format database search results for GPT context"""
    if not properties:
        return "No properties found matching your search criteria."
    
    result_text = f"Found {len(properties)} properties matching: '{query}'\n\n"
    
    for i, prop in enumerate(properties, 1):
        result_text += f"🏠 PROPERTY {i}: {prop['title']}\n"
        result_text += f"💰 PRICE: N$ {prop['price']:,.2f}\n"
        result_text += f"📍 LOCATION: {prop['location']}\n"
        result_text += f"🛏️ BEDROOMS: {prop['bedrooms']} | 🚿 BATHROOMS: {prop['bathrooms']}\n"
        result_text += f"📏 SIZE: {prop.get('size_sqft', 'N/A')} sqft\n"
        result_text += f"🏢 TYPE: {prop['property_type']}\n"
        
        # Add features if available
        if prop.get('features'):
            try:
                features = json.loads(prop['features']) if isinstance(prop['features'], str) else prop['features']
                if features:
                    result_text += f"⭐ FEATURES: {', '.join(features[:5])}\n"
            except:
                pass
        
        # Add agent info
        result_text += f"🤝 AGENT: {prop.get('agent_name', 'N/A')}\n"
        
        # Add external link if available
        if prop.get('listing_url'):
            result_text += f"🔗 LISTING: {prop['listing_url']}\n"
        
        result_text += "─" * 50 + "\n\n"
    
    return result_text

def convert_urls_to_buttons(text):
    """Convert actual https URLs into clickable 'View Property' buttons."""
    # Matches https://... ignoring trailing punctuation like ) or .
    url_pattern = r'https://[^\s<>")]+'
    return re.sub(
        url_pattern,
        lambda m: f"<a href='{m.group(0)}' target='_blank' class='property-link'>View Property</a>",
        text
    )


def chat_url_for(agent_name: str) -> str:
    """Absolute link to an agent's chat page."""
    try:
        # Works inside a request context; builds https/http + host automatically
        return url_for('chat', agent_id=agent_name, _external=True)
    except RuntimeError:
        # Fallback if somehow called without request context
        return f"/chat/{agent_name}"
    
# ─── Agents ──────────────────────────────────────────────────────────────────
AGENT_CONFIG = {
    'Wilne Van Wyk-AI': {'system_prompt':load_prompt('Wilne')},
    'Sergej-AI': {'system_prompt':load_prompt('sergej')},
    'Search-AI': {'system_prompt': load_prompt('Search')},
    'Obert Nortje-AI': {'system_prompt': load_prompt('Obert Nortje')},
    'Christopher Grant Van Wyk-AI': {'system_prompt': load_prompt('Christopher')},
}
global_docs = load_global_docs()
AGENT_DOCUMENTS = preload_documents()

# Mapping agents to their Tally form links
TALLY_FORMS = {
    "Sergej-AI": "https://tally.so/r/mD9W4j",
    "Wilne Van Wyk-AI": "https://tally.so/r/mZr85a",
    "Christopher Grant Van Wyk-AI": "https://tally.so/r/3XPLld",
    "Obert Nortje-AI": "https://tally.so/r/3XPLld",
    # Add more agents here as needed
}

# ─── Chat Handling ───────────────────────────────────────────────────────────
# ─── User Agent Data ─────────────────────────────────────────────────────────
def user_agent_data(agent_id):
    session.setdefault('agent_data', {})
    session['agent_data'].setdefault(agent_id, {
        'history': [], 'rag_file': None, 'document_name': []
    })

    if not session['agent_data'][agent_id]['rag_file'] and agent_id in global_docs:
        docs = global_docs[agent_id]

        if isinstance(docs, list):
            full_paths = [os.path.join(app.config['UPLOAD_FOLDER'], d) for d in docs]
            existing_full_paths = [fp for fp in full_paths if os.path.isfile(fp)]
            if existing_full_paths:
                existing_relative_paths = [os.path.relpath(fp, app.config['UPLOAD_FOLDER']) for fp in existing_full_paths]
                session['agent_data'][agent_id]['rag_file'] = existing_relative_paths
                session['agent_data'][agent_id]['document_name'] = [os.path.basename(fp) for fp in existing_full_paths]
            else:
                session['agent_data'][agent_id]['rag_file'] = None
                session['agent_data'][agent_id]['document_name'] = []
        elif isinstance(docs, str):
            full_path = os.path.join(app.config['UPLOAD_FOLDER'], docs)
            if os.path.isfile(full_path):
                session['agent_data'][agent_id]['rag_file'] = [docs]
                session['agent_data'][agent_id]['document_name'] = [os.path.basename(docs)]
            else:
                session['agent_data'][agent_id]['rag_file'] = None
                session['agent_data'][agent_id]['document_name'] = []
        else:
            session['agent_data'][agent_id]['rag_file'] = None
            session['agent_data'][agent_id]['document_name'] = []

    return session['agent_data'][agent_id]


# ─── Agent Ask ───────────────────────────────────────────────────────────────
def agent_ask(agent_id, user_text, data):
    ts = datetime.now()
    data['history'].append({'role': 'user', 'content': user_text, 'timestamp': ts})

    # --- SEARCH-AI: PURE DATABASE RESULTS (NO GPT) ---
    if agent_id == 'Search-AI':
        try:
            db = PropertyDatabase(db_path='neuroedge_properties.db', agency_name='NeuroEdge Properties')
            properties = db.search_properties(user_text, max_results=15)  # Increased limit
            
            # Create response directly from database (no GPT involved)
            answer = generate_database_response(properties, user_text)
            
        except Exception as e:
            print(f"⚠️ Database search error: {e}")
            answer = "⚠️ Search temporarily unavailable. Please try again in a moment."
        
        data['history'].append({'role': 'assistant', 'content': answer, 'timestamp': ts})
        session.modified = True
        return answer

    # --- REGULAR AGENTS: USE EXISTING GPT CODE ---
    # Standard GPT messages
    messages = [
        {'role': 'system', 'content': AGENT_CONFIG[agent_id]['system_prompt']},
        *data['history'][-6:]  # last 6 messages
    ]

    # Handle RAG context for other agents
    rag_files = data.get('rag_file')
    if rag_files:
        if isinstance(rag_files, str):
            rag_files = [rag_files]
        context_parts = []
        for rel_path in rag_files:
            full_path = os.path.join(app.config['UPLOAD_FOLDER'], rel_path)
            if os.path.exists(full_path):
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        context_parts.append(f.read())
                except Exception as e:
                    print(f"⚠️ Error reading {full_path}: {e}")
        if context_parts:
            context_text = "\n\n".join(context_parts)[:3000]
            messages.insert(1, {'role': 'system', 'content': f"You may use this uploaded context:\n\n{context_text}"})

    # Standard GPT call for regular agents
    try:
        response = openai.chat.completions.create(
            model='gpt-4-turbo',
            messages=[{'role': m['role'], 'content': m['content']} for m in messages],
            temperature=0.7,
            timeout=120
        )
        answer = response.choices[0].message.content.strip()
    except Exception as e:
        answer = f"⚠️ API error: {e}"

    data['history'].append({'role': 'assistant', 'content': answer, 'timestamp': ts})
    session.modified = True
    return answer

def generate_database_response(properties, query):
    """Generate responsive property search results for all devices"""
    
    # Initialize html_response at the top
    html_response = ""
    
    if not properties:
        return f"""
        <div style="
            background: #f8f9fa;
            padding: clamp(15px, 4vw, 25px);
            border-radius: 12px;
            border: 1px solid #dee2e6;
            margin: clamp(10px, 3vw, 20px) 0;
            text-align: center;
            color: #2d3748;
        ">
            <div style="font-size: clamp(2.5rem, 8vw, 4rem); margin-bottom: clamp(8px, 2vw, 15px);">🔍</div>
            <h3 style="color: #2d3748; margin: 0 0 clamp(8px, 2vw, 15px) 0; font-size: clamp(1.2rem, 4vw, 1.5rem); font-weight: 600;">
                No Properties Found
            </h3>
            <p style="color: #4a5568; margin-bottom: clamp(12px, 3vw, 20px); font-size: clamp(0.9rem, 3vw, 1.1rem); line-height: 1.4;">
                No matches for '<strong style="color: #2d3748;">{escape(query)}</strong>'
            </p>
            <div style="
                background: #ffffff;
                padding: clamp(12px, 3vw, 20px);
                border-radius: 8px;
                max-width: min(400px, 90vw);
                margin: 0 auto;
                border: 1px solid #e2e8f0;
            ">
                <p style="margin: 0 0 clamp(8px, 2vw, 12px) 0; font-weight: 600; font-size: clamp(0.9rem, 3vw, 1rem); color: #2d3748;">
                    💡 Try these suggestions:
                </p>
                <div style="text-align: left; font-size: clamp(0.8rem, 2.5vw, 0.9rem); color: #4a5568; line-height: 1.5;">
                    <div style="margin-bottom: 6px;">• Broaden search terms</div>
                    <div style="margin-bottom: 6px;">• Try different locations</div>
                    <div style="margin-bottom: 6px;">• Adjust price range</div>
                    <div>• Search by specific features</div>
                </div>
            </div>
        </div>
        """
    
    # Start building the response for when we have properties
    html_response = f"""
    <div style="margin: clamp(10px, 3vw, 20px) 0; color: #2d3748;">
        <div style="
            background: #2d3748;
            color: white;
            padding: clamp(12px, 3vw, 20px);
            border-radius: 12px;
            margin-bottom: clamp(12px, 3vw, 20px);
            border: 1px solid #4a5568;
        ">
            <h3 style="margin: 0; font-size: clamp(1.1rem, 4vw, 1.4rem); font-weight: 600;">
                🏠 Found {len(properties)} Properties
            </h3>
            <p style="margin: clamp(4px, 1vw, 8px) 0 0 0; opacity: 0.9; font-size: clamp(0.8rem, 2.5vw, 1rem); color: #e2e8f0;">
                Matching: '<strong>{escape(query)}</strong>'
            </p>
        </div>
    """
    
    # Process each property
    for prop in properties:
        formatted_price = "{:,.2f}".format(prop['price'])
        
        # Get features
        features = []
        if prop.get('features'):
            try:
                features = json.loads(prop['features']) if isinstance(prop['features'], str) else prop['features']
            except:
                features = []
        
        status_color = {
            'available': '#38a169', 
            'sold': '#e53e3e', 
            'deleted': '#718096', 
            'archived': '#ed8936'
        }.get(prop.get('status', 'available'), '#38a169')
        
        agent_name = prop.get('agent_name', 'Unknown Agent')
        
        # Add property card to html_response
        html_response += f"""
        <div style="
            background: #ffffff;
            border-radius: 12px;
            padding: clamp(12px, 3vw, 20px);
            margin-bottom: clamp(12px, 3vw, 20px);
            border: 1px solid #e2e8f0;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            color: #2d3748;
        ">
            <!-- Header -->
            <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: clamp(8px, 2vw, 15px); margin-bottom: clamp(8px, 2vw, 12px); flex-wrap: wrap;">
                <h4 style="
                    margin: 0; 
                    color: #2d3748; 
                    font-size: clamp(1rem, 3.5vw, 1.2rem);
                    line-height: 1.4;
                    flex: 1;
                    min-width: min(200px, 60vw);
                    font-weight: 600;
                ">{escape(prop['title'])}</h4>
                <span style="
                    background: {status_color};
                    color: white;
                    padding: clamp(4px, 1vw, 6px) clamp(10px, 2vw, 12px);
                    border-radius: 10px;
                    font-size: clamp(0.7rem, 2vw, 0.8rem);
                    white-space: nowrap;
                    font-weight: 600;
                ">{prop.get('status', 'available').upper()}</span>
            </div>
            
            <!-- Price -->
            <div style="color: #2d3748; font-size: clamp(1.1rem, 4vw, 1.4rem); font-weight: bold; margin-bottom: clamp(8px, 2vw, 12px);">
                N$ {formatted_price}
            </div>
            
            <!-- Property Details -->
            <div style="
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(min(120px, 45vw), 1fr));
                gap: clamp(8px, 2vw, 12px);
                margin-bottom: clamp(8px, 2vw, 12px);
                font-size: clamp(0.8rem, 2.5vw, 0.9rem);
            ">
                <div style="text-align: center; color: #4a5568;">
                    <div style="font-size: clamp(1.2rem, 4vw, 1.5rem);">🛏️</div>
                    <div style="font-weight: 500;">{prop['bedrooms']} bed</div>
                </div>
                <div style="text-align: center; color: #4a5568;">
                    <div style="font-size: clamp(1.2rem, 4vw, 1.5rem);">🚿</div>
                    <div style="font-weight: 500;">{prop['bathrooms']} bath</div>
                </div>
                <div style="text-align: center; color: #4a5568;">
                    <div style="font-size: clamp(1.2rem, 4vw, 1.5rem);">📏</div>
                    <div style="font-weight: 500;">{prop.get('size_sqft', 'N/A')} sqft</div>
                </div>
                <div style="text-align: center; color: #4a5568;">
                    <div style="font-size: clamp(1.2rem, 4vw, 1.5rem);">🏢</div>
                    <div style="font-weight: 500;">{escape(prop['property_type'])}</div>
                </div>
            </div>
            
            <!-- Location -->
            <div style="color: #4a5568; margin-bottom: clamp(8px, 2vw, 12px); font-size: clamp(0.8rem, 2.5vw, 0.9rem); font-weight: 500;">
                📍 {escape(prop['location'])}
            </div>
            
            <!-- Features -->
            {f'''<div style="margin-bottom: clamp(8px, 2vw, 12px); font-size: clamp(0.8rem, 2.5vw, 0.85rem); color: #4a5568;">
                <strong style="color: #2d3748;">Features:</strong> {escape(", ".join(features[:4]))}
            </div>''' if features else ""}
            
            <!-- Agent -->
            <div style="
                background: #f7fafc;
                padding: clamp(8px, 2vw, 12px);
                border-radius: 6px;
                margin-bottom: clamp(10px, 2.5vw, 15px);
                font-size: clamp(0.8rem, 2.5vw, 0.9rem);
                border: 1px solid #e2e8f0;
                color: #4a5568;
            ">
                <strong style="color: #2d3748;">Agent:</strong> {escape(agent_name)}
            </div>
            
            <!-- Action Buttons -->
            <div style="
                display: flex;
                gap: clamp(6px, 1.5vw, 10px);
                flex-wrap: wrap;
            ">
        """
        
        # Buttons with responsive sizing and better colors
        buttons = []
        button_style = """
            color: white;
            padding: clamp(8px, 1.5vw, 12px) clamp(12px, 2.5vw, 16px);
            text-decoration: none;
            border-radius: 6px;
            font-size: clamp(0.75rem, 2.2vw, 0.85rem);
            white-space: nowrap;
            flex: 1;
            min-width: fit-content;
            text-align: center;
            font-weight: 600;
            border: none;
            cursor: pointer;
            transition: all 0.2s ease;
        """
        
        if prop.get('listing_url'):
            buttons.append(f'<a href="{prop["listing_url"]}" target="_blank" style="background:#4a5568;{button_style}" onmouseover="this.style.background=\'#2d3748\'" onmouseout="this.style.background=\'#4a5568\'">🌐 View Listing</a>')
        else:
            buttons.append(f'<a href="/admin/properties/{prop["id"]}" target="_blank" style="background:#718096;{button_style}" onmouseover="this.style.background=\'#4a5568\'" onmouseout="this.style.background=\'#718096\'">👁️ View Details</a>')
        
        agent_encoded = agent_name.replace(' ','%20')
        buttons.append(f'<a href="/chat/{agent_encoded}" target="_blank" style="background:#38a169;{button_style}" onmouseover="this.style.background=\'#2f855a\'" onmouseout="this.style.background=\'#38a169\'">💬 Chat with Agent</a>')
        
        tally_url = TALLY_FORMS.get(agent_name)
        if tally_url:
            buttons.append(f'<a href="{tally_url}" target="_blank" style="background:#ed8936;{button_style}" onmouseover="this.style.background=\'#dd6b20\'" onmouseout="this.style.background=\'#ed8936\'">📋 Contact Form</a>')
        
        html_response += "".join(buttons)
        html_response += "</div></div>"
    
    # Add final tips section
    html_response += """
        <div style="
            background: #ebf8ff;
            padding: clamp(12px, 2.5vw, 16px);
            border-radius: 8px;
            margin-top: clamp(12px, 2.5vw, 16px);
            font-size: clamp(0.8rem, 2.5vw, 0.9rem);
            text-align: center;
            border: 1px solid #bee3f8;
            color: #2d3748;
        ">
            <strong>💡 Tip:</strong> Chat directly with agents for instant answers and viewing schedules.
        </div>
    </div>
    """
    return html_response

def format_listing(agent_name, listing_text):
    """Attach agent chat link cleanly, without breaking URLs."""
    chat_link = chat_url_for(agent_name)
    safe_agent = escape(agent_name)

    # Ensure any existing URLs in listing_text remain untouched
    # Then append the agent chat link on a new line
    return f"{listing_text.strip()}\n\n🔗 <a href='{chat_link}' target='_blank'>Chat with {safe_agent}</a>"


# ─── Language Route ──────────────────────────────────────────────────────────
@app.route('/set_language', methods=['POST'])
def set_language():
    data = request.get_json()
    lang = data.get('language')
    allowed_langs = {'en', 'af', 'de', 'ng', 'zh', 'pt'}
    if lang not in allowed_langs:
        return jsonify({'error': 'Invalid language'}), 400
    session['language'] = lang
    return jsonify({'message': 'Language set', 'language': lang})

# ─── Routes ──────────────────────────────────────────────────────────────────
@app.route('/')
def home():
    lang = session.get('language', 'en')
    # Hide 'Search-AI' and 'Head of property-AI' from visible list
    visible_agents = [
        a for a in AGENT_CONFIG.keys()
        if a not in ['Search-AI', 'Head of property-AI']
    ]
    return render_template(
        'index.html',
        agent_id=None,
        agents=visible_agents,
        AGENT_CONFIG=AGENT_CONFIG,
        messages=None,
        lang=lang,
        TALLY_FORMS=TALLY_FORMS,
        datetime=datetime
    )


@app.route('/chat/<agent_id>', methods=['GET', 'POST'])
def chat(agent_id):
    if agent_id not in AGENT_CONFIG:
        flash('Unknown agent', 'error')
        return redirect(url_for('home'))

    data = user_agent_data(agent_id)
    messages = data.get('history', [])
    tally_form_url = TALLY_FORMS.get(agent_id)
    global_docs = load_global_docs()
    doc_list = global_docs.get(agent_id, [])

    if isinstance(doc_list, list) and doc_list:
        data['document_name'] = [os.path.basename(p) for p in doc_list]
    elif isinstance(doc_list, str):
        data['document_name'] = [os.path.basename(doc_list)]
    else:
        data['document_name'] = []

    # Format timestamps for display
    for msg in messages:
        ts = msg.get('timestamp')
        if ts and not isinstance(ts, str):
            msg['timestamp'] = ts.strftime("%Y-%m-%d %H:%M:%S")

    lang = session.get('language', 'en')

    if request.method == 'POST':
        user_text = request.form.get('user_input', '').strip()
        if user_text:
            ts = datetime.now()
            data['history'].append({'role': 'user', 'content': user_text, 'timestamp': ts})

            # Handle Tally form requests for any agent
            if any(phrase in user_text.lower() for phrase in ['leave my details', 'contact form', '📋']):
                if tally_form_url:
                    response = f"📋 Please <a href='{tally_form_url}' target='_blank'>fill out this short form</a> so your agent can get in touch with you."
                    data['history'].append({'role': 'assistant', 'content': response, 'timestamp': ts})
                    session.modified = True
                    return redirect(url_for('chat', agent_id=agent_id))
            
            # For ALL agents including Search-AI, use agent_ask
            # Search-AI will now use pure database results, others use GPT
            agent_ask(agent_id, user_text, data)
            return redirect(url_for('chat', agent_id=agent_id))

    # GET: render chat page
    return render_template(
        'index.html',
        agent_id=agent_id,
        messages=messages,
        agents=[a for a in AGENT_CONFIG.keys() if a != 'Search-AI'],
        AGENT_CONFIG=AGENT_CONFIG,
        TALLY_FORMS=TALLY_FORMS,
        document_name=data.get('document_name', []),
        lang=lang,
        datetime=datetime,
        tally_form=tally_form_url
    )

@app.route('/upload/<agent_id>', methods=['GET', 'POST'])
@login_required
def upload(agent_id):
    if agent_id not in AGENT_CONFIG:
        flash('Unknown agent', 'error')
        return redirect(url_for('home'))

    if request.method == 'POST':
        file = request.files.get('docfile')
        if not file or file.filename.strip() == '':
            flash('No file selected', 'error')
            return redirect(url_for('upload', agent_id=agent_id))

        if not allowed_file(file.filename):
            flash('File type not allowed', 'error')
            return redirect(url_for('upload', agent_id=agent_id))

        # Save to /var/data/<agent_id>/
        upload_dir = get_user_upload_dir(agent_id)  # ensures directory exists
        filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
        file_path = os.path.join(upload_dir, filename)

        try:
            file.save(file_path)
        except Exception as e:
            flash(f"Error saving file: {e}", 'error')
            return redirect(url_for('upload', agent_id=agent_id))

        # Update JSON registry with filename only
        global_docs = load_global_docs()
        global_docs.setdefault(agent_id, [])
        global_docs[agent_id].append(filename)
        save_global_docs(global_docs)

        # Refresh in-memory documents
        load_agent_documents()

        flash('File uploaded successfully.', 'success')
        return redirect(url_for('chat', agent_id=agent_id))

    return render_template('upload.html', agent_id=agent_id)


@app.route('/reset/<agent_id>', methods=['POST'])
def reset(agent_id):
    if 'agent_data' in session and agent_id in session['agent_data']:
        session['agent_data'][agent_id]['history'] = []  # Only clears chat
        session.modified = True
    flash("Chat has been reset.", "success")
    return redirect(url_for('chat', agent_id=agent_id))

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session or not session['admin_logged_in']:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def change_admin_password(username, new_password):
    """Change admin password in the database"""
    conn = sqlite3.connect('neuroedge_properties.db')  # Use your actual database path
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

def change_password_in_db(username, new_password):
    """Change password using the database class"""
    # Since we already have a database class, let's add a method to it
    # First, add this method to your PropertyDatabase class:
    return db.change_user_password(username, new_password)

# ─── ADMIN ROUTES ────────────────────────────────────────────────────────────

def get_database():
    """Helper function to get database instance with correct arguments"""
    return PropertyDatabase(db_path='neuroedge_properties.db', agency_name=session.get('admin_agency', 'NeuroEdge Properties'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        db = get_database()
        if db.verify_user(username, password):
            session['admin_logged_in'] = True
            session['admin_username'] = username
            session['admin_agency'] = "NeuroEdge Properties"
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('admin_login.html', error="Invalid credentials")
    
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    """Admin logout"""
    session.clear()
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    """Admin dashboard"""
    try:
        db = get_database()
        properties = db.get_all_properties()
        total_properties = len(properties)
        agents = db.get_agents()
        
        return render_template('admin_dashboard.html',
                             agency=session.get('admin_agency', 'Agency'),
                             username=session.get('admin_username', 'Admin'),
                             total_properties=total_properties,
                             agents=agents)
    except Exception as e:
        print(f"Error in admin dashboard: {e}")
        return render_template('admin_dashboard.html',
                             agency=session.get('admin_agency', 'Agency'),
                             username=session.get('admin_username', 'Admin'),
                             total_properties=0,
                             agents=[])

@app.route('/admin/properties', methods=['GET', 'POST'])
@login_required
def admin_properties():
    """Manage properties - with proper deletion"""
    db = get_database()
    
    if request.method == 'POST':
        action = request.form.get('action')
        print(f"DEBUG: Action received: {action}")  # Debug line
        
        if action == 'delete_property':
            property_id = request.form.get('delete_id')
            print(f"DEBUG: Delete property ID: {property_id}")  # Debug line
            
            if property_id:
                try:
                    # Check if property exists first
                    property_data = db.get_property_by_id(property_id)
                    if not property_data:
                        return redirect(url_for('admin_properties', error=f"Property with ID '{property_id}' not found"))
                    
                    success, message = db.permanently_delete_property(property_id)
                    print(f"DEBUG: Delete result - Success: {success}, Message: {message}")  # Debug line
                    
                    if success:
                        return redirect(url_for('admin_properties', success=message))
                    else:
                        return redirect(url_for('admin_properties', error=message))
                except Exception as e:
                    print(f"DEBUG: Delete error: {str(e)}")  # Debug line
                    return redirect(url_for('admin_properties', error=f"Error deleting property: {str(e)}"))
            else:
                return redirect(url_for('admin_properties', error="No property ID provided"))
        
        elif action == 'archive_property':
            property_id = request.form.get('archive_id')
            print(f"DEBUG: Archive property ID: {property_id}")  # Debug line
            
            if property_id:
                try:
                    # Check if property exists first
                    property_data = db.get_property_by_id(property_id)
                    if not property_data:
                        return redirect(url_for('admin_properties', error=f"Property with ID '{property_id}' not found"))
                    
                    success, message = db.soft_delete_property(property_id)
                    print(f"DEBUG: Archive result - Success: {success}, Message: {message}")  # Debug line
                    
                    if success:
                        return redirect(url_for('admin_properties', success=message))
                    else:
                        return redirect(url_for('admin_properties', error=message))
                except Exception as e:
                    print(f"DEBUG: Archive error: {str(e)}")  # Debug line
                    return redirect(url_for('admin_properties', error=f"Error archiving property: {str(e)}"))
            else:
                return redirect(url_for('admin_properties', error="No property ID provided"))
    
    # Get success/error messages from URL parameters
    success = request.args.get('success')
    error = request.args.get('error')
    
    try:
        properties = db.get_all_properties()
        agents = db.get_agents()
        print(f"DEBUG: Loaded {len(properties)} properties")  # Debug line
    except Exception as e:
        properties = []
        agents = []
        error = f"Error loading properties: {str(e)}"
        print(f"DEBUG: Load error: {error}")  # Debug line
    
    return render_template('admin_properties.html',
                         properties=properties,
                         agents=agents,
                         agency=session.get('admin_agency', 'Admin Panel'),
                         success=success,
                         error=error)

@app.route('/admin/properties/<property_id>')
def property_details(property_id):
    """View property details with links"""
    db = get_database()
    property_data = db.get_property_with_links(property_id)
    
    if not property_data:
        return redirect(url_for('admin_properties', error="Property not found"))
    
    # Convert JSON fields
    if property_data.get('features'):
        property_data['features'] = json.loads(property_data['features'])
    if property_data.get('images'):
        property_data['images'] = json.loads(property_data['images'])
    
    return render_template('admin_property_details.html',
                         property=property_data,
                         agency=session['admin_agency'])

@app.route('/admin/properties/add', methods=['GET', 'POST'])
@login_required
def admin_add_property():
    """Add new property form"""
    db = get_database()
    
    if request.method == 'POST':
        try:
            property_data = {
                'id': request.form.get('property_id').upper(),
                'title': request.form.get('title'),
                'description': request.form.get('description'),
                'price': float(request.form.get('price')),
                'property_type': request.form.get('property_type'),
                'bedrooms': int(request.form.get('bedrooms')),
                'bathrooms': int(request.form.get('bathrooms')),
                'size_sqft': int(request.form.get('size_sqft')),
                'location': request.form.get('location'),
                'features': [f.strip() for f in request.form.get('features', '').split(',') if f.strip()],
                'agent_id': request.form.get('agent_id')
            }
            
            if db.add_property(property_data):
                return redirect(url_for('admin_properties'))
            else:
                return render_template('admin_add_property.html',
                                     error="Property ID already exists",
                                     agents=db.get_agents())
            
        except Exception as e:
            return render_template('admin_add_property.html',
                                 error=f"Error: {str(e)}",
                                 agents=db.get_agents())
    
    return render_template('admin_add_property.html', agents=db.get_agents())

@app.route('/admin/properties/edit/<property_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_property(property_id):
    """Edit existing property"""
    db = get_database()
    properties = db.get_all_properties()
    property_data = next((p for p in properties if p['id'] == property_id), None)
    
    if not property_data:
        return redirect(url_for('admin_properties'))
    
    if request.method == 'POST':
        try:
            updates = {
                'title': request.form.get('title'),
                'description': request.form.get('description'),
                'price': float(request.form.get('price')),
                'property_type': request.form.get('property_type'),
                'bedrooms': int(request.form.get('bedrooms')),
                'bathrooms': int(request.form.get('bathrooms')),
                'size_sqft': int(request.form.get('size_sqft')),
                'location': request.form.get('location'),
                'features': json.dumps([f.strip() for f in request.form.get('features', '').split(',') if f.strip()])
            }
            
            db.update_property(property_id, updates)
            return redirect(url_for('admin_properties'))
            
        except Exception as e:
            return render_template('admin_edit_property.html',
                                 property=property_data,
                                 agents=db.get_agents(),
                                 error=str(e))
    
    if property_data.get('features'):
        property_data['features'] = json.loads(property_data['features'])
    
    return render_template('admin_edit_property.html',
                         property=property_data,
                         agents=db.get_agents())

@app.route('/admin/agents', methods=['GET', 'POST'])
@login_required
def admin_agents():
    """Manage agents - with add/delete functionality"""
    db = get_database()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'delete_agent':
            agent_id = request.form.get('agent_id')
            success, message = db.delete_agent(agent_id)
            
            if success:
                return redirect(url_for('admin_agents', success=message))
            else:
                return redirect(url_for('admin_agents', error=message))
        
        elif action == 'add_agent':
            agent_data = {
                'id': request.form.get('agent_id'),
                'name': request.form.get('name'),
                'email': request.form.get('email'),
                'phone': request.form.get('phone'),
                'specialty': request.form.get('specialty'),
                'bio': request.form.get('bio', '')
            }
            
            success, message = db.add_agent(agent_data)
            
            if success:
                return redirect(url_for('admin_agents', success=message))
            else:
                return redirect(url_for('admin_agents', error=message))
    
    success = request.args.get('success')
    error = request.args.get('error')
    
    agents = db.get_agents()
    return render_template('admin_agents.html', 
                         agents=agents,
                         success=success,
                         error=error)

@app.route('/admin/trash', methods=['GET', 'POST'])
@login_required
def admin_trash():
    """Manage soft-deleted properties (trash bin)"""
    db = get_database()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'restore_property':
            property_id = request.form.get('property_id')
            success, message = db.restore_property(property_id)
            
            if success:
                return redirect(url_for('admin_trash', success=message))
            else:
                return redirect(url_for('admin_trash', error=message))
        
        elif action == 'permanently_delete_property':
            property_id = request.form.get('property_id')
            success, message = db.permanently_delete_property(property_id)
            
            if success:
                return redirect(url_for('admin_trash', success=message))
            else:
                return redirect(url_for('admin_trash', error=message))
        
        elif action == 'empty_trash':
            success, message = db.empty_trash()
            
            if success:
                return redirect(url_for('admin_trash', success=message))
            else:
                return redirect(url_for('admin_trash', error=message))
    
    success = request.args.get('success')
    error = request.args.get('error')
    
    deleted_properties = db.get_deleted_properties()
    
    return render_template('admin_trash.html',
                         deleted_properties=deleted_properties,
                         agency=session['admin_agency'],
                         success=success,
                         error=error)

@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    """Manage admin users and change passwords"""
    db = get_database()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'change_password':
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            
            if not db.verify_user(session['admin_username'], current_password):
                return render_template('admin_users.html', error="Current password is incorrect")
            
            if new_password != confirm_password:
                return render_template('admin_users.html', error="New passwords do not match")
            
            if len(new_password) < 6:
                return render_template('admin_users.html', error="Password must be at least 6 characters")
            
            if db.change_user_password(session['admin_username'], new_password):
                return render_template('admin_users.html', success="Password changed successfully")
            else:
                return render_template('admin_users.html', error="Failed to change password")
    
    return render_template('admin_users.html')

# ─── API ROUTES (also need database initialization) ──────────────────────────

@app.route('/api/search', methods=['POST', 'GET'])
def api_search():
    """
    Endpoint for PropertyFinder to search Windhoek Property Brokers listings
    """
    try:
        if request.method == 'GET':
            return jsonify({
                "service": "Windhoek Property Brokers Search API",
                "version": "1.0",
                "status": "active",
                "agency": "Windhoek Property Brokers"
            })
        
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
        
        query = data.get('query', '').strip()
        max_results = data.get('max_results', 5)
        
        if not query:
            return jsonify({"error": "Query parameter required"}), 400
        
        print(f"🔍 WPB Search Request: '{query}'")
        
        # Initialize database for API route
        db = PropertyDatabase(db_path='neuroedge_properties.db', agency_name='NeuroEdge Properties')
        properties = db.search_properties(query, max_results)
        
        formatted_properties = []
        for prop in properties:
            formatted_prop = {
                "property_id": prop['id'],
                "title": prop['title'],
                "price": f"N$ {prop['price']:,.2f}",
                "bedrooms": prop['bedrooms'],
                "bathrooms": prop['bathrooms'],
                "location": prop['location'],
                "type": prop['property_type'],
                "size": f"{prop.get('size_sqft', 0)} sqft",
                "agent_name": prop['agent_name'],
                "agent_contact": prop['agent_phone'],
                "agent_specialty": prop.get('agent_specialty', ''),
                "description": prop.get('description', ''),
                "features": json.loads(prop['features']) if prop['features'] else [],
                "listing_url": prop.get('listing_url', ''),
                "chat_link": f"/chat/{prop['agent_name'].replace(' ', '%20')}",
                "view_link": f"/admin/properties/{prop['id']}"
            }
            formatted_properties.append(formatted_prop)
        
        response = {
            "agency": "NeuroEdge Properties",
            "query": query,
            "properties": formatted_properties,
            "count": len(formatted_properties),
            "response_time": datetime.now().isoformat(),
            "success": True
        }
        
        print(f"✅ WPB Found {len(formatted_properties)} properties for: '{query}'")
        return jsonify(response)
        
    except Exception as e:
        print(f"❌ WPB Search Error: {str(e)}")
        return jsonify({
            "error": str(e),
            "success": False
        }), 500

@app.route('/api/properties', methods=['GET'])
def get_all_properties():
    """Test route to see all properties in WPB database"""
    db = PropertyDatabase(db_path='neuroedge_properties.db', agency_name='NeuroEdge Properties')
    properties = db.get_all_properties()
    return jsonify({
        "agency": "Windhoek Property Brokers",
        "total_properties": len(properties),
        "properties": properties
    })
@app.route('/admin/debug/properties')
@login_required
def debug_properties():
    """Debug route to see all property IDs"""
    db = get_database()
    properties = db.get_all_properties()
    
    property_info = []
    for prop in properties:
        property_info.append({
            'id': prop['id'],
            'title': prop['title'],
            'type': type(prop['id']).__name__
        })
    
    return jsonify(property_info)

@app.errorhandler(404)
def not_found(e):
    flash("Page not found", 'error')
    return redirect(url_for('home'))

@app.errorhandler(413)
def too_large(e):
    flash("File too large (max 16MB)", "error")
    return redirect(request.referrer or url_for('home'))

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    load_agent_documents()  # Load all saved agent documents into memory before starting the app
    app.run(host='0.0.0.0', port=5090)

