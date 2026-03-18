from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import os
import shutil
from datetime import datetime, timedelta
import google.generativeai as genai
from pypdf import PdfReader
from docx import Document
import chromadb
from dotenv import load_dotenv
import jwt
import bcrypt

# Load .env file
load_dotenv()
import sys
import traceback

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Constants
DB_PATH = os.path.join(os.path.dirname(__file__), "database.sqlite")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")
SECRET_KEY = os.environ.get("SECRET_KEY", "arcus_secret_premium_2026_leopard")
ALGORITHM = "HS256"

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# Crypto utils
def get_password_hash(password: str):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str):
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

# Initialize Gemini
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    print(f"DEBUG: Gemini API Key loaded (starts with: {GEMINI_API_KEY[:5]}...)")
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("WARNING: GEMINI_API_KEY not found in environment!")
sys.stdout.flush()

# Initialize ChromaDB for vector storage
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="knowledge_base")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Users Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Notes Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            content TEXT NOT NULL,
            image TEXT,
            user_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    
    # Files Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_type TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Query Logs Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS query_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            query TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    
    # Migrations
    cursor.execute("PRAGMA table_info(notes)")
    columns = [col[1] for col in cursor.fetchall()]
    if "user_id" not in columns:
        cursor.execute("ALTER TABLE notes ADD COLUMN user_id INTEGER DEFAULT 1")
        
    # Seed Admin if not exists
    cursor.execute("SELECT * FROM users WHERE username = 'Admin'")
    if not cursor.fetchone():
        admin_pass = get_password_hash("Leopard12@")
        cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", 
                       ("Admin", admin_pass, "admin"))
                       
    conn.commit()
    conn.close()

init_db()

# Models
class LoginRequest(BaseModel):
    username: str
    password: str

class UserCreate(BaseModel):
    username: str
    password: str
    role: Optional[str] = "user"

class Note(BaseModel):
    title: Optional[str] = ""
    content: str
    image: Optional[str] = None

# Auth Utils
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=7)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Header(None)):
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except:
        return None

# Endpoints
@app.post("/api/login")
async def login(req: LoginRequest):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password_hash, role FROM users WHERE username = ?", (req.username,))
    user = cursor.fetchone()
    conn.close()
    
    if not user or not verify_password(req.password, user[2]):
        raise HTTPException(status_code=401, detail="Błędny login lub hasło")
    
    token = create_access_token({"id": user[0], "username": user[1], "role": user[3]})
    return {"token": token, "username": user[1], "role": user[3], "id": user[0]}

@app.post("/api/notes")
async def create_note(note: Note, user=Depends(get_current_user)):
    user_id = user["id"] if user else 1
    if not note.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO notes (title, content, image, user_id) VALUES (?, ?, ?, ?)", 
                       (note.title, note.content, note.image, user_id))
        note_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return {"id": note_id, "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/notes")
async def get_notes(user=Depends(get_current_user)):
    user_id = user["id"] if user else 1
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        if user and user["role"] == "admin":
            cursor.execute("SELECT id, title, content, image, created_at FROM notes ORDER BY created_at DESC")
        else:
            cursor.execute("SELECT id, title, content, image, created_at FROM notes WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        
        notes = cursor.fetchall()
        conn.close()
        return [{"id": n[0], "title": n[1], "content": n[2], "image": n[3], "created_at": n[4]} for n in notes]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/query")
async def query_knowledge(q: str, user=Depends(get_current_user)):
    try:
        print(f"DEBUG: Processing query: '{q}'")
        count = collection.count()
        if count == 0:
            return {"answer": "Baza wiedzy jest pusta. Wgraj pliki, aby rozpocząć.", "sources": []}

        # Verified model names from list_models.py
        embedding_model = "models/gemini-embedding-001"
        query_result = genai.embed_content(
            model=embedding_model,
            content=q,
            task_type="retrieval_query"
        )
        query_embedding = query_result['embedding']
        
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(3, count)
        )
        
        if not results['documents'] or not results['documents'][0]:
            return {"answer": "Nie znalazłem precyzyjnych informacji w bazie, ale spróbuję odpowiedzieć z własnej wiedzy.", "sources": []}

        context = "\n".join(results['documents'][0])
        
        # --- OPCJA 1: GOOGLE GEMINI (Z LIMITAMI) ---
        # Przywracam model 2.5 Flash zgodnie z prośbą użytkownika
        model = genai.GenerativeModel('models/gemini-2.5-flash')
        prompt = f"Oto kontekst dokumentacji:\n{context}\n\nOdpowiedz na pytanie: {q}"
        sys.stdout.flush()
        response = model.generate_content(prompt)
        answer = response.text


        
        sources = []
        if results.get('metadatas') and results['metadatas'][0]:
            sources = results['metadatas'][0]

        return {"answer": answer, "sources": sources}
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg:
            return {"answer": "Wyczerpano darmowy limit API Gemini (ok. 20-50 zapytań/dobę). Jeśli chcesz używać bota BEZ LIMITÓW, zainstaluj Ollama i daj mi znać - przełączę kod na wersję 100% lokalną!", "sources": []}
        print(f"!!! Error in query: {error_msg}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Błąd AI: {error_msg}")

