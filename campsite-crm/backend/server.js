const express = require('express');
const cors = require('cors');
const sqlite3 = require('sqlite3').verbose();
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const { v4: uuidv4 } = require('uuid');
const moment = require('moment');

const app = express();
const PORT = process.env.PORT || 5000;

const STATUS_OPTIONS = ['active', 'confirmed', 'checked-in', 'checked-out', 'canceled', 'no-show'];
const WAITLIST_STATUS_OPTIONS = ['waiting', 'contacted', 'converted', 'closed'];
const TASK_STATUS_OPTIONS = ['todo', 'in_progress', 'done'];
const CONTACT_STATUS_OPTIONS = ['lead', 'active', 'vip', 'inactive'];
const OPENAI_RESPONSES_URL = 'https://api.openai.com/v1/responses';
const GMAIL_API_BASE = 'https://gmail.googleapis.com/gmail/v1/users/me';
const GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token';
const GOOGLE_USERINFO_URL = 'https://www.googleapis.com/oauth2/v2/userinfo';
const GOOGLE_OAUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth';
const GMAIL_SCOPE = 'https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/userinfo.email';
// In production (SERVE_FRONTEND_BUILD=1) frontend and backend share the same origin.
// In development the React dev server runs on port 3000.
const FRONTEND_URL = process.env.FRONTEND_URL || (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:3000');

const AREA_CAPACITY = {
  cabin: 8,
  'tent site': 20,
  tent: 20,
  kitchen: 1,
  'kitchen area': 1,
  barn: 2,
  pavilion: 1,
  mixed: 4
};

const AREA_DETAILS = {
  cabin: {
    label: 'Cabin',
    base_rate: 110,
    max_party_size: 8,
    included_guests: 4,
    cleaning_fee: 20,
    amenities: ['heating', 'private restroom', 'power', 'pet-friendly']
  },
  tent: {
    label: 'Tent Site',
    base_rate: 45,
    max_party_size: 6,
    included_guests: 2,
    cleaning_fee: 0,
    amenities: ['fire ring', 'picnic table', 'pet-friendly', 'shade']
  },
  kitchen: {
    label: 'Kitchen Area',
    base_rate: 80,
    max_party_size: 14,
    included_guests: 8,
    cleaning_fee: 12,
    amenities: ['covered shelter', 'prep station', 'lighting', 'group-friendly']
  },
  barn: {
    label: 'Horse Barn',
    base_rate: 95,
    max_party_size: 10,
    included_guests: 4,
    cleaning_fee: 18,
    amenities: ['horse stalls', 'water access', 'lighting', 'trailer space']
  },
  pavilion: {
    label: 'Pavilion',
    base_rate: 70,
    max_party_size: 20,
    included_guests: 10,
    cleaning_fee: 10,
    amenities: ['covered shelter', 'group seating', 'power', 'near restrooms']
  },
  mixed: {
    label: 'Mixed Areas',
    base_rate: 88,
    max_party_size: 12,
    included_guests: 6,
    cleaning_fee: 14,
    amenities: ['custom layout', 'group-friendly', 'flexible setup']
  }
};

const CANCELLATION_POLICY = {
  full_refund_days: 14,
  partial_refund_days: 7,
  non_refundable_days: 6,
  admin_fee: 10
};

const STAY_RULES = {
  min_nights_weekend: 2,
  max_nights: 21,
  max_party_size_absolute: 24,
  same_day_cutoff_hour: 18
};

const SITE_LOCK_FEE = 18;
const CHANGE_FEE = 15;

const sanitizeStatus = (value, fallback = 'active') => {
  if (!value) return fallback;
  const normalized = value.toLowerCase();
  return STATUS_OPTIONS.includes(normalized) ? normalized : fallback;
};

const sanitizeWaitlistStatus = (value, fallback = 'waiting') => {
  if (!value) return fallback;
  const normalized = value.toLowerCase();
  return WAITLIST_STATUS_OPTIONS.includes(normalized) ? normalized : fallback;
};

const sanitizeTaskStatus = (value, fallback = 'todo') => {
  if (!value) return fallback;
  const normalized = value.toLowerCase();
  return TASK_STATUS_OPTIONS.includes(normalized) ? normalized : fallback;
};

const sanitizeContactStatus = (value, fallback = 'lead') => {
  if (!value) return fallback;
  const normalized = String(value).trim().toLowerCase();
  return CONTACT_STATUS_OPTIONS.includes(normalized) ? normalized : fallback;
};

const parseJsonOrFallback = (value, fallback) => {
  if (!value || typeof value !== 'string') return fallback;
  try {
    return JSON.parse(value);
  } catch (error) {
    return fallback;
  }
};

const normalizeDate = (value, fallback = null) => {
  if (!value) return fallback;
  const m = moment(value);
  if (!m.isValid()) return fallback;
  return m.format('YYYY-MM-DD');
};

const normalizeAddOns = (value) => {
  let parsed = [];

  if (Array.isArray(value)) {
    parsed = value;
  } else if (typeof value === 'string' && value.trim()) {
    try {
      const json = JSON.parse(value);
      if (Array.isArray(json)) parsed = json;
    } catch (error) {
      parsed = [];
    }
  }

  return parsed
    .map((item) => {
      const name = String(item?.name || '').trim();
      const price = Math.max(parseFloat(item?.price) || 0, 0);
      const quantity = Math.max(parseInt(item?.quantity, 10) || 1, 1);
      if (!name) return null;
      return {
        name,
        price,
        quantity,
        total: parseFloat((price * quantity).toFixed(2))
      };
    })
    .filter(Boolean);
};

const normalizeAreaKey = (value) => {
  const raw = String(value || 'mixed').trim().toLowerCase();
  if (raw === 'tent site') return 'tent';
  if (AREA_DETAILS[raw]) return raw;
  return 'mixed';
};

const sanitizeAmenities = (value) => {
  if (!value) return [];
  if (Array.isArray(value)) {
    return value.map((item) => String(item || '').trim().toLowerCase()).filter(Boolean);
  }
  return String(value)
    .split(',')
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
};

const normalizeContactTags = (value) => {
  let parsed = [];
  if (Array.isArray(value)) {
    parsed = value;
  } else if (typeof value === 'string' && value.trim()) {
    parsed = value.split(',');
  }

  return parsed
    .map((item) => String(item || '').trim().toLowerCase())
    .filter(Boolean)
    .slice(0, 20);
};

const normalizeEmail = (value) => String(value || '').trim().toLowerCase();

const extractEmailFromText = (value) => {
  const text = String(value || '');
  const match = text.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i);
  return normalizeEmail(match?.[0] || '');
};

const sanitizeContactPayload = (payload = {}, { preserveMissing = false } = {}) => {
  const email = normalizeEmail(payload.email || payload.contact_email);
  const fullName = String(payload.full_name || payload.name || '').trim();
  const phone = String(payload.phone || '').trim();
  const company = String(payload.company || '').trim();
  const sourceProvided = Object.prototype.hasOwnProperty.call(payload, 'contact_source')
    || Object.prototype.hasOwnProperty.call(payload, 'source');
  const statusProvided = Object.prototype.hasOwnProperty.call(payload, 'status');
  const source = sourceProvided
    ? String(payload.contact_source || payload.source || '').trim().toLowerCase()
    : null;
  const status = statusProvided ? sanitizeContactStatus(payload.status, 'lead') : null;
  const tags = normalizeContactTags(payload.tags);
  const notes = String(payload.notes || '').trim();
  const summary = String(payload.conversation_summary || '').trim();

  return {
    full_name: fullName || null,
    email: email || null,
    phone: phone || null,
    company: company || null,
    contact_source: preserveMissing ? (source || null) : (source || 'manual'),
    status: preserveMissing ? status : (status || 'lead'),
    tags,
    notes: notes || null,
    conversation_summary: summary || null,
    last_contacted_at: normalizeDate(payload.last_contacted_at, null),
    last_conversation_at: normalizeDate(payload.last_conversation_at, null)
  };
};

const mergeConversationSummaries = (existingSummary, incomingSummary) => {
  const existing = String(existingSummary || '').trim();
  const incoming = String(incomingSummary || '').trim();
  if (!incoming) return existing;
  if (!existing) return incoming;
  if (existing.includes(incoming)) return existing;
  if (incoming.includes(existing)) return incoming;
  return `${existing}\n\nLatest update:\n${incoming}`;
};

const derivePaymentStatus = (booking, today = moment().startOf('day')) => {
  const revenue = parseFloat(booking?.revenue) || 0;
  const amountPaid = parseFloat(booking?.amount_paid) || 0;
  const dueDate = booking?.due_date ? moment(booking.due_date, 'YYYY-MM-DD') : null;
  const outstanding = Math.max(revenue - amountPaid, 0);

  if (outstanding <= 0) return 'paid';
  if (dueDate && dueDate.isValid() && dueDate.isBefore(today, 'day')) return 'overdue';
  if (amountPaid > 0) return 'partial';
  return 'unpaid';
};

const buildAvailabilitySnapshot = (bookings, stayStart, nights, partySize, amenities) => {
  const stayEnd = moment(stayStart).add(nights, 'days');
  const bookedByArea = {};

  Object.keys(AREA_DETAILS).forEach((key) => {
    bookedByArea[key] = 0;
  });

  (bookings || []).forEach((row) => {
    const area = normalizeAreaKey(row.area_rented);
    const status = (row.status || '').toLowerCase();
    if (status === 'canceled' || status === 'no-show') return;

    const rowStart = moment(row.booking_date, 'YYYY-MM-DD');
    const rowEnd = moment(rowStart).add(Math.max(parseInt(row.nights, 10) || 1, 1), 'days');
    const overlaps = rowStart.isBefore(stayEnd, 'day') && rowEnd.isAfter(stayStart, 'day');
    if (overlaps) {
      bookedByArea[area] = (bookedByArea[area] || 0) + 1;
    }
  });

  const list = Object.entries(AREA_DETAILS).map(([areaKey, details]) => {
    const bookedUnits = bookedByArea[areaKey] || 0;
    const totalUnits = AREA_CAPACITY[areaKey] || 1;
    const remainingUnits = Math.max(totalUnits - bookedUnits, 0);
    const amenityMatches = details.amenities.filter((item) => amenities.includes(item.toLowerCase())).length;
    const amenityMatchPct = amenities.length > 0 ? (amenityMatches / amenities.length) * 100 : 100;

    return {
      area_key: areaKey,
      area_name: details.label,
      capacity_units: totalUnits,
      booked_units: bookedUnits,
      remaining_units: remainingUnits,
      available: remainingUnits > 0 && partySize <= details.max_party_size,
      max_party_size: details.max_party_size,
      base_rate: details.base_rate,
      amenities: details.amenities,
      amenity_match_count: amenityMatches,
      amenity_match_pct: parseFloat(amenityMatchPct.toFixed(1))
    };
  });

  return list.sort((a, b) => {
    if (a.available !== b.available) return a.available ? -1 : 1;
    if (a.amenity_match_pct !== b.amenity_match_pct) return b.amenity_match_pct - a.amenity_match_pct;
    return b.remaining_units - a.remaining_units;
  });
};

const computeAlternativeDates = (bookings, startDate, nights, partySize, areaPreference) => {
  const start = moment(startDate, 'YYYY-MM-DD');
  const maxDaysToScan = 30;
  const alternatives = [];

  for (let i = 1; i <= maxDaysToScan; i += 1) {
    const candidateStart = moment(start).add(i, 'days');
    const candidateAreas = buildAvailabilitySnapshot(bookings, candidateStart, nights, partySize, []);
    const matchingAreas = candidateAreas.filter((area) => area.available && (!areaPreference || area.area_key === areaPreference));
    if (matchingAreas.length > 0) {
      alternatives.push({
        start_date: candidateStart.format('YYYY-MM-DD'),
        end_date: moment(candidateStart).add(nights, 'days').format('YYYY-MM-DD'),
        available_areas: matchingAreas.slice(0, 2).map((area) => area.area_name)
      });
    }
    if (alternatives.length >= 6) break;
  }

  return alternatives;
};

const evaluateStayRules = ({ startDate, nights, partySize }) => {
  const start = moment(startDate, 'YYYY-MM-DD');
  const isWeekendStart = start.day() === 5 || start.day() === 6;
  const issues = [];

  if (!start.isValid()) issues.push('Start date is invalid.');
  if (partySize > STAY_RULES.max_party_size_absolute) {
    issues.push(`Party size exceeds maximum allowed (${STAY_RULES.max_party_size_absolute}).`);
  }
  if (nights > STAY_RULES.max_nights) {
    issues.push(`Stay exceeds maximum allowed (${STAY_RULES.max_nights} nights).`);
  }
  if (isWeekendStart && nights < STAY_RULES.min_nights_weekend) {
    issues.push(`Weekend arrivals require at least ${STAY_RULES.min_nights_weekend} nights.`);
  }

  const now = moment();
  const sameDayCheckin = start.isSame(now, 'day');
  if (sameDayCheckin && now.hour() >= STAY_RULES.same_day_cutoff_hour) {
    issues.push(`Same-day booking cutoff is ${STAY_RULES.same_day_cutoff_hour}:00 local time.`);
  }

  return {
    passes: issues.length === 0,
    issues,
    rules: STAY_RULES,
    weekend_start: isWeekendStart,
    same_day_checkin: sameDayCheckin
  };
};

const calculateBookingReadiness = ({
  availabilityRows = [],
  rulesResult,
  selectedAmenities = []
}) => {
  const totalAreas = availabilityRows.length || 1;
  const availableCount = availabilityRows.filter((row) => row.available).length;
  const bestMatch = availabilityRows.reduce((max, row) => Math.max(max, row.amenity_match_pct || 0), 0);
  const availabilityScore = Math.min((availableCount / totalAreas) * 55, 55);
  const amenityScore = selectedAmenities.length > 0 ? Math.min((bestMatch / 100) * 30, 30) : 20;
  const ruleScore = rulesResult?.passes ? 15 : 0;
  const score = Math.max(0, Math.min(100, Math.round(availabilityScore + amenityScore + ruleScore)));

  let band = 'low';
  if (score >= 75) band = 'high';
  else if (score >= 50) band = 'medium';

  return {
    score,
    band,
    factors: {
      areas_available: availableCount,
      total_areas: totalAreas,
      best_amenity_match_pct: parseFloat(bestMatch.toFixed(1)),
      rules_passed: Boolean(rulesResult?.passes)
    }
  };
};

// Middleware
app.use(cors());
app.use(express.json());

// Database setup
const dbPath = path.join(__dirname, 'campsite_crm.db');
const db = new sqlite3.Database(dbPath, (err) => {
  if (err) console.error('Database connection error:', err);
  else console.log('Connected to SQLite database at', dbPath);
});

