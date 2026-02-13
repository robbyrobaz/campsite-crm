const express = require('express');
const cors = require('cors');
const sqlite3 = require('sqlite3').verbose();
const path = require('path');
const { v4: uuidv4 } = require('uuid');
const moment = require('moment');

const app = express();
const PORT = process.env.PORT || 5000;

// Middleware
app.use(cors());
app.use(express.json());

// Database setup
const dbPath = path.join(__dirname, 'campsite_crm.db');
const db = new sqlite3.Database(dbPath, (err) => {
  if (err) console.error('Database connection error:', err);
  else console.log('Connected to SQLite database at', dbPath);
});

// Initialize database tables
const initDb = () => {
  db.serialize(() => {
    // Bookings table
    db.run(`
      CREATE TABLE IF NOT EXISTS bookings (
        id TEXT PRIMARY KEY,
        booking_date TEXT NOT NULL,
        guest_name TEXT NOT NULL,
        guest_type TEXT NOT NULL,
        group_type TEXT,
        nights INTEGER NOT NULL,
        area_rented TEXT NOT NULL,
        revenue REAL NOT NULL,
        status TEXT DEFAULT 'active',
        is_return_booking INTEGER DEFAULT 0,
        notes TEXT,
        created_at TEXT,
        updated_at TEXT
      )
    `);

    // Monthly horse group contracts
    db.run(`
      CREATE TABLE IF NOT EXISTS contracts (
        id TEXT PRIMARY KEY,
        contract_name TEXT NOT NULL,
        group_name TEXT NOT NULL,
        base_monthly_rate REAL NOT NULL,
        per_guest_rate REAL,
        start_date TEXT NOT NULL,
        end_date TEXT,
        status TEXT DEFAULT 'active',
        created_at TEXT,
        updated_at TEXT
      )
    `);

    // Return guest tracking
    db.run(`
      CREATE TABLE IF NOT EXISTS guest_history (
        id TEXT PRIMARY KEY,
        guest_name TEXT NOT NULL,
        total_visits INTEGER DEFAULT 1,
        total_revenue REAL DEFAULT 0,
        last_visit_date TEXT,
        created_at TEXT,
        updated_at TEXT
      )
    `);
  });
};

initDb();

// Routes

// Get dashboard summary
app.get('/api/dashboard/summary', (req, res) => {
  const { startDate, endDate } = req.query;
  const start = startDate || moment().startOf('month').format('YYYY-MM-DD');
  const end = endDate || moment().endOf('month').format('YYYY-MM-DD');

  db.all(`
    SELECT
      COUNT(*) as total_bookings,
      SUM(nights) as total_nights,
      SUM(revenue) as total_revenue,
      COUNT(CASE WHEN is_return_booking = 1 THEN 1 END) as return_bookings
    FROM bookings
    WHERE booking_date BETWEEN ? AND ?
  `, [start, end], (err, rows) => {
    if (err) res.status(500).json({ error: err.message });
    else res.json(rows[0]);
  });
});

// Get bookings by date range
app.get('/api/bookings', (req, res) => {
  const { startDate, endDate, groupBy = 'day' } = req.query;
  const start = startDate || moment().startOf('month').format('YYYY-MM-DD');
  const end = endDate || moment().endOf('month').format('YYYY-MM-DD');

  db.all(`
    SELECT * FROM bookings
    WHERE booking_date BETWEEN ? AND ?
    ORDER BY booking_date DESC
  `, [start, end], (err, rows) => {
    if (err) res.status(500).json({ error: err.message });
    else res.json(rows || []);
  });
});

