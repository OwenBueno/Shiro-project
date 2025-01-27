from pymongo import MongoClient
from config import MONGODB_URI

# Initialize MongoDB client
if (MONGODB_URI):
    try:
        mongo_client = MongoClient(MONGODB_URI)
        # Test the connection
        mongo_client.admin.command('ping')
        print("Successfully connected to MongoDB!")
    except Exception as e:
        print(f"Error connecting to MongoDB: {e}")
        raise e

    db = mongo_client['shiro_bot']
    conversations = db['conversations']