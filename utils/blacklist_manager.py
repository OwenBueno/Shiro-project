# utils/blacklist_manager.py
import json
import os
from typing import List, Set

BLACKLIST_FILE = "blacklist.json"

# Use a set for efficient add, remove, and check operations
_blacklist: Set[int] = set()

def load_blacklist():
    """Loads the blacklist from the JSON file into memory (a set)."""
    global _blacklist
    if os.path.exists(BLACKLIST_FILE):
        try:
            with open(BLACKLIST_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, list): # Expect a list of integers
                    _blacklist = set(int(uid) for uid in data)
                else:
                    _blacklist = set() # Initialize empty if format is unexpected
                    print(f"Warning: Blacklist file '{BLACKLIST_FILE}' was not a list. Initializing empty blacklist.")
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Error loading blacklist file '{BLACKLIST_FILE}': {e}. Initializing empty blacklist.")
            _blacklist = set()
    else:
        _blacklist = set()

def save_blacklist():
    """Saves the current in-memory blacklist (set) to the JSON file (as a list)."""
    global _blacklist
    try:
        with open(BLACKLIST_FILE, 'w') as f:
            json.dump(list(_blacklist), f, indent=4) # Store as list for readability
    except IOError as e:
        print(f"Error saving blacklist file '{BLACKLIST_FILE}': {e}")

def add_to_blacklist(user_id: int) -> bool:
    """Adds a user ID to the blacklist. Returns True if added, False if already present."""
    global _blacklist
    if user_id not in _blacklist:
        _blacklist.add(user_id)
        save_blacklist()
        return True
    return False

def remove_from_blacklist(user_id: int) -> bool:
    """Removes a user ID from the blacklist. Returns True if removed, False if not found."""
    global _blacklist
    if user_id in _blacklist:
        _blacklist.remove(user_id)
        save_blacklist()
        return True
    return False

def get_blacklist() -> List[int]:
    """Returns a list of all blacklisted user IDs."""
    global _blacklist
    return list(_blacklist)

def is_blacklisted(user_id: int) -> bool:
    """Checks if a user ID is currently blacklisted."""
    global _blacklist
    return user_id in _blacklist

# Initial load when the module is imported
load_blacklist() 