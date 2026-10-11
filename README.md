# 🧠 NEXA - Your Personal AI Assistant

NEXA is a real-time multimodal AI assistant powered by LiveKit Agents and Google Gemini Realtime, capable of:

- 🔍 Searching the web  
- 🌤️ Weather checking
- 📨 Sending Emails 
- 📷 Vision through camera (Web app)
- 🗣️ Speech
- 📝 Chat (Web app) 

This agent uses LiveKit for real-time WebRTC audio and video streaming.

---

## 📁 Project Structure

```text
nexa/
├── .env                # API keys and credentials (LiveKit, Gemini, Gmail)
├── .gitignore          # Version control ignore rules
├── README.md           # Project documentation
├── backend/            # Python LiveKit & Gemini voice agent
│   ├── agent.py        # Worker entrypoint
│   ├── prompts.py      # NEXA persona and prompts
│   ├── tools.py        # Function tools (weather, search, email)
│   └── requirements.txt# Backend Python dependencies
└── frontend/           # NEXA user interface (upcoming)
```

---

## 🚀 Getting Started

### 1. Environment Configuration
Ensure your `.env` file exists at the project root with the required credentials:
```env
LIVEKIT_URL=your_livekit_url
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
GOOGLE_API_KEY=your_gemini_api_key
GMAIL_USER=your_gmail_address
GMAIL_APP_PASSWORD=your_gmail_app_password
```

### 2. Backend Setup
1. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # Linux/macOS:
   source venv/bin/activate
   ```
2. Install backend dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```
3. Run the NEXA voice agent:
   ```bash
   cd backend
   python agent.py dev
   ```