@app.get("/api/admin/stats")
async def get_stats(user=Depends(get_current_user)):
    if not user or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Tylko dla Admina")
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.username, COUNT(n.id) as note_count
        FROM users u
        LEFT JOIN notes n ON u.id = n.user_id
        GROUP BY u.id
    """)
    note_stats = cursor.fetchall()
    
    cursor.execute("""
        SELECT u.username, COUNT(q.id) as query_count
        FROM users u
        LEFT JOIN query_logs q ON u.id = q.user_id
        GROUP BY u.id
    """)
    query_stats = cursor.fetchall()
    conn.close()
    
    stats = {}
    for user_stat in note_stats:
        stats[user_stat[0]] = {"notes": user_stat[1], "queries": 0}
    for query_stat in query_stats:
        if query_stat[0] in stats:
            stats[query_stat[0]]["queries"] = query_stat[1]
        else:
            stats[query_stat[0]] = {"notes": 0, "queries": query_stat[1]}
            
    return [{"username": k, "notes": v["notes"], "queries": v["queries"]} for k, v in stats.items()]

@app.post("/api/admin/users")
async def create_new_user(new_user: UserCreate, user=Depends(get_current_user)):
    if not user or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Tylko dla Admina")
        
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        hashed_pass = get_password_hash(new_user.password)
        cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                       (new_user.username, hashed_pass, new_user.role))
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail="Użytkownik już istnieje")

import zipfile
import tempfile

from fastapi import BackgroundTasks

# Store task status
upload_tasks = {}

@app.get("/api/upload/status/{task_id}")
async def get_upload_status(task_id: str):
    return upload_tasks.get(task_id, {"status": "Not found", "done": False})

async def process_file_task(task_id: str, file_path: str, original_filename: str):
    ext = os.path.splitext(original_filename)[1].lower()
    summary = ""
    processed_files = []
    
    try:
        global collection
        collection = chroma_client.get_or_create_collection(name="knowledge_base")

        if ext == ".zip":
            upload_tasks[task_id] = {"status": "Wypakowywanie...", "done": False}
            with tempfile.TemporaryDirectory() as tmpdir:
                # Re-save to temp for zip processing
                temp_zip = os.path.join(tmpdir, "archive.zip")
                shutil.copy(file_path, temp_zip)
                
                with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                    zip_ref.extractall(tmpdir)
                    
                for root, _, files in os.walk(tmpdir):
                    for f_name in files:
                        if f_name == "archive.zip": continue
                        f_path = os.path.join(root, f_name)
                        rel_path = os.path.relpath(f_path, tmpdir)
                        f_ext = os.path.splitext(f_name)[1].lower()
                        
                        upload_tasks[task_id] = {"status": f"Indeksowanie: {rel_path}", "done": False}
                        text = extract_text(f_path, f_ext)
                        if text.strip() and GEMINI_API_KEY:
                            try:
                                doc_id = f"{original_filename}/{rel_path}"
                                res = genai.embed_content(model="models/gemini-embedding-001", content=text, task_type="retrieval_document")
                                collection.upsert(
                                    embeddings=[res['embedding']], 
                                    documents=[text], 
                                    metadatas=[{"filename": rel_path, "source_zip": original_filename, "type": f_ext}], 
                                    ids=[doc_id]
                                )
                                processed_files.append(rel_path)
                            except: pass
                
                if processed_files and GEMINI_API_KEY:
                    upload_tasks[task_id] = {"status": "Generowanie podsumowania...", "done": False}
                    model = genai.GenerativeModel('models/gemini-flash-latest')
                    summary_prompt = f"Podsumuj krótko (maksymalnie 3 zdania) zawartość archiwum ZIP '{original_filename}', które zawiera pliki: {', '.join(processed_files[:10])}. Co to za projekt?"
                    summary = model.generate_content(summary_prompt).text
        else:
            upload_tasks[task_id] = {"status": f"Indeksowanie: {original_filename}", "done": False}
            text = extract_text(file_path, ext)
            if text.strip() and GEMINI_API_KEY:
                res = genai.embed_content(model="models/gemini-embedding-001", content=text, task_type="retrieval_document")
                collection.upsert(
                    embeddings=[res['embedding']], 
                    documents=[text], 
                    metadatas=[{"filename": original_filename, "type": ext}], 
                    ids=[original_filename]
                )
                
                upload_tasks[task_id] = {"status": "Generowanie podsumowania...", "done": False}
                model = genai.GenerativeModel('models/gemini-flash-latest')
                summary_prompt = f"Podsumuj krótko w 2 zdaniach plik '{original_filename}':\n\n{text[:2000]}"
                summary = model.generate_content(summary_prompt).text

        upload_tasks[task_id] = {
            "status": "Zakończono pomyślnie", 
            "done": True, 
            "summary": summary, 
            "files": processed_files
        }
    except Exception as e:
        upload_tasks[task_id] = {"status": f"Błąd w zadaniu: {str(e)}", "done": True, "error": True}

@app.post("/api/upload")
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    print(f"[UPLOAD] Starting upload for: {file.filename}")
    
    # Save file to uploads
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as b: 
        shutil.copyfileobj(file.file, b)
    
    task_id = file.filename # Using filename as simple ID
    upload_tasks[task_id] = {"status": "Oczekiwanie...", "done": False}
    
    background_tasks.add_task(process_file_task, task_id, file_path, file.filename)
    
    return {"task_id": task_id}

def extract_text(fp, ext):
    try:
        if ext == ".pdf":
            return "\n".join([p.extract_text() for p in PdfReader(fp).pages])
        elif ext == ".docx":
            return "\n".join([p.text for p in Document(fp).paragraphs])
        # Include more text types
        elif ext in [".txt", ".sql", ".cs", ".py", ".js", ".md", ".json", ".html", ".css", ".ts", ".tsx", ".java", ".cpp", ".h", ".c"]:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f: 
                return f.read()
    except:
        pass
    return ""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
