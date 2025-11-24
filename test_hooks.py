#!/usr/bin/env python3
"""
Test script to verify hooks are working correctly.
Simulates Claude Code hook invocations by passing JSON to stdin.
"""
import json
import subprocess
import sys
from pathlib import Path

def test_hook(hook_path, test_input):
    """Test a hook by passing JSON input and checking output."""
    print(f"\n{'='*60}")
    print(f"Testing: {hook_path}")
    print(f"{'='*60}")

    try:
        result = subprocess.run(
            ["python", hook_path],
            input=json.dumps(test_input),
            capture_output=True,
            text=True,
            timeout=5
        )

        print(f"Exit Code: {result.returncode}")

        if result.stdout:
            print(f"\nStdout:")
            print(result.stdout)

        if result.stderr:
            print(f"\nStderr:")
            print(result.stderr)

        if result.returncode == 0:
            print("[OK] Hook executed successfully")
            return True
        else:
            print(f"[ERROR] Hook failed with exit code {result.returncode}")
            return False

    except subprocess.TimeoutExpired:
        print("[ERROR] Hook timed out")
        return False
    except Exception as e:
        print(f"[ERROR] Failed to execute hook: {e}")
        return False

def main():
    print("="*60)
    print("Claude Hooks System - Hook Testing")
    print("="*60)

    # Test data simulating Claude Code hook input
    test_data = {
        "hook_event_name": "PostToolUse",
        "session_id": "test-session-123",
        "tool_name": "Bash",
        "tool_use_id": "tool-456",
        "cwd": str(Path.cwd()),
        "permission_mode": "ask"
    }

    mcp_test_data = {
        "hook_event_name": "PostToolUse",
        "session_id": "test-session-123",
        "tool_name": "mcp_test_tool",
        "tool_use_id": "tool-789",
        "cwd": str(Path.cwd()),
        "permission_mode": "ask",
        "tool_parameters": {"param1": "value1"}
    }

    session_test_data = {
        "hook_event_name": "SessionStart",
        "session_id": "test-session-123",
        "cwd": str(Path.cwd())
    }

    # Run tests
    results = []

    print("\n[1/3] Testing session_start.py...")
    results.append(test_hook("hooks/session_start.py", session_test_data))

    print("\n[2/3] Testing zo_report_event.py...")
    results.append(test_hook("hooks/zo_report_event.py", test_data))

    print("\n[3/3] Testing mcp_telemetry.py...")
    results.append(test_hook("hooks/mcp_telemetry.py", mcp_test_data))

    # Summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    total = len(results)
    passed = sum(results)
    failed = total - passed

    print(f"Total: {total} | Passed: {passed} | Failed: {failed}")

    if failed == 0:
        print("\n[SUCCESS] All hooks are working!")
        print("\nNext steps:")
        print("1. Your hooks are now registered in .claude/settings.json")
        print("2. The bridge server is running on http://localhost:9000")
        print("3. Hooks will automatically fire when you use Claude Code")
        print("4. Check logs at: %USERPROFILE%\\.zo\\claude-events\\")
    else:
        print(f"\n[WARNING] {failed} hook(s) failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
