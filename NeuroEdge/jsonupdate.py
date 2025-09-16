import os
import json

BASE_UPLOAD_DIR = "/var/data"
DOC_JSON_PATH = "agent_docs.json"

def rebuild_agent_docs():
    new_docs = {}
    
    if not os.path.exists(BASE_UPLOAD_DIR):
        print("Base folder does not exist:", BASE_UPLOAD_DIR)
        return
    
    for agent_id in os.listdir(BASE_UPLOAD_DIR):
        agent_folder = os.path.join(BASE_UPLOAD_DIR, agent_id)
        if not os.path.isdir(agent_folder):
            continue
        
        # Only include allowed files
        valid_files = [
            f for f in os.listdir(agent_folder) 
            if os.path.isfile(os.path.join(agent_folder, f))
        ]
        if valid_files:
            new_docs[agent_id] = valid_files
    
    # Save new JSON
    with open(DOC_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(new_docs, f, indent=2)
    
    print("✅ agent_docs.json fully rebuilt from /var/data")

if __name__ == "__main__":
    rebuild_agent_docs()
