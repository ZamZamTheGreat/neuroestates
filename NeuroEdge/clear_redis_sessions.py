import redis
import os

REDIS_URL = os.getenv("SESSION_REDIS_URL","rediss://red-d33klrfdiees739lek0g:RH0Y4hRUn6yxvZYv2pb8MONh5K8qamI1@oregon-keyvalue.render.com:6379")
r = redis.from_url(REDIS_URL, decode_responses=False)  # avoid decode errors

# Fetch all session keys
session_keys = r.keys("session:*")

# Delete them
if session_keys:
    r.delete(*session_keys)
    print(f"Deleted {len(session_keys)} old sessions.")
else:
    print("No old sessions found.")
