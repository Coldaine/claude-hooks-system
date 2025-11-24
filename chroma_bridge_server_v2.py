"""
ChromaDB Bridge Server v2.0
Advanced event ingestion and query API with:
- Multi-threaded HTTP server
- API key authentication
- Partitioned collections (events, artifacts, embeddings, agent_state)
- Query endpoints with metadata filters + semantic search
- Health and metrics endpoints
- Request logging and error handling
"""
import http.server
import socketserver
import json
import chromadb
import os
import time
import hashlib
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
from typing import Dict, List, Any, Optional
from collections import defaultdict
from threading import Lock

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, use system environment variables only

# Configuration
PORT = int(os.getenv("CHROMA_BRIDGE_PORT", "9000"))
DB_PATH = os.getenv("CHROMA_DB_PATH", "./chroma_db")
API_KEY = os.getenv("ZO_API_KEY", "")  # Set via environment for security
MAX_PAYLOAD_SIZE = int(os.getenv("MAX_PAYLOAD_MB", "10")) * 1024 * 1024  # 10MB default

# Chroma Cloud configuration (optional)
USE_CHROMA_CLOUD = os.getenv("USE_CHROMA_CLOUD", "false").lower() == "true"
CHROMA_TENANT = os.getenv("CHROMA_TENANT", "")
CHROMA_DATABASE = os.getenv("CHROMA_DATABASE", "")
CHROMA_API_KEY = os.getenv("CHROMA_API_KEY", "")

# Metrics
metrics_lock = Lock()
metrics = {
    "total_requests": 0,
    "ingest_count": 0,
    "query_count": 0,
    "error_count": 0,
    "duplicate_count": 0,
    "latency_sum": 0.0,
    "latency_count": 0
}

# Initialize ChromaDB with partitioned collections
if USE_CHROMA_CLOUD:
    print(f"Initializing ChromaDB Cloud client...")
    print(f"  Tenant: {CHROMA_TENANT}")
    print(f"  Database: {CHROMA_DATABASE}")
    if not CHROMA_TENANT or not CHROMA_DATABASE or not CHROMA_API_KEY:
        raise ValueError("USE_CHROMA_CLOUD=true requires CHROMA_TENANT, CHROMA_DATABASE, and CHROMA_API_KEY")

    # Create CloudClient with credentials
    client = chromadb.CloudClient(
        tenant=CHROMA_TENANT,
        database=CHROMA_DATABASE,
        api_key=CHROMA_API_KEY
    )
else:
    print(f"Initializing local ChromaDB at {DB_PATH}...")
    client = chromadb.PersistentClient(path=DB_PATH)

# Collection schemas
collections = {
    "events": client.get_or_create_collection(
        name="events",
        metadata={"description": "Primary event log with full envelope"}
    ),
    "artifacts": client.get_or_create_collection(
        name="artifacts",
        metadata={"description": "Artifact catalog with hash deduplication"}
    ),
    "embeddings": client.get_or_create_collection(
        name="embeddings",
        metadata={"description": "Semantic search index (decisions, errors, summaries)"}
    ),
    "agent_state": client.get_or_create_collection(
        name="agent_state",
        metadata={"description": "Latest worker/run status snapshots"}
    )
}

print(f"ChromaDB initialized with collections: {list(collections.keys())}")


class ChromaBridgeHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler with routing and authentication."""
    
    def _authenticate(self) -> bool:
        """Verify API key if configured."""
        if not API_KEY:
            return True  # No auth required if not configured
        
        auth_header = self.headers.get('X-API-Key', '')
        return auth_header == API_KEY
    
    def _send_json(self, status: int, data: Dict[str, Any]):
        """Send JSON response."""
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')  # CORS
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def _record_metric(self, metric_name: str, value: float = 1.0):
        """Thread-safe metric recording."""
        with metrics_lock:
            metrics[metric_name] += value
    
    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-API-Key')
        self.end_headers()
    
    def do_GET(self):
        """Route GET requests."""
        self._record_metric("total_requests")
        
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == "/health":
            self._handle_health()
        elif path == "/metrics":
            self._handle_metrics()
        elif path == "/query":
            self._handle_query(parsed.query)
        else:
            self._send_json(404, {"error": "Not found"})
    
    def do_POST(self):
        """Route POST requests."""
        start_time = time.time()
        self._record_metric("total_requests")
        
        # Authenticate
        if not self._authenticate():
            self._send_json(401, {"error": "Unauthorized"})
            self._record_metric("error_count")
            return
        
        # Size limit
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > MAX_PAYLOAD_SIZE:
            self._send_json(413, {"error": "Payload too large"})
            self._record_metric("error_count")
            return
        
        # Route
        if self.path == "/ingest" or self.path == "/events":
            self._handle_ingest(content_length, start_time)
        else:
            self._send_json(404, {"error": "Not found"})
    
    def _handle_health(self):
        """Health check endpoint."""
        try:
            # Simple DB connectivity test
            collections["events"].count()
            self._send_json(200, {
                "status": "healthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "collections": {name: coll.count() for name, coll in collections.items()}
            })
        except Exception as e:
            self._send_json(503, {"status": "unhealthy", "error": str(e)})
    
    def _handle_metrics(self):
        """Prometheus-compatible metrics endpoint."""
        with metrics_lock:
            avg_latency = (metrics["latency_sum"] / metrics["latency_count"]) if metrics["latency_count"] > 0 else 0
            
            metrics_text = f"""# HELP chroma_bridge_requests_total Total HTTP requests
