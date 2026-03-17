const express = require('express');
const cors = require('cors');
const sqlite3 = require('sqlite3');
const { open } = require('sqlite');
const path = require('path');

const app = express();
app.use(cors());
app.use(express.json());

const PORT = 3000;
const DB_PATH = path.join(__dirname, 'database.sqlite');

let db;

(async () => {
    // Open the local database
    db = await open({
        filename: DB_PATH,
        driver: sqlite3.Database
    });

    // Create table for notes if it doesn't exist
    await db.exec(`
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    `);

    console.log('Database initialized.');
})();

// Endpoint to receive notes
app.post('/api/notes', async (req, res) => {
    const { content } = req.body;
    if (!content) {
        return res.status(400).json({ error: 'Content is required' });
    }

    try {
        const result = await db.run('INSERT INTO notes (content) VALUES (?)', content);
        res.status(201).json({ id: result.lastID, success: true });
        console.log(`Note added: ${content}`);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Failed to save note' });
    }
});

// Endpoint to list all notes (optional, for verification)
app.get('/api/notes', async (req, res) => {
    try {
        const notes = await db.all('SELECT * FROM notes ORDER BY created_at DESC');
        res.json(notes);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Failed to fetch notes' });
    }
});

app.listen(PORT, () => {
    console.log(`Server running at http://localhost:${PORT}`);
});
