import { useState, useEffect } from "react";
import { getCurrentWindow, LogicalSize, LogicalPosition } from "@tauri-apps/api/window";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import CodeBlockLowlight from '@tiptap/extension-code-block-lowlight';
import { common, createLowlight } from 'lowlight';
import logo from "./assets/logo.png";
import { useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Load lowlight languages
const lowlight = createLowlight(common);

type ViewState = "IDLE" | "FORM" | "INFO" | "LOGIN";

function App() {
  const [view, setView] = useState<ViewState | "LOGIN" | "ADMIN">("IDLE");
  const [token, setToken] = useState<string | null>(localStorage.getItem("token"));
  const [username, setUsername] = useState<string | null>(localStorage.getItem("username"));
  const [loginForm, setLoginForm] = useState({ user: "", pass: "" });

  const [isLocked, setIsLocked] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [image, setImage] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [chatMessages, setChatMessages] = useState<{ role: 'user' | 'ai', text: string, sources?: any[] }[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isQuerying, setIsQuerying] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (token) {
      // Validation check or just keep it
    }
  }, [token]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  const editor = useEditor({
    extensions: [
      StarterKit,
      CodeBlockLowlight.configure({
        lowlight,
      }),
    ],
    content: '',
    onUpdate: ({ editor }) => {
      setContent(editor.getHTML());
    },
  });

  const handleClipboardPaste = async () => {
    try {
      try {
        const b64Image = await invoke<string>("read_clipboard_image");
        setImage(b64Image);
      } catch (e) {
        // If no image, try reading text
        const clipboardText = await navigator.clipboard.readText();
        if (clipboardText && editor) {
          editor.chain().focus().insertContent(clipboardText).run();
        }
      }
    } catch (err) {
      console.error("Clipboard error:", err);
    }
  };

  useEffect(() => {
    const setupWindow = async () => {
      try {
        const win = getCurrentWindow();
        const screenWidth = window.screen.width;
        await win.setSize(new LogicalSize(48, 48));
        await win.setPosition(new LogicalPosition(screenWidth - 80, 40));
        await win.show();
      } catch (e) {
        console.error("Setup error:", e);
      }
    };
    setupWindow();
  }, []);

  const updateWindow = async (targetView: ViewState) => {
    if (isLocked && targetView !== "IDLE") return;

    const win = getCurrentWindow();
    const screenWidth = window.screen.width;
    const screenHeight = window.screen.height;

    let width = 48;
    let height = 48;

    if (targetView === "FORM" || targetView === "INFO" || targetView === "LOGIN") {
      width = Math.max(450, Math.floor(screenWidth / 4));
      height = Math.max(600, Math.floor(screenHeight / 1.8));
    }

    try {
      await win.setPosition(new LogicalPosition(screenWidth - width - 20, 40));
      await win.setSize(new LogicalSize(width, height));
      setView(targetView);
    } catch (e) {
      console.error("Window update error:", e);
    }
  };

  const handleMinimize = async () => {
    setIsLocked(true);
    await updateWindow("IDLE");
    setTimeout(() => setIsLocked(false), 1000);
  };

  const handleFormat = (type: 'bold' | 'sql' | 'csharp') => {
    if (!editor) return;
    if (type === 'bold') {
      editor.chain().focus().toggleBold().run();
    } else if (type === 'sql') {
      editor.chain().focus().toggleCodeBlock({ language: 'sql' }).run();
    } else if (type === 'csharp') {
      editor.chain().focus().toggleCodeBlock({ language: 'csharp' }).run();
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch("http://localhost:8000/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: loginForm.user, password: loginForm.pass }),
      });
      const data = await res.json();
      if (res.ok) {
        localStorage.setItem("token", data.token);
        localStorage.setItem("username", data.username);
        setToken(data.token);
        setUsername(data.username);
        updateWindow("FORM");
      } else {
        setStatus(data.detail);
      }
    } catch (err) {
      setStatus("Błąd logowania");
    }
  };

  const handleLogout = () => {
    localStorage.clear();
    setToken(null);
    setUsername(null);
    updateWindow("IDLE");
  };


  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("http://localhost:8000/api/upload", {
        method: "POST",
        headers: { "token": token || "" },
        body: formData,
      });
      const data = await res.json();

      if (res.ok && data.task_id) {
        // Start polling for progress
        const pollId = setInterval(async () => {
          try {
            const sRes = await fetch(`http://localhost:8000/api/upload/status/${data.task_id}`);
            const sData = await sRes.json();

            setStatus(sData.status);

            if (sData.done) {
              clearInterval(pollId);
              setIsUploading(false);
              if (sData.summary) {
                setChatMessages(prev => [...prev, {
                  role: 'ai',
                  text: `### 📂 Podsumowanie: ${file.name}\n${sData.summary}`
                }]);
              }
              setTimeout(() => setStatus(""), 5000);
            }
          } catch (err) {
            clearInterval(pollId);
            setIsUploading(false);
          }
        }, 1000);
      } else {
        setStatus("Błąd startu wgrywania");
        setIsUploading(false);
      }
    } catch (err) {
      setStatus("Błąd połączenia");
      setIsUploading(false);
    }
  };

  const handleQuery = async () => {
    if (!query.trim()) return;

    const userMessage = query;
    setChatMessages(prev => [...prev, { role: 'user', text: userMessage }]);
    setQuery("");
    setIsQuerying(true);

    try {
      const res = await fetch(`http://localhost:8000/api/query?q=${encodeURIComponent(userMessage)}`, {
        headers: { "token": token || "" }
      });
      const data = await res.json();
      if (data.answer) {
        setChatMessages(prev => [...prev, {
          role: 'ai',
          text: data.answer,
          sources: data.sources
        }]);
      } else if (data.error) {
        setChatMessages(prev => [...prev, { role: 'ai', text: `Błąd: ${data.error}` }]);
      }
    } catch (err) {
      setChatMessages(prev => [...prev, { role: 'ai', text: "Błąd połączenia z modelem" }]);
    } finally {
      setIsQuerying(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!content.trim()) return;
    try {
      setStatus("Wysyłanie...");
      const res = await fetch("http://localhost:8000/api/notes", {
        method: "POST",
        headers: { "Content-Type": "application/json", "token": token || "" },
        body: JSON.stringify({ title, content, image }),
      });
      if (res.ok) {
        setStatus("Wysłano pomyślnie!");
        setTitle("");
        setContent("");
        setImage(null);
        if (editor) editor.commands.clearContent();
        setTimeout(() => {
          setStatus("");
          handleMinimize();
        }, 1500);
      } else {
        setStatus("Błąd wysyłania");
      }
    } catch (err) {
      setStatus("Błąd połączenia");
    }
  };

  return (
    <main className={`app-container view-${view}`}>
      {view === "IDLE" && (
        <div className="interaction-wrapper">
          <div
            className="main-trigger"
            onClick={() => {
              if (!token) updateWindow("LOGIN");
              else updateWindow("FORM");
            }}
            title="Otwórz ArcusAi"
          >
            <div className="icon-wrapper">
              <div
                className="app-logo"
                style={{
                  backgroundImage: `url(${logo})`,
                  pointerEvents: 'none',
                }}
              />
            </div>
          </div>
        </div>
      )}

      {(view === "FORM" || view === "INFO" || (view as any) === "ADMIN") && (
        <div className={`panel-content ${view === "FORM" ? "form-view" : view === "INFO" ? "info-view" : "admin-view"}`}>
          <div className="panel-sidebar">
            <div
              className="sidebar-logo"
              style={{ backgroundImage: `url(${logo})` }}
            />
          </div>
          <div className="panel-main">
            <div className="panel-header">
              <div className="header-tabs">
                <button
                  className={`tab-btn ${view === "FORM" ? "active" : ""}`}
                  onClick={() => updateWindow("FORM")}
                >
                  Nowa Notatka
                </button>
                <button
                  className={`tab-btn ${view === "INFO" ? "active" : ""}`}
                  onClick={() => updateWindow("INFO")}
                >
                  Zadaj Pytanie
                </button>
              </div>
              <div className="header-actions">
                <span className="user-badge">{username}</span>
                <button className="logout-btn" onClick={handleLogout} title="Wyloguj">🚪</button>
                <button className="close-btn" onClick={handleMinimize}>✕</button>
              </div>
            </div>

            <div className="view-container">
              {view === "FORM" ? (
                <form onSubmit={handleSubmit} className="note-form">
                  <input
                    className="title-input"
                    type="text"
                    placeholder="Tytuł wpisu..."
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    autoFocus
                  />

                  <div className="editor-toolbar">
                    <button
                      type="button"
                      onClick={() => handleFormat('bold')}
                      className={editor?.isActive('bold') ? 'active' : ''}
                      title="Pogrubienie"
                    >
                      <b>B</b>
                    </button>
                    <div className="toolbar-separator"></div>
                    <button
                      type="button"
                      onClick={() => handleFormat('sql')}
                      className={`btn-code ${editor?.isActive('codeBlock', { language: 'sql' }) ? 'active' : ''}`}
                    >
                      SQL
                    </button>
                    <button
                      type="button"
                      onClick={() => handleFormat('csharp')}
                      className={`btn-code ${editor?.isActive('codeBlock', { language: 'csharp' }) ? 'active' : ''}`}
                    >
                      C#
                    </button>
                  </div>

                  <div className="rich-editor-container">
                    <EditorContent editor={editor} className="content-input rich-editor" />
                  </div>

                  {image && (
                    <div className="screenshot-preview">
                      <img src={image} alt="Preview" />
                      <button
                        type="button"
                        className="remove-img"
                        onClick={() => setImage(null)}
                      >✕</button>
                    </div>
                  )}

                  <div className="form-actions">
                    <button
                      type="button"
                      className="clipboard-btn"
                      onClick={handleClipboardPaste}
                      title="Wklej obraz lub tekst ze schowka"
                    >
                      📋 Wklej Schowek
                    </button>
                    <button type="submit" className="submit-btn" onClick={(e) => e.stopPropagation()}>Zapisz</button>
                  </div>
                </form>
              ) : (
                <div className="chat-container">
                  <div className="chat-messages">
                    {chatMessages.length === 0 && (
                      <div className="chat-welcome">
                        <div className="welcome-icon">🧠</div>
                        <p>Jestem Twoim asystentem ArcusAi.</p>
                        <p>Wgraj plik lub po prostu o coś zapytaj.</p>
                      </div>
                    )}
                    {chatMessages.map((msg, i) => (
                      <div key={i} className={`message-bubble chat-${msg.role}`}>
                        <div className="bubble-content">
                          {msg.role === 'ai' ? (
                            <div className="ai-message-wrapper">
                              <ReactMarkdown
                                remarkPlugins={[remarkGfm]}
                                components={{
                                  code({ node, inline, className, children, ...props }: any) {
                                    const match = /language-(\w+)/.exec(className || '');
                                    const language = match ? match[1] : '';
                                    const codeContent = String(children).replace(/\n$/, '');

                                    if (!inline && match) {
                                      return (
                                        <div className="code-block-container">
                                          <div className="code-block-header">
                                            <span>{language}</span>
                                            <button
                                              className="code-copy-btn"
                                              onClick={(e) => {
                                                navigator.clipboard.writeText(codeContent);
                                                const btn = e.target as HTMLButtonElement;
                                                if (btn) {
                                                  const original = btn.innerText;
                                                  btn.innerText = "Skopiowano!";
                                                  setTimeout(() => btn.innerText = original, 2000);
                                                }
                                              }}
                                            >
                                              Kopiuj
                                            </button>
                                          </div>
                                          <pre className={className}>
                                            <code {...props}>{children}</code>
                                          </pre>
                                        </div>
                                      );
                                    }
                                    return (
                                      <code className={className} {...props}>
                                        {children}
                                      </code>
                                    );
                                  }
                                }}
                              >
                                {msg.text}
                              </ReactMarkdown>
                            </div>
                          ) : (
                            <div className="user-text-wrapper">
                              {msg.text}
                            </div>
                          )}
                          {msg.sources && msg.sources.length > 0 && (
                            <div className="message-sources">
                              <small>📁 Źródła: {Array.from(new Set(msg.sources.map((s: any) => s.filename))).join(", ")}</small>
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                    {isQuerying && (
                      <div className="message-bubble chat-ai loading-bubble">
                        <div className="typing-loader">
                          <span>.</span><span>.</span><span>.</span>
                        </div>
                      </div>
                    )}
                    <div ref={chatEndRef} />
                  </div>

                  <div className="chat-input-wrapper">
                    <input
                      type="file"
                      id="chat-file-upload"
                      hidden
                      onChange={handleFileUpload}
                      accept=".pdf,.docx,.sql,.txt,.cs,.py,.js"
                    />
                    <label htmlFor="chat-file-upload" className={`chat-upload-btn ${isUploading ? 'loading' : ''}`}>
                      {isUploading ? <div className="spinner"></div> : "📎"}
                      {isUploading && status && (
                        <div className="upload-tooltip">
                          {status}
                        </div>
                      )}
                    </label>
                    <input
                      className="chat-input-field"
                      type="text"
                      placeholder="Napisz wiadomość..."
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleQuery()}
                    />
                    <button className="chat-send-btn" onClick={handleQuery}>➔</button>
                  </div>
                </div>
              )}
            </div>
            {status && <p className="status-msg chat-status">{status}</p>}
          </div>
        </div>
      )}

      {view === "LOGIN" && (
        <div className="panel-content login-view">
          <div className="panel-sidebar">
            <div className="sidebar-logo" style={{ backgroundImage: `url(${logo})` }} />
          </div>
          <div className="panel-main">
            <div className="panel-header">
              <div className="header-tabs"><span className="tab-btn active">Logowanie</span></div>
              <button className="close-btn" onClick={handleMinimize}>✕</button>
            </div>
            <div className="login-container">
              <div className="login-box">
                <h2>Witamy w ArcusAi</h2>
                <p>Zaloguj się do swojego konta</p>
                <form onSubmit={handleLogin} className="login-form">
                  <input type="text" placeholder="Użytkownik" value={loginForm.user} onChange={e => setLoginForm({ ...loginForm, user: e.target.value })} required />
                  <input type="password" placeholder="Hasło" value={loginForm.pass} onChange={e => setLoginForm({ ...loginForm, pass: e.target.value })} required />
                  <button type="submit" className="submit-btn login-btn">Zaloguj</button>
                </form>
                {status && <p className="error-text">{status}</p>}
                <div className="login-footer">
                  <small></small>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

export default App;
