import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime, timezone

from bson import ObjectId

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Utility to convert ObjectId to str
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

# Pydantic models
class NoticeBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    status: Literal['draft', 'published', 'archived'] = 'draft'
    attachment: Optional[str] = None

class NoticeCreate(NoticeBase):
    pass

class NoticeUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = Field(None, min_length=1)
    status: Optional[Literal['draft', 'published', 'archived']] = None
    attachment: Optional[str] = None

class NoticeOut(NoticeBase):
    id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}

@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}

@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    
    try:
        # Try to import database module
        from database import db
        
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            
            # Try to list collections to verify connectivity
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]  # Show first 10 collections
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
            
    except ImportError:
        response["database"] = "❌ Database module not found (run enable-database first)"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    
    # Check environment variables
    import os
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    
    return response


# CRUD for notices

def _notice_collection():
    from database import db
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    return db["notice"]


def _doc_to_notice(doc) -> NoticeOut:
    return NoticeOut(
        id=str(doc.get("_id")),
        title=doc.get("title"),
        content=doc.get("content"),
        status=doc.get("status", "draft"),
        attachment=doc.get("attachment"),
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at"),
    )


@app.get("/api/notices", response_model=List[NoticeOut])
def list_notices():
    col = _notice_collection()

    # Seed demo data if empty
    if col.count_documents({}) == 0:
        now = datetime.now(timezone.utc)
        demo = [
            {
                "title": "System Maintenance Tonight",
                "content": "We will perform scheduled maintenance between 1 AM and 3 AM UTC. Services may be intermittently unavailable.",
                "status": "published",
                "attachment": "https://images.unsplash.com/photo-1520607162513-77705c0f0d4a?w=800&q=80&auto=format&fit=crop",
                "created_at": now,
                "updated_at": now,
            },
            {
                "title": "New Feature: Dark Mode",
                "content": "You can now switch to dark mode from your profile settings. Let us know your feedback!",
                "status": "published",
                "attachment": "https://images.unsplash.com/photo-1517816743773-6e0fd518b4a6?w=800&q=80&auto=format&fit=crop",
                "created_at": now,
                "updated_at": now,
            },
            {
                "title": "Quarterly Townhall",
                "content": "Join us for the Q4 townhall next Friday at 10 AM. Submit questions in advance via the form.",
                "status": "draft",
                "attachment": None,
                "created_at": now,
                "updated_at": now,
            },
        ]
        col.insert_many(demo)

    docs = list(col.find({}).sort("created_at", -1))
    return [_doc_to_notice(d) for d in docs]


@app.post("/api/notices", response_model=NoticeOut, status_code=201)
def create_notice(payload: NoticeCreate):
    col = _notice_collection()
    now = datetime.now(timezone.utc)
    doc = payload.model_dump()
    doc["created_at"] = now
    doc["updated_at"] = now
    res = col.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _doc_to_notice(doc)


@app.get("/api/notices/{notice_id}", response_model=NoticeOut)
def get_notice(notice_id: str):
    col = _notice_collection()
    if not ObjectId.is_valid(notice_id):
        raise HTTPException(status_code=400, detail="Invalid id")
    doc = col.find_one({"_id": ObjectId(notice_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return _doc_to_notice(doc)


@app.put("/api/notices/{notice_id}", response_model=NoticeOut)
def update_notice(notice_id: str, payload: NoticeUpdate):
    col = _notice_collection()
    if not ObjectId.is_valid(notice_id):
        raise HTTPException(status_code=400, detail="Invalid id")
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    updates["updated_at"] = datetime.now(timezone.utc)
    res = col.find_one_and_update(
        {"_id": ObjectId(notice_id)},
        {"$set": updates},
        return_document=True,
    )
    if not res:
        raise HTTPException(status_code=404, detail="Not found")
    return _doc_to_notice(res)


@app.delete("/api/notices/{notice_id}", status_code=204)
def delete_notice(notice_id: str):
    col = _notice_collection()
    if not ObjectId.is_valid(notice_id):
        raise HTTPException(status_code=400, detail="Invalid id")
    res = col.delete_one({"_id": ObjectId(notice_id)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
