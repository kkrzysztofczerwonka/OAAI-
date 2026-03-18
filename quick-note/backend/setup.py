import os
import sqlite3
import bcrypt
from dotenv import load_dotenv

def get_password_hash(password: str):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def setup():
    print("=== ArcusAI Setup Wizard ===")
    
    # 1. API Key
    api_key = input("Podaj swój GEMINI_API_KEY: ").strip()
    
    # 2. Admin Credentials
    admin_user = input("Podaj nazwę użytkownika Admina (domyślnie: Admin): ").strip() or "Admin"
    admin_pass = input("Podaj hasło dla Admina: ").strip()
    
    if not admin_pass:
        print("Błąd: Hasło nie może być puste!")
        return

    # Create .env
    with open(".env", "w") as f:
        f.write(f"GEMINI_API_KEY={api_key}\n")
        f.write(f"SECRET_KEY={os.urandom(24).hex()}\n")
    
    print("Plik .env został wygenerowany.")

    # Initialize DB and create Admin
    db_path = "database.sqlite"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Ensure tables exist (redundant with main.py but good for setup)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    hashed_pass = get_password_hash(admin_pass)
    try:
        cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", 
                       (admin_user, hashed_pass, "admin"))
        conn.commit()
        print(f"Użytkownik {admin_user} został utworzony pomyślnie.")
    except sqlite3.IntegrityError:
        print(f"Użytkownik {admin_user} już istnieje. Hasło nie zostało zmienione.")
    
    conn.close()
    print("\nKonfiguracja zakończona! Możesz teraz uruchomić serwer.")

if __name__ == "__main__":
    setup()
