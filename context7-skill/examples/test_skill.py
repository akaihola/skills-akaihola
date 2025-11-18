#!/usr/bin/env python3
"""
Test script for generated skill
"""

import json
import subprocess
import sys


def run_command(cmd):
    """Run a command and return the result."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr}"


def main():
    """Test the generated skill."""
    print("Testing generated skill...")

    # Test listing tools
    print("\n1. Listing available tools:")
    tools_output = run_command([sys.executable, "executor.py", "--list"])
    print(tools_output)

    # Parse tools
    try:
        tools = json.loads(tools_output)
        if tools and len(tools) > 0:
            first_tool = tools[0]["name"]

            # Test describing a tool
            print(f"\n2. Describing tool: {first_tool}")
            describe_output = run_command([sys.executable, "executor.py", "--describe", first_tool])
            print(describe_output)
        else:
            print("No tools found to test")
    except json.JSONDecodeError:
        print("Could not parse tools list")

    print("\nTest complete")


if __name__ == "__main__":
    main()
