\# SalesPilot AI – Project Report



\## 1. Introduction



SalesPilot AI is an AI-powered sales automation platform designed to automate customer conversations, qualify potential leads, and simplify sales operations.



The system combines conversational AI, voice calling capabilities, CRM management, and document-based question answering to help sales teams manage customer interactions efficiently.



\## 2. Problem Statement



Traditional sales processes involve repetitive manual tasks such as:

\- Handling customer queries.

\- Collecting customer requirements.

\- Qualifying potential leads.

\- Maintaining customer records.

\- Preparing call summaries.

\- Scheduling follow-up appointments.



These activities consume time and can lead to inconsistent customer management.



SalesPilot AI aims to automate and simplify these activities using artificial intelligence.



\## 3. Project Objectives



The main objectives are:



\- Build an AI-powered sales voice and chat assistant.

\- Automate customer requirement collection.

\- Classify leads into HOT, WARM, and COLD categories.

\- Store customer information and conversations in a CRM.

\- Generate AI-based call summaries.

\- Identify customer sentiment and objections.

\- Support appointment scheduling and management.

\- Provide document-based answers using Retrieval-Augmented Generation (RAG).



\## 4. Technology Stack



| Technology | Purpose |

|---|---|

| React.js | Frontend user interface |

| Vite | Frontend development and build tool |

| Python | Backend programming |

| FastAPI | REST API development |

| Google Gemini 2.5 Flash Lite | AI conversation and information extraction |

| MongoDB Atlas | Database and persistent storage |

| Vapi | Voice agent infrastructure |

| LangChain | Document processing and RAG workflow |

| FAISS | Vector similarity search |



\## 5. System Architecture



The application follows a frontend-backend architecture.



\*\*Workflow:\*\*



1\. Customer interacts through the web chat or voice interface.

2\. Vapi handles voice interaction and connects to the backend.

3\. FastAPI processes requests.

4\. Google Gemini generates AI responses and extracts customer information.

5\. MongoDB stores leads, conversations, calls, and appointments.

6\. LangChain and FAISS retrieve relevant information from uploaded documents.

7\. React dashboard displays the CRM data and activity.



\## 6. Main Modules and Features



\### 6.1 Dashboard Overview

Displays an overview of sales activities and CRM information.



\### 6.2 Lead Management

\- Stores customer information.

\- Extracts requirements from conversations.

\- Classifies leads as HOT, WARM, or COLD.

\- Supports lead deduplication.



\### 6.3 AI Chat

Provides conversational interaction using Google Gemini and maintains conversation history.



\### 6.4 Voice Calling

Uses Vapi voice infrastructure and a custom LLM backend integration to support AI-powered voice conversations.



\### 6.5 Call Management

\- Stores call records and transcripts.

\- Generates call summaries.

\- Identifies customer sentiment and objections.

\- Links call information with CRM leads.



\### 6.6 Appointment Management

Supports appointment creation, listing, updating, and cancellation with validation and duplicate-slot prevention.



\### 6.7 Knowledge Base – RAG

\- Supports PDF document uploads.

\- Splits documents into smaller text chunks.

\- Uses embeddings and FAISS for vector search.

\- Retrieves relevant document content for AI-generated answers.



\## 7. Database Design



MongoDB Atlas is used for persistent data storage.



The application maintains information related to:



\- Leads and customer details.

\- Chat conversations and messages.

\- Voice call records and transcripts.

\- Call summaries and analysis.

\- Appointments.

\- Knowledge base documents and related processing data.



\## 8. AI and RAG Implementation



Google Gemini is used as the primary language model for conversational responses and customer information extraction.



The RAG pipeline uses LangChain and FAISS to retrieve relevant content from uploaded PDF documents.



This allows the assistant to generate answers using relevant business-document context instead of relying only on general model knowledge.



\## 9. Testing and Validation



The following areas were tested during development:



\- Backend health and API functionality.

\- Gemini-powered chat interactions.

\- Lead extraction and qualification.

\- MongoDB persistence.

\- Voice conversation processing.

\- Vapi webhook handling.

\- Call transcript and summary storage.

\- PDF upload and retrieval workflow.

\- Appointment management and validation.

\- Frontend production build.



The frontend production build completed successfully.



\*\*Note:\*\* Full outbound telephone calling requires additional Vapi API credentials and phone-number configuration. It should not be considered fully verified in the current prototype.



\## 10. Limitations



\- Outbound telephone calling requires additional provider configuration.

\- Production deployment and monitoring are not yet fully implemented.

\- Authentication and role-based access control can be added.

\- Scalability and performance can be improved for larger workloads.



\## 11. Future Scope



\- Complete outbound calling integration.

\- Add user authentication and access control.

\- Deploy the application to cloud infrastructure.

\- Add advanced sales analytics and reporting.

\- Improve multilingual conversation support.

\- Add automated follow-up workflows.

\- Improve scalability and production monitoring.



\## 12. Conclusion



SalesPilot AI demonstrates how artificial intelligence can be integrated with voice technology, CRM functionality, and document retrieval to automate important sales activities.



The project provides a working prototype for AI-assisted customer conversations, lead qualification, call analysis, appointment management, and knowledge-base question answering.



It demonstrates practical use of modern AI technologies and full-stack application development.

