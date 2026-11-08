"""
Initialize Pinecone index with manufacturing data
Run this from project root: python setup_chatbot_index.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server.chatbot.helper import load_json_objects_as_documents, download_hugging_face_embeddings
from pinecone.grpc import PineconeGRPC as Pinecone
from pinecone import ServerlessSpec
from langchain_pinecone import PineconeVectorStore
from dotenv import load_dotenv
import time


def setup_pinecone_index():
    """Setup and populate Pinecone index with manufacturing data"""
    
    load_dotenv()
    PINECONE_API_KEY = os.environ.get('PINECONE_API_KEY')
    
    if not PINECONE_API_KEY:
        print("❌ PINECONE_API_KEY not found in environment variables")
        print("Please add it to your .env file")
        return False
    
    os.environ["PINECONE_API_KEY"] = PINECONE_API_KEY

    data_folder = 'server/chatbot/data/'
    
    if not os.path.exists(data_folder):
        print(f"❌ Data folder not found: {data_folder}")
        return False

    print("📄 Loading JSON data...")
    documents = load_json_objects_as_documents(data_folder=data_folder)
    print(f"✅ Loaded {len(documents)} documents.")

    if len(documents) == 0:
        print("❌ No documents loaded. Please check your JSON files.")
        return False

    print("🔄 Loading embeddings model...")
    embeddings = download_hugging_face_embeddings()

    print("🔄 Connecting to Pinecone...")
    pc = Pinecone(api_key=PINECONE_API_KEY)

    index_name = "manufacturingindex"
    dimension = 384

    existing_indexes = [idx.name for idx in pc.list_indexes()]
    
    if index_name in existing_indexes:
        print(f"⚠️  Index '{index_name}' already exists. Deleting old index...")
        pc.delete_index(index_name)
        time.sleep(5)

    print(f"🔄 Creating index '{index_name}'...")
    pc.create_index(
        name=index_name,
        dimension=dimension,
        metric="cosine",
        spec=ServerlessSpec(
            cloud="aws",
            region="us-east-1"
        )
    )
    
    print("⏳ Waiting for index to be ready...")
    while not pc.describe_index(index_name).status['ready']:
        time.sleep(1)
    
    print("✅ Index is ready!")

    print(f"🔄 Embedding and uploading {len(documents)} documents to Pinecone...")
    
    vectorstore = PineconeVectorStore.from_documents(
        documents=documents,
        embedding=embeddings,
        index_name=index_name
    )
    
    print("✅ Documents uploaded successfully!")
    print(f"✅ Pinecone index '{index_name}' is ready for chatbot queries!")
    
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("🤖 CHATBOT PINECONE INDEX SETUP")
    print("=" * 60)
    
    success = setup_pinecone_index()
    
    print("=" * 60)
    if success:
        print("✅ Setup completed successfully!")
        print("You can now use the chatbot.")
    else:
        print("❌ Setup failed. Please check the errors above.")
    print("=" * 60)
