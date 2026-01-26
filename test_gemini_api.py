#!/usr/bin/env python3
"""
Diagnostic script to test Gemini API connection and list available models.
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

try:
    from google import genai
    from google.genai import types
    print("✅ google-genai package imported successfully")
except ImportError as e:
    print(f"❌ Failed to import google-genai: {e}")
    exit(1)

# Get API key
api_key = os.getenv("GEMINI_API_KEY")
if not api_key or api_key == "your-api-key-here":
    print("❌ GEMINI_API_KEY not set in .env file")
    exit(1)

print(f"✅ API Key found: {api_key[:10]}...{api_key[-6:]}")

# Initialize client
try:
    client = genai.Client(api_key=api_key)
    print("✅ Gemini client initialized")
except Exception as e:
    print(f"❌ Failed to initialize client: {e}")
    exit(1)

# List available models
print("\n📋 Attempting to list available models...")
try:
    models = client.models.list()
    print(f"✅ Found {len(list(models))} models\n")
    
    for model in client.models.list():
        print(f"  • {model.name}")
        if hasattr(model, 'supported_generation_methods'):
            print(f"    Methods: {', '.join(model.supported_generation_methods)}")
        print()
except Exception as e:
    print(f"❌ Failed to list models: {e}")
    print("\nTrying alternative approach...")

# Try a simple chat request with different model names
test_models = [
    "gemini-1.5-flash",
    "gemini-1.5-pro", 
    "gemini-pro",
    "models/gemini-1.5-flash",
    "models/gemini-1.5-pro",
]

print("\n🧪 Testing different model names...")
for model_name in test_models:
    try:
        print(f"\nTesting: {model_name}")
        response = client.models.generate_content(
            model=model_name,
            contents="Say 'Hello' in one word"
        )
        print(f"  ✅ SUCCESS! Response: {response.text.strip()}")
        print(f"  💡 Use this model name: {model_name}")
        break
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg:
            print(f"  ❌ Model not found")
        elif "429" in error_msg or "quota" in error_msg.lower():
            print(f"  ⚠️  Quota exceeded - but model exists!")
            print(f"  💡 Use this model name: {model_name}")
            break
        else:
            print(f"  ❌ Error: {error_msg[:100]}")

print("\n" + "="*50)
print("If all models failed, check:")
print("1. API key is correct and active")
print("2. Gemini API is enabled in Google Cloud Console")
print("3. You haven't exceeded free tier quotas")
print("="*50)
