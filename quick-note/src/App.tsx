import { useState, useEffect } from "react";
import { getCurrentWindow, LogicalSize, LogicalPosition } from "@tauri-apps/api/window";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";
import logo from "./assets/logo.png";

type ViewState = "IDLE" | "ACTIONS" | "FORM" | "INFO";

function App() {
  const [view, setView] = useState<ViewState>("IDLE");
  const [isLocked, setIsLocked] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [image, setImage] = useState<string | null>(null);
  const [status, setStatus] = useState("");

  const takeScreenshot = async () => {
    try {
      setStatus("Wybierz obszar...");
      const b64Image = await invoke<string>("take_screenshot");
      if (b64Image) {
        setImage(b64Image);
        setStatus("Zrzut dołączony");
        setTimeout(() => setStatus(""), 2000);
      }
    } catch (err) {
      console.error(err);
      setStatus("Błąd zrzutu");
    }
  };

  useEffect(() => {
    const setupWindow = async () => {
      try {
        const win = getCurrentWindow();
        const screenWidth = window.screen.width;
        await win.setSize(new LogicalSize(64, 64));
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
    
    let width = 64;
    let height = 64;
    let xOffset = 80;

    if (targetView === "ACTIONS") {
      width = 200; // Stabilized width for logo + 2 buttons
      xOffset = 210;
    } else if (targetView === "FORM") {
      width = Math.floor(screenWidth / 4);
      height = Math.floor(screenHeight / 2);
      xOffset = width + 20;
    } else if (targetView === "INFO") {
      width = 400;
      height = 250;
      xOffset = 420;
    }

    try {
      await win.setPosition(new LogicalPosition(screenWidth - xOffset, 40));
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!content.trim()) return;
    try {
      setStatus("Wysyłanie...");
      const res = await fetch("http://localhost:8000/api/notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, content, image }),
      });
      if (res.ok) {
        setStatus("Wysłano pomyślnie!");
        setTitle("");
        setContent("");
        setImage(null);
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
    <main 
      className={`app-container view-${view}`}
      onMouseLeave={() => view === "ACTIONS" && updateWindow("IDLE")}
    >
      <div className="interaction-wrapper">
        {/* Main Trigger Icon */}
        <div 
          className="main-trigger"
          onMouseEnter={() => view === "IDLE" && updateWindow("ACTIONS")}
          onClick={() => {
            if (view === "IDLE") {
              updateWindow("ACTIONS");
            } else if (view === "ACTIONS") {
              updateWindow("IDLE");
            } else {
              handleMinimize();
            }
          }}
        >
          <div className="icon-wrapper">
            <img src={logo} className="app-logo" alt="ArcusAi" />
          </div>
        </div>

        {/* Action Buttons Slide Out */}
        {view === "ACTIONS" && (
          <div className="actions-overlay">
            <button 
              className="action-btn plus" 
              onClick={(e) => {
                e.stopPropagation();
                updateWindow("FORM");
              }}
              title="Dodaj notatkę"
            >
              +
            </button>
            <button 
              className="action-btn info" 
              onClick={(e) => {
                e.stopPropagation();
                updateWindow("INFO");
              }}
              title="Informacje"
            >
              ?
            </button>
          </div>
        )}
      </div>

      {/* Note Form Panel */}
      {view === "FORM" && (
        <div className="panel-content form-view">
          <div className="panel-header">
            <div className="header-title">
               <img src={logo} className="header-logo" alt="logo" />
               <span>Nowy wpis</span>
            </div>
            <button className="close-btn" onClick={handleMinimize}>✕</button>
          </div>
          <form onSubmit={handleSubmit}>
            <input 
              className="title-input"
              type="text" 
              placeholder="Tytuł wpisu..."
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              autoFocus
            />
            <textarea
              className="content-input"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Treść notatki..."
              rows={image ? 3 : 6}
            />
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
                className="screenshot-btn" 
                onClick={takeScreenshot}
                title="Zrób zrzut ekranu"
              >
                📷 Zrób zrzut
              </button>
              <button type="submit" className="submit-btn" onClick={(e) => e.stopPropagation()}>Zapisz w ArcusAi</button>
            </div>
          </form>
          {status && <p className="status-msg">{status}</p>}
        </div>
      )}

      {/* Info Panel */}
      {view === "INFO" && (
        <div className="panel-content info-view">
          <div className="panel-header">
            <div className="header-title">
               <img src={logo} className="header-logo" alt="logo" />
               <span>O ArcusAi</span>
            </div>
            <button className="close-btn" onClick={handleMinimize}>✕</button>
          </div>
          <div className="info-body">
            <p><strong>ArcusAi</strong> to Twój inteligentny system do szybkich notatek.</p>
            <p>Zapisuj pomysły, zadania i ważne informacje jednym kliknięciem.</p>
            <p className="version-info">Wersja 1.2.5 • Backend Python</p>
          </div>
        </div>
      )}
    </main>
  );
}

export default App;
