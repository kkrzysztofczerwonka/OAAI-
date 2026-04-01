from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Header, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import sqlite3
import os
import shutil
from datetime import datetime, timedelta
import google.generativeai as genai
import time
from pypdf import PdfReader
from docx import Document
import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv
import jwt
import bcrypt
import asyncio
from bookstack_service import BookStackService
import traceback
import re
from sentence_transformers import SentenceTransformer

# Load .env file
load_dotenv()

# Configure Gemini
api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
    try:
        print("[AI] Listowanie dostępnych modeli Gemini:")
        available_models = [m.name for m in genai.list_models()]
        for m in available_models:
            print(f"  - {m}")
    except Exception as e:
        print(f"[AI] Nie udało się wylistować modeli (Klucz może być nieaktywny): {e}")
import sys
import traceback
import re

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

# Global embedder variable
_embedder = None

def get_embedder():
    global _embedder
    if _embedder is None:
        print("[EMBED] Ładowanie modelu embeddings (Lazy Load)...")
        try:
            _embedder = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
            print("[EMBED] Model załadowany pomyślnie.")
        except Exception as e:
            print(f"[EMBED] BŁĄD ładowania modelu: {e}")
            raise e
    return _embedder

# Initialize ChromaDB for vector storage
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="knowledge_base_local")

# Initialize BookStack
BOOKSTACK_URL = os.environ.get("BOOKSTACK_URL", "http://192.168.13.12")
BOOKSTACK_TOKEN_ID = os.environ.get("BOOKSTACK_TOKEN_ID", "")
BOOKSTACK_TOKEN_SECRET = os.environ.get("BOOKSTACK_TOKEN_SECRET", "")
bookstack = None
if BOOKSTACK_TOKEN_ID and BOOKSTACK_TOKEN_SECRET:
    bookstack = BookStackService(BOOKSTACK_URL, BOOKSTACK_TOKEN_ID, BOOKSTACK_TOKEN_SECRET)
    print(f"DEBUG: BookStack API initialized (URL: {BOOKSTACK_URL})")
