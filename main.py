import os
from typing import List, Optional, Literal
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime, timezone
from bson import ObjectId

from database import db

app = FastAPI(title="Pretty Drive API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Helpers

def oid(id_str: Optional[str]) -> Optional[ObjectId]:
    if not id_str:
        return None
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

def serialize(doc: dict) -> dict:
    if not doc:
        return doc
    doc["_id"] = str(doc["_id"]) if "_id" in doc else None
    # Convert datetimes
    for k in ["created_at", "updated_at"]:
        if k in doc and isinstance(doc[k], datetime):
            doc[k] = doc[k].isoformat()
    return doc

# Schemas for requests
class CreateFolderRequest(BaseModel):
    name: str
    parent_id: Optional[str] = None

class RenameRequest(BaseModel):
    id: str
    type: Literal["file", "folder"]
    name: str

# Root and health
@app.get("/")
def read_root():
    return {"message": "Pretty Drive Backend Ready"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response

# Drive Endpoints
@app.get("/drive/list")
def list_items(parent_id: Optional[str] = None):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    filt = {"parent_id": parent_id} if parent_id else {"parent_id": None}
    folders = list(db["folder"].find(filt).sort("name", 1))
    files = list(db["fileitem"].find(filt).sort("name", 1))
    return {
        "folders": [serialize(f) for f in folders],
        "files": [serialize(f) for f in files]
    }

@app.post("/drive/folder")
def create_folder(payload: CreateFolderRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    now = datetime.now(timezone.utc)
    doc = {
        "name": payload.name.strip(),
        "parent_id": payload.parent_id or None,
        "created_at": now,
        "updated_at": now,
    }
    if not doc["name"]:
        raise HTTPException(status_code=400, detail="Name required")
    res = db["folder"].insert_one(doc)
    return serialize({"_id": res.inserted_id, **doc})

@app.post("/drive/upload")
async def upload_file(parent_id: Optional[str] = Form(None), file: UploadFile = File(...)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    # Save file to disk
    safe_name = file.filename
    dest_path = os.path.join(UPLOAD_DIR, f"{datetime.now().timestamp()}_{safe_name}")
    with open(dest_path, "wb") as f:
        f.write(await file.read())
    size = os.path.getsize(dest_path)
    now = datetime.now(timezone.utc)
    doc = {
        "name": safe_name,
        "parent_id": parent_id or None,
        "size": size,
        "mime_type": file.content_type or "application/octet-stream",
        "storage_path": dest_path,
        "created_at": now,
        "updated_at": now,
    }
    res = db["fileitem"].insert_one(doc)
    return serialize({"_id": res.inserted_id, **doc})

@app.get("/drive/download/{file_id}")
def download_file(file_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    doc = db["fileitem"].find_one({"_id": oid(file_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")
    path = doc.get("storage_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Stored file missing")
    return FileResponse(path, media_type=doc.get("mime_type"), filename=doc.get("name", "download"))

@app.patch("/drive/rename")
def rename_item(payload: RenameRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    col = "fileitem" if payload.type == "file" else "folder"
    new_name = payload.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Name required")
    res = db[col].find_one_and_update(
        {"_id": oid(payload.id)},
        {"$set": {"name": new_name, "updated_at": datetime.now(timezone.utc)}},
        return_document=True,
    )
    if not res:
        raise HTTPException(status_code=404, detail="Item not found")
    return serialize(res)

@app.delete("/drive/item/{item_id}")
def delete_item(item_id: str, type: Literal["file", "folder"]):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    if type == "file":
        doc = db["fileitem"].find_one({"_id": oid(item_id)})
        if not doc:
            raise HTTPException(status_code=404, detail="File not found")
        # remove from disk
        try:
            if doc.get("storage_path") and os.path.exists(doc["storage_path"]):
                os.remove(doc["storage_path"])
        except Exception:
            pass
        db["fileitem"].delete_one({"_id": doc["_id"]})
        return {"status": "ok"}
    else:
        # recursive delete
        def delete_folder_recursive(folder_id: ObjectId):
            # delete files inside
            for f in db["fileitem"].find({"parent_id": str(folder_id)}):
                try:
                    if f.get("storage_path") and os.path.exists(f["storage_path"]):
                        os.remove(f["storage_path"])
                except Exception:
                    pass
                db["fileitem"].delete_one({"_id": f["_id"]})
            # find subfolders
            for sub in db["folder"].find({"parent_id": str(folder_id)}):
                delete_folder_recursive(sub["_id"])
            # finally delete folder itself
            db["folder"].delete_one({"_id": folder_id})
        folder = db["folder"].find_one({"_id": oid(item_id)})
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        delete_folder_recursive(folder["_id"])
        return {"status": "ok"}

@app.get("/drive/breadcrumbs/{folder_id}")
def get_breadcrumbs(folder_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    crumbs: List[dict] = []
    current = db["folder"].find_one({"_id": oid(folder_id)})
    while current:
        crumbs.append({"_id": str(current["_id"]), "name": current["name"]})
        pid = current.get("parent_id")
        if not pid:
            break
        current = db["folder"].find_one({"_id": ObjectId(pid)})
    crumbs.reverse()
    return {"breadcrumbs": crumbs}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
