from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
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
from bookstack_service import BookStackService

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

# Initialize ChromaDB for vector storage
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="knowledge_base")

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
            print("[SYNC] Odświeżanie mapy struktury BookStack...")
            bookstack_structure_cache = bookstack.get_global_structure()
            last_structure_update = time.time()
        except Exception as e:
            print(f"[ERROR] Nie udało się pobrać struktury: {e}")
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
            return {"text": "Nie podano zapytania."}
            
        print(f"DEBUG: Processing query: '{latest_msg}' with history of {len(req.messages)-1} msgs")
        
        # 0. Get Knowledge Map (Structure)
        knowledge_map = get_knowledge_map()
        
        context = "" # DONT initialize with map, otherwise we can't tell if we found content
        sources = []

        # 0. Agentic Step: Identify Relevant Pages
        target_page_ids = []
        if bookstack and knowledge_map:
            try:
                history_str = ""
                last_mentioned_ids = []
                for m in req.messages[:-1][-5:]:
                    role_map = {"user": "Użytkownik", "ai": "AI Assistant"}
                    history_str += f"{role_map.get(m['role'], m['role'])}: {m['content']}\n"
                    # Scan for IDs in AI responses
                    if m['role'] == 'ai':
                        found = re.findall(r'ID\s*(\d+)', m['content'])
                        for f_id in found: last_mentioned_ids.append(int(f_id))

                id_prompt = f"""Na podstawie poniższej struktury bazy wiedzy wybierz maksymalnie 4-5 ID najistotniejszych stron, które mogą zawierać odpowiedź na pytanie użytkownika.
Zwróć TYLKO same numery ID oddzielone przecinkami. Jeśli nic nie pasuje, zwróć: BRAK.

HISTORIA ROZMOWY:
{history_str}

ZASADA PRIORYTETU:
1. Jeśli użytkownik używa zaimków jak "ta strona", "ten dokument", "podaj jej treść" - wysoce prawdopodobne, że chodzi o ID wspomniane przez AI w historii ({last_mentioned_ids}). Wybierz je.
2. W pierwszej kolejności szukaj stron technicznych (notatek użytkowników), które NIE znajdują się w rozdziałach o nazwie 'dokumentacja'.
3. Jeśli nie znajdziesz nic w notatkach, poszukaj odpowiednich stron w rozdziale 'dokumentacja'. 

STRUKTURA:
{knowledge_map}

OSTATNIE PYTANIE: {latest_msg}"""
                
                id_model = genai.GenerativeModel('gemini-2.5-flash')
                id_response = id_model.generate_content(id_prompt).text.strip()
                print(f"DEBUG: Agent ID Response: {id_response}")
                
                if "BRAK" not in id_response.upper():
                    # Extract IDs from response (regex to be safe)
                    found_ids = re.findall(r'\d+', id_response)
                    target_page_ids = [int(i) for i in found_ids[:10]]
                
                # Check for pronouns in polish to resolve "this page"
                pronouns = ["tej", "tą", "tę", "tego", "ten", "treść", "szczegóły", "strony", "dokumentu", "instrukcj"]
                if any(p in latest_msg.lower() for p in pronouns) and last_mentioned_ids:
                    for l_id in set(last_mentioned_ids):
                        if l_id not in target_page_ids: 
                            target_page_ids.insert(0, l_id)

                # NEW: Direct Title Match Fallback (Very reliable)
                q_words = [w for w in re.split(r'\W+', latest_msg.lower()) if len(w) > 3]
                if bookstack_structure_cache:
                    for s in bookstack_structure_cache.get("shelves", []):
                        for b in s.get("books", []):
                            for ch in b.get("chapters", []):
                                for p in ch.get("pages", []):
                                    # If title is in query or query is in title
                                    title_clean = p["name"].lower()
                                    if title_clean in latest_msg.lower() or latest_msg.lower() in title_clean:
                                        if p["id"] not in target_page_ids:
                                            target_page_ids.append(p["id"])
                                    # Or count word matches
                                    elif sum(1 for w in q_words if w in title_clean) >= 2:
                                        if p["id"] not in target_page_ids:
                                            target_page_ids.append(p["id"])

                # Manual shortcut
                manual_ids = re.findall(r'(?i)ID\s*(\d+)', latest_msg)
                for m_id in manual_ids:
                    val = int(m_id)
                    if val not in target_page_ids: target_page_ids.append(val)
                        
                print(f"DEBUG: Final Target IDs: {target_page_ids}")
            except Exception as e:
                print(f"ERROR: Agentic ID identification failed: {e}")

        # Fetch Content from Identified Pages
        fetched_pids = []
        if target_page_ids:
            for pid in set(target_page_ids):
                try:
                    page_detail = bookstack.get_page(pid)
                    # Log fetch attempt
                    with open(os.path.join(os.path.dirname(__file__), "debug_fetch.log"), "a", encoding="utf-8") as df:
                        df.write(f"[{datetime.now()}] ID {pid} name: {page_detail.get('name')}\n")
                    
                    m_text = page_detail.get("markdown", "")
                    h_content = page_detail.get("html", "")
                    
                    # Clean HTML properly: replace structural tags with newlines first
                    clean_h = ""
                    if h_content:
                        # Replace tags that should act as newlines
                        clean_h = re.sub(r'<(p|br|li|h[1-6]|tr|div|section|article|header|footer|td)[^>]*>', '\n', h_content)
                        # Remove all other tags
                        clean_h = re.sub(r'<[^>]+>', '', clean_h)
                        # Clean up multiple newlines/whitespace
                        clean_h = re.sub(r'\n+', '\n', clean_h).strip()

                    # Use the longer content
                    final_text = m_text if len(m_text) > len(clean_h) else clean_h
                    
                    if final_text and len(final_text.strip()) > 3:
                        context += f"\n--- TREŚĆ DOKUMENTU ID {pid} ({page_detail.get('name')}) START ---\n{final_text[:20000]}\n--- TREŚĆ DOKUMENTU ID {pid} KONIEC ---\n"
                        sources.append(page_detail.get("name"))
                        fetched_pids.append(pid)
                except Exception as e:
                    print(f"ERROR fetching page {pid}: {e}")
            
            print(f"DEBUG: Pomyślnie pobrano treść dla ID: {fetched_pids}")

        # 1. Search BookStack (Primary Source)
        extracted_images = []
        if bookstack:
            # Clean query for better search results
            search_query = latest_msg
            if "?" in search_query:
                search_query = search_query.split("?")[0].strip()
            
            print(f"DEBUG: Searching BookStack with: '{search_query}'")
            results = bookstack.search(search_query)
            
            # If no results and query was long, try word search
            if not results and len(search_query.split()) > 4:
                ref_query = " ".join(search_query.split()[:4])
                print(f"DEBUG: Falling back to refined search: '{ref_query}'")
                results = bookstack.search(ref_query)

            if results:
                # Helper to determine if result is documentation
                def is_documentation(res):
                    # Check chapter or book name from structure cache if available
                    pid = res.get("id")
                    if bookstack_structure_cache:
                        for s in bookstack_structure_cache.get("shelves", []):
                            for b in s.get("books", []):
                                for ch in b.get("chapters", []):
                                    if ch["name"].lower() == "dokumentacja":
                                        for p in ch.get("pages", []):
                                            if p["id"] == pid: return True
                    return False

                # Take Top 8 results
                for res in results[:8]:
                    try:
                        if res.get("type") == "page":
                            page_detail = bookstack.get_page(res.get("id"))
                            
                            # Prefer Markdown
                            text_content = page_detail.get("markdown", "")
                            p_html = page_detail.get("html", "")

                            # Extract images
                            if p_html:
                                img_results = re.findall(r'<img[^>]+src="([^">]+)"', p_html)
                                for img_src in img_results[:3]: 
                                    if img_src not in [i["src"] for i in extracted_images]:
                                        extracted_images.append({"src": img_src, "id": len(extracted_images) + 1})
                            
                            if not text_content:
                                if p_html:
                                    p_text = re.sub(r'<(p|br|li|h[1-6]|tr|div)[^>]*>', '\n', p_html)
                                    text_content = re.sub('<[^<]+?>', '', p_text)
                                    text_content = re.sub(r'\n+', '\n', text_content).strip()
                                else:
                                    text_content = "Brak treści strony."

                            # Increase character limit to 10000 
                            snippet_limit = 10000
                            img_markers = ""
                            if p_html:
                                page_imgs = [img for img in extracted_images if img["src"] in p_html]
                                if page_imgs:
                                    img_markers = " (" + ", ".join([f"[IMAGE_REF_{img['id']}]" for img in page_imgs]) + ")"
                            
                            context += f"\n--- Dokument: {res.get('name')}{img_markers} ---\n{text_content[:snippet_limit]}\n"
                            sources.append(res.get("name"))
                    except Exception as e:
                        print(f"ERROR: Failed to process page {res.get('id')}: {e}")
                        pass
                
        # 2. Fallback to Chroma if empty and exists
        if not context:
            count = collection.count()
            if count > 0:
                embedding_model = "models/gemini-embedding-001"
                query_result = genai.embed_content(model=embedding_model, content=q, task_type="retrieval_query")
                query_embedding = query_result['embedding']
                results = collection.query(query_embeddings=[query_embedding], n_results=min(3, count))
                if results['documents'] and results['documents'][0]:
                    context = "\n".join(results['documents'][0])
                    if results.get('metadatas') and results['metadatas'][0]:
                        sources = [m.get("filename", "nieznany") for m in results['metadatas'][0]]

        if not context:
            return {"answer": "Baza wiedzy (BookStack) jest pusta lub nie znalazłem tam nic o tym.", "sources": []}

        # 3. Generate response with history
        prompt_with_history = "To jest historia konwersacji (użyj jej jako kontekstu):\n"
        # Include last 5 messages for context
        for m in req.messages[:-1][-5:]:
            role_map = {"user": "Użytkownik", "ai": "AI Assistant"}
            prompt_with_history += f"{role_map.get(m['role'], m['role'])}: {m['content']}\n"
            
        prompt_with_history += f"\nOto struktura Twojej Bazy Wiedzy (użyj jej, aby wyjaśnić gdzie leży dokument):\n{knowledge_map}\n\n"
        prompt_with_history += f"Oto TREŚĆ dokumentów/notatek z Bazy Wiedzy (użyj tego do odpowiedzi na pytanie):\n{context}\n\n"
        prompt_with_history += f"PYTANIE UŻYTKOWNIKA: {latest_msg}\n"
        prompt_with_history += "Przeanalizuj uważnie dostarczony kontekst. Jeśli zawiera on odpowiedź na pytanie użytkownika, opisz ją dokładnie. Jeśli odnosisz się do obrazka ze źródła, użyj jego znacznika [IMAGE_REF_X]. Odpowiedz profesjonalnie po polsku."

        # Support for Multimodal Gemini (sending images found in notes)
        parts = [prompt_with_history]
        
        # Add actual images as parts for Gemini to 'see'
        import base64
        import requests as req_lib # To avoid conflict with BookStack requests
        
        processed_images = []
        for img in extracted_images[:4]: 
            try:
                src = img["src"]
                mime_type = "image/png"
                if src.startswith("data:image"):
                    header, encoded = src.split(",", 1)
                    mime_type = header.split(";")[0].split(":")[1]
                    img_data = base64.b64decode(encoded)
                    b64_data = encoded
                elif src.startswith("http") and bookstack:
                    print(f"DEBUG: Downloading image for AI: {src}")
                    img_data = bookstack.get_image_content(src)
                    b64_data = base64.b64encode(img_data).decode('utf-8')
                    # Try to guess mime type from URL or default to png
                    if src.lower().endswith(".jpg") or src.lower().endswith(".jpeg"): mime_type = "image/jpeg"
                    elif src.lower().endswith(".gif"): mime_type = "image/gif"
                else:
                    continue

                parts.append({"mime_type": mime_type, "data": img_data})
                img["data_uri"] = f"data:{mime_type};base64,{b64_data}"
                processed_images.append(img)
            except Exception as e:
                print(f"ERROR processing image {img['id']}: {e}")

        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
            response = model.generate_content(parts)
        except Exception as e:
            print(f"DEBUG: Multimodal attempt failed: {e}. Falling back to text-only...")
            model = genai.GenerativeModel('gemini-2.5-flash')
            response = model.generate_content(prompt_with_history)
        
        answer = response.text
        
        # Replace placeholders with Data URI Markdown images
        for img in processed_images:
            placeholder = f"[IMAGE_REF_{img['id']}]"
            if placeholder in answer:
                answer = answer.replace(placeholder, f"![Obraz {img['id']}]({img['data_uri']})")
        
        # Fallback for any other markers the AI might have used
        answer = re.sub(r'\[IMAGE_REF_\d+\]', '', answer) # Remove leftovers
        
        # Save to DB
        import json
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        if not conv_id:
            # Create new conversation
            title = latest_msg[:50] + "..." if len(latest_msg) > 50 else latest_msg
            cursor.execute("INSERT INTO conversations (user_id, title) VALUES (?, ?)", (user_id, title))
            conv_id = cursor.lastrowid
            
        # Save User Message
        cursor.execute("INSERT INTO messages (conversation_id, role, content, sources) VALUES (?, ?, ?, ?)",
                       (conv_id, "user", latest_msg, "[]"))
        # Save AI Message
        cursor.execute("INSERT INTO messages (conversation_id, role, content, sources) VALUES (?, ?, ?, ?)",
                       (conv_id, "ai", answer, json.dumps(sources)))
        
        # Legacy log
        cursor.execute("INSERT INTO query_logs (user_id, query) VALUES (?, ?)", (user_id, latest_msg))
        
        conn.commit()
        conn.close()

        # Placeholders and image markers
        for img in extracted_images:
            real_marker = f"[IMAGE_REF_{img['id']}]"
            answer = answer.replace(real_marker, f"![Obrazek]({img['src']})")

        return {"answer": answer, "sources": list(set(sources)), "conversation_id": conv_id}
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg:
            return {"answer": "", "sources": []}
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
