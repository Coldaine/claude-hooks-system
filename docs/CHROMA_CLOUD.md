# Configuring Chroma Cloud for Claude Hooks System

This guide explains how to connect your Claude hooks system to Chroma Cloud for remote event storage.

## Why Use Chroma Cloud?

### Chroma Cloud is Good For:

1. **Semantic Search Over Events**
   - Query events by meaning, not just keywords
   - Example: "Show me authentication failures" finds all related auth issues
   - Uses vector embeddings to find semantically similar events

2. **Distributed Event Collection**
   - Multiple VMs send events to one centralized database
   - No need to manage infrastructure or backups
   - Automatic scaling and SOC 2 compliance

3. **Advanced Querying**
   - Combine metadata filters + semantic search
   - Example: Find errors in run `abc123` similar to "database timeout"
   - Fast time-range queries across millions of events

4. **Built-in Deduplication**
   - Hash-based idempotency prevents duplicate events
   - Important when hooks retry on network failures

5. **Partitioned Collections**
   - `events`: Full event log (90-day retention)
   - `artifacts`: File catalog with hash dedup (365-day retention)
   - `embeddings`: Semantic search index for key event types
   - `agent_state`: Latest worker status (upsert semantics)

### When You DON'T Need Chroma Cloud:

- Single developer testing locally
- Only need simple JSONL audit trails
- Low-scale operations (manually reviewing logs)

---

## Step 1: Get Your Chroma Cloud Credentials

1. **Sign in** to Chroma Cloud at https://trychroma.com

2. **Find your credentials** in the dashboard:
   - **Tenant ID**: Your account identifier (e.g., `pmaclyman`)
   - **Database Name**: The database you created (e.g., `ClaudeCallHome`)
   - **API Key**: Authentication token (looks like `chroma_api_xxxxxxxxxxxxxxxx`)

   Look for these in:
   - Dashboard → Settings → API Keys
   - Or Database → Connection Details

---

## Step 2: Configure the Bridge Server

### Option A: Environment Variables (Recommended)

Create a `.env` file in the project root:

```bash
# Enable Chroma Cloud mode
USE_CHROMA_CLOUD=true

# Your Chroma Cloud credentials
CHROMA_API_KEY=chroma_api_xxxxxxxxxxxxxxxx
CHROMA_TENANT=pmaclyman
CHROMA_DATABASE=ClaudeCallHome

# Bridge server settings
CHROMA_BRIDGE_PORT=9000

# Optional: Require X-API-Key header on ingest requests
ZO_API_KEY=your_secret_key_here
```

### Option B: Direct Export (Testing)

```bash
export USE_CHROMA_CLOUD=true
export CHROMA_API_KEY=chroma_api_xxxxxxxxxxxxxxxx
export CHROMA_TENANT=pmaclyman
export CHROMA_DATABASE=ClaudeCallHome

python chroma_bridge_server_v2.py
```

---

## Step 3: Install Dependencies

Make sure you have the ChromaDB Python client installed:

```bash
pip install chromadb
```

For Chroma Cloud specifically, you may need:

```bash
pip install chromadb-client
```

---

## Step 4: Start the Bridge Server

```bash
python chroma_bridge_server_v2.py
```

You should see:

```
Starting Chroma Bridge Server v2.0
Mode: Chroma Cloud
  Tenant: pmaclyman
  Database: ClaudeCallHome
Port: 9000
Auth: Enabled (or Disabled)
Collections: ['events', 'artifacts', 'embeddings', 'agent_state']
Max payload: 10MB

✓ Chroma Bridge Server running on http://localhost:9000
  Endpoints:
    POST /ingest - Ingest events
    GET  /query?collection=events&run_id=... - Query events
    GET  /health - Health check
    GET  /metrics - Prometheus metrics
```

---

## Step 5: Configure Hooks to Send Events

On machines running Claude Code, set the endpoint:

```bash
# Point hooks to your bridge server
export ZO_EVENT_ENDPOINT=http://localhost:9000/ingest

# Optional: Set API key if bridge requires authentication
export ZO_API_KEY=your_secret_key_here
```

For remote access (bridge on different machine):

```bash
export ZO_EVENT_ENDPOINT=https://your-bridge-domain.com/ingest
```

---

## Step 6: Test the Connection

### Health Check

```bash
curl http://localhost:9000/health
```

Expected response:

```json
{
  "status": "healthy",
  "timestamp": "2025-11-24T12:00:00Z",
  "collections": {
    "events": 0,
    "artifacts": 0,
    "embeddings": 0,
    "agent_state": 0
  }
}
```

