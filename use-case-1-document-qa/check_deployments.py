"""
Script to check Azure OpenAI deployments and verify configuration.
"""
import os
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

def check_deployments():
    """Check if the OpenAI deployments exist and are accessible."""
    
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    chat_deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
    embed_deployment = os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT")
    
    print("\n🔵 Checking Azure OpenAI Configuration...")
    print(f"   Endpoint: {endpoint}")
    print(f"   Chat Deployment: {chat_deployment}")
    print(f"   Embed Deployment: {embed_deployment}")
    
    try:
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
        )
        
        # Test chat deployment
        print(f"\n   Testing chat deployment '{chat_deployment}'...")
        try:
            response = client.chat.completions.create(
                model=chat_deployment,
                messages=[{"role": "user", "content": "Say 'test successful'"}],
                max_tokens=10
            )
            print(f"   ✅ Chat deployment is working!")
        except Exception as e:
            print(f"   ❌ Chat deployment error: {str(e)}")
            if "DeploymentNotFound" in str(e):
                print(f"      The deployment '{chat_deployment}' doesn't exist.")
                print(f"      Please check your Azure OpenAI Studio and update .env")
            return False
        
        # Test embedding deployment
        print(f"\n   Testing embedding deployment '{embed_deployment}'...")
        try:
            response = client.embeddings.create(
                model=embed_deployment,
                input="test"
            )
            print(f"   ✅ Embedding deployment is working!")
        except Exception as e:
            print(f"   ❌ Embedding deployment error: {str(e)}")
            if "DeploymentNotFound" in str(e):
                print(f"      The deployment '{embed_deployment}' doesn't exist.")
                print(f"      Please check your Azure OpenAI Studio and update .env")
            return False
        
        print("\n✅ All Azure OpenAI deployments are ready!")
        return True
        
    except Exception as e:
        print(f"\n❌ Failed to connect to Azure OpenAI: {str(e)}")
        return False

if __name__ == "__main__":
    import sys
    success = check_deployments()
    sys.exit(0 if success else 1)
