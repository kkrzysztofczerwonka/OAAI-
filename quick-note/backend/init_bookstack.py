import os
from dotenv import load_dotenv
from bookstack_service import BookStackService
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BookStackInit")

def initialize_structure():
    load_dotenv()
    
    bookstack_url = os.getenv("BOOKSTACK_URL", "http://192.168.13.12")
    token_id = os.getenv("BOOKSTACK_TOKEN_ID")
    token_secret = os.getenv("BOOKSTACK_TOKEN_SECRET")

    if not all([token_id, token_secret]):
        logger.error("Błąd: BOOKSTACK_TOKEN_ID lub BOOKSTACK_TOKEN_SECRET nie są ustawione w .env!")
        return

    # Initialize Service
    service = BookStackService(bookstack_url, token_id, token_secret)

    try:
        # 1. Create Shelf: ai-test
        logger.info("Sprawdzanie półki: 'ai-test'")
        shelf = service.create_shelf("ai-test", "Główna półka dla AI")
        shelf_id = shelf.get("id")
        logger.info(f"Półka 'ai-test' (ID: {shelf_id}) została znaleziona lub utworzona.")

        # 2. Create Books: pliki, notatki
        logger.info("Sprawdzanie książki: 'pliki'")
        book_pliki = service.create_book("pliki", shelf_id, "Książka na przesłane pliki")
        logger.info(f"Książka 'pliki' (ID: {book_pliki.get('id')}) została znaleziona lub utworzona.")

        logger.info("Sprawdzanie książki: 'notatki'")
        book_notatki = service.create_book("notatki", shelf_id, "Książka na notatki")
        logger.info(f"Książka 'notatki' (ID: {book_notatki.get('id')}) została znaleziona lub utworzona.")

        logger.info("--- Inicjalizacja BookStack zakończona pomyślnie ---")
        
    except Exception as e:
        logger.error(f"Błąd podczas inicjalizacji BookStack: {str(e)}")

if __name__ == "__main__":
    initialize_structure()