### Send Test Event

```bash
curl -X POST http://localhost:9000/ingest \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_secret_key_here" \
  -d '{
    "event_id": "test-123",
    "ts": "2025-11-24T12:00:00Z",
    "session_id": "test-session",
    "run_id": "test-run",
    "event_type": "progress",
    "level": "info",
    "msg": "Test event from curl",
    "schema_version": "1.0"
  }'
```

Expected response:

```json
{
  "status": "success",
  "event_id": "test-123",
  "collections_updated": ["events"],
  "latency_ms": 45.23
}
```

### Verify in Chroma Cloud

Check your Chroma Cloud dashboard to see the event stored in the `events` collection.

---

## Architecture: Local vs Cloud

### Local Mode (Default)

```
Claude Hooks → Bridge Server → Local SQLite DB (./chroma_db/)
```

- Events stored on same machine as bridge
- Fast, no network latency
- Limited to single machine's disk space

### Cloud Mode

```
Claude Hooks → Bridge Server → Chroma Cloud API (api.trychroma.com)
                                     ↓
                              Cloud Vector Database
                              (Managed, Scalable)
```

- Events stored in Chroma Cloud
- Accessible from anywhere
- Automatic backups and scaling
- Slight network latency (~50-100ms per event)

---

## Querying Events

### Query by Metadata

```bash
# Get all errors in a specific run
curl "http://localhost:9000/query?collection=events&run_id=abc123&event_type=error&limit=10"
```

### Semantic Search

```bash
# Find events semantically similar to "database connection failed"
curl "http://localhost:9000/query?collection=embeddings&q=database%20connection%20failed&limit=5"
```

### Query by Worker

```bash
# Get latest state for all workers in a run
curl "http://localhost:9000/query?collection=agent_state&run_id=abc123"
```

---

## Troubleshooting

### Error: "ValueError: USE_CHROMA_CLOUD=true requires CHROMA_TENANT, CHROMA_DATABASE, and CHROMA_API_KEY"

**Solution**: Ensure all three environment variables are set:

```bash
export CHROMA_API_KEY=your_key
export CHROMA_TENANT=your_tenant
export CHROMA_DATABASE=your_database
```

### Error: "Connection refused" or "Timeout"

**Possible causes**:
1. Invalid credentials (check API key, tenant, database name)
2. Network firewall blocking `api.trychroma.com`
3. Chroma Cloud service outage (check status page)

**Solution**: Test connection directly:

```python
import chromadb

client = chromadb.CloudClient(
    tenant="your_tenant",
    database="your_database",
    api_key="your_api_key"
)

# Try to list collections
collections = client.list_collections()
print(f"Connected! Collections: {[c.name for c in collections]}")
```

### Events Not Appearing in Cloud

**Check**:
1. Bridge server logs for errors: `python chroma_bridge_server_v2.py` (watch output)
2. Health endpoint: `curl http://localhost:9000/health`
3. Metrics: `curl http://localhost:9000/metrics` (check `chroma_bridge_ingests_total`)

---

## Cost Considerations

Chroma Cloud pricing (as of 2025):
- **Free tier**: Limited storage and queries (good for testing)
- **Paid tiers**: Based on storage GB and queries per month

**Optimization tips**:
1. Set appropriate retention policies (90 days for events, 365 for artifacts)
2. Only embed semantic-searchable events (decisions, errors, key milestones)
3. Use local JSONL fallback for non-critical logging

---

## Security Best Practices

1. **Never commit `.env` to git**: Already in `.gitignore`
2. **Use API key authentication**: Set `ZO_API_KEY` on bridge to require `X-API-Key` header
3. **Enable redaction**: Ensure `ZO_REDACTION_MODE=strict` to remove PII/secrets
4. **Use HTTPS for remote bridges**: Deploy behind nginx with TLS (see `DEPLOYMENT.md`)
5. **Rotate API keys regularly**: Generate new keys in Chroma Cloud dashboard

---

## Next Steps

- [Read the full schema documentation](schema.md)
- [Deploy hooks to Linux VMs](DEPLOYMENT.md)
- [Review security considerations](SECURITY.md)
- [Explore Windows deployment options](WINDOWS_DEPLOYMENT.md)

---

## References

- [Chroma Cloud Documentation](https://docs.trychroma.com/cloud/getting-started)
- [ChromaDB Python Client Reference](https://docs.trychroma.com/reference/python/client)
- [Chroma Clients Guide](https://cookbook.chromadb.dev/core/clients/)
