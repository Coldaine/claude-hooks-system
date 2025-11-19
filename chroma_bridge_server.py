import http.server
import socketserver
import json
import chromadb
import uuid
from datetime import datetime

PORT = 9000
DB_PATH = "./chroma_db"
COLLECTION_NAME = "claude_events"

print(f"Initializing ChromaDB at {DB_PATH}...")
client = chromadb.PersistentClient(path=DB_PATH)
collection = client.get_or_create_collection(name=COLLECTION_NAME)
print(f"ChromaDB initialized. Collection: {COLLECTION_NAME}")

class ChromaBridgeHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            
            data = json.loads(post_data)
            
            # Extract metadata fields matching zo_report_event.py
            # Chroma metadata values must be primitives (str, int, float, bool)
            metadata = {
                "timestamp": data.get("ts", datetime.now().isoformat()),
                "session_id": data.get("session_id", "unknown"),
                "hook_event": data.get("hook_event_name", "unknown"),
                "tool_name": str(data.get("tool_name", "") or ""),
                "cwd": str(data.get("cwd", "") or "")
            }
            
            # Use the full JSON as the document content for retrieval
            document_content = json.dumps(data)
            
            # Generate a unique ID for the event
            doc_id = str(uuid.uuid4())
            
            # Add to Chroma
            collection.add(
                documents=[document_content],
                metadatas=[metadata],
                ids=[doc_id]
            )
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success", "id": doc_id}).encode('utf-8'))
            # print(f"Indexed event: {metadata['hook_event']}")
            
        except Exception as e:
            print(f"Error processing request: {e}")
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            error_msg = json.dumps({"status": "error", "message": str(e)})
            self.wfile.write(error_msg.encode('utf-8'))

    def log_message(self, format, *args):
        return # Suppress default logging to keep console clean

if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), ChromaBridgeHandler) as httpd:
        print(f"Chroma Bridge Server running on http://localhost:{PORT}")
        httpd.serve_forever()
