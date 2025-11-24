# Security & Privacy Guide

## Overview

The Claude Code Hooks System handles potentially sensitive data from development sessions. This guide outlines security controls, redaction strategies, threat model, and operational best practices.

## Threat Model

### Assets

1. **Event Data**: Session transcripts, prompts, tool parameters, error messages
2. **Code Artifacts**: File paths, code snippets, commit messages
3. **System Metadata**: Hostnames, working directories, usernames
4. **API Credentials**: Bridge API keys, MCP credentials
5. **ChromaDB Contents**: Persistent event log with full execution history

### Threats

| Threat | Impact | Mitigation |
|--------|--------|------------|
| **API Key Leakage** | Unauthorized bridge access | Environment variables, `.env` gitignored, rotation |
| **PII Exposure** | Privacy violation | Redaction layer, strict mode by default |
| **Prompt Injection Persistence** | Malicious events stored | Input validation, schema enforcement |
| **Local Log Access** | Unauthorized read of JSONL logs | File permissions (700), encryption at rest |
| **Network Eavesdropping** | Event interception | HTTPS/TLS for remote bridge, local-only default |
| **ChromaDB Tampering** | Event log corruption | DB path permissions, backup strategy |
| **Secret Embedding** | Accidental credential commit | Pre-commit hooks, secret scanning |

### Attack Scenarios

#### Scenario 1: Malicious Hook Replacement

**Attack**: Attacker replaces hook script with backdoored version.

**Mitigations**:
- File integrity checks (hash verification)
- Read-only hook directory (Windows: `icacls /inheritance:r`)
- Code signing (future: GPG signatures on hook-pack releases)

#### Scenario 2: Prompt Injection

**Attack**: User pastes malicious prompt containing secrets; Claude logs to ChromaDB.

**Mitigations**:
- Redaction rules scan for API key patterns before persistence
- Prompt truncation (max 1000 chars in `data.prompt`)
- Manual review of high-risk events (level=error)

#### Scenario 3: Bridge Spoofing

**Attack**: Malicious server impersonates bridge, captures events.

**Mitigations**:
- API key authentication (bi-directional trust)
- HTTPS certificate validation
- Allowlist of bridge endpoints (future: mTLS)

## Redaction System

### Redaction Modes

| Mode | Level | Use Case |
|------|-------|----------|
| **strict** | High | Production, team environments |
| **lenient** | Medium | Personal dev (basic PII only) |
| **disabled** | None | Debug/testing (NEVER in production) |

**Configuration**:
```env
ZO_REDACTION_MODE=strict  # Default
```

### Redaction Rules (strict mode)

#### 1. Email Addresses

**Pattern**: `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b`

**Replacement**: `[EMAIL]`

**Example**:
```
Before: "Contact alice@example.com for access"
After:  "Contact [EMAIL] for access"
```

#### 2. API Keys & Tokens

**Patterns**:
- OpenAI: `sk-[A-Za-z0-9]{48}`
- Anthropic: `sk-ant-[A-Za-z0-9\-]{48,}`
- GitHub: `ghp_[A-Za-z0-9]{36}` (PAT), `gho_[A-Za-z0-9]{36}` (OAuth)
- Generic: `(sk|pk|ck)[-_][A-Za-z0-9]{20,}`
- Bearer tokens: `Bearer\s+[A-Za-z0-9\-._~+/]+={0,2}`

**Replacement**: `[REDACTED_KEY]` or `Bearer [REDACTED_TOKEN]`

**Example**:
```json
{
  "tool_parameters": {
    "api_key": "[REDACTED_KEY]"
  }
}
```

#### 3. JWT Tokens

**Pattern**: `\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b`

**Replacement**: `[REDACTED_JWT]`

#### 4. IP Addresses

**Pattern**: `\b(?:\d{1,3}\.){3}\d{1,3}\b`

**Replacement**: `[IP]`

**Note**: Does not redact private ranges (192.168.x.x, 10.x.x.x) in lenient mode.

#### 5. File Paths

**Strategy**: Redact user home directory.

**Windows**:
```
C:\Users\alice\projects\app → C:\Users\[USER]\projects\app
```

**Unix**:
```
/home/alice/projects/app → ~/projects/app
```

#### 6. Hostnames

**Strategy**: Salted hash with prefix.

```python
salt = os.getenv("HOSTNAME_SALT", "default_salt")
hashed = hashlib.sha256(f"{salt}:{hostname}".encode()).hexdigest()[:12]
return f"host_{hashed}"  # e.g., host_a3f9c8b12e04
```

**Environment Variable**:
```env
HOSTNAME_SALT=your-random-salt-value
```

**Benefits**:
- Consistent hashing within deployment (correlation)
- No reverse lookup (privacy)
- Configurable via salt rotation

### Custom Redaction