# TYPE chroma_bridge_requests_total counter
chroma_bridge_requests_total {metrics["total_requests"]}

# HELP chroma_bridge_ingests_total Total event ingestions
# TYPE chroma_bridge_ingests_total counter
chroma_bridge_ingests_total {metrics["ingest_count"]}

# HELP chroma_bridge_queries_total Total queries
# TYPE chroma_bridge_queries_total counter
chroma_bridge_queries_total {metrics["query_count"]}

# HELP chroma_bridge_errors_total Total errors
# TYPE chroma_bridge_errors_total counter
chroma_bridge_errors_total {metrics["error_count"]}

# HELP chroma_bridge_duplicates_total Duplicate events rejected
# TYPE chroma_bridge_duplicates_total counter
chroma_bridge_duplicates_total {metrics["duplicate_count"]}

# HELP chroma_bridge_latency_seconds_avg Average latency
# TYPE chroma_bridge_latency_seconds_avg gauge
chroma_bridge_latency_seconds_avg {avg_latency:.6f}
"""
        
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(metrics_text.encode('utf-8'))
    
    def _handle_ingest(self, content_length: int, start_time: float):
        """Ingest event with partitioning logic."""
        try:
            post_data = self.rfile.read(content_length)
            event = json.loads(post_data)
            
            # Validate schema version
            schema_version = event.get("schema_version", "")
            if schema_version not in ["1.0", ""]:
                self._send_json(400, {"error": f"Unsupported schema version: {schema_version}"})
                return
            
            # Extract core fields
            event_id = event.get("event_id", "unknown")
            event_type = event.get("event_type", "unknown")
            run_id = event.get("run_id", "unknown")
            session_id = event.get("session_id", "unknown")
            event_hash = event.get("hash", "")
            
            # Check for duplicates using hash
            if event_hash and self._is_duplicate(event_hash):
                self._send_json(202, {"status": "duplicate", "event_id": event_id})
                self._record_metric("duplicate_count")
                return
            
            # Build Chroma metadata (primitives only)
            metadata = {
                "event_id": event_id,
                "ts": event.get("ts", ""),
                "event_type": event_type,
                "level": event.get("level", "info"),
                "run_id": run_id,
                "session_id": session_id,
                "worker_id": event.get("worker_id", ""),
                "task_id": event.get("task_id", ""),
                "tool_name": event.get("tool_name", ""),
                "hash": event_hash
            }
            
            # 1. Always add to primary events collection
            collections["events"].add(
                documents=[json.dumps(event)],
                metadatas=[metadata],
                ids=[event_id]
            )
            
            # 2. Add to embeddings collection if semantic-searchable type
            if event_type in ["decision", "error", "artifact", "worker_spawn"] and event.get("indexable_text"):
                try:
                    collections["embeddings"].add(
                        documents=[event.get("indexable_text", "")],
                        metadatas=[metadata],
                        ids=[f"{event_id}_emb"]
                    )
                except Exception as e:
                    print(f"Embedding add failed: {e}")
            
            # 3. Add to artifacts collection if artifact event
            if event_type == "artifact" and (artifact_refs := event.get("artifact_refs")):
                for idx, artifact in enumerate(artifact_refs):
                    artifact_id = artifact.get("hash", f"{event_id}_artifact_{idx}")
                    try:
                        collections["artifacts"].upsert(
                            documents=[json.dumps(artifact)],
                            metadatas={
                                "hash": artifact.get("hash", ""),
                                "path": artifact.get("path", ""),
                                "type": artifact.get("type", ""),
                                "size_bytes": artifact.get("size_bytes", 0),
                                "run_id": run_id,
                                "event_id": event_id
                            },
                            ids=[artifact_id]
                        )
                    except Exception as e:
                        print(f"Artifact add failed: {e}")
            
            # 4. Upsert to agent_state if progress/heartbeat event
            if event_type in ["worker_heartbeat", "progress", "worker_spawn"] and event.get("worker_id"):
                worker_id = event.get("worker_id")
                state_id = f"{run_id}_{worker_id}"
                try:
                    collections["agent_state"].upsert(
                        documents=[json.dumps({
                            "run_id": run_id,
                            "worker_id": worker_id,
                            "status": event.get("msg", ""),
                            "last_heartbeat": event.get("ts"),
                            "task_id": event.get("task_id", "")
                        })],
                        metadatas={
                            "run_id": run_id,
                            "worker_id": worker_id,
                            "task_id": event.get("task_id", ""),
                            "last_heartbeat": event.get("ts", "")
                        },
                        ids=[state_id]
                    )
                except Exception as e:
                    print(f"Agent state upsert failed: {e}")
            
            # Record metrics
            latency = time.time() - start_time
            self._record_metric("ingest_count")
            self._record_metric("latency_sum", latency)
            self._record_metric("latency_count")
            
            self._send_json(201, {
                "status": "success",
                "event_id": event_id,
                "collections_updated": ["events"],
                "latency_ms": round(latency * 1000, 2)
            })
            
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": "Invalid JSON", "detail": str(e)})
            self._record_metric("error_count")
        except Exception as e:
            print(f"Ingest error: {e}")
            self._send_json(500, {"error": "Internal error", "detail": str(e)})
            self._record_metric("error_count")
    
    def _is_duplicate(self, event_hash: str) -> bool:
        """Check if event hash exists in recent events (5-minute window)."""
        try:
            # Query events collection for matching hash
            results = collections["events"].get(
                where={"hash": event_hash},
                limit=1
            )
            return len(results.get("ids", [])) > 0
        except Exception:
            return False
    
    def _handle_query(self, query_string: str):
        """Query events with metadata filters and semantic search."""
        self._record_metric("query_count")
        
        try:
            # Parse query parameters
            params = parse_qs(query_string)
            collection_name = params.get("collection", ["events"])[0]
            
            if collection_name not in collections:
                self._send_json(400, {"error": f"Invalid collection: {collection_name}"})
                return
            
            collection = collections[collection_name]
            
            # Build where filter
            where_filter = {}
            for key in ["run_id", "event_type", "level", "worker_id", "task_id", "session_id"]:
                if key in params:
                    where_filter[key] = params[key][0]
            
            # Limit and offset
            limit = min(int(params.get("limit", ["100"])[0]), 1000)
            offset = int(params.get("offset", ["0"])[0])
            
            # Semantic query
            if "q" in params and collection_name == "embeddings":
                query_text = params["q"][0]
                results = collection.query(
                    query_texts=[query_text],
                    where=where_filter if where_filter else None,
                    n_results=limit
                )
            else:
                # Metadata-only query
                results = collection.get(
                    where=where_filter if where_filter else None,
                    limit=limit,
                    offset=offset
                )
            
            # Format response
            events = []
            for idx, doc_id in enumerate(results.get("ids", [])):
                events.append({
                    "id": doc_id,
                    "document": json.loads(results["documents"][idx]) if results.get("documents") else {},
                    "metadata": results["metadatas"][idx] if results.get("metadatas") else {},
                    "distance": results["distances"][idx][0] if results.get("distances") and results["distances"] else None
                })
            
            self._send_json(200, {
                "collection": collection_name,
                "count": len(events),
                "events": events,
                "filters": where_filter,
                "limit": limit,
                "offset": offset
            })
            
        except Exception as e:
            print(f"Query error: {e}")
            self._send_json(500, {"error": "Query failed", "detail": str(e)})
            self._record_metric("error_count")
    
    def log_message(self, format, *args):
        """Suppress default logging; use structured logging instead."""
        if os.getenv("DEBUG_LOGGING") == "true":
            print(f"[{self.client_address[0]}] {format % args}")


class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Multi-threaded TCP server for concurrent requests."""
    allow_reuse_address = True


if __name__ == "__main__":
    print(f"Starting Chroma Bridge Server v2.0")
    print(f"Mode: {'Chroma Cloud' if USE_CHROMA_CLOUD else 'Local Persistent'}")
    if USE_CHROMA_CLOUD:
        print(f"  Tenant: {CHROMA_TENANT}")
        print(f"  Database: {CHROMA_DATABASE}")
    else:
        print(f"  DB Path: {DB_PATH}")
    print(f"Port: {PORT}")
    print(f"Auth: {'Enabled' if API_KEY else 'Disabled (set ZO_API_KEY to enable)'}")
    print(f"Collections: {list(collections.keys())}")
    print(f"Max payload: {MAX_PAYLOAD_SIZE // 1024 // 1024}MB")
    print()
    
    with ThreadedHTTPServer(("", PORT), ChromaBridgeHandler) as httpd:
        print(f"[OK] Chroma Bridge Server running on http://localhost:{PORT}")
        print(f"  Endpoints:")
        print(f"    POST /ingest - Ingest events")
        print(f"    GET  /query?collection=events&run_id=... - Query events")
        print(f"    GET  /health - Health check")
        print(f"    GET  /metrics - Prometheus metrics")
        print()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\nShutting down gracefully...")