const ensureColumn = (table, column, definition) => {
  db.all(`PRAGMA table_info(${table})`, (err, columns) => {
    if (err) {
      console.error(`Failed to inspect ${table}:`, err.message);
      return;
    }

    const exists = (columns || []).some((col) => col.name === column);
    if (!exists) {
      db.run(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`, (alterErr) => {
        if (alterErr) {
          console.error(`Failed to add ${column} on ${table}:`, alterErr.message);
        } else {
          console.log(`Added missing column ${table}.${column}`);
        }
      });
    }
  });
};

const getSettingValue = (key) => new Promise((resolve, reject) => {
  db.get('SELECT value FROM integration_settings WHERE key = ?', [key], (err, row) => {
    if (err) return reject(err);
    return resolve(row?.value || null);
  });
});

const upsertSettingValue = (key, value) => new Promise((resolve, reject) => {
  const now = moment().format('YYYY-MM-DD HH:mm:ss');
  db.run(`
    INSERT INTO integration_settings (key, value, updated_at)
    VALUES (?, ?, ?)
    ON CONFLICT(key)
    DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
  `, [key, value, now], (err) => {
    if (err) return reject(err);
    return resolve();
  });
});

const getIntegrationSettings = async () => {
  const keys = [
    'chatgpt_enabled',
    'workspace_name',
    'openai_api_key',
    'openai_model',
    'mcp_shared_secret',
    'oauth_enabled',
    'oauth_client_id',
    'oauth_client_secret',
    'oauth_redirect_uri',
    'gmail_scan_enabled',
    'gmail_account_email',
    'gmail_access_token',
    'gmail_refresh_token',
    'gmail_scan_window_days'
  ];

  const values = await Promise.all(keys.map((key) => getSettingValue(key)));
  const map = Object.fromEntries(keys.map((key, index) => [key, values[index] || '']));

  // Env vars take precedence over DB-stored credentials so users never need to paste keys.
  const envClientId = process.env.GOOGLE_CLIENT_ID || '';
  const envClientSecret = process.env.GOOGLE_CLIENT_SECRET || '';

  return {
    chatgpt_enabled: map.chatgpt_enabled === '1',
    workspace_name: map.workspace_name || 'Campsite CRM',
    openai_api_key: map.openai_api_key || '',
    openai_model: map.openai_model || 'gpt-4.1-mini',
    mcp_shared_secret: map.mcp_shared_secret || '',
    oauth_enabled: map.oauth_enabled === '1',
    oauth_client_id: envClientId || map.oauth_client_id || '',
    oauth_client_secret: envClientSecret || map.oauth_client_secret || '',
    oauth_from_env: Boolean(envClientId && envClientSecret),
    oauth_redirect_uri: map.oauth_redirect_uri || '',
    gmail_scan_enabled: map.gmail_scan_enabled === '1',
    gmail_account_email: map.gmail_account_email || '',
    gmail_access_token: map.gmail_access_token || '',
    gmail_refresh_token: map.gmail_refresh_token || '',
    gmail_scan_window_days: Math.max(parseInt(map.gmail_scan_window_days, 10) || 45, 1)
  };
};

const buildSafeSettingsResponse = (settings) => ({
  chatgpt_enabled: settings.chatgpt_enabled,
  workspace_name: settings.workspace_name,
  openai_key_configured: Boolean(settings.openai_api_key),
  openai_model: settings.openai_model,
  mcp_secret_configured: Boolean(settings.mcp_shared_secret),
  oauth_enabled: settings.oauth_enabled,
  oauth_client_id: settings.oauth_from_env ? '' : settings.oauth_client_id,
  oauth_client_secret_configured: Boolean(settings.oauth_client_secret),
  oauth_from_env: settings.oauth_from_env,
  oauth_redirect_uri: settings.oauth_redirect_uri,
  gmail_scan_enabled: settings.gmail_scan_enabled,
  gmail_account_email: settings.gmail_account_email,
  gmail_token_configured: Boolean(settings.gmail_access_token),
  gmail_connected: Boolean(settings.gmail_access_token),
  gmail_refresh_token_configured: Boolean(settings.gmail_refresh_token),
  gmail_scan_window_days: settings.gmail_scan_window_days
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

    // Waitlist queue
    db.run(`
      CREATE TABLE IF NOT EXISTS waitlist_entries (
        id TEXT PRIMARY KEY,
        guest_name TEXT NOT NULL,
        party_size INTEGER DEFAULT 1,
        preferred_area TEXT,
        requested_start_date TEXT,
        requested_end_date TEXT,
        contact_info TEXT,
        notes TEXT,
        status TEXT DEFAULT 'waiting',
        created_at TEXT,
        updated_at TEXT
      )
    `);

    // Availability alert subscriptions
    db.run(`
      CREATE TABLE IF NOT EXISTS availability_alerts (
        id TEXT PRIMARY KEY,
        guest_name TEXT NOT NULL,
        contact TEXT NOT NULL,
        preferred_area TEXT,
        requested_start_date TEXT,
        nights INTEGER DEFAULT 1,
        party_size INTEGER DEFAULT 1,
        status TEXT DEFAULT 'active',
        created_at TEXT,
        updated_at TEXT
      )
    `);

    // Team tasks
    db.run(`
      CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        details TEXT,
        status TEXT DEFAULT 'todo',
        due_date TEXT,
        created_at TEXT,
        updated_at TEXT
      )
    `);

    // Integration settings
    db.run(`
      CREATE TABLE IF NOT EXISTS integration_settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT
      )
    `);

    // Contacts CRM
    db.run(`
      CREATE TABLE IF NOT EXISTS contacts (
        id TEXT PRIMARY KEY,
        full_name TEXT,
        email TEXT UNIQUE,
        phone TEXT,
        company TEXT,
        contact_source TEXT DEFAULT 'manual',
        status TEXT DEFAULT 'lead',
        tags TEXT DEFAULT '[]',
        notes TEXT,
        conversation_summary TEXT,
        last_contacted_at TEXT,
        last_conversation_at TEXT,
        created_at TEXT,
        updated_at TEXT
      )
    `);

    // Conversation summary history per contact (e.g., Gmail threads)
    db.run(`
      CREATE TABLE IF NOT EXISTS contact_conversations (
        id TEXT PRIMARY KEY,
        contact_id TEXT NOT NULL,
        source TEXT DEFAULT 'manual',
        subject TEXT,
        summary TEXT NOT NULL,
        thread_id TEXT,
        occurred_at TEXT,
        created_at TEXT,
        FOREIGN KEY (contact_id) REFERENCES contacts(id)
      )
    `);

    // Pending Gmail scan updates requiring approval
    db.run(`
      CREATE TABLE IF NOT EXISTS contact_scan_batches (
        id TEXT PRIMARY KEY,
        status TEXT DEFAULT 'pending',
        source TEXT DEFAULT 'gmail',
        total_found INTEGER DEFAULT 0,
        total_applied INTEGER DEFAULT 0,
        created_at TEXT,
        approved_at TEXT,
        notes TEXT
      )
    `);

    db.run(`
      CREATE TABLE IF NOT EXISTS contact_scan_items (
        id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        contact_id TEXT NOT NULL,
        source TEXT DEFAULT 'gmail',
        subject TEXT,
        summary TEXT NOT NULL,
        thread_id TEXT,
        message_id TEXT,
        direction TEXT,
        occurred_at TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT,
        approved_at TEXT,
        FOREIGN KEY (batch_id) REFERENCES contact_scan_batches(id),
        FOREIGN KEY (contact_id) REFERENCES contacts(id)
      )
    `);

    db.run('CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email)');
    db.run('CREATE INDEX IF NOT EXISTS idx_contact_conversations_contact ON contact_conversations(contact_id)');
    db.run('CREATE INDEX IF NOT EXISTS idx_contact_conversations_thread ON contact_conversations(thread_id)');
    db.run('CREATE INDEX IF NOT EXISTS idx_contact_scan_items_batch ON contact_scan_items(batch_id)');
    db.run('CREATE INDEX IF NOT EXISTS idx_contact_scan_items_contact ON contact_scan_items(contact_id)');
    db.run('CREATE INDEX IF NOT EXISTS idx_contact_scan_items_message ON contact_scan_items(message_id)');

    ensureColumn('bookings', 'amount_paid', 'REAL DEFAULT 0');
    ensureColumn('bookings', 'due_date', 'TEXT');
    ensureColumn('bookings', 'add_ons', "TEXT DEFAULT '[]'");
    ensureColumn('contacts', 'status', "TEXT DEFAULT 'lead'");
    ensureColumn('contacts', 'conversation_summary', 'TEXT');
    ensureColumn('contacts', 'last_contacted_at', 'TEXT');
    ensureColumn('contacts', 'last_conversation_at', 'TEXT');
    ensureColumn('contact_scan_items', 'message_id', 'TEXT');
    ensureColumn('contact_scan_items', 'direction', 'TEXT');
    ensureColumn('contact_scan_items', 'scan_contact_name', 'TEXT');
    ensureColumn('contact_scan_items', 'scan_contact_email', 'TEXT');
    ensureColumn('contact_scan_items', 'scan_contact_company', 'TEXT');
    ensureColumn('contact_scan_items', 'scan_contact_phone', 'TEXT');
  });
};

initDb();

const buildDateWhereClause = (startDate, endDate, field = 'booking_date') => {
  const clauses = [];
  const params = [];

  if (startDate) {
    clauses.push(`${field} >= ?`);
    params.push(startDate);
  }
  if (endDate) {
    clauses.push(`${field} <= ?`);
    params.push(endDate);
  }

  const where = clauses.length > 0 ? `WHERE ${clauses.join(' AND ')}` : '';
  return { where, params };
};

const mapBooking = (row) => {
  const addOns = normalizeAddOns(row?.add_ons);
  const amountPaid = parseFloat(row?.amount_paid) || 0;
  const revenue = parseFloat(row?.revenue) || 0;
  return {
    ...row,
    revenue,
    amount_paid: amountPaid,
    balance_due: Math.max(revenue - amountPaid, 0),
    payment_status: derivePaymentStatus(row),
    add_ons: addOns
  };
};

const runAll = (sql, params = []) => new Promise((resolve, reject) => {
  db.all(sql, params, (err, rows) => {
    if (err) return reject(err);
    return resolve(rows || []);
  });
});

const runGet = (sql, params = []) => new Promise((resolve, reject) => {
  db.get(sql, params, (err, row) => {
    if (err) return reject(err);
    return resolve(row || null);
  });
});

const runExec = (sql, params = []) => new Promise((resolve, reject) => {
  db.run(sql, params, function onRun(err) {
    if (err) return reject(err);
    return resolve({ changes: this.changes || 0, lastID: this.lastID || null });
  });
});

const BACKUP_DIR = path.join(__dirname, 'backups');
const AUTO_SAVE_INTERVAL_MS = Math.max(parseInt(process.env.CRM_AUTO_SAVE_INTERVAL_MS, 10) || 5 * 60 * 1000, 30 * 1000);
const backupState = {
  auto_save_interval_ms: AUTO_SAVE_INTERVAL_MS,
  is_running: false,
  last_save_at: null,
  last_save_type: null,
  last_save_path: null,
  last_error: null
};

const buildDataSnapshot = async () => {
  const [bookings, contracts, waitlist, tasks, contacts, conversations, scans, scanItems, settings] = await Promise.all([
    runAll('SELECT * FROM bookings ORDER BY booking_date DESC, created_at DESC'),
    runAll('SELECT * FROM contracts ORDER BY updated_at DESC'),
    runAll('SELECT * FROM waitlist_entries ORDER BY created_at DESC'),
    runAll('SELECT * FROM tasks ORDER BY updated_at DESC'),
    runAll('SELECT * FROM contacts ORDER BY updated_at DESC'),
    runAll('SELECT * FROM contact_conversations ORDER BY occurred_at DESC, created_at DESC'),
    runAll('SELECT * FROM contact_scan_batches ORDER BY created_at DESC'),
    runAll('SELECT * FROM contact_scan_items ORDER BY created_at DESC'),
    runAll('SELECT key, value, updated_at FROM integration_settings ORDER BY key ASC')
  ]);

  return {
    meta: {
      version: 1,
      generated_at: new Date().toISOString(),
      generated_by: 'campsite-crm'
    },
    counts: {
      bookings: bookings.length,
      contracts: contracts.length,
      waitlist_entries: waitlist.length,
      tasks: tasks.length,
      contacts: contacts.length,
      contact_conversations: conversations.length,
      contact_scan_batches: scans.length,
      contact_scan_items: scanItems.length,
      integration_settings: settings.length
    },
    data: {
      bookings,
      contracts,
      waitlist_entries: waitlist,
      tasks,
      contacts,
      contact_conversations: conversations,
      contact_scan_batches: scans,
      contact_scan_items: scanItems,
      integration_settings: settings
    }
  };
};

const writeDataBackup = async (mode = 'manual') => {
  if (backupState.is_running) {
    return {
      ok: false,
      skipped: true,
      message: 'A save is already in progress'
    };
  }

  backupState.is_running = true;
  backupState.last_error = null;

  try {
    const snapshot = await buildDataSnapshot();
    const stamp = moment().format('YYYYMMDD_HHmmss');

    fs.mkdirSync(BACKUP_DIR, { recursive: true });
    const fileName = `crm-backup-${stamp}-${mode}.json`;
    const filePath = path.join(BACKUP_DIR, fileName);
    const latestPath = path.join(BACKUP_DIR, 'crm-backup-latest.json');
    const tmpPath = `${filePath}.tmp`;
    const latestTmpPath = `${latestPath}.tmp`;
    const payload = JSON.stringify(snapshot, null, 2);

    fs.writeFileSync(tmpPath, payload, 'utf8');
    fs.renameSync(tmpPath, filePath);
    fs.writeFileSync(latestTmpPath, payload, 'utf8');
    fs.renameSync(latestTmpPath, latestPath);

    backupState.last_save_at = new Date().toISOString();
    backupState.last_save_type = mode;
    backupState.last_save_path = filePath;

    return {
      ok: true,
      mode,
      saved_at: backupState.last_save_at,
      backup_file: filePath,
      latest_file: latestPath,
      counts: snapshot.counts
    };
  } catch (error) {
    backupState.last_error = error.message;
    return {
      ok: false,
      mode,
      error: error.message
    };
  } finally {
    backupState.is_running = false;
  }
};

const DUMMY_ID_PREFIX = 'dummy_';

const buildDummySeed = () => {
  const now = moment().format('YYYY-MM-DD HH:mm:ss');
  const today = moment().startOf('day');

  const bookings = [
    {
      id: 'dummy_booking_001',
      booking_date: today.clone().subtract(6, 'days').format('YYYY-MM-DD'),
      guest_name: 'Sierra Morgan',
      guest_type: 'family',
      group_type: 'camping',
      nights: 2,
      area_rented: 'cabin',
      revenue: 540,
      amount_paid: 540,
      due_date: today.clone().subtract(8, 'days').format('YYYY-MM-DD'),
      add_ons: JSON.stringify([{ name: 'Firewood Bundle', price: 18, quantity: 2, total: 36 }]),
      status: 'checked-out',
      is_return_booking: 1,
      notes: '[DUMMY] Summer weekend family stay',
      created_at: now,
      updated_at: now
    },
    {
      id: 'dummy_booking_002',
      booking_date: today.clone().subtract(2, 'days').format('YYYY-MM-DD'),
      guest_name: 'North Ridge Scouts',
      guest_type: 'group',
      group_type: 'youth',
      nights: 3,
      area_rented: 'tent',
      revenue: 1240,
      amount_paid: 620,
      due_date: today.clone().add(2, 'days').format('YYYY-MM-DD'),
      add_ons: JSON.stringify([{ name: 'Guided Trail Tour', price: 95, quantity: 1, total: 95 }]),
      status: 'checked-in',
      is_return_booking: 0,
      notes: '[DUMMY] Group booking with late final payment',
      created_at: now,
      updated_at: now
    },
    {
      id: 'dummy_booking_003',
      booking_date: today.clone().add(1, 'days').format('YYYY-MM-DD'),
      guest_name: 'Kira Patel',
      guest_type: 'individual',
      group_type: null,
      nights: 2,
      area_rented: 'tent',
      revenue: 210,
      amount_paid: 50,
      due_date: today.clone().add(3, 'days').format('YYYY-MM-DD'),
      add_ons: JSON.stringify([{ name: 'Late Checkout', price: 25, quantity: 1, total: 25 }]),
      status: 'confirmed',
      is_return_booking: 0,
      notes: '[DUMMY] First-time guest from waitlist conversion',
      created_at: now,
      updated_at: now
    },
    {
      id: 'dummy_booking_004',
      booking_date: today.clone().add(3, 'days').format('YYYY-MM-DD'),
      guest_name: 'Sierra Morgan',
      guest_type: 'family',
      group_type: 'camping',
      nights: 1,
      area_rented: 'pavilion',
      revenue: 300,
      amount_paid: 300,
      due_date: today.clone().add(1, 'days').format('YYYY-MM-DD'),
      add_ons: JSON.stringify([]),
      status: 'active',
      is_return_booking: 1,
      notes: '[DUMMY] Return guest event booking',
      created_at: now,
      updated_at: now
    },
    {
      id: 'dummy_booking_005',
      booking_date: today.clone().add(4, 'days').format('YYYY-MM-DD'),
      guest_name: 'Horseshoe Trainers',
      guest_type: 'group',
      group_type: 'equestrian',
      nights: 2,
      area_rented: 'barn',
      revenue: 780,
      amount_paid: 0,
      due_date: today.clone().add(2, 'days').format('YYYY-MM-DD'),
      add_ons: JSON.stringify([{ name: 'Extra Stall Bedding', price: 14, quantity: 6, total: 84 }]),
      status: 'active',
      is_return_booking: 0,
      notes: '[DUMMY] Barn-first package',
      created_at: now,
      updated_at: now
    },
    {
      id: 'dummy_booking_006',
      booking_date: today.clone().add(8, 'days').format('YYYY-MM-DD'),
      guest_name: 'Quentin Rivers',
      guest_type: 'individual',
      group_type: null,
      nights: 2,
      area_rented: 'kitchen',
      revenue: 415,
      amount_paid: 120,
      due_date: today.clone().add(6, 'days').format('YYYY-MM-DD'),
      add_ons: JSON.stringify([{ name: 'Camp Breakfast Kit', price: 22, quantity: 2, total: 44 }]),
      status: 'confirmed',
      is_return_booking: 0,
      notes: '[DUMMY] Kitchen-area booking with partial payment',
      created_at: now,
      updated_at: now
    }
  ];

  const contracts = [
    {
      id: 'dummy_contract_001',
      contract_name: 'Equestrian Club Monthly',
      group_name: 'Trail Riders Collective',
      base_monthly_rate: 1850,
      per_guest_rate: 24,
      start_date: today.clone().subtract(45, 'days').format('YYYY-MM-DD'),
      end_date: today.clone().add(75, 'days').format('YYYY-MM-DD'),
      status: 'active',
      created_at: now,
      updated_at: now
    },
    {
      id: 'dummy_contract_002',
      contract_name: 'Scout Weekender Package',
      group_name: 'North Ridge Scouts',
      base_monthly_rate: 1320,
      per_guest_rate: 16,
      start_date: today.clone().subtract(10, 'days').format('YYYY-MM-DD'),
      end_date: today.clone().add(110, 'days').format('YYYY-MM-DD'),
      status: 'active',
      created_at: now,
      updated_at: now
    }
  ];

  const waitlist = [
    {
      id: 'dummy_waitlist_001',
      guest_name: 'Mina Torres',
      party_size: 4,
      preferred_area: 'tent',
      requested_start_date: today.clone().add(5, 'days').format('YYYY-MM-DD'),
      requested_end_date: today.clone().add(7, 'days').format('YYYY-MM-DD'),
      contact_info: 'mina.torres@example.com',
      notes: '[DUMMY] Wants shaded site near creek',
      status: 'waiting',
      created_at: now,
      updated_at: now
    },
    {
      id: 'dummy_waitlist_002',
      guest_name: 'Oak & Pine Retreat',
      party_size: 9,
      preferred_area: 'pavilion',
      requested_start_date: today.clone().add(9, 'days').format('YYYY-MM-DD'),
      requested_end_date: today.clone().add(11, 'days').format('YYYY-MM-DD'),
      contact_info: 'events@oakpine.test',
      notes: '[DUMMY] Corporate offsite inquiry',
      status: 'contacted',
      created_at: now,
      updated_at: now
    }
  ];

  const tasks = [
    {
      id: 'dummy_task_001',
      title: 'Confirm caterer for Oak & Pine retreat',
      details: '[DUMMY] Call vendor and lock menu options.',
      status: 'in_progress',
      due_date: today.clone().add(2, 'days').format('YYYY-MM-DD'),
      created_at: now,
      updated_at: now
    },
    {
      id: 'dummy_task_002',
      title: 'Collect remaining payment from North Ridge Scouts',
      details: '[DUMMY] Send reminder and due-date options.',
      status: 'todo',
      due_date: today.clone().add(1, 'days').format('YYYY-MM-DD'),
      created_at: now,
      updated_at: now
    },
    {
      id: 'dummy_task_003',
      title: 'Post-stay follow-up for Sierra Morgan',
      details: '[DUMMY] Ask for review and return booking interest.',
      status: 'done',
      due_date: today.clone().subtract(1, 'days').format('YYYY-MM-DD'),
      created_at: now,
      updated_at: now
    }
  ];

  const contacts = [
    {
      id: 'dummy_contact_001',
      full_name: 'Sierra Morgan',
      email: 'sierra.morgan.dummy@example.com',
      phone: '555-0101',
      company: '',
      contact_source: 'dummy',
      status: 'vip',
      tags: JSON.stringify(['return-guest', 'family']),
      notes: '[DUMMY] Loves cabin + pavilion combo weekends.',
      conversation_summary: 'Prefers Friday arrivals and early check-in.',
      last_contacted_at: today.clone().subtract(1, 'days').format('YYYY-MM-DD'),
      last_conversation_at: today.clone().subtract(1, 'days').format('YYYY-MM-DD'),
      created_at: now,
      updated_at: now
    },
    {
      id: 'dummy_contact_002',
      full_name: 'Aiden Brooks',
      email: 'aiden.brooks.dummy@example.com',
      phone: '555-0132',
      company: 'North Ridge Scouts',
      contact_source: 'dummy',
      status: 'active',
      tags: JSON.stringify(['group', 'scouts']),
      notes: '[DUMMY] Handles all troop reservations.',
      conversation_summary: 'Needs invoice split between two payments.',
      last_contacted_at: today.clone().subtract(2, 'days').format('YYYY-MM-DD'),
      last_conversation_at: today.clone().subtract(2, 'days').format('YYYY-MM-DD'),
      created_at: now,
      updated_at: now
    },
    {
      id: 'dummy_contact_003',
      full_name: 'Mina Torres',
      email: 'mina.torres.dummy@example.com',
      phone: '555-0199',
      company: '',
      contact_source: 'dummy',
      status: 'lead',
      tags: JSON.stringify(['waitlist']),
      notes: '[DUMMY] Interested in tent site availability.',
      conversation_summary: 'Asked to notify if creek-adjacent sites open up.',
      last_contacted_at: today.clone().format('YYYY-MM-DD'),
      last_conversation_at: today.clone().format('YYYY-MM-DD'),
      created_at: now,
      updated_at: now
    }
  ];

  const conversations = [
    {
      id: 'dummy_conversation_001',
      contact_id: 'dummy_contact_001',
      source: 'dummy',
      subject: 'Return booking details',
      summary: 'Confirmed late checkout and extra firewood bundle.',
      thread_id: 'dummy_thread_001',
      occurred_at: today.clone().subtract(1, 'days').format('YYYY-MM-DD'),
      created_at: now
    },
    {
      id: 'dummy_conversation_002',
      contact_id: 'dummy_contact_002',
      source: 'dummy',
      subject: 'Scout invoice split',
      summary: 'Agreed on 50% deposit and balance due by arrival.',
      thread_id: 'dummy_thread_002',
      occurred_at: today.clone().subtract(2, 'days').format('YYYY-MM-DD'),
      created_at: now
    },
    {
      id: 'dummy_conversation_003',
      contact_id: 'dummy_contact_003',
      source: 'dummy',
      subject: 'Waitlist follow-up',
      summary: 'Requested SMS when tent capacity opens.',
      thread_id: 'dummy_thread_003',
      occurred_at: today.clone().format('YYYY-MM-DD'),
      created_at: now
    }
  ];

  return {
    bookings,
    contracts,
    waitlist,
    tasks,
    contacts,
    conversations
  };
};

const removeDummyData = async () => {
  const deletes = {};
  deletes.contact_scan_items = (await runExec(`DELETE FROM contact_scan_items WHERE contact_id LIKE '${DUMMY_ID_PREFIX}%'`)).changes;
  deletes.contact_conversations = (await runExec(`DELETE FROM contact_conversations WHERE contact_id LIKE '${DUMMY_ID_PREFIX}%' OR source = 'dummy'`)).changes;
  deletes.contacts = (await runExec(`DELETE FROM contacts WHERE id LIKE '${DUMMY_ID_PREFIX}%' OR contact_source = 'dummy'`)).changes;
  deletes.tasks = (await runExec(`DELETE FROM tasks WHERE id LIKE '${DUMMY_ID_PREFIX}%' OR details LIKE '%[DUMMY]%'`)).changes;
  deletes.waitlist_entries = (await runExec(`DELETE FROM waitlist_entries WHERE id LIKE '${DUMMY_ID_PREFIX}%' OR notes LIKE '%[DUMMY]%'`)).changes;
  deletes.contracts = (await runExec(`DELETE FROM contracts WHERE id LIKE '${DUMMY_ID_PREFIX}%'`)).changes;
  deletes.guest_history = (await runExec(`DELETE FROM guest_history WHERE id LIKE '${DUMMY_ID_PREFIX}%'`)).changes;
  deletes.bookings = (await runExec(`DELETE FROM bookings WHERE id LIKE '${DUMMY_ID_PREFIX}%' OR notes LIKE '%[DUMMY]%'`)).changes;
  return deletes;
};

const populateDummyData = async () => {
  await removeDummyData();
  const seed = buildDummySeed();

  for (const row of seed.bookings) {
    // eslint-disable-next-line no-await-in-loop
    await runExec(`
      INSERT OR REPLACE INTO bookings (
        id, booking_date, guest_name, guest_type, group_type, nights, area_rented,
        revenue, amount_paid, due_date, add_ons, status, is_return_booking, notes, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `, [
      row.id,
      row.booking_date,
      row.guest_name,
      row.guest_type,
      row.group_type,
      row.nights,
      row.area_rented,
      row.revenue,
      row.amount_paid,
      row.due_date,
      row.add_ons,
      sanitizeStatus(row.status, 'active'),
      row.is_return_booking ? 1 : 0,
      row.notes,
      row.created_at,
      row.updated_at
    ]);
  }

  for (const row of seed.contracts) {
    // eslint-disable-next-line no-await-in-loop
    await runExec(`
      INSERT OR REPLACE INTO contracts (
        id, contract_name, group_name, base_monthly_rate, per_guest_rate, start_date, end_date, status, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `, [
      row.id,
      row.contract_name,
      row.group_name,
      row.base_monthly_rate,
      row.per_guest_rate,
      row.start_date,
      row.end_date,
      row.status,
      row.created_at,
      row.updated_at
    ]);
  }

  for (const row of seed.waitlist) {
    // eslint-disable-next-line no-await-in-loop
    await runExec(`
      INSERT OR REPLACE INTO waitlist_entries (
        id, guest_name, party_size, preferred_area, requested_start_date, requested_end_date, contact_info, notes, status, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `, [
      row.id,
      row.guest_name,
      row.party_size,
      row.preferred_area,
      row.requested_start_date,
      row.requested_end_date,
      row.contact_info,
      row.notes,
      sanitizeWaitlistStatus(row.status, 'waiting'),
      row.created_at,
      row.updated_at
    ]);
  }

  for (const row of seed.tasks) {
    // eslint-disable-next-line no-await-in-loop
    await runExec(`
      INSERT OR REPLACE INTO tasks (id, title, details, status, due_date, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `, [
      row.id,
      row.title,
      row.details,
      sanitizeTaskStatus(row.status, 'todo'),
      row.due_date,
      row.created_at,
      row.updated_at
    ]);
  }

  for (const row of seed.contacts) {
    // eslint-disable-next-line no-await-in-loop
    await runExec(`
      INSERT OR REPLACE INTO contacts (
        id, full_name, email, phone, company, contact_source, status, tags, notes, conversation_summary,
        last_contacted_at, last_conversation_at, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `, [
      row.id,
      row.full_name,
      row.email,
      row.phone,
      row.company,
      row.contact_source,
      sanitizeContactStatus(row.status, 'lead'),
      row.tags,
      row.notes,
      row.conversation_summary,
      row.last_contacted_at,
      row.last_conversation_at,
      row.created_at,
      row.updated_at
    ]);
  }

  for (const row of seed.conversations) {
    // eslint-disable-next-line no-await-in-loop
    await runExec(`
      INSERT OR REPLACE INTO contact_conversations (
        id, contact_id, source, subject, summary, thread_id, occurred_at, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `, [
      row.id,
      row.contact_id,
      row.source,
      row.subject,
      row.summary,
      row.thread_id,
      row.occurred_at,
      row.created_at
    ]);
  }

  return {
    bookings: seed.bookings.length,
    contracts: seed.contracts.length,
    waitlist_entries: seed.waitlist.length,
    tasks: seed.tasks.length,
    contacts: seed.contacts.length,
    contact_conversations: seed.conversations.length
  };
};

setInterval(() => {
  writeDataBackup('auto').catch((error) => {
    backupState.last_error = error.message;
  });
}, AUTO_SAVE_INTERVAL_MS).unref();

setTimeout(() => {
  writeDataBackup('startup').catch((error) => {
    backupState.last_error = error.message;
  });
}, 2000).unref();

const mapContactRow = (row) => ({
  ...row,
  tags: parseJsonOrFallback(row?.tags, []),
  status: sanitizeContactStatus(row?.status, 'lead')
});

const fetchContacts = async ({ search = '', limit = 100 } = {}) => {
  const trimmed = String(search || '').trim().toLowerCase();
  const safeLimit = Math.max(Math.min(parseInt(limit, 10) || 100, 250), 1);
  if (!trimmed) {
    const rows = await runAll('SELECT * FROM contacts ORDER BY updated_at DESC LIMIT ?', [safeLimit]);
    return rows.map(mapContactRow);
  }

  const query = `%${trimmed}%`;
  const rows = await runAll(`
    SELECT * FROM contacts
    WHERE lower(COALESCE(full_name, '')) LIKE ?
      OR lower(COALESCE(email, '')) LIKE ?
      OR lower(COALESCE(company, '')) LIKE ?
      OR lower(COALESCE(notes, '')) LIKE ?
    ORDER BY updated_at DESC
    LIMIT ?
  `, [query, query, query, query, safeLimit]);
  return rows.map(mapContactRow);
};

const getContactByEmail = async (email) => {
  const normalized = normalizeEmail(email);
  if (!normalized) return null;
  const row = await runGet('SELECT * FROM contacts WHERE lower(email) = ?', [normalized]);
  return row ? mapContactRow(row) : null;
};

const getContactById = async (id) => {
  const row = await runGet('SELECT * FROM contacts WHERE id = ?', [id]);
  return row ? mapContactRow(row) : null;
};

const upsertContact = async (payload = {}) => {
  const normalized = sanitizeContactPayload(payload, { preserveMissing: true });
  if (!normalized.email) throw new Error('Contact email is required');

  const existing = await getContactByEmail(normalized.email);
  const now = moment().format('YYYY-MM-DD HH:mm:ss');

  if (!existing) {
    const id = uuidv4();
    await new Promise((resolve, reject) => {
      db.run(`
        INSERT INTO contacts (
          id, full_name, email, phone, company, contact_source, status, tags, notes, conversation_summary,
          last_contacted_at, last_conversation_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `, [
        id,
        normalized.full_name,
        normalized.email,
        normalized.phone,
        normalized.company,
        normalized.contact_source || 'manual',
        sanitizeContactStatus(normalized.status, 'lead'),
        JSON.stringify(normalized.tags),
        normalized.notes,
        normalized.conversation_summary,
        normalized.last_contacted_at,
        normalized.last_conversation_at,
        now,
        now
      ], (err) => (err ? reject(err) : resolve()));
    });

    const created = await getContactById(id);
    return { contact: created, created: true };
  }

  const merged = {
    full_name: normalized.full_name || existing.full_name || null,
    phone: normalized.phone || existing.phone || null,
    company: normalized.company || existing.company || null,
    contact_source: normalized.contact_source || existing.contact_source || 'manual',
    status: sanitizeContactStatus(normalized.status || existing.status, 'lead'),
    tags: Array.from(new Set([...(existing.tags || []), ...(normalized.tags || [])])),
    notes: normalized.notes || existing.notes || null,
    conversation_summary: mergeConversationSummaries(existing.conversation_summary, normalized.conversation_summary),
    last_contacted_at: normalized.last_contacted_at || existing.last_contacted_at || null,
    last_conversation_at: normalized.last_conversation_at || existing.last_conversation_at || null
  };

  await new Promise((resolve, reject) => {
    db.run(`
      UPDATE contacts
      SET full_name = ?,
          phone = ?,
          company = ?,
          contact_source = ?,
          status = ?,
          tags = ?,
          notes = ?,
          conversation_summary = ?,
          last_contacted_at = ?,
          last_conversation_at = ?,
          updated_at = ?
      WHERE id = ?
    `, [
      merged.full_name,
      merged.phone,
      merged.company,
      merged.contact_source,
      sanitizeContactStatus(merged.status, 'lead'),
      JSON.stringify(merged.tags),
      merged.notes,
      merged.conversation_summary || null,
      merged.last_contacted_at,
      merged.last_conversation_at,
      now,
      existing.id
    ], (err) => (err ? reject(err) : resolve()));
  });

  const updated = await getContactById(existing.id);
  return { contact: updated, created: false };
};

const addContactConversation = async ({
  contactId, source = 'manual', subject = '', summary, threadId = null, occurredAt = null
}) => {
  const cleanSummary = String(summary || '').trim();
  if (!contactId || !cleanSummary) return null;

  const now = moment().format('YYYY-MM-DD HH:mm:ss');
  const eventDate = normalizeDate(occurredAt, moment().format('YYYY-MM-DD'));
  const id = uuidv4();

  await new Promise((resolve, reject) => {
    db.run(`
      INSERT INTO contact_conversations (id, contact_id, source, subject, summary, thread_id, occurred_at, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `, [
      id,
      contactId,
      String(source || 'manual').trim().toLowerCase(),
      String(subject || '').trim() || null,
      cleanSummary,
      threadId || null,
      eventDate,
      now
    ], (err) => (err ? reject(err) : resolve()));
  });

  const contact = await getContactById(contactId);
  if (contact) {
    const merged = mergeConversationSummaries(contact.conversation_summary, cleanSummary);
    await new Promise((resolve, reject) => {
      db.run(`
        UPDATE contacts
        SET conversation_summary = ?, last_conversation_at = ?, updated_at = ?
        WHERE id = ?
      `, [merged, eventDate, now, contactId], (err) => (err ? reject(err) : resolve()));
    });
  }

  return id;
};

const fetchTaskRows = async () => {
  const rows = await runAll('SELECT * FROM tasks ORDER BY updated_at DESC');
  return rows.map((row) => ({
    ...row,
    status: sanitizeTaskStatus(row.status, 'todo')
  }));
};

const fetchBookingsForContext = async (limit = 12) => {
  const rows = await runAll(`
    SELECT id, booking_date, guest_name, guest_type, nights, area_rented, revenue, status, notes
    FROM bookings
    ORDER BY booking_date DESC
    LIMIT ?
  `, [limit]);
  return rows || [];
};

const fetchContactsForContext = async (limit = 20) => {
  const rows = await runAll(`
    SELECT id, full_name, email, company, status, tags, last_contacted_at, last_conversation_at
    FROM contacts
    ORDER BY updated_at DESC
    LIMIT ?
  `, [limit]);
  return (rows || []).map(mapContactRow);
};

const fetchDashboardSummaryForContext = async () => {
  const row = await runGet(`
    SELECT
      COUNT(*) as total_bookings,
      SUM(nights) as total_nights,
      SUM(revenue) as total_revenue,
      COUNT(CASE WHEN is_return_booking = 1 THEN 1 END) as return_bookings
    FROM bookings
  `, []);
  return row || {
    total_bookings: 0,
    total_nights: 0,
    total_revenue: 0,
    return_bookings: 0
  };
};

const parseGmailHeader = (headers, name) => {
  const match = (headers || []).find((item) => String(item?.name || '').toLowerCase() === String(name).toLowerCase());
  return String(match?.value || '').trim();
};

const buildConversationSummary = ({ direction, subject, from, to }) => {
  const dir = direction === 'inbound' ? 'Inbound' : 'Outbound';
  const pieces = [dir];
  if (subject) pieces.push(`Subject: ${subject}`);
  if (from) pieces.push(`From: ${from}`);
  if (to) pieces.push(`To: ${to}`);
  return pieces.join(' | ');
};

const upsertWaitlistContactCandidates = async () => {
  const rows = await runAll(`
    SELECT guest_name, contact_info, created_at
    FROM waitlist_entries
    ORDER BY created_at DESC
    LIMIT 200
  `, []);

  for (const row of rows) {
    const email = extractEmailFromText(row.contact_info);
    if (!email) continue;
    // eslint-disable-next-line no-await-in-loop
    await upsertContact({
      full_name: row.guest_name,
      email,
      contact_source: 'waitlist',
      status: 'lead',
      last_contacted_at: normalizeDate(row.created_at, moment().format('YYYY-MM-DD'))
    });
  }
};

const fetchRecentContactsWithInteractions = async (limit = 12) => {
  const safeLimit = Math.max(Math.min(parseInt(limit, 10) || 12, 50), 1);
  await upsertWaitlistContactCandidates();

  const contacts = await runAll(`
    SELECT *
    FROM contacts
    ORDER BY
      COALESCE(last_conversation_at, last_contacted_at, updated_at) DESC,
      updated_at DESC
    LIMIT ?
  `, [safeLimit]);

  const contactRows = contacts.map(mapContactRow);
  const contactIds = contactRows.map((row) => row.id);
  if (contactIds.length === 0) return [];

  const placeholders = contactIds.map(() => '?').join(', ');
  const conversations = await runAll(`
    SELECT *
    FROM contact_conversations
    WHERE contact_id IN (${placeholders})
    ORDER BY occurred_at DESC, created_at DESC
  `, contactIds);

  const byContact = new Map();
  conversations.forEach((item) => {
    if (!byContact.has(item.contact_id)) byContact.set(item.contact_id, []);
    byContact.get(item.contact_id).push(item);
  });

  return contactRows.map((contact) => {
    const rows = byContact.get(contact.id) || [];
    return {
      ...contact,
      recent_interactions: rows.slice(0, 3)
    };
  });
};

const buildPendingScanContactId = (email = '') => {
  const normalized = normalizeEmail(email);
  const seed = normalized || uuidv4();
  return `pending:${crypto.createHash('sha1').update(seed).digest('hex').slice(0, 20)}`;
};

const gmailRequest = async (pathSuffix, accessToken) => {
  const response = await fetch(`${GMAIL_API_BASE}${pathSuffix}`, {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${accessToken}`
    }
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data?.error?.message || 'Gmail API request failed');
  }
  return data;
};

// Exchange a refresh token for a new access token and persist it.
const refreshGmailAccessToken = async (settings) => {
  if (!settings.gmail_refresh_token || !settings.oauth_client_id || !settings.oauth_client_secret) {
    throw new Error('Missing OAuth credentials for token refresh');
  }
  const response = await fetch(GOOGLE_TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: settings.oauth_client_id,
      client_secret: settings.oauth_client_secret,
      refresh_token: settings.gmail_refresh_token,
      grant_type: 'refresh_token'
    })
  });
  const data = await response.json();
  if (!response.ok || !data.access_token) {
    throw new Error(data.error_description || data.error || 'Token refresh failed');
  }
  await upsertSettingValue('gmail_access_token', data.access_token);
  return data.access_token;
};

// Returns a valid Gmail access token, auto-refreshing via refresh_token when available.
const getValidGmailToken = async () => {
  const settings = await getIntegrationSettings();
  if (settings.gmail_refresh_token && settings.oauth_client_id && settings.oauth_client_secret) {
    try {
      return await refreshGmailAccessToken(settings);
    } catch (e) {
      console.warn('Gmail token refresh failed, falling back to stored access token:', e.message);
    }
  }
  return settings.gmail_access_token;
};

const fetchRecentGmailMessagesForScan = async ({
  accessToken,
  accountEmail = '',
  scanWindowDays = 45,
  maxMessages = 50
}) => {
  const qParts = [`newer_than:${Math.max(parseInt(scanWindowDays, 10) || 45, 1)}d`];
  if (accountEmail) {
    qParts.push(`(to:${accountEmail} OR from:${accountEmail})`);
  }
  const params = new URLSearchParams({
    maxResults: String(Math.max(Math.min(parseInt(maxMessages, 10) || 50, 100), 5)),
    q: qParts.join(' ')
  });

  const listData = await gmailRequest(`/messages?${params.toString()}`, accessToken);
  const messages = listData?.messages || [];
  if (!messages.length) return [];

  const detailed = [];
  for (const message of messages) {
    const detailParams = new URLSearchParams({
      format: 'metadata',
      metadataHeaders: 'From'
    });
    detailParams.append('metadataHeaders', 'To');
    detailParams.append('metadataHeaders', 'Subject');
    detailParams.append('metadataHeaders', 'Date');
    // eslint-disable-next-line no-await-in-loop
    const detail = await gmailRequest(`/messages/${message.id}?${detailParams.toString()}`, accessToken);
    const headers = detail?.payload?.headers || [];
    detailed.push({
      id: message.id,
      thread_id: detail?.threadId || null,
      from: parseGmailHeader(headers, 'From'),
      to: parseGmailHeader(headers, 'To'),
      subject: parseGmailHeader(headers, 'Subject'),
      snippet: String(detail?.snippet || '').trim(),
      date: parseGmailHeader(headers, 'Date')
    });
  }

  return detailed;
};

const buildHeuristicGmailSuggestions = (messages = []) => {
  return (messages || [])
    .map((message) => {
      const from = String(message?.from || '');
      const senderEmail = extractEmailFromText(from || message?.email);
      if (!senderEmail) return null;

      const rawName = String(from || '').replace(/<[^>]+>/g, '').replace(/"/g, '').trim();
      const subject = String(message?.subject || '').trim();
      const snippet = String(message?.snippet || message?.summary || '').trim();
      const conversationSummary = [subject ? `Subject: ${subject}` : '', snippet]
        .filter(Boolean)
        .join('\n');

      return {
        full_name: rawName || null,
        email: senderEmail,
        company: null,
        phone: null,
        tags: ['gmail-import'],
        status: 'lead',
        contact_source: 'gmail',
        confidence: 0.45,
        reason: 'Heuristic sender extraction from Gmail metadata.',
        conversation_summary: conversationSummary || null,
        subject: subject || null,
        thread_id: String(message?.thread_id || message?.threadId || '').trim() || null,
        occurred_at: normalizeDate(message?.date || message?.occurred_at, moment().format('YYYY-MM-DD'))
      };
    })
    .filter(Boolean);
};

const scanGmailWithOpenAi = async ({ messages = [], settings, apiKey }) => {
  const model = settings?.openai_model || 'gpt-4.1-mini';
  const inputMessages = (messages || []).slice(0, 100).map((item) => ({
    from: String(item?.from || ''),
    to: String(item?.to || ''),
    subject: String(item?.subject || ''),
    snippet: String(item?.snippet || item?.body_preview || ''),
    thread_id: String(item?.thread_id || item?.threadId || ''),
    date: normalizeDate(item?.date || item?.internalDate, null)
  }));

  const response = await fetch(OPENAI_RESPONSES_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`
    },
    body: JSON.stringify({
      model,
      input: [
        {
          role: 'system',
          content: [
            'You identify potential CRM contacts from Gmail snippets.',
            'Return valid JSON only with shape: {"suggestions":[...]}',
            'Each suggestion must include: full_name, email, company, phone, tags, status, confidence, reason, conversation_summary, subject, thread_id, occurred_at.',
            'If email is missing/invalid, skip that suggestion.',
            'status must be one of: lead, active, vip, inactive.',
            'confidence must be 0..1.'
          ].join(' ')
        },
        {
          role: 'user',
          content: JSON.stringify({
            instruction: 'Extract contact suggestions from these Gmail messages and summarize recent conversation context.',
            messages: inputMessages
          })
        }
      ]
    })
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data?.error?.message || 'OpenAI Gmail scan request failed');
  }

  const raw = data.output_text || '';
  let parsed = { suggestions: [] };
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    parsed = { suggestions: [] };
  }

  const suggestions = Array.isArray(parsed?.suggestions) ? parsed.suggestions : [];
  return suggestions
    .map((item) => ({
      ...sanitizeContactPayload({
        ...item,
        contact_source: item?.contact_source || 'gmail',
        status: sanitizeContactStatus(item?.status, 'lead')
      }),
      confidence: Math.max(Math.min(parseFloat(item?.confidence) || 0, 1), 0),
      reason: String(item?.reason || '').trim() || 'Suggested by OpenAI scan',
      subject: String(item?.subject || '').trim() || null,
      thread_id: String(item?.thread_id || '').trim() || null,
      occurred_at: normalizeDate(item?.occurred_at, moment().format('YYYY-MM-DD'))
    }))
    .filter((item) => item.email);
};

const dedupeContactSuggestions = (suggestions = []) => {
  const byEmail = new Map();

  (suggestions || []).forEach((item) => {
    const email = normalizeEmail(item?.email);
    if (!email) return;

    const candidate = {
      ...item,
      email
    };

    if (!byEmail.has(email)) {
      byEmail.set(email, candidate);
      return;
    }

    const existing = byEmail.get(email);
    const existingConfidence = parseFloat(existing?.confidence) || 0;
    const nextConfidence = parseFloat(candidate?.confidence) || 0;

    if (nextConfidence > existingConfidence) {
      byEmail.set(email, {
        ...existing,
        ...candidate,
        tags: Array.from(new Set([...(existing.tags || []), ...(candidate.tags || [])]))
      });
      return;
    }

    byEmail.set(email, {
      ...existing,
      tags: Array.from(new Set([...(existing.tags || []), ...(candidate.tags || [])])),
      conversation_summary: mergeConversationSummaries(existing.conversation_summary, candidate.conversation_summary)
    });
  });

  return Array.from(byEmail.values());
};

const getArrivalRadarRows = (res) => {
  const today = moment().startOf('day').format('YYYY-MM-DD');

  db.all(`
    SELECT id, booking_date, guest_name, area_rented, nights, status
    FROM bookings
    WHERE booking_date >= ?
    ORDER BY booking_date ASC
    LIMIT 7
  `, [today], (err, rows) => {
    if (err) return res.status(500).json({ error: err.message });

    const upcoming = (rows || []).map((row) => ({
      ...row,
      nights: row.nights || 0,
      departure_date: moment(row.booking_date).add(row.nights || 0, 'days').format('YYYY-MM-DD')
    }));

    return res.json(upcoming);
  });
};

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
  const { startDate, endDate } = req.query;
  const start = startDate || moment().startOf('month').format('YYYY-MM-DD');
  const end = endDate || moment().endOf('month').format('YYYY-MM-DD');

  db.all(`
    SELECT * FROM bookings
    WHERE booking_date BETWEEN ? AND ?
    ORDER BY booking_date DESC
  `, [start, end], (err, rows) => {
    if (err) return res.status(500).json({ error: err.message });
    return res.json((rows || []).map(mapBooking));
  });
});

// Get bookings grouped by period
app.get('/api/bookings/grouped/:period', (req, res) => {
  const { period } = req.params;
  const { startDate, endDate } = req.query;
  const start = startDate || moment().startOf('month').format('YYYY-MM-DD');
  const end = endDate || moment().endOf('month').format('YYYY-MM-DD');

  let groupByClause;
  switch (period) {
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
  const {
    guest_name,
    guest_type,
    group_type,
    nights,
    area_rented,
    revenue,
    notes,
    status,
    booking_date,
    is_return_booking = 0,
    amount_paid,
    due_date,
    add_ons
  } = req.body;

  const id = uuidv4();
  const now = moment().format('YYYY-MM-DD HH:mm:ss');
  const bookingDate = normalizeDate(booking_date, moment().format('YYYY-MM-DD'));
  const bookingStatus = sanitizeStatus(status);
  const nightsValue = Math.max(parseInt(nights, 10) || 1, 1);
  const revenueValue = Math.max(parseFloat(revenue) || 0, 0);
  const returnFlag = is_return_booking ? 1 : 0;
  const amountPaidValue = Math.max(parseFloat(amount_paid) || 0, 0);
  const dueDateValue = normalizeDate(due_date, null);
  const addOnsValue = JSON.stringify(normalizeAddOns(add_ons));

  db.run(`
    INSERT INTO bookings (
      id, booking_date, guest_name, guest_type, group_type, nights, area_rented,
      revenue, amount_paid, due_date, add_ons, status, is_return_booking, notes, created_at, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `, [
    id,
    bookingDate,
    guest_name,
    guest_type,
    group_type,
    nightsValue,
    area_rented,
    revenueValue,
    amountPaidValue,
    dueDateValue,
    addOnsValue,
    bookingStatus,
    returnFlag,
    notes,
    now,
    now
  ], function onInsert(err) {
    if (err) return res.status(500).json({ error: err.message });
    return res.status(201).json({ id, message: 'Booking created successfully' });
  });
});

// Update booking
app.put('/api/bookings/:id', (req, res) => {
  const { id } = req.params;
  const {
    guest_name,
    guest_type,
    group_type,
    nights,
    area_rented,
    revenue,
    notes,
    is_return_booking,
    status,
    booking_date,
    amount_paid,
    due_date,
    add_ons
  } = req.body;

  const now = moment().format('YYYY-MM-DD HH:mm:ss');
  const bookingStatus = sanitizeStatus(status, 'active');
  const nightsValue = Math.max(parseInt(nights, 10) || 1, 1);
  const revenueValue = Math.max(parseFloat(revenue) || 0, 0);
  const returnFlag = is_return_booking ? 1 : 0;
  const bookingDateValue = normalizeDate(booking_date, null);
  const amountPaidValue = Math.max(parseFloat(amount_paid) || 0, 0);
  const dueDateValue = normalizeDate(due_date, null);
  const addOnsValue = JSON.stringify(normalizeAddOns(add_ons));

  db.run(`
    UPDATE bookings
    SET guest_name = ?,
        guest_type = ?,
        group_type = ?,
        nights = ?,
        area_rented = ?,
        revenue = ?,
        notes = ?,
        is_return_booking = ?,
        status = ?,
        booking_date = COALESCE(?, booking_date),
        amount_paid = ?,
        due_date = ?,
        add_ons = ?,
        updated_at = ?
    WHERE id = ?
  `, [
    guest_name,
    guest_type,
    group_type,
    nightsValue,
    area_rented,
    revenueValue,
    notes,
    returnFlag,
    bookingStatus,
    bookingDateValue,
    amountPaidValue,
    dueDateValue,
    addOnsValue,
    now,
    id
  ], function onUpdate(err) {
    if (err) return res.status(500).json({ error: err.message });
    return res.json({ message: 'Booking updated successfully' });
  });
});

// Delete booking
app.delete('/api/bookings/:id', (req, res) => {
  const { id } = req.params;
  db.run('DELETE FROM bookings WHERE id = ?', [id], function onDelete(err) {
    if (err) return res.status(500).json({ error: err.message });
    return res.json({ message: 'Booking deleted successfully' });
  });
});

// Booking status summary
app.get('/api/bookings/status-summary', (req, res) => {
  const { startDate, endDate } = req.query;
  const { where, params } = buildDateWhereClause(startDate, endDate, 'booking_date');

  db.all(`
    SELECT status, COUNT(*) as count
    FROM bookings
    ${where}
    GROUP BY status
  `, params, (err, rows) => {
    if (err) return res.status(500).json({ error: err.message });

    const summary = STATUS_OPTIONS.map((status) => ({
      status,
      count: rows.find((row) => row.status === status)?.count || 0
    }));

    return res.json(summary);
  });
});

// Upcoming arrivals alias
app.get('/api/bookings/upcoming', (req, res) => getArrivalRadarRows(res));
app.get('/api/bookings/arrival-radar', (req, res) => getArrivalRadarRows(res));

// Revenue by guest type
app.get('/api/bookings/by-guest-type', (req, res) => {
  const { startDate, endDate } = req.query;
  const { where, params } = buildDateWhereClause(startDate, endDate, 'booking_date');

  db.all(`
    SELECT guest_type, COUNT(*) as booking_count, SUM(revenue) as total_revenue
    FROM bookings
    ${where}
    GROUP BY guest_type
    ORDER BY total_revenue DESC
  `, params, (err, rows) => {
    if (err) return res.status(500).json({ error: err.message });

    const cleaned = (rows || []).map((row) => ({
      guest_type: row.guest_type || 'Unknown',
      booking_count: row.booking_count || 0,
      total_revenue: row.total_revenue || 0
    }));

    return res.json(cleaned);
  });
});

// Add-on upsell analytics
app.get('/api/addons/summary', (req, res) => {
  const { startDate, endDate } = req.query;
  const { where, params } = buildDateWhereClause(startDate, endDate, 'booking_date');

  db.all(`
    SELECT add_ons
    FROM bookings
    ${where}
  `, params, (err, rows) => {
    if (err) return res.status(500).json({ error: err.message });

    const grouped = {};

    (rows || []).forEach((row) => {
      const addOns = normalizeAddOns(row.add_ons);
      addOns.forEach((item) => {
        const key = item.name.toLowerCase();
        if (!grouped[key]) {
          grouped[key] = {
            name: item.name,
            quantity: 0,
            revenue: 0
          };
        }
        grouped[key].quantity += item.quantity;
        grouped[key].revenue += item.total;
      });
    });

    const data = Object.values(grouped)
      .map((item) => ({
        ...item,
        revenue: parseFloat(item.revenue.toFixed(2))
      }))
      .sort((a, b) => b.revenue - a.revenue);

    return res.json({
      total_addon_revenue: parseFloat(data.reduce((sum, row) => sum + row.revenue, 0).toFixed(2)),
      items: data
    });
  });
});

// Payment tracking summary
app.get('/api/payments/summary', (req, res) => {
  const { startDate, endDate } = req.query;
  const { where, params } = buildDateWhereClause(startDate, endDate, 'booking_date');
  const today = moment().startOf('day');

  db.all(`
    SELECT id, guest_name, booking_date, due_date, revenue, amount_paid, status
    FROM bookings
    ${where}
    ORDER BY booking_date DESC
  `, params, (err, rows) => {
    if (err) return res.status(500).json({ error: err.message });

    let totalRevenue = 0;
    let totalCollected = 0;
    let totalOutstanding = 0;
    const overdueBookings = [];

    (rows || []).forEach((row) => {
      const booking = mapBooking(row);
      const paymentStatus = derivePaymentStatus(booking, today);
      const isInactive = ['canceled', 'no-show'].includes((booking.status || '').toLowerCase());

      if (!isInactive) {
        totalRevenue += booking.revenue || 0;
        totalCollected += booking.amount_paid || 0;
        totalOutstanding += booking.balance_due || 0;
      }

      if (paymentStatus === 'overdue' && !isInactive) {
        overdueBookings.push({
          id: booking.id,
          guest_name: booking.guest_name,
          due_date: booking.due_date,
          balance_due: booking.balance_due
        });
      }
    });

    return res.json({
      total_revenue: parseFloat(totalRevenue.toFixed(2)),
      total_collected: parseFloat(totalCollected.toFixed(2)),
      total_outstanding: parseFloat(totalOutstanding.toFixed(2)),
      overdue_count: overdueBookings.length,
      overdue_bookings: overdueBookings.slice(0, 8)
    });
  });
});

// Messaging queue preview
app.get('/api/messages/upcoming', (req, res) => {
  const today = moment().startOf('day');
  const start = moment(today).subtract(1, 'day').format('YYYY-MM-DD');
  const end = moment(today).add(7, 'days').format('YYYY-MM-DD');

  db.all(`
    SELECT id, guest_name, booking_date, nights, due_date, revenue, amount_paid, status
    FROM bookings
    WHERE booking_date BETWEEN ? AND ?
  `, [start, end], (err, rows) => {
    if (err) return res.status(500).json({ error: err.message });

    const queue = [];

    (rows || []).forEach((row) => {
      const booking = mapBooking(row);
      const status = (booking.status || '').toLowerCase();
      if (status === 'canceled' || status === 'no-show') return;

      const arrival = moment(booking.booking_date, 'YYYY-MM-DD');
      const departure = moment(arrival).add(parseInt(booking.nights, 10) || 0, 'days');
      const daysToArrival = arrival.diff(today, 'days');

      if (daysToArrival >= 0 && daysToArrival <= 2) {
        queue.push({
          booking_id: booking.id,
          guest_name: booking.guest_name,
          message_type: 'pre-arrival',
          send_on: moment.max(today, moment(arrival).subtract(1, 'day')).format('YYYY-MM-DD'),
          reason: `Arrival in ${daysToArrival} day(s)`
        });
      }

      if (departure.diff(today, 'days') === 0) {
        queue.push({
          booking_id: booking.id,
          guest_name: booking.guest_name,
          message_type: 'post-stay',
          send_on: today.format('YYYY-MM-DD'),
          reason: 'Departure day follow-up'
        });
      }

      const paymentStatus = derivePaymentStatus(booking, today);
      if (paymentStatus === 'overdue' || paymentStatus === 'partial') {
        queue.push({
          booking_id: booking.id,
          guest_name: booking.guest_name,
          message_type: 'payment-reminder',
          send_on: today.format('YYYY-MM-DD'),
          reason: `Balance due $${booking.balance_due.toFixed(2)}`
        });
      }
    });

    queue.sort((a, b) => a.send_on.localeCompare(b.send_on));
    return res.json(queue.slice(0, 20));
  });
});

// Occupancy-based pricing guidance
app.get('/api/pricing/recommendations', (req, res) => {
  const today = moment().startOf('day');
  const end = moment(today).add(30, 'days');

  db.all(`
    SELECT id, area_rented, booking_date, nights, status
    FROM bookings
    WHERE booking_date BETWEEN ? AND ?
  `, [today.format('YYYY-MM-DD'), end.format('YYYY-MM-DD')], (err, rows) => {
    if (err) return res.status(500).json({ error: err.message });

    const areaStats = {};
    const windowDays = 30;

    (rows || []).forEach((row) => {
      const status = (row.status || '').toLowerCase();
      if (status === 'canceled' || status === 'no-show') return;

      const areaKey = (row.area_rented || 'mixed').toLowerCase();
      if (!areaStats[areaKey]) {
        areaStats[areaKey] = {
          area: row.area_rented || 'Mixed',
          capacity: AREA_CAPACITY[areaKey] || 4,
          booking_count: 0,
          booked_nights: 0
        };
      }

      areaStats[areaKey].booking_count += 1;
      areaStats[areaKey].booked_nights += Math.max(parseInt(row.nights, 10) || 0, 0);
    });

    const recommendations = Object.values(areaStats).map((row) => {
      const capacityNights = row.capacity * windowDays;
      const occupancyRate = capacityNights > 0 ? (row.booked_nights / capacityNights) * 100 : 0;

      let action = 'hold';
      let suggestedChangePct = 0;

      if (occupancyRate >= 80) {
        action = 'raise';
        suggestedChangePct = 12;
      } else if (occupancyRate >= 65) {
        action = 'raise';
        suggestedChangePct = 8;
      } else if (occupancyRate < 35) {
        action = 'discount';
        suggestedChangePct = -10;
      } else if (occupancyRate < 50) {
        action = 'discount';
        suggestedChangePct = -5;
      }

      return {
        area: row.area,
        occupancy_rate: parseFloat(occupancyRate.toFixed(1)),
        booking_count: row.booking_count,
        booked_nights: row.booked_nights,
        capacity_nights: capacityNights,
        action,
        suggested_change_pct: suggestedChangePct
      };
    }).sort((a, b) => b.occupancy_rate - a.occupancy_rate);

    return res.json({
      window_start: today.format('YYYY-MM-DD'),
      window_end: end.format('YYYY-MM-DD'),
      recommendations
    });
  });
});

// Booking assistant: availability, amenities, and alternate dates
app.get('/api/booking-assistant/availability', (req, res) => {
  const requestedStart = normalizeDate(req.query.startDate, moment().format('YYYY-MM-DD'));
  const nights = Math.max(parseInt(req.query.nights, 10) || 2, 1);
  const partySize = Math.max(parseInt(req.query.partySize, 10) || 2, 1);
  const amenities = sanitizeAmenities(req.query.amenities);
  const areaPreference = req.query.area ? normalizeAreaKey(req.query.area) : null;
  const scanStart = moment(requestedStart).subtract(1, 'day').format('YYYY-MM-DD');
  const scanEnd = moment(requestedStart).add(45, 'days').format('YYYY-MM-DD');

  db.all(`
    SELECT booking_date, nights, area_rented, status
    FROM bookings
    WHERE booking_date BETWEEN ? AND ?
  `, [scanStart, scanEnd], (err, rows) => {
    if (err) return res.status(500).json({ error: err.message });

    const availability = buildAvailabilitySnapshot(rows || [], moment(requestedStart), nights, partySize, amenities);
    const filtered = areaPreference ? availability.filter((row) => row.area_key === areaPreference) : availability;
    const recommended = filtered.filter((row) => row.available).slice(0, 3);

    return res.json({
      search: {
        start_date: requestedStart,
        end_date: moment(requestedStart).add(nights, 'days').format('YYYY-MM-DD'),
        nights,
        party_size: partySize,
        amenities,
        area_preference: areaPreference
      },
      availability: filtered,
      recommended_areas: recommended,
      alternative_dates: computeAlternativeDates(rows || [], requestedStart, nights, partySize, areaPreference)
    });
  });
});

// Booking assistant: pricing breakdown with fees/deposit
app.post('/api/booking-assistant/cost-estimate', (req, res) => {
  const areaKey = normalizeAreaKey(req.body.area);
  const areaConfig = AREA_DETAILS[areaKey] || AREA_DETAILS.mixed;
  const nights = Math.max(parseInt(req.body.nights, 10) || 1, 1);
  const partySize = Math.max(parseInt(req.body.partySize, 10) || 1, 1);
  const addOns = normalizeAddOns(req.body.add_ons);
  const extraGuests = Math.max(partySize - areaConfig.included_guests, 0);
  const extraGuestFeePerNight = 12;

  const baseLodging = areaConfig.base_rate * nights;
  const extraGuestTotal = extraGuests * extraGuestFeePerNight * nights;
  const addOnTotal = addOns.reduce((sum, item) => sum + (item.total || 0), 0);
  const siteLockEnabled = req.body.site_lock === true;
  const siteLockFee = siteLockEnabled ? SITE_LOCK_FEE : 0;
  const serviceFee = (baseLodging + addOnTotal) * 0.06;
  const cleaningFee = areaConfig.cleaning_fee;
  const tax = (baseLodging + addOnTotal + serviceFee + cleaningFee + extraGuestTotal + siteLockFee) * 0.085;
  const total = baseLodging + addOnTotal + serviceFee + cleaningFee + extraGuestTotal + siteLockFee + tax;
  const depositDue = total * 0.25;

  return res.json({
    area: areaConfig.label,
    nights,
    party_size: partySize,
    line_items: {
      base_lodging: parseFloat(baseLodging.toFixed(2)),
      extra_guest_fee: parseFloat(extraGuestTotal.toFixed(2)),
      add_ons: parseFloat(addOnTotal.toFixed(2)),
      site_lock_fee: parseFloat(siteLockFee.toFixed(2)),
      service_fee: parseFloat(serviceFee.toFixed(2)),
      cleaning_fee: parseFloat(cleaningFee.toFixed(2)),
      tax: parseFloat(tax.toFixed(2))
    },
    total_estimate: parseFloat(total.toFixed(2)),
    deposit_due_today: parseFloat(depositDue.toFixed(2)),
    remaining_balance: parseFloat((total - depositDue).toFixed(2))
  });
});

// Booking assistant: stay rules and policy guardrails
app.get('/api/booking-assistant/stay-rules', (req, res) => {
  const startDate = normalizeDate(req.query.startDate, moment().format('YYYY-MM-DD'));
  const nights = Math.max(parseInt(req.query.nights, 10) || 1, 1);
  const partySize = Math.max(parseInt(req.query.partySize, 10) || 1, 1);

  return res.json({
    search: { start_date: startDate, nights, party_size: partySize },
    ...evaluateStayRules({ startDate, nights, partySize })
  });
});

// Booking assistant: self-service change/cancel impact preview
app.post('/api/booking-assistant/manage-preview', (req, res) => {
  const currentStartDate = normalizeDate(req.body.current_start_date, moment().add(14, 'days').format('YYYY-MM-DD'));
  const proposedStartDate = normalizeDate(req.body.proposed_start_date, currentStartDate);
  const total = Math.max(parseFloat(req.body.total) || 0, 0);
  const currentNights = Math.max(parseInt(req.body.current_nights, 10) || 1, 1);
  const proposedNights = Math.max(parseInt(req.body.proposed_nights, 10) || currentNights, 1);
  const today = moment().startOf('day');
  const tripStart = moment(currentStartDate, 'YYYY-MM-DD');
  const daysUntilArrival = Math.max(tripStart.diff(today, 'days'), 0);
  const isDateChanged = proposedStartDate !== currentStartDate || proposedNights !== currentNights;
  const daysChanged = Math.abs(moment(proposedStartDate).diff(moment(currentStartDate), 'days'));

  const cancellation = {
    eligible: daysUntilArrival >= 0,
    refund: 0,
    credit: 0,
    fees: 0,
    policy_band: ''
  };

  if (daysUntilArrival >= CANCELLATION_POLICY.full_refund_days) {
    cancellation.refund = Math.max(total - CANCELLATION_POLICY.admin_fee, 0);
    cancellation.fees = CANCELLATION_POLICY.admin_fee;
    cancellation.policy_band = 'full_refund_window';
  } else if (daysUntilArrival >= CANCELLATION_POLICY.partial_refund_days) {
    cancellation.refund = Math.max((total * 0.5) - CANCELLATION_POLICY.admin_fee, 0);
    cancellation.credit = Math.max((total * 0.4), 0);
    cancellation.fees = CANCELLATION_POLICY.admin_fee;
    cancellation.policy_band = 'partial_refund_window';
  } else {
    cancellation.refund = 0;
    cancellation.credit = Math.max(total * 0.3, 0);
    cancellation.fees = 0;
    cancellation.policy_band = 'non_refundable_window';
  }

  const changeFees = isDateChanged ? CHANGE_FEE : 0;
  const changeRiskBand = daysChanged >= 7 ? 'high_shift' : (daysChanged > 0 ? 'minor_shift' : 'same_itinerary');

  return res.json({
    current_booking: {
      start_date: currentStartDate,
      nights: currentNights,
      total: parseFloat(total.toFixed(2))
    },
    proposed_booking: {
      start_date: proposedStartDate,
      nights: proposedNights
    },
    change: {
      changed: isDateChanged,
      shift_days: daysChanged,
      change_fee: changeFees,
      risk_band: changeRiskBand
    },
    cancellation: {
      ...cancellation,
      refund: parseFloat(cancellation.refund.toFixed(2)),
      credit: parseFloat(cancellation.credit.toFixed(2)),
      fees: parseFloat(cancellation.fees.toFixed(2))
    }
  });
});

// Booking assistant: subscribe for availability alerts
app.post('/api/booking-assistant/availability-alerts', (req, res) => {
  const guestName = String(req.body.guest_name || '').trim();
  const contact = String(req.body.contact || '').trim();
  const preferredArea = req.body.preferred_area ? normalizeAreaKey(req.body.preferred_area) : 'mixed';
  const requestedStartDate = normalizeDate(req.body.requested_start_date, moment().format('YYYY-MM-DD'));
  const nights = Math.max(parseInt(req.body.nights, 10) || 1, 1);
  const partySize = Math.max(parseInt(req.body.party_size, 10) || 1, 1);

  if (!guestName || !contact) {
    return res.status(400).json({ error: 'guest_name and contact are required.' });
  }

  const id = uuidv4();
  const now = moment().format('YYYY-MM-DD HH:mm:ss');
  db.run(`
    INSERT INTO availability_alerts (
      id, guest_name, contact, preferred_area, requested_start_date, nights, party_size, status, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `, [
    id,
    guestName,
    contact,
    preferredArea,
    requestedStartDate,
    nights,
    partySize,
    'active',
    now,
    now
  ], (err) => {
    if (err) return res.status(500).json({ error: err.message });
    return res.status(201).json({
      id,
      message: 'Availability alert created',
      alert: {
        guest_name: guestName,
        contact,
        preferred_area: preferredArea,
        requested_start_date: requestedStartDate,
        nights,
        party_size: partySize,
        status: 'active'
      }
    });
  });
});

// Booking assistant: booking readiness score for fast decisioning
app.get('/api/booking-assistant/readiness-score', (req, res) => {
  const startDate = normalizeDate(req.query.startDate, moment().format('YYYY-MM-DD'));
  const nights = Math.max(parseInt(req.query.nights, 10) || 1, 1);
  const partySize = Math.max(parseInt(req.query.partySize, 10) || 1, 1);
  const amenities = sanitizeAmenities(req.query.amenities);
  const areaPreference = req.query.area ? normalizeAreaKey(req.query.area) : null;
  const scanStart = moment(startDate).subtract(1, 'day').format('YYYY-MM-DD');
  const scanEnd = moment(startDate).add(30, 'days').format('YYYY-MM-DD');

  db.all(`
    SELECT booking_date, nights, area_rented, status
    FROM bookings
    WHERE booking_date BETWEEN ? AND ?
  `, [scanStart, scanEnd], (err, rows) => {
    if (err) return res.status(500).json({ error: err.message });

    const fullAvailability = buildAvailabilitySnapshot(rows || [], moment(startDate), nights, partySize, amenities);
    const filtered = areaPreference ? fullAvailability.filter((row) => row.area_key === areaPreference) : fullAvailability;
    const rulesResult = evaluateStayRules({ startDate, nights, partySize });
    const readiness = calculateBookingReadiness({
      availabilityRows: filtered,
      rulesResult,
      selectedAmenities: amenities
    });

    return res.json({
      search: {
        start_date: startDate,
        nights,
        party_size: partySize,
        amenities,
        area_preference: areaPreference
      },
      readiness,
      rule_issues: rulesResult.issues
    });
  });
});

// Booking assistant: cancellation window preview
app.get('/api/booking-assistant/cancellation-preview', (req, res) => {
  const startDate = normalizeDate(req.query.startDate, moment().add(14, 'days').format('YYYY-MM-DD'));
  const estimatedTotal = Math.max(parseFloat(req.query.total) || 0, 0);
  const tripStart = moment(startDate, 'YYYY-MM-DD');
  const fullRefundDeadline = moment(tripStart).subtract(CANCELLATION_POLICY.full_refund_days, 'days');
  const partialRefundDeadline = moment(tripStart).subtract(CANCELLATION_POLICY.partial_refund_days, 'days');
  const partialRefundAmount = Math.max((estimatedTotal * 0.5) - CANCELLATION_POLICY.admin_fee, 0);
  const fullRefundAmount = Math.max(estimatedTotal - CANCELLATION_POLICY.admin_fee, 0);

  return res.json({
    trip_start: startDate,
    estimated_total: parseFloat(estimatedTotal.toFixed(2)),
    policy: {
      full_refund_if_canceled_on_or_before: fullRefundDeadline.format('YYYY-MM-DD'),
      partial_refund_if_canceled_between: {
        start: moment(fullRefundDeadline).add(1, 'day').format('YYYY-MM-DD'),
        end: partialRefundDeadline.format('YYYY-MM-DD')
      },
      non_refundable_if_canceled_on_or_after: moment(partialRefundDeadline).add(1, 'day').format('YYYY-MM-DD'),
      admin_fee: CANCELLATION_POLICY.admin_fee
    },
    refund_examples: {
      full_refund_amount: parseFloat(fullRefundAmount.toFixed(2)),
      partial_refund_amount: parseFloat(partialRefundAmount.toFixed(2)),
      non_refundable_amount: 0
    }
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

// Active contracts snapshot
app.get('/api/contracts/active', (req, res) => {
  const today = moment().format('YYYY-MM-DD');

  db.all(`
    SELECT id, contract_name, group_name, base_monthly_rate, per_guest_rate, start_date, end_date, status
    FROM contracts
    WHERE status = 'active'
      AND date(start_date) <= date(?)
      AND (end_date IS NULL OR end_date = '' OR date(end_date) >= date(?))
    ORDER BY end_date ASC
  `, [today, today], (err, rows) => {
    if (err) return res.status(500).json({ error: err.message });

    const activeContracts = (rows || []).map((row) => ({
      ...row,
      start_date: row.start_date,
      end_date: row.end_date || 'TBD'
    }));

    return res.json(activeContracts);
  });
});

// Waitlist endpoints
app.get('/api/waitlist', (req, res) => {
  const { status } = req.query;
  let sql = 'SELECT * FROM waitlist_entries';
  const params = [];

  if (status) {
    sql += ' WHERE status = ?';
    params.push(sanitizeWaitlistStatus(status));
  }

  sql += ' ORDER BY created_at DESC';

  db.all(sql, params, (err, rows) => {
    if (err) return res.status(500).json({ error: err.message });
    return res.json(rows || []);
  });
});

app.post('/api/waitlist', (req, res) => {
  const {
    guest_name,
    party_size,
    preferred_area,
    requested_start_date,
    requested_end_date,
    contact_info,
    notes,
    status
  } = req.body;

  if (!guest_name) {
    return res.status(400).json({ error: 'guest_name is required' });
  }

  const id = uuidv4();
  const now = moment().format('YYYY-MM-DD HH:mm:ss');

  db.run(`
    INSERT INTO waitlist_entries (
      id, guest_name, party_size, preferred_area, requested_start_date, requested_end_date,
      contact_info, notes, status, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `, [
    id,
    guest_name,
    Math.max(parseInt(party_size, 10) || 1, 1),
    preferred_area || null,
    normalizeDate(requested_start_date, null),
    normalizeDate(requested_end_date, null),
    contact_info || null,
    notes || null,
    sanitizeWaitlistStatus(status, 'waiting'),
    now,
    now
  ], (err) => {
    if (err) return res.status(500).json({ error: err.message });
    return res.status(201).json({ id, message: 'Waitlist entry added' });
  });
});

app.put('/api/waitlist/:id', (req, res) => {
  const { id } = req.params;
  const {
    guest_name,
    party_size,
    preferred_area,
    requested_start_date,
    requested_end_date,
    contact_info,
    notes,
    status
  } = req.body;

  const now = moment().format('YYYY-MM-DD HH:mm:ss');

  db.run(`
    UPDATE waitlist_entries
    SET guest_name = ?,
        party_size = ?,
        preferred_area = ?,
        requested_start_date = ?,
        requested_end_date = ?,
        contact_info = ?,
        notes = ?,
        status = ?,
        updated_at = ?
    WHERE id = ?
  `, [
    guest_name,
    Math.max(parseInt(party_size, 10) || 1, 1),
    preferred_area || null,
    normalizeDate(requested_start_date, null),
    normalizeDate(requested_end_date, null),
    contact_info || null,
    notes || null,
    sanitizeWaitlistStatus(status, 'waiting'),
    now,
    id
  ], function onWaitlistUpdate(err) {
    if (err) return res.status(500).json({ error: err.message });
    return res.json({ message: 'Waitlist entry updated', changes: this.changes });
  });
});

app.delete('/api/waitlist/:id', (req, res) => {
  const { id } = req.params;
  db.run('DELETE FROM waitlist_entries WHERE id = ?', [id], function onWaitlistDelete(err) {
    if (err) return res.status(500).json({ error: err.message });
    return res.json({ message: 'Waitlist entry deleted', changes: this.changes });
  });
});

app.post('/api/waitlist/:id/convert', (req, res) => {
  const { id } = req.params;
  const {
    guest_type = 'individual',
    group_type = null,
    nights = 1,
    area_rented,
    revenue = 0,
    amount_paid = 0,
    notes = '',
    status = 'confirmed'
  } = req.body;

  db.get('SELECT * FROM waitlist_entries WHERE id = ?', [id], (err, entry) => {
    if (err) return res.status(500).json({ error: err.message });
    if (!entry) return res.status(404).json({ error: 'Waitlist entry not found' });

    const bookingId = uuidv4();
    const now = moment().format('YYYY-MM-DD HH:mm:ss');
    const bookingDate = normalizeDate(entry.requested_start_date, moment().format('YYYY-MM-DD'));
    const area = area_rented || entry.preferred_area || 'tent';

    db.run(`
      INSERT INTO bookings (
        id, booking_date, guest_name, guest_type, group_type, nights, area_rented,
        revenue, amount_paid, due_date, add_ons, status, is_return_booking, notes, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `, [
      bookingId,
      bookingDate,
      entry.guest_name,
      guest_type,
      group_type,
      Math.max(parseInt(nights, 10) || 1, 1),
      area,
      Math.max(parseFloat(revenue) || 0, 0),
      Math.max(parseFloat(amount_paid) || 0, 0),
      normalizeDate(entry.requested_start_date, null),
      JSON.stringify([]),
      sanitizeStatus(status, 'confirmed'),
      0,
      notes || entry.notes,
      now,
      now
    ], (insertErr) => {
      if (insertErr) return res.status(500).json({ error: insertErr.message });

      db.run(`
        UPDATE waitlist_entries
        SET status = 'converted', updated_at = ?
        WHERE id = ?
      `, [now, id], (updateErr) => {
        if (updateErr) return res.status(500).json({ error: updateErr.message });
        return res.json({ message: 'Waitlist entry converted to booking', booking_id: bookingId });
      });
    });
  });
});

// Task endpoints
app.get('/api/tasks', async (req, res) => {
  try {
    const tasks = await fetchTaskRows();
    return res.json(tasks);
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.post('/api/tasks', (req, res) => {
  const { title, details, status, due_date } = req.body;
  if (!title) return res.status(400).json({ error: 'title is required' });

  const id = uuidv4();
  const now = moment().format('YYYY-MM-DD HH:mm:ss');

  db.run(`
    INSERT INTO tasks (id, title, details, status, due_date, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `, [
    id,
    String(title).trim(),
    details || null,
    sanitizeTaskStatus(status, 'todo'),
    normalizeDate(due_date, null),
    now,
    now
  ], (err) => {
    if (err) return res.status(500).json({ error: err.message });
    return res.status(201).json({ id, message: 'Task created' });
  });
});

app.put('/api/tasks/:id', (req, res) => {
  const { id } = req.params;
  const { title, details, status, due_date } = req.body;
  const now = moment().format('YYYY-MM-DD HH:mm:ss');
  const nextStatus = status ? sanitizeTaskStatus(status, 'todo') : null;
  const nextDueDate = typeof due_date === 'undefined' ? null : normalizeDate(due_date, null);

  db.run(`
    UPDATE tasks
    SET title = COALESCE(?, title),
        details = COALESCE(?, details),
        status = COALESCE(?, status),
        due_date = COALESCE(?, due_date),
        updated_at = ?
    WHERE id = ?
  `, [
    title ? String(title).trim() : null,
    details ?? null,
    nextStatus,
    nextDueDate,
    now,
    id
  ], function onTaskUpdate(err) {
    if (err) return res.status(500).json({ error: err.message });
    if (!this.changes) return res.status(404).json({ error: 'Task not found' });
    return res.json({ message: 'Task updated' });
  });
});

app.delete('/api/tasks/:id', (req, res) => {
  const { id } = req.params;
  db.run('DELETE FROM tasks WHERE id = ?', [id], function onTaskDelete(err) {
    if (err) return res.status(500).json({ error: err.message });
    if (!this.changes) return res.status(404).json({ error: 'Task not found' });
    return res.json({ message: 'Task deleted' });
  });
});

// Contact endpoints
app.get('/api/contacts', async (req, res) => {
  try {
    const contacts = await fetchContacts({
      search: req.query.search || '',
      limit: req.query.limit || 100
    });
    return res.json(contacts);
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.get('/api/contacts/recent', async (req, res) => {
  try {
    const contacts = await fetchRecentContactsWithInteractions(req.query.limit || 12);
    return res.json(contacts);
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.post('/api/contacts', async (req, res) => {
  try {
    const { contact, created } = await upsertContact(req.body || {});
    return res.status(created ? 201 : 200).json({
      message: created ? 'Contact created' : 'Contact updated',
      contact
    });
  } catch (error) {
    return res.status(400).json({ error: error.message });
  }
});

app.post('/api/contacts/suggestions/from-gmail', async (req, res) => {
  try {
    const settings = await getIntegrationSettings();
    const messages = Array.isArray(req.body?.messages) ? req.body.messages : [];
    if (!messages.length) return res.status(400).json({ error: 'messages[] is required' });

    let suggestions = [];
    const apiKey = settings.openai_api_key || process.env.OPENAI_API_KEY || '';
    const canUseOpenAi = settings.chatgpt_enabled && settings.gmail_scan_enabled && apiKey;

    if (canUseOpenAi) {
      try {
        suggestions = await scanGmailWithOpenAi({ messages, settings, apiKey });
      } catch (openAiError) {
        suggestions = buildHeuristicGmailSuggestions(messages);
        return res.json({
          source: 'heuristic_fallback',
          warning: `OpenAI scan failed: ${openAiError.message}`,
          suggestions
        });
      }
    } else {
      suggestions = buildHeuristicGmailSuggestions(messages);
    }

    return res.json({
      source: canUseOpenAi ? 'openai' : 'heuristic',
      suggestions
    });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.post('/api/contacts/suggestions/from-live-gmail', async (req, res) => {
  try {
    const settings = await getIntegrationSettings();
    if (!settings.gmail_scan_enabled) {
      return res.status(400).json({ error: 'Gmail not connected. Use Settings → Connect Gmail Account first.' });
    }
    const accessToken = await getValidGmailToken();
    if (!accessToken) {
      return res.status(400).json({ error: 'Gmail not connected. Use Settings → Connect Gmail Account first.' });
    }

    const scanWindowDays = Math.max(parseInt(req.body?.scan_window_days, 10) || settings.gmail_scan_window_days || 45, 1);
    const maxMessages = Math.max(Math.min(parseInt(req.body?.max_messages, 10) || 50, 100), 5);

    const messages = await fetchRecentGmailMessagesForScan({
      accessToken,
      accountEmail: settings.gmail_account_email,
      scanWindowDays,
      maxMessages
    });

    const apiKey = settings.openai_api_key || process.env.OPENAI_API_KEY || '';
    const canUseOpenAi = settings.chatgpt_enabled && apiKey;

    let source = canUseOpenAi ? 'openai' : 'heuristic';
    let warning = null;
    let suggestions = [];

    if (canUseOpenAi) {
      try {
        suggestions = await scanGmailWithOpenAi({ messages, settings, apiKey });
      } catch (openAiError) {
        source = 'heuristic_fallback';
        warning = openAiError.message;
        suggestions = buildHeuristicGmailSuggestions(messages);
      }
    } else {
      suggestions = buildHeuristicGmailSuggestions(messages);
    }

    const deduped = dedupeContactSuggestions(suggestions);
    const withMatches = await Promise.all(deduped.map(async (item) => {
      const existing = await getContactByEmail(item.email);
      return {
        ...item,
        existing_contact_id: existing?.id || null,
        existing_contact_name: existing?.full_name || null,
        existing_contact_status: existing?.status || null,
        action: existing ? 'update' : 'create'
      };
    }));

    return res.json({
      source,
      warning,
      scan_window_days: scanWindowDays,
      max_messages: maxMessages,
      scanned_messages: messages.length,
      suggestions: withMatches
    });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.post('/api/contacts/suggestions/apply', async (req, res) => {
  try {
    const suggestions = Array.isArray(req.body?.suggestions) ? req.body.suggestions : [];
    if (!suggestions.length) return res.status(400).json({ error: 'suggestions[] is required' });

    let createdCount = 0;
    let updatedCount = 0;
    const applied = [];

    for (const item of suggestions) {
      // eslint-disable-next-line no-await-in-loop
      const { contact, created } = await upsertContact({
        ...item,
        contact_source: item?.contact_source || 'gmail'
      });
      if (created) createdCount += 1;
      else updatedCount += 1;

      if (item?.conversation_summary) {
        // eslint-disable-next-line no-await-in-loop
        await addContactConversation({
          contactId: contact.id,
          source: item?.contact_source || 'gmail',
          subject: item?.subject || '',
          summary: item.conversation_summary,
          threadId: item?.thread_id || null,
          occurredAt: item?.occurred_at || null
        });
      }

      applied.push(contact);
    }

    return res.json({
      message: 'Suggestions applied',
      created_count: createdCount,
      updated_count: updatedCount,
      contacts: applied
    });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.post('/api/contacts/merge-recent-summaries', async (req, res) => {
  try {
    const days = Math.max(Math.min(parseInt(req.body?.days, 10) || 30, 365), 1);
    const cutoff = moment().subtract(days, 'days').format('YYYY-MM-DD');
    const rows = await runAll(`
      SELECT contact_id, summary, occurred_at
      FROM contact_conversations
      WHERE COALESCE(occurred_at, '') >= ?
      ORDER BY COALESCE(occurred_at, created_at) DESC
    `, [cutoff]);

    let mergedCount = 0;
    const byContact = new Map();
    (rows || []).forEach((row) => {
      if (!row?.contact_id || !row?.summary) return;
      const existing = byContact.get(row.contact_id) || '';
      const existingDate = (byContact.get(`${row.contact_id}:latest`) || '');
      const nextDate = normalizeDate(row.occurred_at, null) || '';
      byContact.set(row.contact_id, mergeConversationSummaries(existing, row.summary));
      if (!existingDate || (nextDate && nextDate > existingDate)) {
        byContact.set(`${row.contact_id}:latest`, nextDate);
      }
    });

    const now = moment().format('YYYY-MM-DD HH:mm:ss');
    const contactIds = Array.from(byContact.keys()).filter((key) => !key.includes(':latest'));
    for (const contactId of contactIds) {
      const summary = byContact.get(contactId);
      const latestDate = byContact.get(`${contactId}:latest`) || null;
      // eslint-disable-next-line no-await-in-loop
      const contact = await getContactById(contactId);
      if (!contact) continue;

      const merged = mergeConversationSummaries(contact.conversation_summary, summary);
      // eslint-disable-next-line no-await-in-loop
      await new Promise((resolve, reject) => {
        db.run(`
          UPDATE contacts
          SET conversation_summary = ?, last_conversation_at = COALESCE(?, last_conversation_at), updated_at = ?
          WHERE id = ?
        `, [merged, latestDate, now, contactId], (err) => (err ? reject(err) : resolve()));
      });
      mergedCount += 1;
    }

    return res.json({
      message: 'Recent conversation summaries merged',
      days,
      merged_count: mergedCount
    });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.get('/api/contacts/:id', async (req, res) => {
  try {
    const contact = await getContactById(req.params.id);
    if (!contact) return res.status(404).json({ error: 'Contact not found' });

    const conversations = await runAll(`
      SELECT id, source, subject, summary, thread_id, occurred_at, created_at
      FROM contact_conversations
      WHERE contact_id = ?
      ORDER BY COALESCE(occurred_at, created_at) DESC
      LIMIT 30
    `, [req.params.id]);

    return res.json({ ...contact, conversations });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.put('/api/contacts/:id', async (req, res) => {
  try {
    const existing = await getContactById(req.params.id);
    if (!existing) return res.status(404).json({ error: 'Contact not found' });

    const incoming = sanitizeContactPayload(req.body || {}, { preserveMissing: true });
    const now = moment().format('YYYY-MM-DD HH:mm:ss');
    const merged = {
      full_name: incoming.full_name || existing.full_name || null,
      phone: incoming.phone || existing.phone || null,
      company: incoming.company || existing.company || null,
      contact_source: incoming.contact_source || existing.contact_source || 'manual',
      status: incoming.status || existing.status || 'lead',
      tags: Array.from(new Set([...(existing.tags || []), ...(incoming.tags || [])])),
      notes: incoming.notes || existing.notes || null,
      conversation_summary: mergeConversationSummaries(existing.conversation_summary, incoming.conversation_summary),
      last_contacted_at: incoming.last_contacted_at || existing.last_contacted_at || null,
      last_conversation_at: incoming.last_conversation_at || existing.last_conversation_at || null
    };

    await new Promise((resolve, reject) => {
      db.run(`
        UPDATE contacts
        SET full_name = ?, phone = ?, company = ?, contact_source = ?, status = ?, tags = ?, notes = ?,
            conversation_summary = ?, last_contacted_at = ?, last_conversation_at = ?, updated_at = ?
        WHERE id = ?
      `, [
        merged.full_name,
        merged.phone,
        merged.company,
        merged.contact_source,
        sanitizeContactStatus(merged.status, 'lead'),
        JSON.stringify(merged.tags),
        merged.notes,
        merged.conversation_summary,
        merged.last_contacted_at,
        merged.last_conversation_at,
        now,
        req.params.id
      ], (err) => (err ? reject(err) : resolve()));
    });

    const updated = await getContactById(req.params.id);
    return res.json({ message: 'Contact updated', contact: updated });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.post('/api/contacts/:id/conversation-summary', async (req, res) => {
  try {
    const contact = await getContactById(req.params.id);
    if (!contact) return res.status(404).json({ error: 'Contact not found' });
    const summary = String(req.body?.summary || '').trim();
    if (!summary) return res.status(400).json({ error: 'summary is required' });

    await addContactConversation({
      contactId: req.params.id,
      source: req.body?.source || 'manual',
      subject: req.body?.subject || '',
      summary,
      threadId: req.body?.thread_id || null,
      occurredAt: req.body?.occurred_at || null
    });

    const updated = await getContactById(req.params.id);
    return res.json({ message: 'Conversation summary merged', contact: updated });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.get('/api/integrations/chatgpt/gmail/scans/pending', async (req, res) => {
  try {
    const batches = await runAll(`
      SELECT id, status, source, total_found, total_applied, created_at, approved_at, notes
      FROM contact_scan_batches
      WHERE status = 'pending'
      ORDER BY created_at DESC
      LIMIT 8
    `, []);

    if (!batches.length) return res.json([]);
    const batchIds = batches.map((batch) => batch.id);
    const placeholders = batchIds.map(() => '?').join(', ');
    const items = await runAll(`
      SELECT
        i.id, i.batch_id, i.contact_id, i.subject, i.summary, i.thread_id, i.message_id, i.direction, i.occurred_at,
        COALESCE(c.full_name, i.scan_contact_name) AS full_name,
        COALESCE(c.email, i.scan_contact_email) AS email
      FROM contact_scan_items i
      LEFT JOIN contacts c ON c.id = i.contact_id
      WHERE i.batch_id IN (${placeholders}) AND i.status = 'pending'
      ORDER BY i.occurred_at DESC, i.created_at DESC
    `, batchIds);

    const itemsByBatch = new Map();
    items.forEach((item) => {
      if (!itemsByBatch.has(item.batch_id)) itemsByBatch.set(item.batch_id, []);
      itemsByBatch.get(item.batch_id).push(item);
    });

    return res.json(batches.map((batch) => ({
      ...batch,
      items: (itemsByBatch.get(batch.id) || []).slice(0, 25)
    })));
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.post('/api/integrations/chatgpt/gmail/scan', async (req, res) => {
  try {
    const settings = await getIntegrationSettings();
    if (!settings.chatgpt_enabled) {
      return res.status(400).json({ error: 'Enable ChatGPT integration first.' });
    }
    if (!settings.gmail_scan_enabled) {
      return res.status(400).json({ error: 'Gmail not connected. Use Settings → Connect Gmail Account first.' });
    }
    const accessToken = await getValidGmailToken();
    if (!accessToken) {
      return res.status(400).json({ error: 'Gmail not connected. Use Settings → Connect Gmail Account first.' });
    }

    const now = moment().format('YYYY-MM-DD HH:mm:ss');
    const scanWindowDays = Math.max(parseInt(req.body?.scan_window_days, 10) || settings.gmail_scan_window_days || 45, 1);
    const maxMessages = Math.max(Math.min(parseInt(req.body?.max_messages, 10) || 50, 100), 5);
    const messages = await fetchRecentGmailMessagesForScan({
      accessToken,
      accountEmail: settings.gmail_account_email,
      scanWindowDays,
      maxMessages
    });

    if (!messages.length) {
      return res.json({
        batch_id: null,
        status: 'empty',
        source: 'gmail',
        total_found: 0,
        items: []
      });
    }

    const apiKey = settings.openai_api_key || process.env.OPENAI_API_KEY || '';
    const canUseOpenAi = settings.chatgpt_enabled && apiKey;
    const suggestions = canUseOpenAi
      ? await scanGmailWithOpenAi({ messages, settings, apiKey })
      : buildHeuristicGmailSuggestions(messages);

    const batchId = uuidv4();
    await new Promise((resolve, reject) => {
      db.run(`
        INSERT INTO contact_scan_batches (id, status, source, total_found, total_applied, created_at, notes)
        VALUES (?, 'pending', 'gmail', 0, 0, ?, ?)
      `, [batchId, now, `Window: ${scanWindowDays}d`], (err) => (err ? reject(err) : resolve()));
    });

    let totalFound = 0;
    for (const suggestion of suggestions) {
      const suggestionEmail = normalizeEmail(suggestion.email);
      if (!suggestionEmail) continue;

      // Do not write conversation updates during scan; approval applies them.
      // We still resolve an existing contact id to preserve dedupe behavior.
      // eslint-disable-next-line no-await-in-loop
      const existingContact = await getContactByEmail(suggestionEmail);
      const resolvedContactId = existingContact?.id || buildPendingScanContactId(suggestionEmail);

      const occurredAt = normalizeDate(suggestion.occurred_at, moment().format('YYYY-MM-DD'));
      const threadId = String(suggestion.thread_id || '').trim() || null;
      const summary = String(suggestion.conversation_summary || '').trim();
      if (!summary) continue;

      // eslint-disable-next-line no-await-in-loop
      const exists = await runGet(`
        SELECT id
        FROM contact_conversations
        WHERE contact_id = ? AND source = 'gmail'
          AND (
            (thread_id IS NOT NULL AND thread_id = ?)
            OR (summary = ? AND occurred_at = ?)
          )
        LIMIT 1
      `, [resolvedContactId, threadId, summary, occurredAt]);
      if (exists) continue;

      const itemId = uuidv4();
      // eslint-disable-next-line no-await-in-loop
      await new Promise((resolve, reject) => {
        db.run(`
          INSERT INTO contact_scan_items (
            id, batch_id, contact_id, source, subject, summary, thread_id, message_id, direction, occurred_at, status, created_at,
            scan_contact_name, scan_contact_email, scan_contact_company, scan_contact_phone
          ) VALUES (?, ?, ?, 'gmail', ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
        `, [
          itemId,
          batchId,
          resolvedContactId,
          suggestion.subject || null,
          summary,
          threadId,
          suggestion.message_id || null,
          suggestion.direction || null,
          occurredAt,
          now,
          suggestion.full_name || null,
          suggestionEmail,
          suggestion.company || null,
          suggestion.phone || null
        ], (err) => (err ? reject(err) : resolve()));
      });
      totalFound += 1;
    }

    const nextStatus = totalFound > 0 ? 'pending' : 'empty';
    await new Promise((resolve, reject) => {
      db.run(`
        UPDATE contact_scan_batches
        SET total_found = ?, status = ?
        WHERE id = ?
      `, [totalFound, nextStatus, batchId], (err) => (err ? reject(err) : resolve()));
    });

    const items = await runAll(`
      SELECT
        i.id, i.contact_id, i.subject, i.summary, i.thread_id, i.direction, i.occurred_at,
        COALESCE(c.full_name, i.scan_contact_name) AS full_name,
        COALESCE(c.email, i.scan_contact_email) AS email
      FROM contact_scan_items i
      LEFT JOIN contacts c ON c.id = i.contact_id
      WHERE i.batch_id = ?
      ORDER BY i.occurred_at DESC, i.created_at DESC
      LIMIT 25
    `, [batchId]);

    return res.json({
      batch_id: batchId,
      status: nextStatus,
      source: canUseOpenAi ? 'openai' : 'heuristic',
      total_found: totalFound,
      items
    });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.post('/api/integrations/chatgpt/gmail/scans/:batchId/approve', async (req, res) => {
  try {
    const batch = await runGet('SELECT * FROM contact_scan_batches WHERE id = ?', [req.params.batchId]);
    if (!batch) return res.status(404).json({ error: 'Scan batch not found' });
    if (batch.status !== 'pending') {
      return res.status(400).json({ error: `Batch is ${batch.status}; only pending batches can be approved.` });
    }

    const items = await runAll(`
      SELECT
        id, contact_id, source, subject, summary, thread_id, occurred_at,
        scan_contact_name, scan_contact_email, scan_contact_company, scan_contact_phone
      FROM contact_scan_items
      WHERE batch_id = ? AND status = 'pending'
      ORDER BY occurred_at DESC, created_at DESC
    `, [batch.id]);
    if (!items.length) return res.status(400).json({ error: 'No pending updates found for this batch.' });

    const now = moment().format('YYYY-MM-DD HH:mm:ss');
    let applied = 0;
    for (const item of items) {
      // eslint-disable-next-line no-await-in-loop
      let contact = await getContactById(item.contact_id);
      if (!contact) {
        // eslint-disable-next-line no-await-in-loop
        const upserted = await upsertContact({
          full_name: item.scan_contact_name || '',
          email: item.scan_contact_email || '',
          company: item.scan_contact_company || '',
          phone: item.scan_contact_phone || '',
          contact_source: 'gmail'
        });
        contact = upserted?.contact || null;
      }
      if (!contact?.id) continue;

      // eslint-disable-next-line no-await-in-loop
      const exists = await runGet(`
        SELECT id
        FROM contact_conversations
        WHERE contact_id = ? AND source = ?
          AND (
            (thread_id IS NOT NULL AND thread_id = ?)
            OR (summary = ? AND occurred_at = ?)
          )
        LIMIT 1
      `, [contact.id, item.source || 'gmail', item.thread_id || null, item.summary, item.occurred_at || null]);

      if (!exists) {
        // eslint-disable-next-line no-await-in-loop
        await addContactConversation({
          contactId: contact.id,
          source: item.source || 'gmail',
          subject: item.subject || '',
          summary: item.summary,
          threadId: item.thread_id || null,
          occurredAt: item.occurred_at || null
        });
        applied += 1;
      }

      // eslint-disable-next-line no-await-in-loop
      await new Promise((resolve, reject) => {
        db.run('UPDATE contact_scan_items SET status = ?, approved_at = ? WHERE id = ?', ['approved', now, item.id], (err) => (err ? reject(err) : resolve()));
      });
    }

    await new Promise((resolve, reject) => {
      db.run(
        'UPDATE contact_scan_batches SET status = ?, total_applied = ?, approved_at = ? WHERE id = ?',
        ['approved', applied, now, batch.id],
        (err) => (err ? reject(err) : resolve())
      );
    });

    return res.json({
      message: 'Scan updates approved and applied.',
      batch_id: batch.id,
      total_items: items.length,
      total_applied: applied
    });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.get('/api/data-management/status', async (req, res) => {
  try {
    const [bookings, contracts, waitlist, tasks, contacts, conversations] = await Promise.all([
      runGet('SELECT COUNT(*) AS total FROM bookings'),
      runGet('SELECT COUNT(*) AS total FROM contracts'),
      runGet('SELECT COUNT(*) AS total FROM waitlist_entries'),
      runGet('SELECT COUNT(*) AS total FROM tasks'),
      runGet('SELECT COUNT(*) AS total FROM contacts'),
      runGet('SELECT COUNT(*) AS total FROM contact_conversations')
    ]);

    return res.json({
      auto_save: {
        interval_ms: backupState.auto_save_interval_ms,
        interval_minutes: Math.round((backupState.auto_save_interval_ms / 60000) * 100) / 100,
        last_save_at: backupState.last_save_at,
        last_save_type: backupState.last_save_type,
        last_save_path: backupState.last_save_path,
        in_progress: backupState.is_running,
        last_error: backupState.last_error
      },
      totals: {
        bookings: bookings?.total || 0,
        contracts: contracts?.total || 0,
        waitlist_entries: waitlist?.total || 0,
        tasks: tasks?.total || 0,
        contacts: contacts?.total || 0,
        contact_conversations: conversations?.total || 0
      }
    });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.post('/api/data-management/save', async (req, res) => {
  try {
    const result = await writeDataBackup('manual');
    if (!result.ok) {
      const status = result.skipped ? 409 : 500;
      return res.status(status).json(result);
    }
    return res.json({
      message: 'Data snapshot saved',
      ...result
    });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.post('/api/data-management/dummy/populate', async (req, res) => {
  try {
    const inserted = await populateDummyData();
    const saveResult = await writeDataBackup('post-dummy-populate');

    return res.json({
      message: 'Dummy data populated',
      inserted,
      backup: saveResult
    });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.post('/api/data-management/dummy/remove', async (req, res) => {
  try {
    const removed = await removeDummyData();
    const saveResult = await writeDataBackup('post-dummy-remove');

    return res.json({
      message: 'Dummy data removed',
      removed,
      backup: saveResult
    });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

// ChatGPT/OpenAI integration settings
app.get('/api/integrations/chatgpt/settings', async (req, res) => {
  try {
    const settings = await getIntegrationSettings();
    const mcpUrl = `${req.protocol}://${req.get('host')}/mcp`;
    return res.json({
      ...buildSafeSettingsResponse(settings),
      mcp_url: mcpUrl,
      oauth_redirect_default: `${req.protocol}://${req.get('host')}/api/integrations/chatgpt/oauth/callback`
    });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.put('/api/integrations/chatgpt/settings', async (req, res) => {
  try {
    const payload = req.body || {};
    const current = await getIntegrationSettings();
    const next = {
      chatgpt_enabled: payload.chatgpt_enabled === true,
      workspace_name: payload.workspace_name || current.workspace_name || 'Campsite CRM',
      openai_api_key: typeof payload.openai_api_key === 'string' && payload.openai_api_key.trim()
        ? payload.openai_api_key.trim()
        : current.openai_api_key,
      openai_model: payload.openai_model || current.openai_model || 'gpt-4.1-mini',
      mcp_shared_secret: typeof payload.mcp_shared_secret === 'string' && payload.mcp_shared_secret.trim()
        ? payload.mcp_shared_secret.trim()
        : current.mcp_shared_secret,
      oauth_enabled: payload.oauth_enabled === true,
      oauth_client_id: payload.oauth_client_id || '',
      oauth_client_secret: typeof payload.oauth_client_secret === 'string' && payload.oauth_client_secret.trim()
        ? payload.oauth_client_secret.trim()
        : current.oauth_client_secret,
      oauth_redirect_uri: payload.oauth_redirect_uri || '',
      gmail_scan_enabled: payload.gmail_scan_enabled === true,
      gmail_account_email: normalizeEmail(payload.gmail_account_email || ''),
      gmail_access_token: typeof payload.gmail_access_token === 'string' && payload.gmail_access_token.trim()
        ? payload.gmail_access_token.trim()
        : current.gmail_access_token,
      gmail_refresh_token: current.gmail_refresh_token,
      gmail_scan_window_days: Math.max(parseInt(payload.gmail_scan_window_days, 10) || current.gmail_scan_window_days || 45, 1)
    };

    await Promise.all([
      upsertSettingValue('chatgpt_enabled', next.chatgpt_enabled ? '1' : '0'),
      upsertSettingValue('workspace_name', next.workspace_name),
      upsertSettingValue('openai_api_key', next.openai_api_key),
      upsertSettingValue('openai_model', next.openai_model),
      upsertSettingValue('mcp_shared_secret', next.mcp_shared_secret),
      upsertSettingValue('oauth_enabled', next.oauth_enabled ? '1' : '0'),
      upsertSettingValue('oauth_client_id', next.oauth_client_id),
      upsertSettingValue('oauth_client_secret', next.oauth_client_secret),
      upsertSettingValue('oauth_redirect_uri', next.oauth_redirect_uri),
      upsertSettingValue('gmail_scan_enabled', next.gmail_scan_enabled ? '1' : '0'),
      upsertSettingValue('gmail_account_email', next.gmail_account_email),
      upsertSettingValue('gmail_access_token', next.gmail_access_token),
      upsertSettingValue('gmail_scan_window_days', String(next.gmail_scan_window_days))
    ]);

    return res.json({
      message: 'Integration settings saved',
      settings: buildSafeSettingsResponse(next)
    });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.get('/api/integrations/chatgpt/mcp-instructions', async (req, res) => {
  try {
    const settings = await getIntegrationSettings();
    const mcpUrl = `${req.protocol}://${req.get('host')}/mcp`;
    return res.json({
      workspace: settings.workspace_name,
      mcp_url: mcpUrl,
      requires_bearer_token: Boolean(settings.mcp_shared_secret),
      oauth_supported: settings.oauth_enabled,
      note: 'Use an MCP-compatible client and point it at this endpoint. For ChatGPT-based tools, use an MCP bridge or custom action proxy.',
      quickstart: [
        'Set chatgpt_enabled=true and add an OpenAI API key in CRM settings.',
        'Enable gmail_scan_enabled to allow GPT-powered Gmail contact suggestions.',
        'Set mcp_shared_secret to protect CRM tools.',
        `Connect your MCP client to ${mcpUrl}.`,
        'Expose tools: crm.get_summary, crm.list_bookings, crm.create_booking, crm.list_waitlist, crm.list_tasks, crm.create_task, crm.update_task_status, crm.list_contacts, crm.upsert_contact, crm.gpt_suggest_contacts_from_gmail.'
      ]
    });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

app.post('/api/integrations/chatgpt/test', async (req, res) => {
  try {
    const settings = await getIntegrationSettings();
    const apiKey = settings.openai_api_key || process.env.OPENAI_API_KEY || '';
    if (!settings.chatgpt_enabled) {
      return res.status(400).json({ ok: false, error: 'chatgpt_enabled is false' });
    }
    if (!apiKey) {
      return res.status(400).json({ ok: false, error: 'No OpenAI API key configured' });
    }

    const response = await fetch(OPENAI_RESPONSES_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`
      },
      body: JSON.stringify({
        model: settings.openai_model || 'gpt-4.1-mini',
        input: 'Reply with exactly: Connected to Campsite CRM.'
      })
    });

    const data = await response.json();
    if (!response.ok) {
      return res.status(502).json({
        ok: false,
        error: data?.error?.message || 'OpenAI request failed'
      });
    }

    return res.json({
      ok: true,
      model: settings.openai_model || 'gpt-4.1-mini',
      preview: (data.output_text || '').slice(0, 120)
    });
  } catch (error) {
    return res.status(500).json({ ok: false, error: error.message });
  }
});

app.post('/api/chatgpt/chat', async (req, res) => {
  try {
    const { message, history = [], include_crm_context = true } = req.body || {};
    if (!message || !String(message).trim()) {
      return res.status(400).json({ error: 'message is required' });
    }

    const settings = await getIntegrationSettings();
    if (!settings.chatgpt_enabled) {
      return res.status(403).json({ error: 'ChatGPT integration is disabled in settings' });
    }

    const apiKey = settings.openai_api_key || process.env.OPENAI_API_KEY || '';
    if (!apiKey) {
      return res.status(400).json({ error: 'OpenAI API key is not configured in settings' });
    }

    const contextParts = [];
    if (include_crm_context) {
      const [summary, bookings, tasks, waitlist, contacts] = await Promise.all([
        fetchDashboardSummaryForContext(),
        fetchBookingsForContext(10),
        fetchTaskRows(),
        runAll('SELECT id, guest_name, preferred_area, requested_start_date, requested_end_date, status FROM waitlist_entries ORDER BY created_at DESC LIMIT 8'),
        fetchContactsForContext(20)
      ]);

      contextParts.push(`Summary: ${JSON.stringify(summary)}`);
      contextParts.push(`Recent bookings: ${JSON.stringify(bookings)}`);
      contextParts.push(`Tasks: ${JSON.stringify(tasks)}`);
      contextParts.push(`Waitlist: ${JSON.stringify(waitlist || [])}`);
      contextParts.push(`Contacts: ${JSON.stringify(contacts || [])}`);
    }

    const systemMessage = [
      `You are the assistant for ${settings.workspace_name || 'Campsite CRM'}.`,
      'Give operational answers that are concise, accurate, and action-oriented.',
      'If CRM context is included, prioritize it over generic assumptions.',
      contextParts.join('\n')
    ].join('\n');

    const normalizedHistory = Array.isArray(history)
      ? history
        .filter((item) => item && typeof item.content === 'string' && typeof item.role === 'string')
        .slice(-8)
        .map((item) => ({
          role: item.role === 'assistant' ? 'assistant' : 'user',
          content: item.content
        }))
      : [];

    const response = await fetch(OPENAI_RESPONSES_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`
      },
      body: JSON.stringify({
        model: settings.openai_model || 'gpt-4.1-mini',
        input: [
          { role: 'system', content: systemMessage },
          ...normalizedHistory,
          { role: 'user', content: String(message) }
        ]
      })
    });

    const data = await response.json();
    if (!response.ok) {
      return res.status(502).json({ error: data?.error?.message || 'OpenAI API request failed' });
    }

    let reply = data.output_text || '';
    if (!reply) {
      reply = (data.output || [])
        .flatMap((item) => item?.content || [])
        .map((content) => content?.text || '')
        .join('\n')
        .trim();
    }

    return res.json({
      reply: reply || 'No response text returned.',
      model: settings.openai_model || 'gpt-4.1-mini'
    });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

const requireMcpAuth = async (req, res, next) => {
  try {
    const settings = await getIntegrationSettings();
    const secret = settings.mcp_shared_secret;
    if (!secret) return next();

    const authHeader = req.headers.authorization || '';
    const token = authHeader.startsWith('Bearer ') ? authHeader.slice('Bearer '.length).trim() : '';
    if (!token || token !== secret) {
      return res.status(401).json({
        jsonrpc: '2.0',
        id: null,
        error: { code: -32001, message: 'Unauthorized MCP token' }
      });
    }

    return next();
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
};

app.post('/mcp', requireMcpAuth, async (req, res) => {
  const payload = req.body || {};
  const jsonrpc = payload.jsonrpc || '2.0';
  const id = payload.id ?? null;
  const method = payload.method;
  const params = payload.params || {};

  const sendResult = (result) => res.json({ jsonrpc, id, result });
  const sendError = (code, message) => res.status(400).json({ jsonrpc, id, error: { code, message } });

  try {
    if (!method) return sendError(-32600, 'Invalid request: method required');

    if (method === 'initialize') {
      return sendResult({
        protocolVersion: '2024-11-05',
        serverInfo: { name: 'campsite-crm-mcp', version: '1.0.0' },
        capabilities: {
          tools: {}
        }
      });
    }

    if (method === 'tools/list') {
      return sendResult({
        tools: [
          {
            name: 'crm.get_summary',
            description: 'Get top-level CRM KPI summary (bookings, nights, revenue, return bookings).',
            inputSchema: { type: 'object', properties: {} }
          },
          {
            name: 'crm.list_bookings',
            description: 'List bookings, optionally filtered by startDate/endDate.',
            inputSchema: {
              type: 'object',
              properties: {
                startDate: { type: 'string' },
                endDate: { type: 'string' },
                limit: { type: 'number' }
              }
            }
          },
          {
            name: 'crm.create_booking',
            description: 'Create a new booking.',
            inputSchema: {
              type: 'object',
              required: ['guest_name', 'guest_type', 'nights', 'area_rented', 'revenue'],
              properties: {
                guest_name: { type: 'string' },
                guest_type: { type: 'string' },
                nights: { type: 'number' },
                area_rented: { type: 'string' },
                revenue: { type: 'number' },
                booking_date: { type: 'string' },
                notes: { type: 'string' },
                status: { type: 'string' }
              }
            }
          },
          {
            name: 'crm.list_waitlist',
            description: 'List waitlist entries.',
            inputSchema: {
              type: 'object',
              properties: {
                status: { type: 'string' }
              }
            }
          },
          {
            name: 'crm.list_tasks',
            description: 'List operational tasks.',
            inputSchema: { type: 'object', properties: {} }
          },
          {
            name: 'crm.create_task',
            description: 'Create an operational task.',
            inputSchema: {
              type: 'object',
              required: ['title'],
              properties: {
                title: { type: 'string' },
                details: { type: 'string' },
                status: { type: 'string' },
                due_date: { type: 'string' }
              }
            }
          },
          {
            name: 'crm.update_task_status',
            description: 'Update task status.',
            inputSchema: {
              type: 'object',
              required: ['id', 'status'],
              properties: {
                id: { type: 'string' },
                status: { type: 'string' }
              }
            }
          },
          {
            name: 'crm.list_contacts',
            description: 'List CRM contacts with optional search.',
            inputSchema: {
              type: 'object',
              properties: {
                search: { type: 'string' },
                limit: { type: 'number' }
              }
            }
          },
          {
            name: 'crm.upsert_contact',
            description: 'Create or update a contact by email and merge conversation summary.',
            inputSchema: {
              type: 'object',
              required: ['email'],
              properties: {
                full_name: { type: 'string' },
                email: { type: 'string' },
                phone: { type: 'string' },
                company: { type: 'string' },
                tags: { type: 'array', items: { type: 'string' } },
                status: { type: 'string' },
                notes: { type: 'string' },
                conversation_summary: { type: 'string' }
              }
            }
          },
          {
            name: 'crm.gpt_suggest_contacts_from_gmail',
            description: 'Use ChatGPT scan logic on Gmail message snippets and return contact suggestions.',
            inputSchema: {
              type: 'object',
              required: ['messages'],
              properties: {
                messages: { type: 'array' }
              }
            }
          }
        ]
      });
    }

    if (method === 'tools/call') {
      const name = params?.name;
      const args = params?.arguments || {};
      let result;

      if (name === 'crm.get_summary') {
        result = await fetchDashboardSummaryForContext();
      } else if (name === 'crm.list_bookings') {
        const { startDate, endDate, limit = 20 } = args;
        const { where, params: queryParams } = buildDateWhereClause(startDate, endDate, 'booking_date');
        result = await runAll(`
          SELECT id, booking_date, guest_name, guest_type, nights, area_rented, revenue, status
          FROM bookings
          ${where}
          ORDER BY booking_date DESC
          LIMIT ?
        `, [...queryParams, Math.max(parseInt(limit, 10) || 20, 1)]);
      } else if (name === 'crm.create_booking') {
        const bookingId = uuidv4();
        const now = moment().format('YYYY-MM-DD HH:mm:ss');
        const nights = Math.max(parseInt(args.nights, 10) || 1, 1);
        const revenue = Math.max(parseFloat(args.revenue) || 0, 0);
        await new Promise((resolve, reject) => {
          db.run(`
            INSERT INTO bookings (
              id, booking_date, guest_name, guest_type, group_type, nights, area_rented,
              revenue, amount_paid, due_date, add_ons, status, is_return_booking, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          `, [
            bookingId,
            normalizeDate(args.booking_date, moment().format('YYYY-MM-DD')),
            args.guest_name,
            args.guest_type,
            args.group_type || null,
            nights,
            args.area_rented,
            revenue,
            0,
            null,
            JSON.stringify([]),
            sanitizeStatus(args.status, 'active'),
            0,
            args.notes || null,
            now,
            now
          ], (err) => (err ? reject(err) : resolve()));
        });
        result = { booking_id: bookingId, message: 'Booking created' };
      } else if (name === 'crm.list_waitlist') {
        const status = args?.status ? sanitizeWaitlistStatus(args.status) : null;
        result = await runAll(`
          SELECT id, guest_name, party_size, preferred_area, requested_start_date, requested_end_date, status
          FROM waitlist_entries
          ${status ? 'WHERE status = ?' : ''}
          ORDER BY created_at DESC
        `, status ? [status] : []);
      } else if (name === 'crm.list_tasks') {
        result = await fetchTaskRows();
      } else if (name === 'crm.create_task') {
        const id = uuidv4();
        const now = moment().format('YYYY-MM-DD HH:mm:ss');
        await new Promise((resolve, reject) => {
          db.run(`
            INSERT INTO tasks (id, title, details, status, due_date, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
          `, [
            id,
            String(args.title || '').trim(),
            args.details || null,
            sanitizeTaskStatus(args.status, 'todo'),
            normalizeDate(args.due_date, null),
            now,
            now
          ], (err) => (err ? reject(err) : resolve()));
        });
        result = { task_id: id, message: 'Task created' };
      } else if (name === 'crm.update_task_status') {
        const now = moment().format('YYYY-MM-DD HH:mm:ss');
        await new Promise((resolve, reject) => {
          db.run(`
            UPDATE tasks
            SET status = ?, updated_at = ?
            WHERE id = ?
          `, [
            sanitizeTaskStatus(args.status, 'todo'),
            now,
            args.id
          ], function onMcpTaskUpdate(err) {
            if (err) return reject(err);
            if (!this.changes) return reject(new Error('Task not found'));
            return resolve();
          });
        });
        result = { id: args.id, status: sanitizeTaskStatus(args.status, 'todo') };
      } else if (name === 'crm.list_contacts') {
        result = await fetchContacts({
          search: args?.search || '',
          limit: args?.limit || 50
        });
      } else if (name === 'crm.upsert_contact') {
        const applied = await upsertContact(args || {});
        result = {
          created: applied.created,
          contact: applied.contact
        };
      } else if (name === 'crm.gpt_suggest_contacts_from_gmail') {
        const settings = await getIntegrationSettings();
        const messages = Array.isArray(args?.messages) ? args.messages : [];
        const apiKey = settings.openai_api_key || process.env.OPENAI_API_KEY || '';
        const canUseOpenAi = settings.chatgpt_enabled && settings.gmail_scan_enabled && apiKey;

        if (canUseOpenAi) {
          try {
            const suggestions = await scanGmailWithOpenAi({ messages, settings, apiKey });
            result = { source: 'openai', suggestions };
          } catch (openAiError) {
            result = {
              source: 'heuristic_fallback',
              warning: openAiError.message,
              suggestions: buildHeuristicGmailSuggestions(messages)
            };
          }
        } else {
          result = {
            source: 'heuristic',
            suggestions: buildHeuristicGmailSuggestions(messages)
          };
        }
      } else {
        return sendError(-32601, `Unknown tool: ${name}`);
      }

      return sendResult({
        content: [
          {
            type: 'text',
            text: JSON.stringify(result, null, 2)
          }
        ],
        structuredContent: result
      });
    }

    return sendError(-32601, `Unknown method: ${method}`);
  } catch (error) {
    return res.status(500).json({
      jsonrpc,
      id,
      error: { code: -32000, message: error.message }
    });
  }
});

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'OK', timestamp: new Date().toISOString() });
});

// ── Gmail OAuth 2.0 flow ─────────────────────────────────────────────────────

// Returns the URL that should be registered as an authorized redirect URI
// in Google Cloud Console for this deployment.
const getGmailCallbackUri = (req) => {
  return `${req.protocol}://${req.get('host')}/api/auth/gmail/callback`;
};

// GET /api/auth/gmail/connect-url
// Returns the Google OAuth authorization URL so the frontend can navigate to it.
app.get('/api/auth/gmail/connect-url', async (req, res) => {
  try {
    const settings = await getIntegrationSettings();
    if (!settings.oauth_client_id) {
      return res.status(400).json({ error: 'OAuth Client ID not configured. Add it in Settings → Integration Settings.' });
    }
    const redirectUri = getGmailCallbackUri(req);
    const params = new URLSearchParams({
      client_id: settings.oauth_client_id,
      redirect_uri: redirectUri,
      response_type: 'code',
      scope: GMAIL_SCOPE,
      access_type: 'offline',
      prompt: 'consent'
    });
    return res.json({
      url: `${GOOGLE_OAUTH_URL}?${params.toString()}`,
      redirect_uri: redirectUri
    });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

// GET /api/auth/gmail/callback
// Google redirects here after the user grants access.
app.get('/api/auth/gmail/callback', async (req, res) => {
  const { code, error } = req.query;
  const base = FRONTEND_URL || '';
  if (error) {
    return res.redirect(`${base}/?gmail_error=${encodeURIComponent(String(error))}`);
  }
  if (!code) {
    return res.redirect(`${base}/?gmail_error=no_code`);
  }
  try {
    const settings = await getIntegrationSettings();
    if (!settings.oauth_client_id || !settings.oauth_client_secret) {
      return res.redirect(`${base}/?gmail_error=${encodeURIComponent('OAuth credentials not configured')}`);
    }
    const redirectUri = getGmailCallbackUri(req);
    // Exchange code for tokens
    const tokenRes = await fetch(GOOGLE_TOKEN_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        code,
        client_id: settings.oauth_client_id,
        client_secret: settings.oauth_client_secret,
        redirect_uri: redirectUri,
        grant_type: 'authorization_code'
      })
    });
    const tokenData = await tokenRes.json();
    if (!tokenRes.ok || !tokenData.access_token) {
      const msg = tokenData.error_description || tokenData.error || 'Token exchange failed';
      return res.redirect(`${base}/?gmail_error=${encodeURIComponent(msg)}`);
    }
    // Fetch connected account email
    let accountEmail = '';
    try {
      const profileRes = await fetch(GOOGLE_USERINFO_URL, {
        headers: { Authorization: `Bearer ${tokenData.access_token}` }
      });
      const profile = await profileRes.json();
      accountEmail = profile.email || '';
    } catch (_) { /* non-fatal */ }
    // Persist tokens and enable Gmail scan
    await Promise.all([
      upsertSettingValue('gmail_access_token', tokenData.access_token),
      upsertSettingValue('gmail_refresh_token', tokenData.refresh_token || ''),
      upsertSettingValue('gmail_account_email', accountEmail),
      upsertSettingValue('gmail_scan_enabled', '1')
    ]);
    return res.redirect(`${base}/?gmail_connected=1`);
  } catch (e) {
    return res.redirect(`${FRONTEND_URL || ''}/?gmail_error=${encodeURIComponent(e.message)}`);
  }
});

// GET /api/auth/gmail/status — current Gmail connection state
app.get('/api/auth/gmail/status', async (req, res) => {
  try {
    const settings = await getIntegrationSettings();
    return res.json({
      connected: Boolean(settings.gmail_access_token),
      account_email: settings.gmail_account_email || '',
      has_refresh_token: Boolean(settings.gmail_refresh_token),
      scan_enabled: settings.gmail_scan_enabled,
      oauth_client_configured: Boolean(settings.oauth_client_id && settings.oauth_client_secret),
      oauth_from_env: settings.oauth_from_env,
      callback_uri: getGmailCallbackUri(req)
    });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

// POST /api/auth/gmail/disconnect — revoke stored tokens
app.post('/api/auth/gmail/disconnect', async (req, res) => {
  try {
    const settings = await getIntegrationSettings();
    // Best-effort revoke with Google (non-fatal if it fails)
    if (settings.gmail_refresh_token) {
      try {
        await fetch(`https://oauth2.googleapis.com/revoke?token=${encodeURIComponent(settings.gmail_refresh_token)}`, {
          method: 'POST'
        });
      } catch (_) { /* ignore */ }
    }
    await Promise.all([
      upsertSettingValue('gmail_access_token', ''),
      upsertSettingValue('gmail_refresh_token', ''),
      upsertSettingValue('gmail_account_email', ''),
      upsertSettingValue('gmail_scan_enabled', '0')
    ]);
    return res.json({ ok: true, message: 'Gmail disconnected' });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
});

const serveFrontendBuild = process.env.SERVE_FRONTEND_BUILD === '1';
if (serveFrontendBuild) {
  const frontendBuildPath = path.join(__dirname, '..', 'frontend', 'build');
  const frontendIndexPath = path.join(frontendBuildPath, 'index.html');

  if (fs.existsSync(frontendIndexPath)) {
    app.use(express.static(frontendBuildPath));
    app.get(/^\/(?!api\/|health$).*/, (req, res) => {
      res.sendFile(frontendIndexPath);
    });
    console.log(`Serving frontend build from ${frontendBuildPath}`);
  } else {
    console.warn(`SERVE_FRONTEND_BUILD=1 but missing ${frontendIndexPath}`);
  }
}

// Start server
app.listen(PORT, () => {
  console.log(`✨ Campsite CRM Server running on port ${PORT}`);
  console.log('📊 Dashboard available at http://localhost:3000');
});

const healthAliasPort = parseInt(process.env.HEALTH_ALIAS_PORT || '', 10)
  || (PORT === 5000 ? null : 5000);
if (healthAliasPort && healthAliasPort !== PORT) {
  const aliasApp = express();
  aliasApp.get('/health', (req, res) => {
    res.json({
      status: 'OK',
      timestamp: new Date().toISOString(),
      proxied_to_port: PORT
    });
  });
  aliasApp.listen(healthAliasPort, () => {
    console.log(`Health alias listening on port ${healthAliasPort}`);
  });
}
