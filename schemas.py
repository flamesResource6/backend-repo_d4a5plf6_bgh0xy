"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field
from typing import Optional

# Core Drive schemas

class Folder(BaseModel):
    """
    Drive folders
    Collection name: "folder"
    """
    name: str = Field(..., min_length=1, max_length=120, description="Folder name")
    parent_id: Optional[str] = Field(None, description="Parent folder _id as string. None for root")

class FileItem(BaseModel):
    """
    Drive files
    Collection name: "fileitem"
    """
    name: str = Field(..., min_length=1, max_length=255, description="Display name")
    parent_id: Optional[str] = Field(None, description="Parent folder _id as string. None for root")
    size: int = Field(..., ge=0, description="File size in bytes")
    mime_type: str = Field(..., description="MIME type")
    storage_path: str = Field(..., description="Server-side storage path for the file")

# Example schemas (kept for reference)
class User(BaseModel):
    name: str
    email: str
    address: str
    age: Optional[int] = None
    is_active: bool = True

class Product(BaseModel):
    title: str
    description: Optional[str] = None
    price: float
    category: str
    in_stock: bool = True