**Extend** `event_utils.redact_payload()`:

```python
# hooks/event_utils.py
def redact_payload(data: Dict[str, Any], mode: str = "strict") -> Dict[str, Any]:
    # ... existing rules ...
    
    # Custom: Redact Slack webhook URLs
    patterns["slack_webhook"] = (
        r'https://hooks\.slack\.com/services/[A-Z0-9/]+',
        '[SLACK_WEBHOOK]'
    )
    
    # Custom: Redact database connection strings
    patterns["db_conn"] = (
        r'postgresql://[^@]+@[^/]+/\w+',
        'postgresql://[REDACTED]@[REDACTED]/[REDACTED]'
    )
    
    # ... apply patterns ...
```

### Redaction Metadata

Events include `redaction` field documenting applied rules:

```json
{
  "event_id": "...",
  "data": { "sanitized": "content" },
  "redaction": {
    "applied": true,
    "rules": ["email", "api_key", "hostname"],
    "mode": "strict"
  }
}
```

**Use Cases**:
- Audit trail (what was redacted)
- Debug (verify redaction worked)
- Compliance reporting

## Authentication & Authorization

### Bridge API Key

**Setup**:

```powershell
# Bridge server
$env:ZO_API_KEY = "$(openssl rand -hex 32)"  # Generate secure key
python chroma_bridge_server_v2.py

# Hooks (auto-detected)
$env:ZO_API_KEY = "same-key-as-server"
```

**Header Format**:
```http
POST /ingest HTTP/1.1
Host: localhost:9000
Content-Type: application/json
X-API-Key: your-secret-key-here

{"event_id": "..."}
```

**Key Rotation**:

```powershell
# Generate new key
$NewKey = openssl rand -hex 32

# Update bridge server (rolling restart)
$env:ZO_API_KEY = $NewKey
Restart-Service chroma-bridge

# Update all repositories
echo "ZO_API_KEY=$NewKey" | Out-File -Append .env
```

### Future: HMAC Signatures

**Proposal** (not yet implemented):

```python
# Hook signs event
import hmac, hashlib, time

timestamp = str(int(time.time()))
payload = json.dumps(event)
signature = hmac.new(
    API_KEY.encode(),
    f"{timestamp}.{payload}".encode(),
    hashlib.sha256
).hexdigest()

headers = {
    "X-Signature": signature,
    "X-Timestamp": timestamp
}
```

**Bridge validates**:
- Timestamp within ±5 minutes (replay protection)
- Signature matches HMAC(timestamp + payload)

### Role-Based Access (Future)

**Proposal**: Multi-tenant bridge with user/project isolation.

```json
{
  "roles": {
    "admin": ["read:all", "write:all", "delete:events"],
    "developer": ["read:own", "write:events"],
    "viewer": ["read:own"]
  }
}
```

## Transport Security

### Local Deployment (Default)

**Config**: `http://localhost:9000`

**Security**: Loopback only, no network exposure.

**Use Case**: Single-user development.

### Remote Deployment

**Requirements**:
- HTTPS/TLS (certificate validation)
- Reverse proxy (nginx, Caddy)
- Network segmentation (internal VPN)

**nginx Example**:

```nginx
upstream chroma_bridge {
    server 127.0.0.1:9000;
}

server {
    listen 443 ssl http2;
    server_name chroma.internal.company.com;
    
    ssl_certificate /etc/ssl/certs/chroma.crt;
    ssl_certificate_key /etc/ssl/private/chroma.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    # Client certificate (mTLS)
    ssl_client_certificate /etc/ssl/certs/ca.crt;
    ssl_verify_client optional;
    
    location / {
        proxy_pass http://chroma_bridge;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Client-Cert $ssl_client_s_dn;
    }
}
```

**Client Config**:
```env
ZO_EVENT_ENDPOINT=https://chroma.internal.company.com/ingest
```

### Certificate Pinning (Advanced)

**Prevent MITM** with certificate fingerprint validation:

```python
# hooks/event_utils.py (future enhancement)
import ssl, hashlib

def verify_cert_fingerprint(cert, expected_sha256):
    cert_der = ssl.DER_cert_to_PEM_cert(cert)
    cert_hash = hashlib.sha256(cert_der.encode()).hexdigest()
    if cert_hash != expected_sha256:
        raise ValueError("Certificate fingerprint mismatch")

# Usage
expected_fingerprint = os.getenv("BRIDGE_CERT_SHA256")
```

## Data Retention & Cleanup

### Local JSONL Logs

**Default**: No automatic cleanup (unbounded growth).

**Manual Cleanup**:

```powershell
# Delete logs older than 30 days
$LogDir = "$env:USERPROFILE\.zo\claude-events"
Get-ChildItem $LogDir -Filter "events-*.jsonl" | 
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item
```

