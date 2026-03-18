import { useState, useEffect } from 'react';
import { 
  LayoutDashboard, Database, FileText, Activity, Layers, 
  LogOut, Lock, User as UserIcon, Key, Trash2, RefreshCw,
  Search, Info, ChevronLeft, ChevronRight, Eye, UserPlus, Tag, Plus, X
} from 'lucide-react';

interface Label { name: string; color: string; }
interface UserData { username: string; role: string; created_at: string; note_count: number; }
interface KBItem { id: string; metadata: any; content?: string; loadingContent?: boolean; }
interface LogEntry { id: number; username: string; query: string; created_at: string; }

function App() {
  const [isLoggedIn, setIsLoggedIn] = useState<boolean>(!!localStorage.getItem("token"));
  const [activeTab, setActiveTab] = useState<'dashboard' | 'users' | 'logs' | 'kb' | 'labels'>('dashboard');
  
  // Data States
  const [stats, setStats] = useState<any[]>([]);
  const [users, setUsers] = useState<UserData[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [kbItems, setKbItems] = useState<KBItem[]>([]);
  const [labels, setLabels] = useState<Label[]>([]);
  const [kbTotal, setKbTotal] = useState(0);
  const [kbPage, setKbPage] = useState(1);
  const kbSize = 10;

  // Form states
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newLabel, setNewLabel] = useState({ name: '', color: '#2563eb' });
  const [loginForm, setLoginForm] = useState({ user: 'Admin', pass: '' });
  const [newUser, setNewUser] = useState({ username: '', password: '', role: 'user' });

  const API_BASE = "http://192.168.13.131:8000"; 
  const TOKEN = localStorage.getItem("token");

  const fetchData = async () => {
    if (!TOKEN) return;
    setLoading(true);
    setError(null);
    try {
      const endpoints: Record<string, string> = {
        dashboard: "/api/admin/stats",
        users: "/api/admin/users",
        logs: "/api/admin/logs",
        labels: "/api/admin/labels",
        kb: `/api/admin/kb?page=${kbPage}&size=${kbSize}`
      };
      
      const res = await fetch(`${API_BASE}${endpoints[activeTab]}`, { 
        headers: { "token": TOKEN } 
      });

      if (res.status === 440 || res.status === 401 || res.status === 403) {
        handleLogout();
        return;
      }

      const data = await res.json();
      if (activeTab === 'dashboard') setStats(Array.isArray(data) ? data : []);
      else if (activeTab === 'users') setUsers(Array.isArray(data) ? data : []);
      else if (activeTab === 'logs') setLogs(Array.isArray(data) ? data : []);
      else if (activeTab === 'labels') setLabels(Array.isArray(data) ? data : []);
      else if (activeTab === 'kb') {
        setKbItems(data.items || []);
        setKbTotal(data.total || 0);
      }
    } catch (e) {
      setError("Synchronizacja nieudana. Sprawdź połączenie z API.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isLoggedIn) fetchData();
  }, [activeTab, kbPage, isLoggedIn]);

  const handleLogout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    setIsLoggedIn(false);
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/login`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username: loginForm.user, password: loginForm.pass})
      });
      const data = await res.json();
      if (res.ok && data.role === 'admin') {
        localStorage.setItem('token', data.token);
        localStorage.setItem('username', data.username);
        setIsLoggedIn(true);
      } else {
        setError(data.detail || "Błąd logowania lub brak uprawnień admina.");
      }
    } catch (err) {
      setError("Błąd połączenia z serwerem.");
    } finally {
      setLoading(false);
    }
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/api/admin/users`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "token": TOKEN || "" },
        body: JSON.stringify(newUser)
      });
      if (res.ok) {
        setNewUser({ username: '', password: '', role: 'user' });
        fetchData();
        alert("Utworzono użytkownika!");
      } else {
        const d = await res.json();
        alert("Błąd: " + (d.detail || "Nieznany"));
      }
    } catch (err) { alert("Błąd połączenia."); }
  };

  const handleDeleteUser = async (u: string) => {
    if (u === 'Admin') { alert("Nie można usunąć konta Admin."); return; }
    if (!window.confirm(`Usunąć ${u}?`)) return;
    await fetch(`${API_BASE}/api/admin/users/${u}`, { method: 'DELETE', headers: { 'token': TOKEN || '' } });
    fetchData();
  };

  const handleAddLabel = async () => {
    if (!newLabel.name) return;
    await fetch(`${API_BASE}/api/admin/labels`, {
      method: 'POST',
      headers: {'token': TOKEN || '', 'Content-Type': 'application/json'},
      body: JSON.stringify(newLabel)
    });
    setNewLabel({ name: '', color: '#2563eb' });
    fetchData();
  };

  const fetchChunkContent = async (id: string) => {
    setKbItems(prev => prev.map(i => i.id === id ? { ...i, loadingContent: true } : i));
    try {
      const res = await fetch(`${API_BASE}/api/admin/kb/${id}`, { headers: { "token": TOKEN || "" } });
      const data = await res.json();
      setKbItems(prev => prev.map(i => i.id === id ? { ...i, content: data.content, loadingContent: false } : i));
    } catch (e) {
      setKbItems(prev => prev.map(i => i.id === id ? { ...i, loadingContent: false } : i));
    }
  };

  const updateChunkMetadata = async (id: string, patch: any) => {
    await fetch(`${API_BASE}/api/admin/kb/${id}/metadata`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'token': TOKEN || '' },
      body: JSON.stringify(patch)
    });
    fetchData();
  };

  const addLabelToChunk = (id: string, label: string) => {
    const item = kbItems.find(i => i.id === id);
    if (!item) return;
    const current = item.metadata.labels ? item.metadata.labels.split(',') : [];
    if (!current.includes(label)) {
      updateChunkMetadata(id, { labels: [...current, label].join(',') });
    }
  };

  const removeLabelFromChunk = (id: string, label: string) => {
    const item = kbItems.find(i => i.id === id);
    if (!item) return;
    const current = item.metadata.labels ? item.metadata.labels.split(',') : [];
    updateChunkMetadata(id, { labels: current.filter((l: string) => l !== label).join(',') });
  };

  if (!isLoggedIn) return (
    <div className="login-screen" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#f1f5f9' }}>
      <div className="glass-panel" style={{ width: '380px', padding: '2.5rem', borderRadius: '16px' }}>
        <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
          <div style={{ width: '56px', height: '56px', background: '#2563eb', borderRadius: '12px', margin: '0 auto 1rem', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Lock color="white" size={28} />
          </div>
          <h1 style={{ fontSize: '1.4rem', fontWeight: 800 }}>ArcusAI Admin</h1>
        </div>
        <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <input className="input-field" placeholder="Login" value={loginForm.user} onChange={e=>setLoginForm({...loginForm, user:e.target.value})} style={{padding:12}} />
          <input className="input-field" type="password" placeholder="Hasło" value={loginForm.pass} onChange={e=>setLoginForm({...loginForm, pass:e.target.value})} style={{padding:12}} />
          {error && <p style={{ color: '#ef4444', fontSize: '0.8rem', textAlign: 'center' }}>{error}</p>}
          <button type="submit" className="btn-primary" style={{padding:12}}>Zaloguj</button>
        </form>
      </div>
    </div>
  );

  return (
    <div className="admin-layout">
      <aside className="sidebar">
        <div className="logo-section"><Layers size={22} color="#2563eb" /><span className="logo-text">ArcusAI</span></div>
        <nav className="nav-menu">
           <div className={`nav-item ${activeTab==='dashboard'?'active':''}`} onClick={()=>setActiveTab('dashboard')}><LayoutDashboard size={18}/> Dashboard</div>
           <div className={`nav-item ${activeTab==='users'?'active':''}`} onClick={()=>setActiveTab('users')}><UserPlus size={18}/> Użytkownicy</div>
           <div className={`nav-item ${activeTab==='kb'?'active':''}`} onClick={()=>setActiveTab('kb')}><Database size={18}/> Baza Wiedzy</div>
           <div className={`nav-item ${activeTab==='labels'?'active':''}`} onClick={()=>setActiveTab('labels')}><Tag size={18}/> Etykiety</div>
           <div className={`nav-item ${activeTab==='logs'?'active':''}`} onClick={()=>setActiveTab('logs')}><Activity size={18}/> Logi</div>
        </nav>
        <div style={{ marginTop: 'auto' }} className="nav-item" onClick={handleLogout}><LogOut size={18} /> Wyloguj</div>
      </aside>

      <main className="main-content">
        <header style={{ display:'flex', justifyContent:'space-between', marginBottom:'2rem' }}>
          <h1 className="section-title" style={{margin:0}}>
            {activeTab==='dashboard'?'Panel Główny': activeTab==='users'?'Użytkownicy': activeTab==='kb'?'Knowledge Base': activeTab==='labels'?'Etykiety AI': 'Logi systemowe'}
          </h1>
          <button onClick={fetchData} className="delete-btn"><RefreshCw size={14} className={loading?'animate-spin':''}/></button>
        </header>

        {activeTab === 'dashboard' && (
          <div className="stats-grid">
            <div className="stat-card"><div className="stat-label">System OK</div><div className="stat-value">{stats.length}</div><p style={{color:'#64748b', fontSize:'0.8rem'}}>Aktywnych profilów</p></div>
            <div className="stat-card"><div className="stat-label">Razem Notatek</div><div className="stat-value">{stats.reduce((a, s) => a + s.notes, 0)}</div></div>
            <div className="stat-card"><div className="stat-label">Razem AI Query</div><div className="stat-value">{stats.reduce((a, s) => a + s.queries, 0)}</div></div>
          </div>
        )}

        {activeTab === 'users' && (
          <section>
            <div className="data-table-container">
              <table className="data-table">
                <thead><tr><th>Użytkownik</th><th>Rola</th><th>Notatki</th><th>Akcja</th></tr></thead>
                <tbody>
                  {users.map(u => (
                    <tr key={u.username}>
                      <td style={{ fontWeight: 600 }}>{u.username}</td>
                      <td><span className={`badge ${u.role === 'admin' ? 'badge-blue' : 'badge-purple'}`}>{u.role}</span></td>
                      <td>{u.note_count}</td>
                      <td><button disabled={u.username === 'Admin'} onClick={()=>handleDeleteUser(u.username)} className="delete-btn"><Trash2 size={16} /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="glass-panel" style={{ marginTop: '2rem', padding: '1.5rem', background: '#f8fafc' }}>
               <h4>Dodaj nowego użytkownika</h4>
               <form onSubmit={handleCreateUser} style={{ display: 'flex', gap: '1rem' }}>
                 <input className="input-field" placeholder="Username" value={newUser.username} onChange={e=>setNewUser({...newUser, username:e.target.value})} style={{padding:8, borderRadius:6}} />
                 <input className="input-field" type="password" placeholder="Pass" value={newUser.password} onChange={e=>setNewUser({...newUser, password:e.target.value})} style={{padding:8, borderRadius:6}} />
                 <button className="btn-primary" style={{padding:'8px 16px', borderRadius:6}}>Utwórz</button>
               </form>
            </div>
          </section>
        )}

        {activeTab === 'logs' && (
          <div className="data-table-container">
            <table className="data-table">
              <thead><tr><th>Czas</th><th>User</th><th>Query</th></tr></thead>
              <tbody>
                {logs.map(log => (
                  <tr key={log.id}>
                    <td style={{fontSize:'0.8rem', color:'#64748b'}}>{new Date(log.created_at).toLocaleString()}</td>
                    <td style={{fontWeight:600}}>{log.username}</td>
                    <td>{log.query}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {activeTab === 'labels' && (
          <section>
            <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: '2rem', background: '#f8fafc' }}>
              <h4>Nowa etykieta AI</h4>
              <div style={{ display: 'flex', gap: '1rem' }}>
                <input className="input-field" placeholder="Nazwa" value={newLabel.name} onChange={e=>setNewLabel({...newLabel, name: e.target.value})} style={{padding:8}} />
                <input type="color" value={newLabel.color} onChange={e=>setNewLabel({...newLabel, color: e.target.value})} style={{height:40}} />
                <button className="btn-primary" style={{padding:'4px 20px', borderRadius:6}} onClick={handleAddLabel}>Dodaj</button>
              </div>
            </div>
            <div className="stats-grid">
              {labels.map(l => (
                <div key={l.name} className="stat-card" style={{ borderLeft: `5px solid ${l.color}` }}>
                  <div className="stat-label">Etykieta</div>
                  <div className="stat-value" style={{ fontSize: '1.2rem' }}>{l.name}</div>
                </div>
              ))}
            </div>
          </section>
        )}

        {activeTab === 'kb' && (
          <>
            <div className="kb-list">
              {kbItems.map(item => (
                <div key={item.id} className="kb-item">
                  <div className="kb-icon" style={{ background: item.metadata.type === 'note' ? '#f3e8ff' : '#dbeafe' }}>{item.metadata.type === 'note' ? <Layers size={20} color="#6b21a8" /> : <FileText size={20} color="#1e40af" />}</div>
                  <div className="kb-content">
                    <div className="kb-header">
                      <div className="kb-title">{item.metadata.filename || item.metadata.title || 'Chunk'} <span style={{fontSize:10, color:'#94a3b8'}}>{item.id}</span></div>
                      <div style={{ display:'flex', gap:8 }}>
                        <select className="meta-pill" style={{cursor:'pointer'}} onChange={(e) => { addLabelToChunk(item.id, e.target.value); e.target.value = ""; }} value="">
                           <option value="" disabled>+ Etykieta</option>
                           {labels.map(l => <option key={l.name} value={l.name}>{l.name}</option>)}
                        </select>
                        <button className="delete-btn" onClick={()=>fetchChunkContent(item.id)}><Eye size={16}/></button>
                        <button className="delete-btn"><Trash2 size={16}/></button>
                      </div>
                    </div>
                    {item.content && <div style={{ background: '#f8fafc', padding: '10px', borderRadius: 8, fontSize: '0.85rem', marginBottom: 10, border: '1px dashed #e2e8f0' }}>{item.content}</div>}
                    {item.loadingContent && <div style={{fontSize:'0.8rem', color:'#2563eb'}}>Wczytywanie...</div>}
                    <div className="kb-meta-pills" style={{ display:'flex', flexWrap:'wrap', gap:6 }}>
                      <span className="meta-pill" style={{background:'#f1f5f9'}}>Typ: {item.metadata.type}</span>
                      <span className="meta-pill" style={{background:'#f1f5f9'}}>Autor: {item.metadata.author || 'System'}</span>
                      {item.metadata.labels && item.metadata.labels.split(',').map((l: string) => (
                        <span key={l} className="badge badge-blue" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                          {l} <X size={10} style={{cursor:'pointer'}} onClick={()=>removeLabelFromChunk(item.id, l)} />
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div style={{ display:'flex', gap:20, justifyContent:'center', marginTop:20 }}>
               <button disabled={kbPage===1} onClick={()=>setKbPage(p=>p-1)} className="delete-btn"><ChevronLeft/></button>
               <span style={{fontWeight:600}}>Strona {kbPage} / {Math.ceil(kbTotal/kbSize)}</span>
               <button disabled={kbPage >= Math.ceil(kbTotal/kbSize)} onClick={()=>setKbPage(p=>p+1)} className="delete-btn"><ChevronRight/></button>
            </div>
          </>
        )}
      </main>
      <style>{`.animate-spin { animation: spin 2s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

export default App;