// Get bookings grouped by period
app.get('/api/bookings/grouped/:period', (req, res) => {
  const { period } = req.params;
  const { startDate, endDate } = req.query;
  const start = startDate || moment().startOf('month').format('YYYY-MM-DD');
  const end = endDate || moment().endOf('month').format('YYYY-MM-DD');

  let groupByClause;
  switch(period) {
    case 'week':
      groupByClause = `strftime('%Y-W%W', booking_date)`;
      break;
    case 'month':
      groupByClause = `strftime('%Y-%m', booking_date)`;
      break;
    case 'day':
    default:
      groupByClause = `strftime('%Y-%m-%d', booking_date)`;
  }

  db.all(`
    SELECT
      ${groupByClause} as period,
      COUNT(*) as booking_count,
      SUM(nights) as total_nights,
      SUM(revenue) as total_revenue
    FROM bookings
    WHERE booking_date BETWEEN ? AND ?
    GROUP BY ${groupByClause}
    ORDER BY period DESC
  `, [start, end], (err, rows) => {
    if (err) res.status(500).json({ error: err.message });
    else res.json(rows || []);
  });
});

// Create new booking
app.post('/api/bookings', (req, res) => {
  const { guest_name, guest_type, group_type, nights, area_rented, revenue, notes } = req.body;
  const id = uuidv4();
  const now = moment().format('YYYY-MM-DD HH:mm:ss');
  const bookingDate = moment().format('YYYY-MM-DD');

  db.run(`
    INSERT INTO bookings (id, booking_date, guest_name, guest_type, group_type, nights, area_rented, revenue, notes, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `, [id, bookingDate, guest_name, guest_type, group_type, nights, area_rented, revenue, notes, now, now], 
  function(err) {
    if (err) res.status(500).json({ error: err.message });
    else res.status(201).json({ id, message: 'Booking created successfully' });
  });
});

// Update booking
app.put('/api/bookings/:id', (req, res) => {
  const { id } = req.params;
  const { guest_name, guest_type, group_type, nights, area_rented, revenue, notes, is_return_booking } = req.body;
  const now = moment().format('YYYY-MM-DD HH:mm:ss');

  db.run(`
    UPDATE bookings
    SET guest_name = ?, guest_type = ?, group_type = ?, nights = ?, area_rented = ?, revenue = ?, notes = ?, is_return_booking = ?, updated_at = ?
    WHERE id = ?
  `, [guest_name, guest_type, group_type, nights, area_rented, revenue, notes, is_return_booking || 0, now, id],
  function(err) {
    if (err) res.status(500).json({ error: err.message });
    else res.json({ message: 'Booking updated successfully' });
  });
});

// Delete booking
app.delete('/api/bookings/:id', (req, res) => {
  const { id } = req.params;
  db.run(`DELETE FROM bookings WHERE id = ?`, [id], function(err) {
    if (err) res.status(500).json({ error: err.message });
    else res.json({ message: 'Booking deleted successfully' });
  });
});

// Get return guest analysis
app.get('/api/return-guests', (req, res) => {
  db.all(`
    SELECT guest_name, COUNT(*) as visit_count, SUM(revenue) as total_revenue
    FROM bookings
    GROUP BY guest_name
    HAVING COUNT(*) > 1
    ORDER BY total_revenue DESC
  `, [], (err, rows) => {
    if (err) res.status(500).json({ error: err.message });
    else res.json(rows || []);
  });
});

// Get area utilization
app.get('/api/areas', (req, res) => {
  const { startDate, endDate } = req.query;
  const start = startDate || moment().startOf('month').format('YYYY-MM-DD');
  const end = endDate || moment().endOf('month').format('YYYY-MM-DD');

  db.all(`
    SELECT
      area_rented,
      COUNT(*) as booking_count,
      SUM(revenue) as total_revenue,
      SUM(nights) as total_nights
    FROM bookings
    WHERE booking_date BETWEEN ? AND ?
    GROUP BY area_rented
    ORDER BY total_revenue DESC
  `, [start, end], (err, rows) => {
    if (err) res.status(500).json({ error: err.message });
    else res.json(rows || []);
  });
});

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'OK', timestamp: new Date().toISOString() });
});

// Start server
app.listen(PORT, () => {
  console.log(`✨ Campsite CRM Server running on port ${PORT}`);
  console.log(`📊 Dashboard available at http://localhost:3000`);
});