else:
    print("WARNING: BookStack credentials missing in environment!")

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
    
    # Conversations Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    
    # Messages Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER,
            role TEXT,
            content TEXT,
            sources TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id)
        )
    """)
    
    # Legacy Query Logs (Keep or migrate)
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

def normalize_text(text: str) -> str:
    """Normalize Polish text by removing accents for better matching"""
    import unicodedata
    if not text: return ""
    text = text.lower().replace('ł', 'l').replace('Ł', 'l')
    return "".join(c for c in unicodedata.normalize('NFD', text)
                   if unicodedata.category(c) != 'Mn')

def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]:
    """Split text into manageable chunks for embedding"""
    if not text: return []
    # Simple character-based splitting with overlap
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        # Try to find a logical break point (newline or space) near the end
        if end < len(text):
            # Look back for a newline or space
            break_point = -1
            search_area = text[end-100:end]
            for sep in ['\n\n', '\n', '. ', ' ']:
                idx = search_area.rfind(sep)
                if idx != -1:
                    break_point = end - 100 + idx + len(sep)
                    break
            if break_point != -1:
                end = break_point
        
        chunks.append(text[start:end].strip())
        start = end - overlap
        if start >= len(text) - overlap:
            break
            
    return [c for c in chunks if len(c) > 20]

async def process_page_for_vector_db(page_id: int):
    """Fetch page, chunk it and store embeddings in ChromaDB"""
    if not bookstack: return
    try:
        print(f"[VECTOR] Rozpoczynam przetwarzanie strony ID {page_id}...", flush=True)
        page = bookstack.get_page(page_id)
        
        # Get content
        m_text = page.get("markdown", "")
        h_content = page.get("html", "")
        
        # Clean HTML properly
        clean_h = ""
        if h_content:
            clean_h = re.sub(r'<(p|br|li|h[1-6]|tr|div|section|article|header|footer|td)[^>]*>', '\n', h_content)
            clean_h = re.sub(r'<[^>]+>', '', clean_h)
            clean_h = re.sub(r'\n+', '\n', clean_h).strip()

        # Use the richer content
        final_text = m_text if len(m_text) > len(clean_h) else clean_h
        
        if not final_text or len(final_text.strip()) < 10:
            print(f"[VECTOR] Strona ID {page_id} jest pusta lub za krótka. Pomijam.")
            return

        chunks = chunk_text(final_text)
        
        # Remove old chunks for this page
        collection.delete(where={"page_id": page_id})
        
        if not chunks: return
        
        # Generate embeddings in blocks (or one by one if preferred)
        # Using models/text-embedding-004
        ids = []
        embeddings = []
        documents = []
        metadatas = []
        
        for i, chunk in enumerate(chunks):
            try:
                # Add context (title) to each chunk for better retrieval
                augmented_chunk = f"Tytuł: {page.get('name')}\n\n{chunk}"
                
                # Generowanie wektora lokalnie (za darmo)
                model = get_embedder()
                embedding = model.encode(augmented_chunk).tolist()
                ids.append(f"page_{page_id}_chunk_{i}")
                embeddings.append(embedding)
                documents.append(chunk) # Store original chunk text
                metadatas.append({
                    "page_id": page_id,
                    "book_id": page.get("book_id"),
                    "chapter_id": page.get("chapter_id"),
                    "title": page.get("name"), 
                    "chunk_index": i,
                    "updated_at": datetime.now().isoformat()
                })
            except Exception as embed_e:
                print(f"[VECTOR] Błąd embeddingu dla chunk {i} strony {page_id}: {embed_e}")
        
        if ids:
            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas
            )
            print(f"[VECTOR] Pomyślnie zindeksowano stronę '{page.get('name')}' ({len(ids)} chunków  - LOKALNIE).", flush=True)
            
    except Exception as e:
        print(f"[VECTOR] Błąd przetwarzania strony {page_id}: {e}", flush=True)
        traceback.print_exc()

# Global Cache for BookStack Structure
bookstack_structure_cache = None
last_structure_update = 0

def get_knowledge_map():
    global bookstack_structure_cache, last_structure_update
    if not bookstack: return ""
    
    import time
    # Refresh every 30 mins
    if not bookstack_structure_cache or (time.time() - last_structure_update > 1800):
        try:
            print("[SYNC] Odświeżanie mapy struktury BookStack...", flush=True)
            bookstack_structure_cache = bookstack.get_global_structure()

            bookstack.refresh_map() 
            last_structure_update = time.time()
        except Exception as e:
            print(f"[ERROR] Nie udało się pobrać struktury: {e}", flush=True)
            return ""
            
    # Format as list of strings
    map_str = "Struktura Bazy Wiedzy (Półki -> Książki -> Rozdziały -> Strony):\n"
    for shelf in bookstack_structure_cache.get("shelves", []):
        map_str += f"Półka: {shelf['name']}\n"
        for book in shelf.get("books", []):
            map_str += f"  Książka: {book['name']}\n"
            # Pages directly in book
            for p in book.get("pages_direct", []):
                map_str += f"    - Strona ID {p['id']}: {p['name']}\n"
            # Chapters and their pages
            for chapter in book.get("chapters", []):
                map_str += f"    Rozdział: {chapter['name']}\n"
                for p in chapter.get("pages", []):
                    map_str += f"      - Strona ID {p['id']}: {p['name']}\n"
    return map_str
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
    tags: Optional[List[Dict[str, str]]] = None # [{"name": "Key", "value": "Val"}]
    priority: Optional[int] = 0
    book_id: Optional[int] = None
    chapter_id: Optional[int] = None

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

class SuggestRequest(BaseModel):
    content: str

@app.post("/api/suggest-metadata")
async def suggest_metadata(req: SuggestRequest, user=Depends(get_current_user)):
    if not GEMINI_API_KEY:
        return {"error": "Gemini API key not configured"}
    
    knowledge_map = get_knowledge_map()
    
    prompt = f"""
    Przeanalizuj poniższą notatkę techniczną i zasugeruj wartości dla 5 pól metadanych oraz odpowiednie MIEJSCE zapisu w bazie wiedzy.
    Wybierz NAJBARDZIEJ PASUJĄCE wartości z podanych list. Jeśli nic nie pasuje, zostaw puste "".
    
    TAGI (zasugeruj dowolne, pasujące słowa kluczowe):
    1. Rozwiązanie (np. sql, skrypt, konfiguracja)
    2. Podrozwiązanie (szczegół techniczny, np. procedura, widok)
    3. Produkt (np. optima, xl, dms)
    4. Obszar (np. handel, księgowość, magazyn)
    5. Firma (jeśli dotyczy konkretnego klienta)

    MIEJSCE W BAZIE WIEDZY:
    Zasugeruj NAJBARDZIEJ PASUJACĄ Książkę (Book) i opcjonalnie Rozdział (Chapter) z poniższej struktury:
    {knowledge_map}

    TREŚĆ NOTATKI:
    \"\"\"{req.content}\"\"\"

    Zasady sugerowania miejsca:
    - Wybierz Książkę, która najlepiej pasuje tematycznie.
    - Jeśli w Książce istnieją Rozdziały, wybierz najbardziej odpowiedni lub zostaw pusty jeśli notatka powinna trafić bezpośrednio do książki.
    - Zwróć DOKŁADNE nazwy Książki i Rozdziału jakie występują w strukturze.

    Zwróć odpowiedź WYŁĄCZNIE jako czysty JSON (bez markdownu) o strukturze:
    {{
      "rozwiazanie": "...",
      "podrozwiazanie": "...",
      "produkt": "...",
      "obszar": "...",
      "firma": "...",
      "ksiazka_nazwa": "...",
      "rozdzial_nazwa": "..."
    }}
    """
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3].strip()
        elif text.startswith("```"):
            text = text[3:-3].strip()
            
        import json
        suggestion = json.loads(text)
        
        # Translate names to IDs for the frontend if found
        suggestion["book_id"] = None
        suggestion["chapter_id"] = None
        
        if bookstack_structure_cache and suggestion.get("ksiazka_nazwa"):
            for shelf in bookstack_structure_cache.get("shelves", []):
                for book in shelf.get("books", []):
                    if book["name"].lower() == suggestion["ksiazka_nazwa"].lower():
                        suggestion["book_id"] = book["id"]
                        if suggestion.get("rozdzial_nazwa"):
                            for ch in book.get("chapters", []):
                                if ch["name"].lower() == suggestion["rozdzial_nazwa"].lower():
                                    suggestion["chapter_id"] = ch["id"]
                                    break
                        break
        
        return suggestion
    except Exception as e:
        print(f"Error suggesting metadata: {e}")
        return {"rozwiazanie": "", "podrozwiazanie": "", "produkt": "", "obszar": "", "firma": "", "book_id": None, "chapter_id": None}

@app.post("/api/webhook/bookstack")
async def bookstack_webhook(request: Request):
    """Webhook for BookStack events to trigger vector indexing"""
    try:
        payload = await request.json()
        event = payload.get("event")
        related_item = payload.get("related_item", {})
        
        print(f"[WEBHOOK] Otrzymano zdarzenie: {event} dla elementu ID {related_item.get('id')}")
        
        if event in ["page_create", "page_update"]:
            page_id = related_item.get("id")
            if page_id:
                # Process in background
                asyncio.create_task(process_page_for_vector_db(page_id))
        elif event == "page_delete":
            page_id = related_item.get("id")
            if page_id:
                collection.delete(where={"page_id": page_id})
                print(f"[VECTOR] Usunięto stronę ID {page_id} z bazy.", flush=True)
        elif event == "book_delete":
            book_id = related_item.get("id")
            if book_id:
                collection.delete(where={"book_id": book_id})
                print(f"[VECTOR] Usunięto całą książkę ID {book_id} z bazy.", flush=True)
        elif event == "chapter_delete":
            chapter_id = related_item.get("id")
            if chapter_id:
                collection.delete(where={"chapter_id": chapter_id})
                print(f"[VECTOR] Usunięto cały rozdział ID {chapter_id} z bazy.", flush=True)
                
        return {"status": "success"}
    except Exception as e:
        print(f"[WEBHOOK] Błąd: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/admin/reindex-all")
async def reindex_all_pages(background_tasks: BackgroundTasks):
    """Admin endpoint to force reindex all pages from BookStack"""
    if not bookstack:
        print("[REINDEX] Błąd: BookStack nie jest skonfigurowany!")
        return {"error": "BookStack connection not configured"}
        
    def run_full_reindex():
        try:
            print("[REINDEX] START: Rozpoczynam pełne reindeksowanie..", flush=True)
            
            # NOWOŚĆ: Czyścimy całą bazę wektorową przed reindeksacją, żeby pozbyć się "duchów" starych stron
            if collection.count() > 0:
                print(f"[REINDEX] Czyszczę bazę z {collection.count()} starych fragmentów...", flush=True)
                # Ponieważ na razie mamy tylko BookStack, usuwamy wszystko (pobieramy wszystkie ID lub po prostu usuwamy kolekcję)
                # ChromaDB nie pozwala na delete() bez warunku, więc usuwamy po metadanych lub po prostu pobieramy wszystkie ID
                all_ids = collection.get()['ids']
                if all_ids:
                    collection.delete(ids=all_ids)
                print("[REINDEX] Baza wyczyszczona. Rozpoczynam pobieranie danych.", flush=True)

            books = bookstack.list_books()
            print(f"[REINDEX] Znaleziono {len(books)} książek do przetworzenia.")
            
            total_pages = 0
            for book in books:
                print(f"[REINDEX] Pobieram strony z książki: {book['name']} (ID: {book['id']})")
                try:
                    pages = bookstack.list_pages(book_id=book["id"])
                    print(f"[REINDEX] Książka '{book['name']}' ma {len(pages)} stron.")
                    
                    for p in pages:
                        # Wywołujemy to synchronicznie wewnątrz worker thread-a
                        try:
                            # Używamy asyncio.run tylko jeśli nie ma aktywnego loopa w tym wątku
                            try:
                                loop = asyncio.get_event_loop()
                                if loop.is_running():
                                    # Jeśli jesteśmy w async workerze, odpalamy jako task i czekamy synchronicznie
                                    coro = process_page_for_vector_db(p["id"])
                                    asyncio.run_coroutine_threadsafe(coro, loop).result()
                                else:
                                    loop.run_until_complete(process_page_for_vector_db(p["id"]))
                            except RuntimeError:
                                asyncio.run(process_page_for_vector_db(p["id"]))
                                
                            total_pages += 1
                        except Exception as e:
                            print(f"[REINDEX] Błąd przy stronie {p.get('id', 'unknown')}: {e}", flush=True)
                    
                except Exception as book_e:
                    print(f"[REINDEX] Błąd przy przetwarzaniu książki {book.get('id')}: {book_e}", flush=True)
                    
            print(f"[REINDEX] FINISH: Zakończono! Przetworzono łącznie {total_pages} stron.", flush=True)
        except Exception as e:
            print(f"[REINDEX] Błąd krytyczny w zadaniu w tle: {e}", flush=True)
            traceback.print_exc()

    background_tasks.add_task(run_full_reindex)
    print("[REINDEX] Zadanie dodane do kolejki BackgroundTasks.", flush=True)
    return {"status": "started", "message": "Reindeksowanie uruchomione w tle."}

@app.get("/api/admin/debug-page/{page_id}")
async def debug_page_content(page_id: int):
    """Debug endpoint to check if a page exists in ChromaDB"""
    if not collection:
        return {"error": "Collection not initialized"}
    
    # Próbujemy pobrać fragmenty jako int
    res = collection.get(where={"page_id": page_id})
    # Próbujemy jako str
    if not res['documents']:
        res = collection.get(where={"page_id": str(page_id)})
        
    return {
        "page_id": page_id,
        "chunk_count": len(res['documents']) if res['documents'] else 0,
        "titles": [m.get("title") for m in res['metadatas']] if res['metadatas'] else [],
        "preview": [doc[:100] + "..." for doc in res['documents'][:3]] if res['documents'] else []
    }

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
        # 1. Save to SQLite as backup/metadata
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO notes (title, content, image, user_id) VALUES (?, ?, ?, ?)", 
                       (note.title, note.content, note.image, user_id))
        note_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # 2. Sync to BookStack
        if bookstack:
            book_id = note.book_id
            chapter_id = note.chapter_id
            
            # Default fallback if no valid target provided
            if not book_id:
                book_id = bookstack.get_book_id_by_name("notatki")
                
            if book_id:
                # Send content directly as it's already HTML from TipTap
                html_content = note.content
                bookstack.create_page(
                    book_id=book_id, 
                    chapter_id=chapter_id,
                    name=note.title or f"Notatka {note_id}", 
                    html=html_content,
                    tags=note.tags,
                    priority=note.priority or 0
                )
                print(f"[SYNC] Notatka '{note.title}' dodana do BookStack (Book ID: {book_id}, Chapter ID: {chapter_id}) z tagami: {note.tags}")
        
        return {"id": note_id, "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/notes")
async def get_notes(user=Depends(get_current_user)):
    # Prefer BookStack for notes if available
    if bookstack:
        try:
            book_id = bookstack.get_book_id_by_name("notatki")
            if book_id:
                pages = bookstack.list_pages(book_id=book_id)
                # Fetch full content for each note (if not too many)
                results = []
                for p in pages[:20]: # Limit to last 20 notes for performance
                    p_detail = bookstack.get_page(p["id"])
                    text_content = re.sub('<[^<]+?>', '', p_detail.get("html", ""))
                    results.append({
                        "id": p["id"], 
                        "title": p["name"], 
                        "content": text_content, 
                        "image": None, 
                        "created_at": p.get("created_at")
                    })
                return results
        except Exception as e:
            print(f"ERROR: BookStack get_notes failed: {str(e)}")

    # Fallback to SQLite
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

class ChatRequest(BaseModel):
    messages: List[Dict[str, str]] 
    conversation_id: Optional[int] = None

@app.get("/api/conversations")
async def get_conversations(user=Depends(get_current_user)):
    user_id = user["id"] if user else 1
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, created_at FROM conversations WHERE user_id = ? ORDER BY created_at DESC LIMIT 5", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "created_at": r[2]} for r in rows]

@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: int, user=Depends(get_current_user)):
    user_id = user["id"] if user else 1
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Delete messages first
    cursor.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
    # Delete conversation
    cursor.execute("DELETE FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user_id))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.get("/api/conversations/{conv_id}")
async def get_conversation_history(conv_id: int, user=Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT role, content, sources FROM messages WHERE conversation_id = ? ORDER BY created_at ASC", (conv_id,))
    rows = cursor.fetchall()
    import json
    history = []
    for r in rows:
        history.append({
            "role": r[0],
            "text": r[1],
            "sources": json.loads(r[2]) if r[2] else []
        })
    conn.close()
    return history

@app.post("/api/query")
async def query_knowledge(req: ChatRequest, user=Depends(get_current_user)):
    try:
        user_id = user["id"] if user else 1
        conv_id = req.conversation_id
        
        # Get latest query
        latest_msg = req.messages[-1]["content"] if req.messages else ""
        if not latest_msg:
            return {"answer": "Nie podano zapytania.", "sources": []}
            
        print(f"[QUERY] Przetwarzanie pytania: '{latest_msg}'")
        
        # 0. Get Knowledge Map (Structure) for context
        knowledge_map = get_knowledge_map()
        
        context = ""
        sources = []
        extracted_images = []

        # 1. VECTOR SEARCH (Primary)
        try:
            # Check if collection has data
            count = collection.count()
            if count > 0:
                print(f"[VECTOR] Szukam w {count} fragmentach...")
                # Embed current query
                model = get_embedder()
                query_embedding = model.encode(latest_msg).tolist()
                
                results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=min(150, count) # Wracamy do 150
                )
                
                if results['documents'] and results['documents'][0]:
                    # 1. GRUPOWANIE I RANKOWANIE STRON (Reranking)
                    page_scores = {} # page_id -> score
                    page_metadata = {} # page_id -> meta
                    
                    # Czyścimy query_words i bierzemy rdzenie (min. 4 litery) LUB krótkie numery wersji
                    raw_words = [w.lower() for w in latest_msg.split()]
                    query_roots = []
                    for w in raw_words:
                        if len(w) >= 4:
                            query_roots.append(w[:4])
                        elif any(char.isdigit() for char in w): # Zachowujemy krótkie numery typu "7.1"
                            query_roots.append(w)
                    
                    # --- NOWOŚĆ: Przeszukiwanie struktury po rdzeniach tytułów (Z PUNKTACJĄ) ---
                    forced_scored_ids = {} # p_id -> score
                    if bookstack and bookstack.all_pages_map:
                        for p_id, p_info in bookstack.all_pages_map.items():
                            p_title_lower = p_info.get("name", "").lower()
                            matches = 0
                            exact_hits = 0
                            
                            for word in raw_words:
                                if word in p_title_lower:
                                    exact_hits += 1 # Dokładne trafienie całego słowa (np. "7.1")
                                    
                            for root in query_roots:
                                if root in p_title_lower:
                                    matches += 1
                                    
                            if matches >= 1:
                                # Punktacja: 
                                # Trafienie rdzenia = 10 pkt
                                # Dokładne trafienie pełnego słowa = +50 pkt (Kluczowe dla wersji!)
                                forced_scored_ids[p_id] = (matches * 10.0) + (exact_hits * 50.0)
                                
                    # Sortujemy wymuszone strony po wyniku
                    forced_sorted = sorted(forced_scored_ids.items(), key=lambda x: x[1], reverse=True)
                    forced_final_ids = [p[0] for p in forced_sorted[:10]] # Bierzemy Top 10 dopasowań tytułów

                    for i in range(len(results['metadatas'][0])):
                        meta = results['metadatas'][0][i]
                        p_id = meta.get("page_id")
                        p_title = meta.get("title", "").lower()
                        distance = results['distances'][0][i] if 'distances' in results else 0.5
                        
                        if not p_id: continue
                        
                        if p_id not in page_scores:
                            # Startowy wynik oparty na bliskości wektorowej (niższy dystans = lepiej)
                            page_scores[p_id] = (1.0 - distance)
                            page_metadata[p_id] = meta
                            
                        # BONUS ZA TYTUŁ: Jeśli rdzeń z pytania jest w tytule strony - boost!
                        title_bonus = 0
                        for root in query_roots:
                            if root in p_title:
                                title_bonus += 2.5 # Jeszcze silniejszy impuls (z 2.0 na 2.5)
                        
                        page_scores[p_id] += title_bonus

                    # Wybieramy Top strony po zboostowanym wyniku wektorowym
                    sorted_pages = sorted(page_scores.items(), key=lambda x: x[1], reverse=True)
                    top_page_ids = [p[0] for p in sorted_pages[:3]]
                    
                    for f_id in reversed(forced_final_ids):
                        if f_id not in top_page_ids:
                            top_page_ids.insert(0, f_id)
                    
                    top_page_ids = list(dict.fromkeys(top_page_ids))[:3]
                    
                    print(f"[QUERY] Wybrane strony do ekspansji: {top_page_ids}", flush=True)

                    seen_page_ids = set()
                    
                    # 2. Ekspansja dla wybranych stron
                    for p_id in top_page_ids:
                        # Jeśli strona była forsowana, a nie ma jej w metadata z ChromaDB, pobierzemy tytuł z mapy
                        if p_id in page_metadata:
                            target_meta = page_metadata[p_id]
                            p_title = target_meta.get("title", "Dokument")
                        elif bookstack and str(p_id) in [str(k) for k in bookstack.all_pages_map.keys()]:
                            p_title = bookstack.all_pages_map[p_id].get("name", "Dokument")
                        else:
                            p_title = f"Strona ID {p_id}"
                        
                        # Pobieramy fragmenty z bazy wektorowej
                        full_page_data = collection.get(where={"page_id": p_id})
                        if not (full_page_data and full_page_data['documents']):
                            full_page_data = collection.get(where={"page_id": str(p_id)})
                        
                        limited_chunks = []
                        num_chunks = 0
                        
                        if full_page_data and full_page_data['documents']:
                            num_chunks = len(full_page_data['documents'])
                            print(f"[QUERY] Ekspansja strony ID {p_id} ({p_title}): {num_chunks} fragm.", flush=True)
                            
                            # Sortowanie i limitowanie (żeby nie zapchać kontekstu gigantami)
                            indexed_chunks = []
                            for idx, doc in enumerate(full_page_data['documents']):
                                c_idx = full_page_data['metadatas'][idx].get("chunk_index", 0)
                                indexed_chunks.append((c_idx, doc))
                            indexed_chunks.sort()
                            
                            # Bierzemy max 60 fragmentów (około 20-30 stron tekstu)
                            limited_chunks = [c[1] for c in indexed_chunks[:60]]
                        elif bookstack:
                            # FALLBACK: Jeśli nie ma w bzie wektorowej, dociągamy bezpośrednio z API w locie
                            try:
                                print(f"[QUERY] Ekspansja strony ID {p_id} ({p_title}): Pobieranie bezpośrednio z API...", flush=True)
                                page_detail = bookstack.get_page(p_id)
                                text_content = re.sub('<[^<]+?>', '', page_detail.get("html", ""))
                                limited_chunks = [text_content[:20000]] # Bierzemy solidny kawałek tekstu
                                num_chunks = 1
                            except Exception as e:
                                print(f"[QUERY] Błąd pobierania strony {p_id} z API: {e}", flush=True)

                        if limited_chunks:
                            context += f"\n--- TREŚĆ STRONY: {p_title} (ID {p_id}) ---\n"
                            context += "\n".join(limited_chunks)
                            if num_chunks > 60:
                                context += f"\n[UWAGA: Wyświetlono tylko pierwsze 60 fragmentów tej strony]\n"
                            context += "\n" + "-"*50 + "\n\n"
                            seen_page_ids.add(p_id)
                            
                            # Dodajemy źródło z linkiem
                            source_entry = {"title": p_title, "url": f"{BOOKSTACK_URL.rstrip('/')}/pages/{p_id}"}
                            if source_entry not in sources:
                                sources.append(source_entry)

                    # 3. Dopisujemy resztę drobnicy z wyników wyszukiwania (jeśli nie były w top 3)
                    for i, doc in enumerate(results['documents'][0]):
                        meta = results['metadatas'][0][i]
                        p_id = meta.get("page_id")
                        if p_id in seen_page_ids: continue
                        
                        p_title = meta.get("title", "Nieznany dokument")
                        context += f"\n--- Fragment z: {p_title} (ID: {p_id}) ---\n{doc}\n"
                        # USUNIĘTE: nie dodajemy drobnicy do listy źródeł na dole
            else:
                print("[VECTOR] Baza wektorowa jest pusta.")
        except Exception as vec_e:
            print(f"[VECTOR] Błąd wyszukiwania wektorowego: {vec_e}")

        # 2. Fallback to direct search if context is still empty
        if not context and bookstack:
            print("[QUERY] Fallback do wyszukiwania tekstowego...")
            results = bookstack.search(latest_msg)
            for res in results[:3]:
                if res.get("type") == "page":
                    try:
                        page_detail = bookstack.get_page(res.get("id"))
                        text_content = re.sub('<[^<]+?>', '', page_detail.get("html", ""))
                        context += f"\n--- Dokument: {res.get('name')} ---\n{text_content[:3000]}\n"
                        sources.append({"title": res.get('name'), "url": f"{BOOKSTACK_URL.rstrip('/')}/pages/{res.get('id')}"})
                    except: pass

        if not context:
            return {"answer": "Baza wiedzy jest pusta lub nie znalazłem tam nic o tym.", "sources": []}

        # 3. Generate response with history
        prompt_with_history = "To jest historia konwersacji (użyj jej jako kontekstu):\n"
        for m in req.messages[:-1][-5:]:
            role_map = {"user": "Użytkownik", "ai": "AI Assistant"}
            prompt_with_history += f"{role_map.get(m['role'], m['role'])}: {m['content']}\n"
            
        prompt_with_history += f"\nOto struktura Bazy Wiedzy (użyj dla orientacji):\n{knowledge_map}\n\n"
        prompt_with_history += f"Oto NAJBARDZIEJ TRAFNE FRAGMENTY z Twojej Bazy Wiedzy:\n{context}\n\n"
        prompt_with_history += f"PYTANIE UŻYTKOWNIKA: {latest_msg}\n"
        prompt_with_history += "Przeanalizuj fragmenty i odpowiedz na pytanie użytkownika. Jeśli fragmenty zawierają rozwiązanie, opisz je dokładnie. Odpowiedz profesjonalnie po polsku."

        # Multimodal if images found
        parts = [prompt_with_history]
        processed_images = []
        import base64
        
        for img in extracted_images[:3]: 
            try:
                src = img["src"]
                mime_type = "image/png"
                if src.startswith("data:image"):
                    header, encoded = src.split(",", 1)
                    mime_type = header.split(";")[0].split(":")[1]
                    img_data = base64.b64decode(encoded)
                    b64_data = encoded
                elif src.startswith("http") and bookstack:
                    img_data = bookstack.get_image_content(src)
                    b64_data = base64.b64encode(img_data).decode('utf-8')
                    if src.lower().endswith(".jpg") or src.lower().endswith(".jpeg"): mime_type = "image/jpeg"
                else: continue

                parts.append({"mime_type": mime_type, "data": img_data})
                img["data_uri"] = f"data:{mime_type};base64,{b64_data}"
                processed_images.append(img)
            except: pass

        # 3. GENERATION
        # Use Gemini to generate answer based on context
        system_instruction = f"""Jesteś ArcusAI, profesjonalnym asystentem IT i ekspertem systemów Comarch (Optima, XL).
