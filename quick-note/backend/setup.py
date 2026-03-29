import os
import sqlite3
import bcrypt
from dotenv import load_dotenv, set_key

def get_password_hash(password: str):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def setup():
    print("=== ArcusAI Setup Wizard ===")
    
    # Load current .env if exists
    if os.path.exists(".env"):
        load_dotenv(".env")
        print("Wykryto istniejący plik .env. Sugerujemy aktualne wartości jako domyślne.")
    else:
        # Create empty .env if not exists
        with open(".env", "a"): pass

    def get_input(prompt, env_key, default=""):
        env_val = os.getenv(env_key, default)
        result = input(f"{prompt} (obecnie: {env_val}): ").strip()
        if not result:
            return env_val
        return result

    # 1. API Keys and Credentials
    api_key = get_input("Podaj swój GEMINI_API_KEY", "GEMINI_API_KEY")
    bs_url = get_input("Podaj URL BookStack (np. http://192.168.13.12)", "BOOKSTACK_URL", "http://192.168.13.12")
    bs_token_id = get_input("Podaj BookStack TOKEN_ID", "BOOKSTACK_TOKEN_ID")
    bs_token_secret = get_input("Podaj BookStack TOKEN_SECRET", "BOOKSTACK_TOKEN_SECRET")
    
    # Save to .env (use set_key to preserve other variables)
    set_key(".env", "GEMINI_API_KEY", api_key)
    set_key(".env", "BOOKSTACK_URL", bs_url)
    set_key(".env", "BOOKSTACK_TOKEN_ID", bs_token_id)
    set_key(".env", "BOOKSTACK_TOKEN_SECRET", bs_token_secret)
    
    if not os.getenv("SECRET_KEY"):
        set_key(".env", "SECRET_KEY", os.urandom(24).hex())

    # 2. Admin Credentials
    print("\n--- Konfiguracja użytkownika Admin w bazie danych ---")
    admin_user = input("Podaj nazwę użytkownika (domyślnie: Admin): ").strip() or "Admin"
    admin_pass = input("Podaj nowe hasło dla Admina (lub naciśnij Enter, aby pominąć): ").strip()
    
    if admin_pass:
        db_path = "database.sqlite"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Ensure tables exist
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
            cursor.execute("INSERT OR REPLACE INTO users (username, password_hash, role) VALUES (?, ?, ?)", 
                        (admin_user, hashed_pass, "admin"))
            conn.commit()
            print(f"Użytkownik {admin_user} został skonfigurowany.")
        except Exception as e:
            print(f"Błąd bazy danych: {e}")
        
        conn.close()
    
    print("\nKonfiguracja .env zakończona pomyślnie.")

if __name__ == "__main__":
    setup()
