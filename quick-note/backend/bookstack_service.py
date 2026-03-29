import os
import requests
from typing import Optional, Dict, List, Any
import logging

class BookStackService:
    def __init__(self, base_url: str, token_id: str, token_secret: str):
        self.base_url = base_url.rstrip('/')
        if not self.base_url.endswith('/api'):
            self.base_url = f"{self.base_url}/api"
            
        self.headers = {
            "Authorization": f"Token {token_id}:{token_secret}",
            "Accept": "application/json"
        }
        self.logger = logging.getLogger("BookStackService")

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        response = requests.get(f"{self.base_url}/{endpoint}", headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    def _post(self, endpoint: str, data: Optional[Dict] = None, files: Optional[Dict] = None) -> Dict:
        if files:
            # Multi-part form for uploads
            response = requests.post(f"{self.base_url}/{endpoint}", headers=self.headers, data=data, files=files)
        else:
            # JSON for everything else
            response = requests.post(f"{self.base_url}/{endpoint}", headers=self.headers, json=data)
        response.raise_for_status()
        return response.json()

    def list_shelves(self, filter_name: Optional[str] = None) -> List[Dict]:
        params = {}
        if filter_name:
            params["filter[name]"] = filter_name
        return self._get("shelves", params=params).get("data", [])

    def create_shelf(self, name: str, description: str = "") -> Dict:
        # Check if exists first
        existing = self.list_shelves(name)
        if existing:
            return existing[0]
        
        return self._post("shelves", data={"name": name, "description": description})

    def list_books(self, filter_name: Optional[str] = None) -> List[Dict]:
        params = {}
        if filter_name:
            params["filter[name]"] = filter_name
        return self._get("books", params=params).get("data", [])

    def create_book(self, name: str, shelf_id: int, description: str = "") -> Dict:
        # Check if exists first
        existing = self.list_books(name)
        for book in existing:
            # We assume it should be in this shelf, but BookStack list doesn't show shelf_id easily without detail call
            # For simplicity, we just return if name matches
            return book
            
        return self._post("books", data={"name": name, "shelf_id": shelf_id, "description": description})

    def list_chapters(self, book_id: Optional[int] = None, filter_name: Optional[str] = None) -> List[Dict]:
        params = {}
        if book_id:
            params["filter[book_id]"] = book_id
        if filter_name:
            params["filter[name]"] = filter_name
        return self._get("chapters", params=params).get("data", [])

    def list_pages(self, book_id: Optional[int] = None, filter_name: Optional[str] = None) -> List[Dict]:
        params = {}
        if book_id:
            params["filter[book_id]"] = book_id
        if filter_name:
            params["filter[name]"] = filter_name
        return self._get("pages", params=params).get("data", [])

    def get_page(self, page_id: int) -> Dict:
        return self._get(f"pages/{page_id}")

    def create_page(self, book_id: Optional[int] = None, chapter_id: Optional[int] = None, name: str = "", html: str = "", markdown: str = "", tags: List[Dict] = None, priority: int = 0) -> Dict:
        data = {"name": name}
        if book_id: data["book_id"] = book_id
        if chapter_id: data["chapter_id"] = chapter_id
        if html: data["html"] = html
        if markdown: data["markdown"] = markdown
        if tags: data["tags"] = tags
        if priority: data["priority"] = priority
        
        return self._post("pages", data=data)

    def upload_attachment(self, page_id: int, file_path: str, filename: str) -> Dict:
        with open(file_path, "rb") as f:
            files = {"file": (filename, f)}
            return self._post(f"attachments/upload-to-page/{page_id}", data={"name": filename}, files=files)

    def search(self, query: str) -> List[Dict]:
        """Search across all content in BookStack"""
        return self._get("search", params={"query": query}).get("data", [])

    def get_shelf_id_by_name(self, name: str) -> Optional[int]:
        shelves = self.list_shelves(name)
        # Filter for exact name match
        for s in shelves:
            if s.get("name") == name:
                return s.get("id")
        return None

    def get_book_id_by_name(self, name: str) -> Optional[int]:
        books = self.list_books(name)
        # Filter for exact name match
        for b in books:
            if b.get("name") == name:
                return b.get("id")
        return None

    def get_chapter_id_by_name(self, name: str, book_id: Optional[int] = None) -> Optional[int]:
        chapters = self.list_chapters(book_id, name)
        for c in chapters:
            if c.get("name") == name:
                return c.get("id")
        return None

    def get_global_structure(self) -> Dict[str, Any]:
        """Fetch all shelves, books, chapters and page titles to build a complete 'Knowledge Map'"""
        structure = {
            "shelves": []
        }
        
        try:
            # 1. Fetch all shelves
            shelves_data = self.list_shelves()
            
            # 2. Get detailed view for each shelf to see books
            for s in shelves_data:
                shelf_id = s.get('id')
                shelf_detail = self._get(f"shelves/{shelf_id}")
                
                shelf_books = []
                for b in shelf_detail.get('books', []):
                    book_id = b.get('id')
                    
                    # 3. Fetch chapters and ALL pages for this book
                    chapters_map = {}
                    try:
                        # Fetch chapters
                        ch_data = self.list_chapters(book_id=book_id)
                        for c in ch_data:
                            chapters_map[c['id']] = {
                                "id": c['id'],
                                "name": c['name'],
                                "pages": []
                            }
                        
                        # Fetch all pages for this book (to avoid N+1)
                        # The list_pages endpoint can be filtered by book_id
                        pages_data = self.list_pages(book_id=book_id)
                        
                        book_pages_without_chapter = []
                        for p in pages_data:
                            page_info = {"id": p['id'], "name": p['name']}
                            chap_id = p.get('chapter_id')
                            if chap_id and chap_id in chapters_map:
                                chapters_map[chap_id]["pages"].append(page_info)
                            else:
                                book_pages_without_chapter.append(page_info)
                                
                    except Exception as e:
                        print(f"Error fetching detail for book {book_id}: {e}")
                        pass
                        
                    shelf_books.append({
                        "id": book_id,
                        "name": b.get('name'),
                        "chapters": list(chapters_map.values()),
                        "pages_direct": book_pages_without_chapter
                    })

                structure["shelves"].append({
                    "id": shelf_id,
                    "name": s.get('name'),
                    "books": shelf_books
                })
                
        except Exception as e:
            print(f"Error building global structure: {e}")
            
        return structure
    def get_image_content(self, url: str) -> bytes:
        """Download an image from a full URL using service authentication"""
        response = requests.get(url, headers=self.headers, timeout=10)
        response.raise_for_status()
        return response.content
