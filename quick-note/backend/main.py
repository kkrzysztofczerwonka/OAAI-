from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sqlite3
import os
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.path.join(os.path.dirname(__file__), "database.sqlite")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            content TEXT NOT NULL,
            image TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migration: check for 'image' column
    cursor.execute("PRAGMA table_info(notes)")
    columns = [col[1] for col in cursor.fetchall()]
    if "image" not in columns:
        cursor.execute("ALTER TABLE notes ADD COLUMN image TEXT")
    if "title" not in columns:
        cursor.execute("ALTER TABLE notes ADD COLUMN title TEXT")
        
    conn.commit()
    conn.close()

init_db()

class Note(BaseModel):
    title: Optional[str] = ""
    content: str
    image: Optional[str] = None # Base64 image data

@app.post("/api/notes")
async def create_note(note: Note):
    if not note.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO notes (title, content, image) VALUES (?, ?, ?)", 
                       (note.title, note.content, note.image))
        note_id = cursor.lastrowid
        conn.commit()
        conn.close()
        img_status = "with image" if note.image else "no image"
        print(f"[{datetime.now()}] Note added ({img_status}): {note.title}")
        return {"id": note_id, "success": True}
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Failed to save note")

@app.get("/api/notes")
async def get_notes():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, content, image, created_at FROM notes ORDER BY created_at DESC")
        notes = cursor.fetchall()
        conn.close()
        return [{"id": n[0], "title": n[1], "content": n[2], "image": n[3], "created_at": n[4]} for n in notes]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
