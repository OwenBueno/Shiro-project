from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGODB_URI
import logging
from typing import Optional
import asyncio

logger = logging.getLogger('db_config')

class DatabaseConnection:
    _instance = None
    _lock = asyncio.Lock()
    
    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None
        self.conversations = None
        self.initialized = False
    
    @classmethod
    async def get_instance(cls):
        if not cls._instance:
            async with cls._lock:
                if not cls._instance:
                    cls._instance = DatabaseConnection()
        return cls._instance
    
    async def initialize(self):
        if self.initialized:
            return
        
        async with self._lock:
            if self.initialized:
                return
                
            try:
                logger.info("Connecting to MongoDB...")
                self.client = AsyncIOMotorClient(MONGODB_URI)
                # Test the connection
                await self.client.admin.command('ping')
                
                self.db = self.client.shiro_db
                self.conversations = self.db.conversations
                self.initialized = True
                logger.info("Successfully connected to MongoDB")
            except Exception as e:
                logger.error(f"Error connecting to MongoDB: {e}")
                self.client = None
                self.db = None
                self.conversations = None
                self.initialized = False
                raise
    
    async def close(self):
        if self.client:
            logger.info("Closing MongoDB connection...")
            self.client.close()
            self.client = None
            self.db = None
            self.conversations = None
            self.initialized = False
            logger.info("MongoDB connection closed")

# Global instance
db_connection = None

async def get_db():
    global db_connection
    if db_connection is None:
        db_connection = await DatabaseConnection.get_instance()
    return db_connection

async def init_db():
    db = await get_db()
    await db.initialize()
    return db

async def close_db():
    if db_connection:
        await db_connection.close()