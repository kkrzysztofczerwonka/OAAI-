# ArcusAI - Notatki i Asystent Wiedzy

Inteligentny system do zarządzania notatkami oraz baza wiedzy oparta na AI (Gemini Flash), która pozwala na czatowanie z dokumentacją i własnymi plikami.

---

## 📂 Struktura Projektu

- `/backend` - Serwer FastAPI (Python), baza wektorowa Chromadb i obsługa AI.
- `/src` - Frontend w React (Vite).
- `/src-tauri` - Konfiguracja Tauri (Rust) do generowania aplikacji desktopowej.

---

## 🛠 Instalacja Backend (Serwer Linux/Ubuntu)

Aby zainstalować system na serwerze i ustawić go jako autostartującą usługę:

1. Przejdź do katalogu `backend`:
   ```bash
   cd backend
   ```
2. Nadaj uprawnienia skryptowi instalacyjnemu:
   ```bash
   chmod +x install_server.sh
   ```
3. Uruchom skrypt (zapyta o klucz API i dane Admina):
   ```bash
   ./install_server.sh
   ```

Skrypt automatycznie:
- Stworzy wirtualne środowisko Python.
- Zainstaluje zależności.
- Skonfiguruje użytkownika Admin i klucz GEMINI_API_KEY.
- Utworzy usługę `systemd` (serwer wstanie sam po restarcie maszyny).

---

## 🧪 Uruchamianie Lokalne (Windows)

1. **Backend**:
   ```powershell
   cd backend
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   python setup.py  # Skonfiguruj klucz i admina
   python main.py
   ```

2. **Frontend (Tauri dev)**:
   ```powershell
   npm install
   npm run tauri dev
   ```

---

## 🖥 Kompilacja Aplikacji Desktop (.exe)

Aby zbudować gotową paczkę instalacyjną Windows:

1. Upewnij się, że masz zainstalowane [Rust i WebView2](https://tauri.app/v1/guides/getting-started/prerequisites).
2. Wygeneruj paczkę:
   ```powershell
   npm run tauri build
   ```
3. Gotowy instalator `.msi` oraz plik `.exe` znajdziesz w:
   `src-tauri\target\release\bundle\msi\quick-note_X.X.X_x64_en-US.msi`

---

## ✨ Kluczowe Funkcje
- **Chat w dymkach**: Profesjonalna stylizacja (Biało-czarny dla użytkownika, szary dla AI).
- **Kompaktowe odpowiedzi**: Minimalne odstępy między akapitami (3px) dla lepszej czytelności.
- **Wgrywanie plików**: Obsługa PDF, Docx, SQL, CS, Python (baza wektorowa).
- **Zapisywanie Notatek**: Edytor bogaty w funkcje (Tiptap) z obsługą obrazów ze schowka.
- **Bezpieczeństwo**: System logowania z hashowaniem haseł (Bcrypt) i tokenami JWT.

---

## 🔒 Dane Logowania
Podstawowe dane logowania są ustalane podczas pierwszego uruchomienia skryptu `setup.py`. Domyślna rola to `admin`, dająca dostęp do statystyk zapytań i notatek wszystkich użytkowników.
