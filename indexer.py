import os
import sys
import json
from pypdf import PdfReader

def index_pdfs():
    # Paths relative to the script directory
    base_dir = os.path.dirname(os.path.abspath(__file__))
    kb_dir = os.path.join(base_dir, "knowledge_base")
    output_file = os.path.join(base_dir, "indexed_knowledge.json")
    
    print(f"=== AstroVeda PDF Indexer ===")
    print(f"Scanning directory: {kb_dir}")
    
    if not os.path.exists(kb_dir):
        print(f"Error: 'knowledge_base' directory does not exist at {kb_dir}!")
        sys.exit(1)
        
    pdf_files = [f for f in os.listdir(kb_dir) if f.endswith(".pdf")]
    if not pdf_files:
        print(f"No PDF files found in {kb_dir}.")
        # Write an empty list to output_file
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump([], f)
        print(f"Created empty index file: {output_file}")
        return
        
    print(f"Found {len(pdf_files)} PDF books to process.")
    
    indexed_books = []
    for idx, filename in enumerate(pdf_files, 1):
        file_path = os.path.join(kb_dir, filename)
        book_name = filename.replace(".pdf", "")
        print(f"\n[{idx}/{len(pdf_files)}] Parsing '{filename}'...")
        
        try:
            reader = PdfReader(file_path)
            pages_data = []
            for page_idx, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                text = text.strip()
                if not text:
                    continue
                
                # Chunk page text to 250 chars with 50 char overlap
                chunk_size = 250
                overlap = 50
                start = 0
                while start < len(text):
                    end = start + chunk_size
                    chunk = text[start:end]
                    pages_data.append({
                        "page_number": page_idx,
                        "text": chunk.strip()
                    })
                    if end >= len(text):
                        break
                    start += chunk_size - overlap
            
            indexed_books.append({
                "book": book_name,
                "pages": pages_data
            })
            print(f" -> Success! Parsed {len(pages_data)} pages.")
        except Exception as e:
            print(f" -> Error parsing '{filename}': {e}")
            
    # Save structured index to JSON file
    print(f"\nSaving index to {output_file}...")
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(indexed_books, f, indent=2, ensure_ascii=False)
        print("=== Indexing Completed Successfully! ===")
    except Exception as e:
        print(f"Error saving indexed_knowledge.json: {e}")
        sys.exit(1)

if __name__ == "__main__":
    index_pdfs()
