"""
Test the embedding deployment
"""
import os
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

def test_embedding():
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    deployment = os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION")
    
    print(f"\n🔵 Testing Embedding Deployment...")
    print(f"   Endpoint: {endpoint}")
    print(f"   Deployment: {deployment}")
    print(f"   API Version: {api_version}")
    
    try:
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version
        )
        
        print(f"\n   Generating embedding for test text...")
        response = client.embeddings.create(
            model=deployment,
            input="This is a test document about insurance policies."
        )
        
        embedding = response.data[0].embedding
        dimensions = len(embedding)
        
        print(f"\n   ✅ Embedding generated successfully!")
        print(f"   ✅ Dimensions: {dimensions}")
        print(f"   ✅ First 5 values: {embedding[:5]}")
        print(f"\n✅ text-embedding-3-small is working perfectly!")
        return True
        
    except Exception as e:
        print(f"\n   ❌ Error: {str(e)}")
        return False

if __name__ == "__main__":
    import sys
    success = test_embedding()
    sys.exit(0 if success else 1)