Twoim zadaniem jest udzielanie konkretnych, merytorycznych odpowiedzi na podstawie dostarczonej Bazy Wiedzy.

ZASADY ODPOWIADANIA:
1. Skup się wyłącznie na faktach zawartych w kontekście. Jeśli w kontekście jest kod SQL lub ścieżka w programie - podaj je dokładnie w blokach kodu.
2. Formatuje odpowiedź w sposób przejrzysty: używaj nagłówków (##), list punktowych i pogrubień.
3. Bądź zwięzły i konkretny. Nie lej wody. Odpowiadaj w stylu "Standardowej odpowiedzi AI" (jak ChatGPT/Gemini).
4. Jeśli informacje są niepełne, otwarcie o tym poinformuj i zasugeruj kontakt z serwisem, ale wykorzystaj wszelkie dostępne poszlaki.
"""
        
        generation_config = {
            # 0.0 = sztywne fakty, 1.0 = duża kreatywność. Dla systemów IT zalecane 0.1 - 0.3.
            "temperature": 0.2, 
            
            # Prawdopodobieństwo skumulowane - model wybiera słowa, których suma prawdopodobieństwa wynosi X.
            "top_p": 0.95,
            
            # Liczba najbardziej prawdopodobnych słów branych pod uwagę przy generowaniu.
            "top_k": 40,
            
            # Maksymalna długość odpowiedzi (limit tokenów). Zapobiega zbyt długim wypracowaniom.
            "max_output_tokens": 2048, 
            

            "stop_sequences": [] 
        }

        try:
            model = genai.GenerativeModel(
                model_name='gemini-2.5-flash',
                system_instruction=system_instruction
            )
            response = model.generate_content(
                parts if len(parts) > 1 else prompt_with_history,
                generation_config=generation_config
            )
        except Exception as gen_err:
            print(f"[AI] Błąd generowania (próba uproszczona): {gen_err}")
            model = genai.GenerativeModel('gemini-2.5-flash')
            response = model.generate_content(prompt_with_history)
        
        answer = response.text
        
        # Replace markers with Data URIs in the answer
        for img in processed_images:
            placeholder = f"[IMAGE_REF_{img['id']}]"
            if placeholder in answer:
                answer = answer.replace(placeholder, f"![Obraz {img['id']}]({img['data_uri']})")
        
        # Clean up any leftover markers
        answer = re.sub(r'\[IMAGE_REF_\d+\]', '', answer)
        
        # Save to DB
        import json
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        if not conv_id:
            title = latest_msg[:50] + "..." if len(latest_msg) > 50 else latest_msg
            cursor.execute("INSERT INTO conversations (user_id, title) VALUES (?, ?)", (user_id, title))
            conv_id = cursor.lastrowid
            
        cursor.execute("INSERT INTO messages (conversation_id, role, content, sources) VALUES (?, ?, ?, ?)",
                       (conv_id, "user", latest_msg, "[]"))
        cursor.execute("INSERT INTO messages (conversation_id, role, content, sources) VALUES (?, ?, ?, ?)",
                       (conv_id, "ai", answer, json.dumps(sources)))
        conn.commit()
        conn.close()

        # Usunięcie duplikatów ze źródeł (słowniki nie są hashable, więc nie używamy set())
        unique_sources = []
        seen_urls = set()
        for s in sources:
            if isinstance(s, dict) and s.get('url'):
                if s['url'] not in seen_urls:
                    unique_sources.append(s)
                    seen_urls.add(s['url'])
            elif s not in unique_sources: # Fallback dla starych stringów
                unique_sources.append(s)

        return {"answer": answer, "sources": unique_sources, "conversation_id": conv_id}
    except Exception as e:
        print(f"!!! Error in query: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Błąd AI: {str(e)}")

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
        
        # BookStack Integration
        if bookstack:
            try:
                # Find the 'pliki' book ID
                book_id = bookstack.get_book_id_by_name("pliki")
                if book_id:
                    # 1. Create a page with the filename as title (content empty)
                    page_res = bookstack.create_page(book_id, original_filename, "")
                    page_id = page_res.get("id")
                    
                    # 2. Upload the file as an attachment
                    bookstack.upload_attachment(page_id, file_path, original_filename)
                    print(f"[TASK] Plik '{original_filename}' dodany do BookStack (Page ID: {page_id})")
                else:
                    print(f"WARNING: Book 'pliki' not found in BookStack!")
            except Exception as be_err:
                print(f"ERROR: Failed to upload to BookStack: {str(be_err)}")

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
                model = genai.GenerativeModel('models/gemini-2.5-flash')
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
