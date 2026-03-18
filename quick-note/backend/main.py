from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Header
from fastapi.staticfiles import StaticFiles
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
import asyncio

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
        
    # Seed/Update Admin
    cursor.execute("SELECT id FROM users WHERE username = 'Admin'")
    admin_user = cursor.fetchone()
    if not admin_user:
        admin_pass = get_password_hash("Leopard12@")
        cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", 
                       ("Admin", admin_pass, "admin"))
    else:
        # Force admin role for existing Admin user
        cursor.execute("UPDATE users SET role = 'admin' WHERE username = 'Admin'")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            color TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
                       
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
        # 1. Save to SQLite
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO notes (title, content, image, user_id) VALUES (?, ?, ?, ?)", 
                       (note.title, note.content, note.image, user_id))
        note_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # 2. Index in ChromaDB (RAG)
        if GEMINI_API_KEY:
            try:
                # Combine title and content for better context
                full_text = f"Tytuł: {note.title}\nAutor: {user['username'] if user else 'System'}\nTreść: {note.content}"
                res = genai.embed_content(
                    model="models/gemini-embedding-001",
                    content=full_text,
                    task_type="retrieval_document"
                )
                
                collection.upsert(
                    embeddings=[res['embedding']],
                    documents=[full_text],
                    metadatas=[{"type": "note", "id": str(note_id), "title": note.title, "author": user['username'] if user else 'System'}],
                    ids=[f"note_{note_id}"]
                )
                print(f"[INDEX] Note {note_id} indexed in ChromaDB")
            except Exception as e:
                print(f"[INDEX ERROR] Failed to index note: {str(e)}")

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
            cursor.execute("""
                SELECT n.id, n.title, n.content, n.image, n.created_at, u.username
                FROM notes n
                JOIN users u ON n.user_id = u.id
                ORDER BY n.created_at DESC
            """)
        else:
            cursor.execute("""
                SELECT n.id, n.title, n.content, n.image, n.created_at, u.username
                FROM notes n
                JOIN users u ON n.user_id = u.id
                WHERE n.user_id = ?
                ORDER BY n.created_at DESC
            """, (user_id,))
        
        notes = cursor.fetchall()
        conn.close()
        return [{"id": n[0], "title": n[1], "content": n[2], "image": n[3], "created_at": n[4], "author": n[5]} for n in notes]
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

        # Format context with labels and authors
        ctx_list = []
        if results['documents'] and results['documents'][0]:
            for i, doc in enumerate(results['documents'][0]):
                meta = results['metadatas'][0][i]
                labels = meta.get('labels', '')
                author = meta.get('author', 'System')
                ctx_list.append(f"[Źródło: {meta.get('filename','Notatka')}, Autor: {author}, Etykiety: {labels}]\n{doc}")
                
        context = "\n---\n".join(ctx_list)
        
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

        # Log query for admin
        try:
            user_id = user["id"] if user else 1
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO query_logs (user_id, query) VALUES (?, ?)", (user_id, q))
            conn.commit()
            conn.close()
        except: pass

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

@app.get("/api/admin/logs")
async def get_admin_logs(user=Depends(get_current_user)):
    if not user or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Tylko dla Admina")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT q.id, u.username, q.query, q.created_at 
        FROM query_logs q 
        JOIN users u ON q.user_id = u.id 
        ORDER BY q.created_at DESC LIMIT 50
    """)
    logs = cursor.fetchall()
    conn.close()
    return [{"id": l[0], "username": l[1], "query": l[2], "created_at": l[3]} for l in logs]

@app.get("/api/admin/kb")
async def get_admin_kb(page: int = 1, size: int = 10, user=Depends(get_current_user)):
    if not user or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Tylko dla Admina")
    try:
        # Get all IDs first to count total
        res_all = collection.get(include=[])
        total = len(res_all['ids'])
        
        # Get paginated slice (ChromaDB doesn't have direct skip/limit in .get() easily 
        # for all scenarios, but we can simulate or use include)
        offset = (page - 1) * size
        
        # In this chroma version, we might fetch IDs and slice them
        target_ids = res_all['ids'][offset : offset + size]
        
        if not target_ids:
            return {"items": [], "total": total}

        res = collection.get(ids=target_ids, include=['metadatas'])
        items = []
        for i in range(len(res['ids'])):
            items.append({
                "id": res['ids'][i],
                "metadata": res['metadatas'][i]
            })
        return {"items": items, "total": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/kb/{chunk_id}")
async def get_chunk_content(chunk_id: str, user=Depends(get_current_user)):
    if not user or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Tylko dla Admina")
    try:
        res = collection.get(ids=[chunk_id], include=['documents'])
        if res['documents']:
            return {"content": res['documents'][0]}
        raise HTTPException(status_code=404, detail="Not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/admin/kb/{chunk_id}")
async def delete_admin_kb_chunk(chunk_id: str, user=Depends(get_current_user)):
    if not user or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Tylko dla Admina")
    try:
        collection.delete(ids=[chunk_id])
        return {"success": True, "message": f"Chunk {chunk_id} deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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

@app.get("/api/admin/users")
async def get_all_users(user=Depends(get_current_user)):
    if not user or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Tylko dla Admina")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.username, u.role, u.created_at, COUNT(n.id) as note_count 
        FROM users u
        LEFT JOIN notes n ON u.id = n.user_id
        GROUP BY u.id
    """)
    users = [{"username": r[0], "role": r[1], "created_at": r[2], "note_count": r[3]} for r in cursor.fetchall()]
    conn.close()
    return users

