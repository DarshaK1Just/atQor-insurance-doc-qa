"""
Script to create Azure Blob Storage containers if they don't exist.
Run this before starting the application.
"""
import sys
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

def setup_containers():
    """Create blob containers if they don't exist."""
    connection_string = os.getenv("BLOB_CONNECTION_STRING")
    
    if not connection_string:
        print("⚠️  BLOB_CONNECTION_STRING not set in .env")
        print("   The app will use local storage (./data) instead.")
        print("   This is fine for development!")
        return True
    
    try:
        # Create BlobServiceClient
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        
        # Containers to create
        containers = [
            os.getenv("BLOB_CONTAINER_ORIGINALS", "originals"),
            os.getenv("BLOB_CONTAINER_EXTRACTS", "extracts")
        ]
        
        print("\n🔵 Checking Azure Blob Storage containers...")
        
        for container_name in containers:
            try:
                container_client = blob_service_client.get_container_client(container_name)
                
                # Try to get container properties (this will fail if it doesn't exist)
                if container_client.exists():
                    print(f"   ✅ Container '{container_name}' already exists")
                else:
                    # Create the container
                    container_client.create_container()
                    print(f"   ✅ Container '{container_name}' created successfully")
                    
            except Exception as e:
                print(f"   ❌ Error with container '{container_name}': {str(e)}")
                return False
        
        print("\n✅ Azure Blob Storage is ready!")
        return True
        
    except Exception as e:
        print(f"\n❌ Failed to connect to Azure Blob Storage: {str(e)}")
        print("   Check your BLOB_CONNECTION_STRING in .env")
        return False

if __name__ == "__main__":
    success = setup_containers()
    sys.exit(0 if success else 1)