**Automated (Task Scheduler)**:

```powershell
# cleanup-logs.ps1
$RetentionDays = 30
$LogDir = "$env:USERPROFILE\.zo\claude-events"

Get-ChildItem $LogDir -Filter "*.jsonl" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$RetentionDays) } |
    Compress-Archive -DestinationPath "$LogDir\archive-$(Get-Date -Format 'yyyyMMdd').zip" -Update

# Delete originals after archive
Get-ChildItem $LogDir -Filter "*.jsonl" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$RetentionDays) } |
    Remove-Item
```

**Schedule**:
```powershell
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-File C:\scripts\cleanup-logs.ps1"
$Trigger = New-ScheduledTaskTrigger -Daily -At 2am
Register-ScheduledTask -TaskName "Claude Events Cleanup" -Action $Action -Trigger $Trigger
```

### ChromaDB Retention

**Collection Pruning** (manual):

```python
import chromadb
from datetime import datetime, timedelta

client = chromadb.PersistentClient(path="./chroma_db")
events = client.get_collection("events")

# Delete events older than 90 days
cutoff = (datetime.now() - timedelta(days=90)).isoformat()
old_events = events.get(where={"ts": {"$lt": cutoff}})

for event_id in old_events["ids"]:
    events.delete(ids=[event_id])
```

**Future**: Automated retention policy in bridge server (TTL per collection).

## Compliance Considerations

### GDPR (EU)

**Right to Erasure**:
- Provide script to delete all events for a `session_id` or `run_id`
- Redaction mode `strict` minimizes PII exposure

**Data Minimization**:
- Truncate prompts (max 1000 chars)
- Store hash instead of full payload for large artifacts

**Consent**:
- Document in `.env.example` that telemetry is enabled
- Provide opt-out via `ZO_EVENT_ENDPOINT=` (unset)

### SOC 2 / ISO 27001

**Access Control**:
- API key authentication
- File permissions (700 for logs, 600 for `.env`)
- Audit trail (`/metrics` logs all access)

**Encryption**:
- Transport: HTTPS/TLS
- At-rest: OS-level encryption (BitLocker, LUKS)

**Logging**:
- Bridge request logs (IP, timestamp, endpoint, status)
- Failed auth attempts tracked in metrics

## Incident Response

### Scenario: API Key Compromised

**Steps**:

1. **Rotate key immediately**:
   ```powershell
   $env:ZO_API_KEY = "$(openssl rand -hex 32)"
   ```

2. **Audit logs**:
   ```powershell
   curl "http://localhost:9000/metrics"
   # Check for unusual request patterns
   ```

3. **Revoke compromised key**:
   - Update all repositories with new key
   - Add old key to blocklist (future feature)

4. **Investigate**:
   - Review recent events for anomalies
   - Check `.git/config` for unauthorized `core.hooksPath` changes

### Scenario: Sensitive Data Exposed

**Steps**:

1. **Identify affected events**:
   ```powershell
   curl "http://localhost:9000/query?collection=events&session_id=compromised_session"
   ```

2. **Delete events**:
   ```python
   events.delete(where={"session_id": "compromised_session"})
   ```

3. **Purge local logs**:
   ```powershell
   Remove-Item ~/.zo/claude-events/events-$(Get-Date -Format 'yyyyMMdd').jsonl
   ```

4. **Strengthen redaction**:
   - Add custom pattern to `event_utils.redact_payload()`
   - Test with `ZO_REDACTION_MODE=strict`

## Security Checklist

- [ ] API key set via environment variable (not hardcoded)
- [ ] `.env` file gitignored
- [ ] Redaction mode = `strict` in production
- [ ] HTTPS/TLS for remote bridge
- [ ] File permissions: `chmod 700 ~/.zo` (Unix) or `icacls` (Windows)
- [ ] Log retention policy defined
- [ ] Certificate validation enabled
- [ ] Secrets scanning in pre-commit hooks
- [ ] API key rotation schedule (quarterly)
- [ ] Incident response plan documented
- [ ] Backup strategy for ChromaDB
- [ ] Monitoring for failed auth attempts

## Reporting Security Issues

**Do NOT open public GitHub issues for security vulnerabilities.**

**Contact**: security@yourcompany.com

**PGP Key**: [Link to public key]

**Disclosure Timeline**:
- Day 0: Report received, acknowledgment sent
- Day 7: Initial assessment, severity assigned
- Day 30: Patch developed, coordinated disclosure
- Day 90: Public disclosure (if patched)

## References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [CWE-200: Information Exposure](https://cwe.mitre.org/data/definitions/200.html)
- [GDPR Article 17: Right to Erasure](https://gdpr-info.eu/art-17-gdpr/)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)

---

**Last Updated**: 2025-11-19

**Review Schedule**: Quarterly
