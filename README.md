# atQor - Insurance Document Intelligence Q&A System

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Azure](https://img.shields.io/badge/Azure-AI%20Services-0078D4.svg)](https://azure.microsoft.com/en-us/services/cognitive-services/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.0+-FF4B4B.svg)](https://streamlit.io/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com/)

An enterprise-grade Document Intelligence system for insurance documents with Azure AI integration. This system enables grounded Q&A over multi-document corpora with page-level citations and cross-document reasoning capabilities.

## 🌟 Features

- **Multi-Document Processing**: Supports PDF, DOCX, JPG, PNG, and TIFF formats
- **Intelligent Extraction**: Azure Document Intelligence for layout-aware text extraction
- **Semantic Search**: Hybrid search combining vector and keyword matching
- **Grounded Answers**: Every answer is backed by source citations with page numbers
- **Real-time Streaming**: Token-by-token answer streaming with live agentic trace
- **Cross-Document Reasoning**: Compare and analyze information across multiple documents
- **Production-Ready UI**: Modern Streamlit frontend with zero-flicker polling
- **Scalable Architecture**: FastAPI backend with async processing pipeline

## 🏗️ Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Streamlit UI  │────▶│   FastAPI API    │────▶│  Azure Services │
│  (Frontend)     │     │   (Backend)      │     │  - Doc Intel    │
└─────────────────┘     └──────────────────┘     │  - OpenAI       │
                              │                   │  - AI Search    │
                              │                   │  - Blob Storage │
                              ▼                   └─────────────────┘
                        ┌──────────────────┐
                        │  Processing      │
                        │  Pipeline        │
                        │  - Extraction    │
                        │  - Classification│
                        │  - Chunking      │
                        │  - Indexing      │
                        └──────────────────┘
```

## 📋 Prerequisites

- Python 3.9 or higher
- Azure subscription with the following services:
  - Azure OpenAI Service
  - Azure AI Document Intelligence
  - Azure AI Search
  - Azure Blob Storage

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/darshakkakani/atQor-insurance-doc-qa.git
cd atQor-insurance-doc-qa
```

### 2. Set Up Virtual Environment

```bash
cd use-case-1-document-qa
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Azure Services

Copy the example environment file and fill in your Azure credentials:

```bash
copy .env.example .env
```

Edit `.env` with your Azure service details:

```env
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-ada-002
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=your-key
AZURE_SEARCH_ENDPOINT=https://your-search.search.windows.net
AZURE_SEARCH_KEY=your-search-key
AZURE_STORAGE_CONNECTION_STRING=your-connection-string
```

### 5. Run the Application

**Option A: Using the Quick Start Script (Windows)**
```bash
.\QUICK_START.bat
```

**Option B: Manual Start**

Terminal 1 - Start Backend:
```bash
cd use-case-1-document-qa
uvicorn src.api.main:app --reload --port 8000
```

Terminal 2 - Start Frontend:
```bash
cd use-case-1-document-qa
streamlit run frontend/app.py --server.port 8501
```

### 6. Access the Application

Open your browser and navigate to:
- **Frontend UI**: http://localhost:8501
- **API Docs**: http://localhost:8000/docs

## ☁️ Deploying to Streamlit Cloud

### Prerequisites
1. Push your code to a GitHub repository
2. Have your Azure service credentials ready

### Deployment Steps

1. **Go to [Streamlit Cloud](https://share.streamlit.io/)**

2. **Click "New app" and configure:**
   - **Repository**: `your-username/atQor-insurance-doc-qa`
   - **Branch**: `master`
   - **Main file path**: `streamlit_app.py`

3. **Configure Secrets** (Click "Advanced settings" → "Secrets"):
   
   Paste your environment variables in TOML format:
   
   ```toml
   # Azure AI Foundry
   AZURE_OPENAI_ENDPOINT = "https://your-resource.openai.azure.com/"
   AZURE_OPENAI_API_KEY = "your-api-key"
   AZURE_OPENAI_API_VERSION = "2024-05-01-preview"
   AZURE_OPENAI_CHAT_DEPLOYMENT = "your-chat-model"
   AZURE_OPENAI_EMBED_DEPLOYMENT = "text-embedding-3-small"
   EMBED_DIMENSIONS = "1536"
   
   # Azure Document Intelligence
   DOCINTEL_ENDPOINT = "https://your-docintel.cognitiveservices.azure.com/"
   DOCINTEL_KEY = "your-docintel-key"
   DOCINTEL_PAGE_WINDOW = "2"
   
   # Azure AI Search
   SEARCH_ENDPOINT = "https://your-search.search.windows.net"
   SEARCH_KEY = "your-search-key"
   SEARCH_INDEX_NAME = "insurance-chunks"
   
   # Azure Blob Storage (optional)
   BLOB_CONNECTION_STRING = "your-connection-string"
   BLOB_CONTAINER_ORIGINALS = "originals"
   BLOB_CONTAINER_EXTRACTS = "extracts"
   
   # App Configuration
   DATA_DIR = "./data"
   CHUNK_MAX_TOKENS = "512"
   CHUNK_OVERLAP_TOKENS = "80"
   TOP_K = "5"
   
   # LLM Provider (azure or gemini)
   LLM_PROVIDER = "gemini"
   GEMINI_API_KEY = "your-gemini-key"
   GEMINI_CHAT_MODEL = "gemini-2.5-flash"
   
   # Performance
   STRUCTURED_OUTPUTS = "off"
   MAX_ANSWER_TOKENS = "1500"
   EMBED_KEEPALIVE_SECONDS = "120"
   WARMUP_ON_STARTUP = "true"
   ```

4. **Deploy**: Click "Deploy" and wait for the app to start

5. **Access**: Your app will be available at `https://your-app-name.streamlit.app`

### Important Notes
- The app runs both FastAPI backend and Streamlit frontend in a single process
- Backend starts automatically on port 8000
- First startup may take 10-15 seconds as services initialize
- Free tier has resource limitations - consider upgrading for production use

## 📚 Documentation

- [Azure Setup Guide](use-case-1-document-qa/AZURE_SETUP_GUIDE.md)
- [Architecture Design Review](ARCHITECTURE_DESIGN_REVIEW.md)
- [Solution Plan](SOLUTION_PLAN.md)
- [Foundry Project Setup](use-case-1-document-qa/FOUNDRY_PROJECT_SETUP.md)

## 🧪 Testing

Run the test suite:

```bash
pytest tests/
```

Run evaluation metrics:

```bash
python evals/evaluate.py
```

## 📁 Project Structure

```
atQor/
├── use-case-1-document-qa/
│   ├── src/
│   │   ├── api/              # FastAPI endpoints
│   │   ├── core/             # Configuration and Azure clients
│   │   ├── generation/       # RAG and answer generation
│   │   ├── indexing/         # Chunking and embedding
│   │   ├── ingestion/        # Document extraction pipeline
│   │   └── retrieval/        # Query planning and search
│   ├── frontend/             # Streamlit UI
│   ├── evals/                # Evaluation framework
│   ├── tests/                # Unit tests
│   ├── sample-documents/     # Demo corpus
│   └── requirements.txt
├── ARCHITECTURE_DESIGN_REVIEW.md
├── SOLUTION_PLAN.md
└── README.md
```

## 🔧 Key Components

### Backend (FastAPI)
- **Document Ingestion**: Async pipeline for document processing
- **RAG Service**: Grounded answer generation with citations
- **Search**: Hybrid retrieval with Azure AI Search
- **Status Tracking**: Real-time document processing status

### Frontend (Streamlit)
- **Zero-Click Ingestion**: Files processed on drop
- **Live Polling**: Only when needed, fragment-based reruns
- **Citation Preview**: Embedded PDF/image viewer in modal
- **Suggestion Chips**: Quick-start queries

### Processing Pipeline
1. **Extraction**: Azure Document Intelligence with layout analysis
2. **Classification**: LLM-based document type detection
3. **Chunking**: Structure-aware semantic chunking
4. **Indexing**: Vector + keyword indexing in Azure AI Search

## 🎯 Use Cases

- Policy document Q&A
- Claims form processing
- Medical report analysis
- Cross-policy comparison
- Coverage verification

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is proprietary and confidential.

## 👥 Authors

- **Darshak Kakani** - [darshakkakani](https://github.com/darshakkakani)

## 🙏 Acknowledgments

- Azure AI Services for document processing capabilities
- Streamlit for the excellent UI framework
- FastAPI for the high-performance backend framework

## 📞 Support

For questions or issues, please create an issue in the GitHub repository.

---

**Built with ❤️ using Azure AI**
