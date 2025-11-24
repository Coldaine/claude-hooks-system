#!/usr/bin/env python3
"""
Shared utilities for Claude Code event envelope construction, redaction, and hashing.
Provides canonical schema v1.0 compliance for all hook scripts.
"""
import os
import re
import uuid
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


SCHEMA_VERSION = "1.0"

# Event type enumeration
EVENT_TYPES = {
    "session_start", "session_end", "worker_spawn", "worker_heartbeat",
    "progress", "artifact", "error", "tool_invocation", "decision", "done"
}

LEVELS = {"debug", "info", "warn", "error"}
AGENT_ROLES = {"conductor", "worker", "system"}


def generate_event_id() -> str:
    """Generate unique event ID (UUID v4)."""
    return str(uuid.uuid4())


def generate_run_id() -> str:
    """Generate unique run ID (UUID v4) for orchestration session."""
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    """Return current UTC timestamp in RFC3339 format."""
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def hash_content(data: Dict[str, Any], fields: Optional[List[str]] = None) -> str:
    """
    Generate SHA256 hash of event content for deduplication.
    
    Args:
        data: Event data dictionary
        fields: Optional list of fields to include in hash (default: session_id, ts, event_type, data)
    
    Returns:
        Hex-encoded SHA256 hash
    """
    if fields is None:
        fields = ["session_id", "ts", "event_type", "data"]
    
    hash_input = {k: data.get(k) for k in fields if k in data}
    canonical = json.dumps(hash_input, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def sanitize_hostname() -> str:
    """Return sanitized hostname (hashed with prefix)."""
    try:
        import platform
        hostname = platform.node() or os.environ.get('COMPUTERNAME', 'unknown')
        
        # Hash with salt for privacy
        salt = os.environ.get('HOSTNAME_SALT', 'default_salt')
        hashed = hashlib.sha256(f"{salt}:{hostname}".encode()).hexdigest()[:12]
        return f"host_{hashed}"
    except Exception:
        return "host_unknown"


def redact_payload(data: Dict[str, Any], mode: str = "strict") -> Dict[str, Any]:
    """
    Apply redaction rules to event payload.
    
    Args:
        data: Event data to redact (modified in-place)
        mode: Redaction mode - "strict" | "lenient" | "disabled"
    
    Returns:
        Redacted data dict with redaction metadata
    """
    if mode == "disabled":
        return data
    
    rules_applied = []
    
    # Redaction patterns
    patterns = {
        "email": (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]'),
        "api_key": (r'\b(sk|pk|ck|ghp|gho|glpat)[-_][A-Za-z0-9]{20,}\b', '[REDACTED_KEY]'),
        "bearer_token": (r'\bBearer\s+[A-Za-z0-9\-._~+/]+={0,2}\b', 'Bearer [REDACTED_TOKEN]'),
        "jwt": (r'\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b', '[REDACTED_JWT]'),
        "ip_address": (r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '[IP]'),
    }
    
    def redact_string(text: str) -> str:
        """Apply redaction patterns to string."""
        if not isinstance(text, str):
            return text
        
        modified = text
        for rule_name, (pattern, replacement) in patterns.items():
            if re.search(pattern, modified):
                modified = re.sub(pattern, replacement, modified)
                if rule_name not in rules_applied:
                    rules_applied.append(rule_name)
        
        return modified
    
    def redact_recursive(obj: Any) -> Any:
        """Recursively redact strings in nested structures."""
        if isinstance(obj, dict):
            return {k: redact_recursive(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [redact_recursive(item) for item in obj]
        elif isinstance(obj, str):
            return redact_string(obj)
        else:
            return obj
    
    # Apply recursive redaction
    redacted_data = redact_recursive(data.copy())
    
    # Add redaction metadata
    if rules_applied:
        redacted_data['redaction'] = {
            'applied': True,
            'rules': rules_applied,
            'mode': mode
        }
    
    return redacted_data


def redact_filepath(path: str) -> str:
    """
    Redact sensitive portions of file paths (user home directory).
    
    Args:
        path: File path to sanitize
    
    Returns:
        Redacted path
    """
    if not path:
        return path
    
    # Redact user home directory
    home = os.path.expanduser('~')
    if path.startswith(home):
        path = path.replace(home, '~', 1)
    
    # Redact Windows user paths
    if os.name == 'nt':
        path = re.sub(r'C:\\Users\\[^\\]+', r'C:\\Users\\[USER]', path)
    
    return path


def extract_indexable_text(event: Dict[str, Any], max_chars: int = 2000) -> str:
    """
    Extract plain text suitable for embedding/semantic search.
    
    Args:
        event: Event envelope
        max_chars: Maximum characters to extract
    
    Returns:
        Plain text summary
    """
    parts = []
    
    # Core message
    if msg := event.get('msg'):
        parts.append(msg)
    
    # Event type and tool context
    event_type = event.get('event_type', '')
    tool_name = event.get('tool_name', '')
    if tool_name:
        parts.append(f"Tool: {tool_name}")
    
    # Task and worker context
    if task_id := event.get('task_id'):
        parts.append(f"Task: {task_id}")
    if worker_id := event.get('worker_id'):
        parts.append(f"Worker: {worker_id}")
    
    # Decision/error details
    if event_type == 'decision' and (data := event.get('data')):
        if reasoning := data.get('reasoning'):
            parts.append(f"Reasoning: {reasoning}")
    
    if event_type == 'error' and (error_detail := event.get('error_detail')):
        parts.append(f"Error: {error_detail.get('message', '')}")
    
    # Artifact references
    if artifact_refs := event.get('artifact_refs'):
        artifact_names = [ref.get('path', '') for ref in artifact_refs[:3]]
        if artifact_names:
            parts.append(f"Artifacts: {', '.join(artifact_names)}")
    
    # Join and truncate
    text = " | ".join(filter(None, parts))
    return text[:max_chars] if len(text) > max_chars else text


def build_event_envelope(
    event_type: str,
    session_id: str,
    run_id: Optional[str] = None,
    level: str = "info",
    hook_event_name: Optional[str] = None,
    msg: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    agent_role: Optional[str] = None,
    worker_id: Optional[str] = None,
    task_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    tool_use_id: Optional[str] = None,
    artifact_refs: Optional[List[Dict[str, Any]]] = None,
    parent_event_id: Optional[str] = None,
    error_detail: Optional[Dict[str, Any]] = None,
    cwd: Optional[str] = None,
    redaction_mode: str = "strict"
) -> Dict[str, Any]:
    """
    Build canonical event envelope conforming to schema v1.0.
    
    Args:
        event_type: Event type enum value
        session_id: Claude session ID
        run_id: Orchestration run ID (generated if not provided)
        level: Severity level (debug|info|warn|error)
        hook_event_name: Original hook name
        msg: Human-readable summary
        data: Structured payload (will be redacted)
        agent_role: conductor|worker|system
        worker_id: Worker instance ID
        task_id: Task identifier
        tool_name: Tool invoked
        tool_use_id: Tool execution ID
        artifact_refs: List of artifact references
        parent_event_id: Causal link
        error_detail: Error metadata
        cwd: Working directory
        redaction_mode: strict|lenient|disabled
    
    Returns:
        Complete event envelope
    """
    # Validate required fields
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Invalid event_type: {event_type}. Must be one of {EVENT_TYPES}")
    
    if level not in LEVELS:
        raise ValueError(f"Invalid level: {level}. Must be one of {LEVELS}")
    
    if agent_role and agent_role not in AGENT_ROLES:
        raise ValueError(f"Invalid agent_role: {agent_role}. Must be one of {AGENT_ROLES}")
    
    # Generate core IDs
    event_id = generate_event_id()
    ts = utc_now_iso()
    if not run_id:
        run_id = generate_run_id()
    
    # Build source metadata
    source = {
        "host": sanitize_hostname(),
        "remote": os.getenv("CLAUDE_CODE_REMOTE") == "true",
        "cwd": redact_filepath(cwd or os.getcwd()),
        "project_dir": os.getenv("CLAUDE_PROJECT_DIR", "unknown")
    }
    
    # Build base envelope
    envelope = {
        "event_id": event_id,
        "ts": ts,
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "run_id": run_id,
        "event_type": event_type,
        "level": level,
        "source": source
    }
    
    # Add optional fields
    if hook_event_name:
        envelope["hook_event_name"] = hook_event_name
    if msg:
        envelope["msg"] = msg[:500]  # Truncate to max length
    if agent_role:
        envelope["agent_role"] = agent_role
    if worker_id:
        envelope["worker_id"] = worker_id
    if task_id:
        envelope["task_id"] = task_id
    if tool_name:
        envelope["tool_name"] = tool_name
    if tool_use_id:
        envelope["tool_use_id"] = tool_use_id
    if artifact_refs:
        envelope["artifact_refs"] = artifact_refs
    if parent_event_id:
        envelope["parent_event_id"] = parent_event_id
    if error_detail:
        envelope["error_detail"] = error_detail
    
    # Apply redaction to data payload
    if data:
        envelope["data"] = redact_payload(data, mode=redaction_mode)
    
    # Generate content hash
    envelope["hash"] = hash_content(envelope)
    
    # Extract indexable text
    envelope["indexable_text"] = extract_indexable_text(envelope)
    
    return envelope


def get_run_id_from_env_or_generate() -> str:
    """
    Get run_id from environment or generate new one.
    Allows Conductor to set RUN_ID env var for spawned workers.
    """
    return os.getenv("CLAUDE_RUN_ID") or generate_run_id()


# Chroma Cloud direct connection
_chroma_client = None
_chroma_collection = None


def get_chroma_collection(collection_name: str = "events"):
    """
    Get or create a Chroma Cloud collection for direct event storage.

    Requires environment variables:
        CHROMA_API_KEY: Chroma Cloud API key
        CHROMA_TENANT: Chroma Cloud tenant ID
        CHROMA_DATABASE: Chroma Cloud database name

    Returns:
        ChromaDB collection or None if not configured/available
    """
    global _chroma_client, _chroma_collection

    # Return cached collection if available
    if _chroma_collection is not None:
        return _chroma_collection

    # Check for required environment variables
    api_key = os.getenv("CHROMA_API_KEY")
    tenant = os.getenv("CHROMA_TENANT")
    database = os.getenv("CHROMA_DATABASE", "ClaudeCallHome")

    if not api_key or not tenant:
        return None

    try:
        import chromadb

        if _chroma_client is None:
            _chroma_client = chromadb.CloudClient(
                tenant=tenant,
                database=database,
                api_key=api_key
            )

        _chroma_collection = _chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"description": "Claude Code event log"}
        )
        return _chroma_collection

    except ImportError:
        return None
    except Exception as e:
        import sys
        print(f"[chroma] connection error: {e}", file=sys.stderr)
        return None


def send_event_to_chroma(event: Dict[str, Any], collection_name: str = "events") -> bool:
    """
    Send an event directly to Chroma Cloud.

    Args:
        event: Event envelope dictionary
        collection_name: Target collection name

    Returns:
        True if sent successfully, False otherwise
    """
    collection = get_chroma_collection(collection_name)
    if collection is None:
        return False

    try:
        # Build metadata for filtering
        metadata = {
            "event_id": event.get("event_id", ""),
            "session_id": event.get("session_id", ""),
            "run_id": event.get("run_id", ""),
            "event_type": event.get("event_type", ""),
            "level": event.get("level", ""),
            "ts": event.get("ts", ""),
            "tool_name": event.get("tool_name", ""),
            "worker_id": event.get("worker_id", ""),
            "task_id": event.get("task_id", ""),
            "hash": event.get("hash", "")
        }
        # Remove empty values (Chroma doesn't like None/empty)
        metadata = {k: v for k, v in metadata.items() if v}

        collection.add(
            ids=[event["event_id"]],
            documents=[json.dumps(event, ensure_ascii=False)],
            metadatas=[metadata]
        )
        return True

    except Exception as e:
        import sys
        print(f"[chroma] send error: {e}", file=sys.stderr)
        return False