@app.patch("/api/admin/kb/{chunk_id}/metadata")
async def update_kb_metadata(chunk_id: str, patch: dict, user=Depends(get_current_user)):
    if not user or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Tylko dla Admina")
    try:
        # Get existing metadata
        res = collection.get(ids=[chunk_id], include=['metadatas'])
        if not res['metadatas']:
            raise HTTPException(status_code=404, detail="Not found")
            
        current_meta = res['metadatas'][0]
        # Merge patch into current_meta
        for k, v in patch.items():
            current_meta[k] = v
            
        collection.update(ids=[chunk_id], metadatas=[current_meta])
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/labels")
async def get_labels(user=Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name, color FROM labels")
    labels = [{"name": r[0], "color": r[1]} for r in cursor.fetchall()]
    conn.close()
    return labels

@app.post("/api/admin/labels")
async def add_label(label: dict, user=Depends(get_current_user)):
    if not user or user["role"] != "admin": raise HTTPException(status_code=403)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO labels (name, color) VALUES (?, ?)", (label["name"], label.get("color", "#2563eb")))
        conn.commit()
    except: pass
    conn.close()
    return {"success": True}

@app.delete("/api/admin/users/{username}")
async def delete_user(username: str, user=Depends(get_current_user)):
    if not user or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Tylko dla Admina")
    if username == "Admin":
        raise HTTPException(status_code=400, detail="Nie można usunąć głównego konta Admin")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/upload/status/{task_id}")
async def get_upload_status(task_id: str):
    return upload_tasks.get(task_id, {"status": "Not found", "done": False})

# Helper function to split text into chunks
def split_text(text, chunk_size=8000):
    if not text: return []
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

async def process_file_task(task_id: str, file_path: str, original_filename: str):
    ext = os.path.splitext(original_filename)[1].lower()
    summary = ""
    processed_files = []
    
    try:
        print(f"[TASK] Rozpoczęcie: {original_filename}")
        global collection
        collection = chroma_client.get_or_create_collection(name="knowledge_base")

        if ext == ".zip":
            upload_tasks[task_id] = {"status": "Wypakowywanie...", "done": False}
            with tempfile.TemporaryDirectory() as tmpdir:
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
                        
                        text = extract_text(f_path, f_ext)
                        if text.strip() and GEMINI_API_KEY:
                            chunks = split_text(text)
                            batch_size = 50
                            for j in range(0, len(chunks), batch_size):
                                batch = chunks[j:j+batch_size]
                                upload_tasks[task_id] = {"status": f"Indeksowanie ZIP: {rel_path} ({j//batch_size + 1}/{(len(chunks)+batch_size-1)//batch_size})", "done": False}
                                res = genai.embed_content(model="models/gemini-embedding-001", content=batch, task_type="retrieval_document")
                                collection.upsert(
                                    embeddings=res['embedding'], 
                                    documents=batch, 
                                    metadatas=[{"filename": rel_path, "source_zip": original_filename, "type": f_ext, "chunk": j+k} for k in range(len(batch))], 
                                    ids=[f"{original_filename}/{rel_path}_chunk_{j+k}" for k in range(len(batch))]
                                )
                                await asyncio.sleep(1) # Rate limit safety
                            processed_files.append(rel_path)
        else:
            text = extract_text(file_path, ext)
            if text.strip() and GEMINI_API_KEY:
                chunks = split_text(text)
                total_chunks = len(chunks)
                batch_size = 50
                total_batches = (total_chunks + batch_size - 1) // batch_size
                print(f"[TASK] Plik {original_filename} podzielony na {total_chunks} fragmentów ({total_batches} paczek)")
                
                for i in range(0, total_chunks, batch_size):
                    batch = chunks[i:i + batch_size]
                    current_batch = i // batch_size + 1
                    upload_tasks[task_id] = {"status": f"Indeksowanie paczki {current_batch}/{total_batches}", "done": False}
                    print(f"[TASK] Wysyłanie paczki {current_batch}/{total_batches} do Gemini...")
                    
                    try:
                        res = genai.embed_content(model="models/gemini-embedding-001", content=batch, task_type="retrieval_document")
                        collection.upsert(
                            embeddings=res['embedding'], 
                            documents=batch, 
                            metadatas=[{"filename": original_filename, "type": ext, "chunk": i+k} for k in range(len(batch))], 
                            ids=[f"{original_filename}_chunk_{i+k}" for k in range(len(batch))]
                        )
                        await asyncio.sleep(1) # Rate limit safety
                    except Exception as be:
                        print(f"[BATCH ERROR] {str(be)}")
                        if "429" in str(be):
                            await asyncio.sleep(10) # Longer wait on quota error
                
                upload_tasks[task_id] = {"status": "Generowanie podsumowania...", "done": False}
                model = genai.GenerativeModel('models/gemini-flash-latest')
                summary_prompt = f"Podsumuj krótko w 2 zdaniach plik '{original_filename}':\n\n{text[:3000]}"
                summary = model.generate_content(summary_prompt).text

        upload_tasks[task_id] = { "status": "Zakończono pomyślnie", "done": True, "summary": summary, "files": processed_files }
        print(f"[TASK] Sukces: {original_filename}")
    except Exception as e:
        print(f"[TASK ERROR] {str(e)}")
        upload_tasks[task_id] = {"status": f"Błąd: {str(e)}", "done": True, "error": True}


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


# Serve Admin Panel static files
ADMIN_DIST_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "admin-panel", "dist")
if os.path.exists(ADMIN_DIST_PATH):
    app.mount("/admin", StaticFiles(directory=ADMIN_DIST_PATH, html=True), name="admin")
    print(f"[SERVER] Admin panel mounted at /admin (from {ADMIN_DIST_PATH})")
else:
    print(f"[WARNING] Admin dist folder not found at {ADMIN_DIST_PATH}. Build it with 'npm run build' in admin-panel folder.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
