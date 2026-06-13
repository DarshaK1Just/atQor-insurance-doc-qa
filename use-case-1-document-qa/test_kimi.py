"""
Quick test to see if Kimi k2.6 deployment works
"""
import os
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

def test_kimi():
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION")
    
    print(f"\n🔵 Testing Kimi k2.6 Deployment...")
    print(f"   Endpoint: {endpoint}")
    print(f"   Deployment: {deployment}")
    print(f"   API Version: {api_version}")
    
    try:
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version
        )
        
        print(f"\n   Sending test message to {deployment}...")
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "user", "content": "Say 'Hello! I am Kimi k2.6 and I am working!'"}
            ],
            max_tokens=50
        )
        
        answer = response.choices[0].message.content
        print(f"\n   ✅ Response from Kimi: {answer}")
        print(f"\n✅ Kimi k2.6 is working perfectly!")
        return True
        
    except Exception as e:
        print(f"\n   ❌ Error: {str(e)}")
        print(f"\n   This might mean:")
        print(f"   - The deployment name is incorrect")
        print(f"   - The endpoint format is different for serverless models")
        print(f"   - The API key is incorrect")
        return False

if __name__ == "__main__":
    import sys
    success = test_kimi()
    sys.exit(0 if success else 1)
