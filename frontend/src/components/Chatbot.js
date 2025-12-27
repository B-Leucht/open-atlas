import React, { useEffect, useRef, useState } from 'react';
import './Chatbot.css';

const API_BASE_URL = "http://localhost:8000";

export default function Chatbot() {
  // --- STATE MANAGEMENT ---
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState([
    { id: 1, text: "Hello! Ask me anything about Munich Open Data.", sender: 'bot' }
  ]);
  const [sending, setSending] = useState(false);
  const [apiHealthy, setApiHealthy] = useState(null);
  
  const messagesRef = useRef(null);

  // --- EFFECTS ---

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
    }
  }, [messages]);

  // Check API health when component loads
  useEffect(() => {
    checkHealth();
  }, []);

  // --- FUNCTIONS ---

  const checkHealth = async () => {
    try {
      // Note: This expects your Python server to be running on localhost:8000
      const response = await fetch(`${API_BASE_URL}/health`);
      if (response.ok) {
        const data = await response.json();
        setApiHealthy(data.status === 'healthy');
      } else {
        setApiHealthy(false);
      }
    } catch (error) {
      console.warn("Health check failed:", error);
      setApiHealthy(false);
    }
  };

  const send = async () => {
    if (!input.trim()) return;

    const userMessageText = input;
    
    // 1. Update UI with user message
    const newUserMsg = { id: Date.now(), text: userMessageText, sender: 'user' };
    setMessages(prev => [...prev, newUserMsg]);
    setInput('');
    setSending(true);

    try {
      // 2. Call the Python API
      const response = await fetch(`${API_BASE_URL}/query`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query: userMessageText,
          conversation_id: "web-client-session" 
        }),
      });

      if (!response.ok) {
        throw new Error(`Server error: ${response.statusText}`);
      }

      const data = await response.json();

      // 3. Update UI with Bot Response
      const newBotMsg = { id: Date.now() + 1, text: data.answer, sender: 'bot' };
      setMessages(prev => [...prev, newBotMsg]);

    } catch (error) {
      console.error("Query failed:", error);
      const errorMsg = { id: Date.now() + 1, text: "Sorry, I'm having trouble connecting to the server.", sender: 'bot' };
      setMessages(prev => [...prev, errorMsg]);
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  // --- RENDER ---
  return (
    <div className="chatbot">
      {open && (
        <div className="chat-window" role="dialog" aria-label="Chatbot window">
          <div className="chat-header">
            <div className="chat-title">Chat</div>
            <div className="chat-status" style={{ fontSize: '0.8rem', opacity: 0.9 }}>
              {apiHealthy === null ? 'Checking...' : apiHealthy ? 'API: healthy' : 'API: unreachable'}
            </div>
            <button className="chat-close" onClick={() => setOpen(false)} aria-label="Close chat">×</button>
          </div>

          <div className="chat-messages" ref={messagesRef}>
            {messages.map(m => (
              <div key={m.id} className={`chat-message ${m.sender}`}>
                <div className="chat-bubble">{m.text}</div>
              </div>
            ))}
          </div>

          <div className="chat-input">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a message..."
              rows={1}
            />
            <button className="chat-send" onClick={send} disabled={sending || !input.trim()}>
              {sending ? '...' : 'Send'}
            </button>
          </div>
        </div>
      )}

      <button className="chat-toggle" onClick={async () => {
        if (!open) await checkHealth();
        setOpen(o => !o);
      }} aria-label="Open chat">
        💬
      </button>
    </div>
  );
}

