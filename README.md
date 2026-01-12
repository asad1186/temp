### 🔥 Advanced Agentic RAG Diagram

```markdown
## 🧠 Agentic RAG Architecture
flowchart TD
    U[🧑 User]
    API[⚡ FastAPI]
    
    subgraph Agent[🧠 AI Agent]
        R[🔀 Routing Prompt]
        M[💾 Session Memory]
    end

    subgraph RAG[📚 Retrieval Pipeline]
        E[📐 Embeddings]
        V[📦 FAISS Index]
        D[📄 PDFs / Docs]
    end

    LLM[🤖 OpenAI / Azure OpenAI]

    U -->|Query| API
    API --> Agent
    Agent --> R
    R -->|Direct| LLM
    R -->|Tool| RAG
    RAG --> V
    V --> D
    RAG --> Agent
    LLM --> Agent
    Agent --> M
    Agent --> API
    API -->|Answer + Sources| U

```mermaid

## 📌 Overview
(short description)

## 🏗️ Architecture Overview
(2–3 lines explanation)

## 🧠 Agentic RAG Architecture
👉 PASTE DIAGRAM HERE 👈

## 🧠 Agent Design
(text)

## 📚 RAG Pipeline
(text)

## 🚀 API
(text)

## ⚠️ Limitations
(text)

## 🔮 Future Improvements
(text)
