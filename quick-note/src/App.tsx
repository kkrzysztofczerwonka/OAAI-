import { useState, useEffect } from "react";
import { getCurrentWindow, LogicalSize, LogicalPosition } from "@tauri-apps/api/window";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";
import { useEditor, EditorContent } from '@tiptap/react';
import { StarterKit } from '@tiptap/starter-kit';
import { CodeBlockLowlight } from '@tiptap/extension-code-block-lowlight';
import { Placeholder } from '@tiptap/extension-placeholder';
import { Underline } from '@tiptap/extension-underline';
import { TextAlign } from '@tiptap/extension-text-align';
import { Image } from '@tiptap/extension-image';
import { Table } from '@tiptap/extension-table';
import { TableRow } from '@tiptap/extension-table-row';
import { TableCell } from '@tiptap/extension-table-cell';
import { TableHeader } from '@tiptap/extension-table-header';
import { Link } from '@tiptap/extension-link';
import { TaskList } from '@tiptap/extension-task-list';
import { TaskItem } from '@tiptap/extension-task-item';
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
  const [apiUrl, setApiUrl] = useState<string>(localStorage.getItem("apiUrl") || "http://localhost:8000");
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
  const [noteData, setNoteData] = useState({
    rozwiazanie: "",
    podrozwiazanie: "",
    produkt: "",
    obszar: "",
    firma: "",
    book_id: null as number | null,
    chapter_id: null as number | null,
    ksiazka_nazwa: "",
    rozdzial_nazwa: ""
  });
  const [priority, setPriority] = useState<number>(0);
  const [isFormVisible, setIsFormVisible] = useState(false);
  const [isSuggesting, setIsSuggesting] = useState(false);
  const [currentConversationId, setCurrentConversationId] = useState<number | null>(null);
  const [recentConversations, setRecentConversations] = useState<{ id: number, title: string }[]>([]);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (token) {
      // Validation check or just keep it
    }
  }, [token]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  const fetchRecentConversations = async () => {
    if (!token) return;
    try {
      const res = await fetch(`${apiUrl}/api/conversations`, {
        headers: { "token": token }
      });
      const data = await res.json();
      if (res.ok) setRecentConversations(data);
    } catch (e) { console.error(e); }
  };

  useEffect(() => {
    if (view === "INFO") fetchRecentConversations();
  }, [view, token]);

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        bulletList: {},
        orderedList: {},
        heading: { levels: [2, 3, 4, 5] },
      }),
      Underline,
      TextAlign.configure({ types: ['heading', 'paragraph'] }),
      Image.configure({ inline: true, allowBase64: true }),
      Table.configure({ resizable: true }),
      TableRow,
      TableHeader,
      TableCell,
      Link.configure({ openOnClick: false }),
      TaskList,
      TaskItem.configure({ nested: true }),
      CodeBlockLowlight.configure({ lowlight }),
      Placeholder.configure({
        placeholder: 'Zacznij pisać...',
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
        if (editor && b64Image) {
          editor.chain().focus().setImage({ src: b64Image }).run();
        } else {
          setImage(b64Image);
        }
      } catch (e) {
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

  const handleFormat = (type: string, value?: any) => {
    if (!editor) return;
    const chain = editor.chain().focus();

    switch (type) {
      case 'bold': chain.toggleBold().run(); break;
      case 'italic': chain.toggleItalic().run(); break;
      case 'underline': chain.toggleUnderline().run(); break;
      case 'strike': chain.toggleStrike().run(); break;
      case 'h2': chain.toggleHeading({ level: 2 }).run(); break;
      case 'h3': chain.toggleHeading({ level: 3 }).run(); break;
      case 'bulletList': chain.toggleBulletList().run(); break;
      case 'orderedList': chain.toggleOrderedList().run(); break;
      case 'taskList': chain.toggleTaskList().run(); break;
      case 'alignLeft': chain.setTextAlign('left').run(); break;
      case 'alignCenter': chain.setTextAlign('center').run(); break;
      case 'alignRight': chain.setTextAlign('right').run(); break;
      case 'table': chain.insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(); break;
      case 'hr': chain.setHorizontalRule().run(); break;
      case 'codeBlock':
        if (value) chain.toggleCodeBlock({ language: value }).run();
        break;
      case 'sql': chain.toggleCodeBlock({ language: 'sql' }).run(); break;
      case 'csharp': chain.toggleCodeBlock({ language: 'csharp' }).run(); break;
    }
  };

  const setCallout = (_type: 'info' | 'success' | 'warning' | 'danger') => {
    if (!editor) return;
    // For now using blockquote as a generic callout
    editor.chain().focus().toggleBlockquote().run();
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch(`${apiUrl}/api/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: loginForm.user, password: loginForm.pass }),
      });
      const data = await res.json();
      if (res.ok) {
        localStorage.setItem("token", data.token);
        localStorage.setItem("username", data.username);
        localStorage.setItem("apiUrl", apiUrl);
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
      const res = await fetch(`${apiUrl}/api/upload`, {
        method: "POST",
        headers: { "token": token || "" },
        body: formData,
      });
      const data = await res.json();

      if (res.ok && data.task_id) {
        // Start polling for progress
        const pollId = setInterval(async () => {
          try {
            const sRes = await fetch(`${apiUrl}/api/upload/status/${data.task_id}`);
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

    const userMessage = { role: 'user' as const, text: query };
    const currentHistory = [...chatMessages, userMessage];

    setChatMessages(currentHistory);
    setQuery("");
    setIsQuerying(true);

    try {
      const res = await fetch(`${apiUrl}/api/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "token": token || ""
        },
        body: JSON.stringify({
          messages: currentHistory.map(m => ({
            role: m.role,
            content: m.text
          })),
          conversation_id: currentConversationId
        })
      });
      const data = await res.json();
      if (data.answer) {
        setChatMessages(prev => [...prev, {
          role: 'ai',
          text: data.answer,
          sources: data.sources
        }]);
        if (data.conversation_id) {
          setCurrentConversationId(data.conversation_id);
          fetchRecentConversations();
        }
      } else if (data.error) {
        setChatMessages(prev => [...prev, { role: 'ai', text: `Błąd: ${data.error}` }]);
      }
    } catch (err) {
      setChatMessages(prev => [...prev, { role: 'ai', text: "Błąd połączenia z modelem" }]);
    } finally {
      setIsQuerying(false);
    }
  };

  const handleSuggest = async () => {
    if (!content.trim() || isSuggesting) return;
    setIsSuggesting(true);
    try {
      const res = await fetch(`${apiUrl}/api/suggest-metadata`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "token": token || ""
        },
        body: JSON.stringify({ content: editor?.getText() || content })
      });
      const data = await res.json();
      if (data && !data.error) {
        setNoteData({
          rozwiazanie: data.rozwiazanie || "",
          podrozwiazanie: data.podrozwiazanie || "",
          produkt: data.produkt || "",
          obszar: data.obszar || "",
          firma: data.firma || "",
          book_id: data.book_id || null,
          chapter_id: data.chapter_id || null,
          ksiazka_nazwa: data.ksiazka_nazwa || "",
          rozdzial_nazwa: data.rozdzial_nazwa || ""
        });
      }
      setIsFormVisible(true);
    } catch (err) {
      console.error("Suggestion error:", err);
      setIsFormVisible(true); // Still show form even if AI fails
    } finally {
      setIsSuggesting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    if (e && e.preventDefault) e.preventDefault();
    if (!content.trim()) return;
    try {
      setStatus("Wysyłanie...");
      const res = await fetch(`${apiUrl}/api/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "token": token || "" },
        body: JSON.stringify({
          title,
          content,
          image,
          tags: [
            ...(noteData.rozwiazanie ? [{ name: "Rozwiązanie", value: noteData.rozwiazanie }] : []),
            ...(noteData.podrozwiazanie ? [{ name: "Podrozwiązanie", value: noteData.podrozwiazanie }] : []),
            ...(noteData.produkt ? [{ name: "Produkt", value: noteData.produkt }] : []),
            ...(noteData.obszar ? [{ name: "Obszar", value: noteData.obszar }] : []),
            ...(noteData.firma ? [{ name: "Firma", value: noteData.firma }] : []),
          ],
          priority,
          book_id: noteData.book_id,
          chapter_id: noteData.chapter_id
        }),
      });
      if (res.ok) {
        setStatus("Wysłano pomyślnie!");
        setTitle("");
        setContent("");
        setImage(null);
        setNoteData({
          rozwiazanie: "",
          podrozwiazanie: "",
          produkt: "",
          obszar: "",
          firma: "",
          book_id: null,
          chapter_id: null,
          ksiazka_nazwa: "",
          rozdzial_nazwa: ""
        });
        setPriority(0);
        setIsFormVisible(false);
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
    <main className={`app-container ${view === "IDLE" ? "idle-view" : ""}`}>
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
                <>
                  <form onSubmit={handleSubmit} className="note-form">
                    <input
                      className="title-input"
                      type="text"
                      placeholder="Tytuł wpisu..."
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      autoFocus
                    />

                    <div className="editor-toolbar bookstack-style">
                      <div className="toolbar-section">
                        <button type="button" onClick={() => editor?.chain().focus().undo().run()} title="Cofnij">↺</button>
                        <button type="button" onClick={() => editor?.chain().focus().redo().run()} title="Ponów">↻</button>
                      </div>

                      <div className="toolbar-divider"></div>

                      <div className="toolbar-section">
                        <select
                          className="format-dropdown"
                          onChange={(e) => {
                            const val = e.target.value;
                            if (val === 'p') editor?.chain().focus().setParagraph().run();
                            else if (val.startsWith('h')) editor?.chain().focus().toggleHeading({ level: parseInt(val[1]) as any }).run();
                          }}
                          value={
                            editor?.isActive('heading', { level: 2 }) ? 'h2' :
                              editor?.isActive('heading', { level: 3 }) ? 'h3' :
                                editor?.isActive('heading', { level: 4 }) ? 'h4' : 'p'
                          }
                        >
                          <option value="p">Paragraf</option>
                          <option value="h2">Nagłówek 2</option>
                          <option value="h3">Nagłówek 3</option>
                          <option value="h4">Nagłówek 4</option>
                        </select>
                      </div>

                      <div className="toolbar-divider"></div>

                      <div className="toolbar-section">
                        <button type="button" onClick={() => handleFormat('bold')} className={editor?.isActive('bold') ? 'active' : ''} title="Pogrubienie"><b>B</b></button>
                        <button type="button" onClick={() => handleFormat('italic')} className={editor?.isActive('italic') ? 'active' : ''} title="Kursywa"><i>I</i></button>
                        <button type="button" onClick={() => handleFormat('underline')} className={editor?.isActive('underline') ? 'active' : ''} title="Podkreślenie"><u>U</u></button>
                      </div>

                      <div className="toolbar-divider"></div>

                      <div className="toolbar-section">
                        <button type="button" onClick={() => handleFormat('alignLeft')} className={editor?.isActive({ textAlign: 'left' }) ? 'active' : ''}>≡</button>
                        <button type="button" onClick={() => handleFormat('alignCenter')} className={editor?.isActive({ textAlign: 'center' }) ? 'active' : ''}>≣</button>
                        <button type="button" onClick={() => handleFormat('alignRight')} className={editor?.isActive({ textAlign: 'right' }) ? 'active' : ''}>≡</button>
                      </div>

                      <div className="toolbar-divider"></div>

                      <div className="toolbar-section">
                        <button type="button" onClick={() => handleFormat('bulletList')} className={editor?.isActive('bulletList') ? 'active' : ''}>•</button>
                        <button type="button" onClick={() => handleFormat('orderedList')} className={editor?.isActive('orderedList') ? 'active' : ''}>1.</button>
                      </div>

                      <div className="toolbar-divider"></div>

                      <div className="toolbar-section">
                        <button type="button" onClick={() => handleFormat('table')} title="Tabela">⊞</button>
                        <button type="button" onClick={() => handleFormat('hr')} title="Linia">―</button>
                        <button type="button" onClick={() => setCallout('info')} title="Cytat">❝</button>
                      </div>

                      <div className="toolbar-divider"></div>

                      <div className="toolbar-section">
                        <select
                          className="language-selector-mini"
                          onChange={(e) => handleFormat('codeBlock', e.target.value)}
                          value={editor?.getAttributes('codeBlock').language || ""}
                        >
                          <option value="">Kod...</option>
                          <option value="javascript">JS</option>
                          <option value="python">PY</option>
                          <option value="sql">SQL</option>
                          <option value="csharp">C#</option>
                          <option value="php">PHP</option>
                          <option value="html">HTML</option>
                        </select>
                      </div>
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

                    {!isFormVisible && (
                      <div className="pre-form-actions">
                        <button
                          type="button"
                          className={`suggest-action-btn ${isSuggesting ? 'loading' : ''}`}
                          onClick={handleSuggest}
                          disabled={!content.trim() || isSuggesting}
                        >
                          {isSuggesting ? (
                            <>
                              <div className="spinner"></div>
                              <span>Analizowanie treści...</span>
                            </>
                          ) : (
                            "Dalej / Analizuj"
                          )}
                        </button>
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
                    </div>
                  </form>

                  {isFormVisible && (
                    <div className="meta-overlay-wrapper fade-in" onClick={() => setIsFormVisible(false)}>
                      <div className="meta-overlay-content" onClick={e => e.stopPropagation()}>
                        <div className="meta-header">
                          <div className="ai-badge">🤖 Zasugerowane przez AI</div>
                          <h3>Analiza i Metadane</h3>
                          <button type="button" className="close-overlay-btn" onClick={() => setIsFormVisible(false)}>✕</button>
                        </div>

                        <div className="meta-body">
                          <div className="meta-grid">
                            <div className="meta-group">
                              <h4>Kategorie i Tagi</h4>
                              <div className="note-form-grid">
                                <div className="form-field">
                                  <label>Rozwiązanie:</label>
                                  <input
                                    placeholder="Np. sql, skrypt..."
                                    value={noteData.rozwiazanie}
                                    onChange={(e) => setNoteData({ ...noteData, rozwiazanie: e.target.value })}
                                  />
                                </div>

                                <div className="form-field">
                                  <label>Podrozwiązanie:</label>
                                  <input
                                    placeholder="Np. procedura, widok..."
                                    value={noteData.podrozwiazanie}
                                    onChange={(e) => setNoteData({ ...noteData, podrozwiazanie: e.target.value })}
                                  />
                                </div>

                                <div className="form-field">
                                  <label>Produkt:</label>
                                  <input
                                    placeholder="Np. dms, xl, optima..."
                                    value={noteData.produkt}
                                    onChange={(e) => setNoteData({ ...noteData, produkt: e.target.value })}
                                  />
                                </div>

                                <div className="form-field">
                                  <label>Obszar:</label>
                                  <input
                                    placeholder="Np. handel, księgowość..."
                                    value={noteData.obszar}
                                    onChange={(e) => setNoteData({ ...noteData, obszar: e.target.value })}
                                  />
                                </div>

                                <div className="form-field">
                                  <label>Firma:</label>
                                  <input
                                    placeholder="Np. firma..."
                                    value={noteData.firma}
                                    onChange={(e) => setNoteData({ ...noteData, firma: e.target.value })}
                                  />
                                </div>

                                <div className="form-field">
                                  <label>Priorytet:</label>
                                  <input
                                    type="number"
                                    value={priority}
                                    onChange={(e) => setPriority(parseInt(e.target.value) || 0)}
                                  />
                                </div>
                              </div>
                            </div>

                            <div className="meta-group placement-group">
                              <h4>Miejsce w Bazie Wiedzy</h4>
                              <div className="placement-info">
                                <div className="form-field">
                                  <label>Książka (Docelowa):</label>
                                  <div className="suggestion-readonly">
                                    {noteData.ksiazka_nazwa || "Domyślna (notatki)"}
                                  </div>
                                </div>
                                {noteData.rozdzial_nazwa && (
                                  <div className="form-field">
                                    <label>Rozdział:</label>
                                    <div className="suggestion-readonly">
                                      {noteData.rozdzial_nazwa}
                                    </div>
                                  </div>
                                )}
                                <p className="placement-hint">AI wybrało powyższą lokalizację na podstawie struktury Twojej bazy wiedzy.</p>
                              </div>
                            </div>
                          </div>
                        </div>

                        <div className="overlay-footer">
                          <button type="button" className="cancel-btn" onClick={() => setIsFormVisible(false)}>Cofnij do edycji</button>
                          <button type="button" className="confirm-btn" onClick={handleSubmit}>Potwierdź i Zapisz Notatkę</button>
                        </div>
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <div className="chat-container">
                  <div className="chat-header-actions">
                    <div className="recent-chats-list">
                      <button
                        className="new-chat-btn"
                        onClick={() => {
                          setChatMessages([]);
                          setCurrentConversationId(null);
                        }}
                      >
                        + Nowy Czat
                      </button>
                      <div className="recent-items">
                        {recentConversations.map(c => (
                          <div key={c.id} className="recent-chat-wrapper">
                            <button
                              className={`recent-chat-item ${currentConversationId === c.id ? 'active' : ''}`}
                              onClick={async () => {
                                try {
                                  setStatus("Ładowanie...");
                                  const res = await fetch(`${apiUrl}/api/conversations/${c.id}`, {
                                    headers: { "token": token || "" }
                                  });
                                  const data = await res.json();
                                  if (res.ok) {
                                    setChatMessages(data);
                                    setCurrentConversationId(c.id);
                                  }
                                  setStatus("");
                                } catch (e) { setStatus("Błąd ładowania"); }
                              }}
                              title={c.title}
                            >
                              {c.title.length > 15 ? c.title.substring(0, 15) + "..." : c.title}
                            </button>
                            <button
                              className="delete-chat-btn"
                              title="Usuń konwersację"
                              onClick={async (e) => {
                                e.stopPropagation();
                                if (!window.confirm("Czy na pewno chcesz usunąć tę konwersację?")) return;
                                try {
                                  const res = await fetch(`${apiUrl}/api/conversations/${c.id}`, {
                                    method: 'DELETE',
                                    headers: { "token": token || "" }
                                  });
                                  if (res.ok) {
                                    if (currentConversationId === c.id) {
                                      setChatMessages([]);
                                      setCurrentConversationId(null);
                                    }
                                    fetchRecentConversations();
                                  }
                                } catch (e) { console.error("Error deleting chat", e); }
                              }}
                            >✕</button>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

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
                    <label className={`chat-upload-btn ${isUploading ? 'loading' : ''}`} title="Wgraj plik do analizy">
                      {isUploading ? <div className="spinner"></div> : "📎"}
                      <input type="file" onChange={handleFileUpload} disabled={isUploading} hidden />
                    </label>
                    <input
                      type="text"
                      className="chat-input-field"
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
                  <input type="text" placeholder="Adres API (np. http://localhost:8000)" value={apiUrl} onChange={e => setApiUrl(e.target.value)} required />
                  <input type="text" placeholder="Użytkownik" value={loginForm.user} onChange={e => setLoginForm({ ...loginForm, user: e.target.value })} required />
                  <input type="password" placeholder="Hasło" value={loginForm.pass} onChange={e => setLoginForm({ ...loginForm, pass: e.target.value })} required />
                  <button type="submit" className="submit-btn login-btn">Zaloguj</button>
                </form>
              </div>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

export default App;
