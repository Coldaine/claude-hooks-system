#!/usr/bin/env python3
"""
Quick test script to verify Chroma Cloud connection.
Run this before starting the bridge server to ensure credentials work.
"""
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

print("=" * 60)
print("Testing Chroma Cloud Connection")
print("=" * 60)

# Get credentials from environment
api_key = os.getenv("CHROMA_API_KEY")
tenant = os.getenv("CHROMA_TENANT")
database = os.getenv("CHROMA_DATABASE")

print(f"\nCredentials loaded:")
print(f"  API Key: {api_key[:20]}..." if api_key else "  API Key: NOT SET")
print(f"  Tenant: {tenant}")
print(f"  Database: {database}")

if not all([api_key, tenant, database]):
    print("\n[ERROR]: Missing credentials in .env file")
    print("   Please ensure CHROMA_API_KEY, CHROMA_TENANT, and CHROMA_DATABASE are set")
    exit(1)

print("\nAttempting to connect to Chroma Cloud...")

try:
    import chromadb

    # Create CloudClient
    client = chromadb.CloudClient(
        api_key=api_key,
        tenant=tenant,
        database=database
    )

    print("[OK] Connection successful!\n")

    # List existing collections
    print("Listing collections...")
    collections = client.list_collections()

    if collections:
        print(f"Found {len(collections)} existing collection(s):")
        for coll in collections:
            count = coll.count()
            print(f"  - {coll.name}: {count} documents")
    else:
        print("  No collections found (database is empty)")

    # Test creating a collection
    print("\nTesting collection creation...")
    test_collection = client.get_or_create_collection(
        name="test_connection",
        metadata={"description": "Test collection from connection script"}
    )
    print(f"[OK] Test collection '{test_collection.name}' created/retrieved")

    # Test adding a document
    print("\nTesting document insertion...")
    test_collection.add(
        documents=["This is a test document"],
        metadatas=[{"source": "connection_test"}],
        ids=["test-doc-1"]
    )
    print(f"[OK] Test document added successfully")

    # Verify count
    count = test_collection.count()
    print(f"   Collection now has {count} document(s)")

    # Clean up test collection
    print("\nCleaning up test collection...")
    client.delete_collection("test_connection")
    print("[OK] Test collection deleted")

    print("\n" + "=" * 60)
    print("SUCCESS! Chroma Cloud connection is working!")
    print("=" * 60)
    print("\nYou're ready to start the bridge server:")
    print("  python chroma_bridge_server_v2.py")
    print()

except ImportError:
    print("\n[ERROR]: chromadb package not installed")
    print("   Install it with: pip install chromadb")
    exit(1)

except Exception as e:
    print(f"\n❌ ERROR: Connection failed")
    print(f"   {type(e).__name__}: {e}")
    print("\nTroubleshooting:")
    print("  1. Verify your credentials are correct in .env")
    print("  2. Check if you can access api.trychroma.com")
    print("  3. Ensure your API key has not expired")
    exit(1)
