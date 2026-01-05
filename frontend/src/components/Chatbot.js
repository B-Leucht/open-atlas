import React, { useEffect, useRef, useState } from 'react';
import './Chatbot.css';

// Use the same API as the rest of the app
const API_BASE_URL = `http://${window.location.hostname}:5001/api`;

export default function Chatbot() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState([
    { id: 1, text: "Hello! Ask me anything about Munich Open Data.", sender: 'bot' }
  ]);
  const [sending, setSending] = useState(false);
  const [apiHealthy, setApiHealthy] = useState(null);

  const messagesRef = useRef(null);

  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
    }
  }, [messages]);

  useEffect(() => {
    checkHealth();
  }, []);

  const checkHealth = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/health`);
      if (response.ok) {
        setApiHealthy(true);
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
    const newUserMsg = { id: Date.now(), text: userMessageText, sender: 'user' };
    setMessages(prev => [...prev, newUserMsg]);
    setInput('');
    setSending(true);

    try {
      const response = await fetch(`${API_BASE_URL}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query: userMessageText
        }),
      });

      const data = await response.json();

      if (data.success) {
        const newBotMsg = { id: Date.now() + 1, text: data.answer, sender: 'bot' };
        setMessages(prev => [...prev, newBotMsg]);
      } else {
        const errorMsg = { id: Date.now() + 1, text: data.error || "Something went wrong.", sender: 'bot' };
        setMessages(prev => [...prev, errorMsg]);
      }
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

  return (
    <div className="chatbot">
      {open && (
        <div className="chat-window" role="dialog" aria-label="Chatbot window">
          <div className="chat-header">
            <div className="chat-title">Data Assistant</div>
            <div className="chat-status">
              {apiHealthy === null ? 'Checking...' : apiHealthy ? 'Connected' : 'Offline'}
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
              placeholder="Ask about Munich data..."
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
