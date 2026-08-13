import os
import hashlib
import requests
import threading
import http.server
import socketserver
import tempfile
import time
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from typing import List, Dict
from .decorators import register_skill

@register_skill
def scrape_and_download_files(urls: List[str], save_dir: str = None) -> Dict[str, dict]:
    """
    Scrape main text and download specific types of files from a list of URLs.
    
    Args:
        urls (List[str]): A list of webpage URLs to scrape.
        save_dir (str): The directory where extracted text and files will be saved.
        
    Returns:
        dict: A dictionary mapping each URL to its saved text path and downloaded file paths.
              Format: { 'url': {'text_path': '...', 'files': ['...', ...]} }
    """
    if not save_dir:
        save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
    os.makedirs(save_dir, exist_ok=True)
    
    target_extensions = {'.pdf', '.png', '.jpg', '.jpeg', '.zip'}
    results = {}
    
    # Common headers to prevent basic blocks from websites
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    for url in urls:
        url_results = {"text_path": None, "files": []}
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
        except Exception as e:
            print(f"Failed to fetch webpage {url}: {e}")
            results[url] = url_results
            continue

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. Extract and save main text
        body = soup.body if soup.body else soup
        # Get text, strip whitespaces and use newlines as separator
        text_content = body.get_text(separator='\n', strip=True)
        
        # Use a short hash to avoid filesystem invalid characters and collisions
        url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:8]
        text_filename = f"{url_hash}_content.txt"
        text_path = os.path.join(save_dir, text_filename)
        
        try:
            with open(text_path, 'w', encoding='utf-8') as f:
                f.write(text_content)
            url_results["text_path"] = text_path
        except Exception as e:
            print(f"Failed to save text for {url}: {e}")

        # 2. Extract specific file links
        file_urls = set()
        
        # Check all <a> tags for target file links (e.g., pdf, zip)
        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href')
            if not href:
                continue
            parsed = urlparse(href)
            ext = os.path.splitext(parsed.path)[1].lower()
            if ext in target_extensions:
                file_urls.add(urljoin(url, href))
                
        # Check all <img> tags for target images (e.g., png, jpg)
        for img_tag in soup.find_all('img', src=True):
            src = img_tag.get('src')
            if not src:
                continue
            parsed = urlparse(src)
            ext = os.path.splitext(parsed.path)[1].lower()
            if ext in target_extensions:
                file_urls.add(urljoin(url, src))

        # 3. Download the files
        for file_url in file_urls:
            try:
                file_resp = requests.get(file_url, headers=headers, stream=True, timeout=15)
                file_resp.raise_for_status()
                
                parsed_file_url = urlparse(file_url)
                original_filename = os.path.basename(parsed_file_url.path)
                if not original_filename:
                    original_filename = "downloaded_file"
                    
                # Prefix with hash to avoid overwriting files with the same name from different pages
                safe_filename = f"{url_hash}_{original_filename}"
                file_path = os.path.join(save_dir, safe_filename)
                
                with open(file_path, 'wb') as f:
                    for chunk in file_resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            
                url_results["files"].append(file_path)
            except Exception as e:
                print(f"Failed to download {file_url}: {e}")
                
        results[url] = url_results
        
    return results

def run_tests():
    # 1. Create a temporary directory to act as the web server's document root
    server_dir = tempfile.TemporaryDirectory()
    
    # 2. Create dummy files to serve
    index_html_path = os.path.join(server_dir.name, "index.html")
    with open(index_html_path, "w", encoding="utf-8") as f:
        f.write("""
        <!DOCTYPE html>
        <html>
        <head><title>Test Page</title></head>
        <body>
            <h1>Welcome to the test page</h1>
            <p>This is some main content text.</p>
            <a href="document.pdf">Download PDF here</a>
            <img src="picture.png" alt="A test picture" />
            <a href="archive.zip">Download ZIP</a>
            <a href="https://nonexistent.domain/broken.jpg">Broken link</a>
        </body>
        </html>
        """)
        
    # Dummy PDF
    with open(os.path.join(server_dir.name, "document.pdf"), "wb") as f:
        f.write(b"%PDF-1.4 dummy pdf content")
        
    # Dummy PNG
    with open(os.path.join(server_dir.name, "picture.png"), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n dummy image content")
        
    # Dummy ZIP
    with open(os.path.join(server_dir.name, "archive.zip"), "wb") as f:
        f.write(b"PK\x03\x04 dummy zip content")

    # 3. Setup a local HTTP Server in a background thread
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=server_dir.name, **kwargs)
        def log_message(self, format, *args):
            pass  # Suppress server logs

    httpd = socketserver.TCPServer(("127.0.0.1", 0), QuietHandler)
    port = httpd.server_address[1]
    
    server_thread = threading.Thread(target=httpd.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    # 4. Prepare execution variables
    save_dir = tempfile.TemporaryDirectory()
    test_url = f"http://127.0.0.1:{port}/index.html"
    
    print(f"Testing URL: {test_url}")
    print(f"Save Directory: {save_dir.name}")
    
    try:
        # 5. Call the function
        results = scrape_and_download_files([test_url], save_dir.name)
        
        # 6. Verify assertions
        assert test_url in results, "URL not found in results."
        
        result_data = results[test_url]
        assert result_data["text_path"] is not None, "Text path should not be None."
        assert len(result_data["files"]) == 3, f"Expected 3 downloaded files, got {len(result_data['files'])}."
        
        # Check text file content
        with open(result_data["text_path"], "r", encoding="utf-8") as f:
            text_content = f.read()
            assert "Welcome to the test page" in text_content, "Text content missing heading."
            assert "This is some main content text." in text_content, "Text content missing paragraph."
            
        # Check downloaded files exist physically
        for file_path in result_data["files"]:
            assert os.path.exists(file_path), f"File {file_path} was not created."
            assert os.path.getsize(file_path) > 0, f"File {file_path} is empty."
            
        print("All tests passed successfully!")
        
    finally:
        # 7. Cleanup
        httpd.shutdown()
        httpd.server_close()
        server_dir.cleanup()
        save_dir.cleanup()

if __name__ == "__main__":
    run_tests()