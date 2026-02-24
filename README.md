# 🏕️ Campsite CRM - Sales & Booking Management System

A beautiful, modern CRM system built specifically for campsite businesses to track sales, bookings, revenue, and customer relationships.

## ✨ Features

### 📊 Dashboard
- **Real-time statistics** on total bookings, revenue, nights booked
- **Return guest tracking** to identify repeat customers
- **Recent bookings preview** for quick overview
- **Actionable insights** with average booking values and return rates

### 📅 Booking Management
- **Add new bookings** with detailed guest information
- **Track booking types**: Individual, Family, Group, Corporate, Church/Organization
- **Detailed booking data**: Guest name, type, nights, area, revenue, notes
- **Easy booking deletion** for corrections
- **Date filtering** to view specific time periods

### 💰 Revenue Tracking
- **Track revenue by booking**
- **View revenue by time period**: Day, Week, Month
- **Area-based revenue analysis** to see which areas generate most income
- **Return guest revenue** to measure customer lifetime value

### 🔄 Return Guest Analysis
- **Identify repeat customers** automatically
- **Track visit count** and total revenue per guest
- **Loyalty badges** (VIP, Loyal, Returning)
- **Guest insights** including top customers and visit frequency

### 🏕️ Area Utilization
- **Track usage by area**: Cabins, Tents, Kitchen, Barn, Pavilion
- **Revenue breakdown** by area
- **Booking count** and nights booked per area
- **Performance metrics** to optimize area pricing and promotion

### 🛰️ Arrival & Departure Radar
- Manage the next seven arrivals with guest name, area, nights, status, and the computed departure date so you can plan turnovers.
- Status chips keep confirmations, check-ins, checked-outs, cancellations, and no-shows visible at a glance.
- Backed by `GET /api/bookings/arrival-radar`, the new dashboard card always shows the freshest arrivals and departures.

### 🔖 Booking Status Tracker
- The booking form and edit flows now persist a status dropdown (Active, Confirmed, Checked-In, Checked-Out, Canceled, No-Show).
- Dashboard badges powered by `GET /api/bookings/status-summary` surface live counts for each status and keep the team aligned.

### ⭐ Guest Value Spotlight
- Highlights the top three return guests by lifetime revenue using the `/api/return-guests` data feed.
- Shows visit count, revenue, and loyalty badges (VIP if >3 visits, Loyal if >1) so the best patrons stay top-of-mind.

### 📈 Revenue by Guest Type
- Chart.js renders a colorful comparison so you can see revenue and booking counts by guest type (Individual, Family, Group, Corporate, Church).
- `GET /api/bookings/by-guest-type` aggregates booking_count and total_revenue for the selected window powering the chart.

### 🤝 Contract Snapshot
- Surfaces active horse group contracts (name, group, dates, status) plus renewal windows so you never miss a renewal.
- `GET /api/contracts/active` sends the current contracts to the dashboard card.

### 💳 Payment Center & Balance Tracking
- Each booking now tracks `amount_paid`, `due_date`, computed `balance_due`, and an automatic payment status (`paid`, `partial`, `unpaid`, `overdue`).
- New payment tab gives a quick ledger view and lets staff update paid amounts + due dates in seconds.
- `GET /api/payments/summary` powers collected/outstanding/overdue KPIs.

### 📝 Waitlist Manager
- Capture guests when the campsite is full and track them through `waiting`, `contacted`, `converted`, or `closed`.
- One-click conversion turns a waitlist entry into a confirmed booking once inventory opens up.
- Backed by `GET/POST/PUT/DELETE /api/waitlist` and `POST /api/waitlist/:id/convert`.

### ✅ Task Board
- Track operational tasks (`todo`, `in_progress`, `done`) directly in CRM.
- Tasks are exposed via both REST and MCP tools so ChatGPT assistants can plan and update operations.
- Backed by `GET/POST/PUT/DELETE /api/tasks`.

### 🤖 ChatGPT + MCP Integration Hub
- New Settings tab connects OpenAI/ChatGPT with optional MCP shared-secret auth.
- In-app ChatGPT panel lets users ask questions against live CRM context (bookings, waitlist, tasks, summary).
- MCP JSON-RPC endpoint at `POST /mcp` exposes tools for summary, bookings, waitlist, and tasks.
- Integration endpoints: `/api/integrations/chatgpt/settings`, `/api/integrations/chatgpt/test`, `/api/chatgpt/chat`.

### 🧺 Add-on Upsell Tracking
- Booking form now includes add-on selections (firewood, s'mores kit, kayak rental, etc.) with quantity support.
- Dashboard highlights top-selling add-ons and total add-on revenue.
- `GET /api/addons/summary` aggregates add-on quantity and revenue.

### 📬 Automated Message Queue
- Dashboard previews pre-arrival, departure-day follow-up, and payment reminder messages for the next cycle.
- Built to support operational follow-through even before external email/SMS automation is connected.
- `GET /api/messages/upcoming` returns the actionable queue.

### 📈 Occupancy-Based Pricing Recommendations
- A 30-day occupancy window now produces area-level price guidance (`raise`, `hold`, `discount`) with suggested percent changes.
- Helps operators react to demand without guessing.
- `GET /api/pricing/recommendations` returns the recommendation set.

### 🧭 Booking Assistant (New)
- Added a dedicated booking assistant tab with five high-value booking features inspired by campsite booking leaders:
1. **Availability by area** for selected dates, nights, and party size.
2. **Amenity-based area matching** (power, pet-friendly, shelter, horse stalls, etc.).
3. **Alternate date suggestions** when preferred options are tight.
4. **Transparent trip cost estimate** (base, add-ons, service fee, tax, deposit due today).
5. **Cancellation preview** with full/partial/non-refundable windows and refund examples.
6. **Stay rules checker** (weekend minimums, max nights, same-day cutoff, party-size guardrails).
7. **Self-service change/cancel preview** with estimated fee, refund amount, and rebooking credit.
8. **Availability alert capture** (email/phone) so guests can be contacted when inventory opens.
9. **Booking readiness score** to quickly gauge confidence before finalizing a booking.
10. **Site-lock transparency** with optional exact-site lock fee included in quote.

## 🚀 Quick Start

### Prerequisites
- Node.js (v14 or higher)
- npm or yarn

### Backend Setup

```bash
cd campsite-crm/backend

# Install dependencies
npm install

# Start the server
npm start
```

The backend will run on `http://localhost:5000`

### Frontend Setup

```bash
cd campsite-crm/frontend

# Install dependencies
npm install

# Optional: enable Google OAuth login
cp .env.example .env
# then set REACT_APP_GOOGLE_CLIENT_ID in .env

# Start the development server
npm start
```

The frontend will open at `http://localhost:3000`

## Login (beta)

- Google OAuth login is available via Google Identity Services when `REACT_APP_GOOGLE_CLIENT_ID` is set.
- A `Continue with Beta Bypass` button remains available for non-live testing.
- Login currently gates app access only; all signed-in users see the same shared CRM data.

## Always-On Mode (recommended)

To keep Campsite CRM live across terminal closes, crashes, and reboots, run:

```bash
cd campsite-crm
./scripts/install-systemd-user.sh
```

This installs `~/.config/systemd/user/campsite-crm.service` with `Restart=always` and serves the app at `http://localhost:3000`.

Useful commands:

```bash
systemctl --user status campsite-crm.service
journalctl --user -u campsite-crm.service -f
systemctl --user restart campsite-crm.service
```

## 📁 Project Structure

```
campsite-crm/
├── backend/
│   ├── server.js           # Express server & API routes
│   ├── campsite_crm.db     # SQLite database (auto-created)
│   └── package.json
│
└── frontend/
    ├── src/
    │   ├── App.jsx         # Main app component
    │   ├── App.css         # Global styles
    │   ├── components/     # React components
    │   │   ├── Dashboard.jsx
    │   │   ├── BookingForm.jsx
    │   │   ├── BookingsTable.jsx
    │   │   ├── ReturnGuestAnalysis.jsx
    │   │   └── AreaUtilization.jsx
    │   └── styles/         # Component-specific CSS
    └── package.json
```

## 🎨 Design Features

### Color Theme (Perfect for Your Wife!)
- **Primary**: Turquoise (#00d9ff) - Fresh & modern
- **Secondary**: Pink (#ff006e) - Beautiful & elegant
- **Accent**: Orange (#fb5607) - Energetic & fun

### UI Elements
- **Glassmorphism effects** with soft shadows
- **Smooth animations** and transitions
- **Responsive design** - works on desktop, tablet, mobile
- **Depth & shine** with layered cards and gradients

## 📊 API Endpoints

### Dashboard
- `GET /api/dashboard/summary` - Get dashboard statistics for the selected period

### Bookings
- `GET /api/bookings` - Fetch all bookings with optional start/end filters
- `GET /api/bookings/grouped/:period` - Group bookings by day/week/month
- `POST /api/bookings` - Create a booking (accepts `booking_date`, `status`, `nights`, `area_rented`, `revenue`, etc.)
- `PUT /api/bookings/:id` - Update booking details or status (supports arrival date + status changes)
- `DELETE /api/bookings/:id` - Delete a booking
- `GET /api/bookings/status-summary` - Return counts per status for the dashboard badges
- `GET /api/bookings/arrival-radar` - Surface the next seven arrivals with computed departure dates and status
- `GET /api/payments/summary` - Revenue collected vs outstanding balances with overdue counts
- `GET /api/addons/summary` - Add-on revenue + quantity leaderboard
- `GET /api/messages/upcoming` - Generated pre-arrival/post-stay/payment reminder queue
- `GET /api/pricing/recommendations` - Occupancy-driven pricing guidance by area
- `GET /api/booking-assistant/availability` - Availability + amenity matching + alternate date suggestions
- `POST /api/booking-assistant/cost-estimate` - Full booking price breakdown and deposit amount
- `GET /api/booking-assistant/cancellation-preview` - Date-based cancellation/refund preview
- `GET /api/booking-assistant/stay-rules` - Validate stay against booking rules
- `POST /api/booking-assistant/manage-preview` - Estimate modify/cancel outcomes before staff changes booking
- `POST /api/booking-assistant/availability-alerts` - Save alert subscriptions for out-of-stock date/area requests
- `GET /api/booking-assistant/readiness-score` - Return booking confidence score from availability + rules + amenity fit

### Analytics
- `GET /api/return-guests` - Get return guest analysis
- `GET /api/areas` - Get area utilization data
- `GET /api/bookings/by-guest-type` - Aggregate booking_count and total_revenue grouped by guest_type

### Waitlist
- `GET /api/waitlist` - List waitlist entries
- `POST /api/waitlist` - Add a waitlist entry
- `PUT /api/waitlist/:id` - Update waitlist status/details
- `DELETE /api/waitlist/:id` - Remove waitlist entry
- `POST /api/waitlist/:id/convert` - Convert waitlist entry into a booking

### Tasks
- `GET /api/tasks` - List all operational tasks
- `POST /api/tasks` - Create a task
- `PUT /api/tasks/:id` - Update task details/status
- `DELETE /api/tasks/:id` - Delete a task

### ChatGPT & MCP Integration
- `GET /api/integrations/chatgpt/settings` - Read integration settings (safe metadata only)
- `PUT /api/integrations/chatgpt/settings` - Save integration settings
- `POST /api/integrations/chatgpt/test` - Validate OpenAI connection
- `GET /api/integrations/chatgpt/mcp-instructions` - Retrieve MCP setup metadata
- `POST /api/chatgpt/chat` - Ask ChatGPT from inside CRM (optionally with live CRM context)
- `POST /mcp` - MCP JSON-RPC endpoint (`initialize`, `tools/list`, `tools/call`)

### Contracts
- `GET /api/contracts/active` - Show active horse group contracts with start/end windows

### Health Check
- `GET /health` - API health status

## 💾 Database Schema

### bookings table
- `id` (TEXT) - Unique identifier
- `booking_date` (TEXT) - Booking date
- `guest_name` (TEXT) - Guest name
- `guest_type` (TEXT) - Individual, Family, Group, etc.
- `group_type` (TEXT) - Type of group (if applicable)
- `nights` (INTEGER) - Number of nights
- `area_rented` (TEXT) - Cabin, Tent, Kitchen, etc.
- `revenue` (REAL) - Booking revenue
- `amount_paid` (REAL) - Amount already collected
- `due_date` (TEXT) - Balance due date
- `add_ons` (TEXT/JSON) - Serialized add-on items sold with booking
- `is_return_booking` (INTEGER) - 1 if return guest
- `notes` (TEXT) - Additional notes
- `created_at` (TEXT) - Creation timestamp
- `updated_at` (TEXT) - Last update timestamp

### contracts table
For horse group monthly contracts:
- `id` (TEXT)
- `contract_name` (TEXT)
- `group_name` (TEXT)
- `base_monthly_rate` (REAL)
- `per_guest_rate` (REAL)
- `start_date` (TEXT)
- `end_date` (TEXT)

### guest_history table
Track repeat customers:
- `id` (TEXT)
- `guest_name` (TEXT)
- `total_visits` (INTEGER)
- `total_revenue` (REAL)
- `last_visit_date` (TEXT)

## 🔧 Configuration

### Environment Variables
Create a `.env` file in the backend directory (optional):

```
PORT=5000
NODE_ENV=development
```

### Database
SQLite database is auto-created at `backend/campsite_crm.db` on first run.
No additional setup needed!

## 📱 Usage Guide

### Adding a Booking
1. Navigate to "➕ New Booking" tab
2. Fill in guest information
3. Enter booking details (nights, area, revenue)
4. Add optional notes
5. Click "💾 Save Booking"

### Viewing Bookings
1. Go to "📅 Bookings" tab
2. Use date range selector to filter
3. View all bookings in table format
4. Click 🗑️ to delete if needed

### Analyzing Performance
1. **Dashboard**: See overall statistics
2. **Return Guests**: Identify loyal customers
3. **Area Usage**: Optimize pricing by area
4. Use date range filters for custom periods

## 🎯 Future Enhancements

- [ ] Export reports as PDF/Excel
- [ ] Email notifications for bookings
- [ ] Custom pricing rules by area/season
- [ ] Booking calendar view
- [ ] Guest communication templates
- [ ] Advanced analytics & forecasting
- [ ] Multi-user support with roles
- [ ] Mobile app
- [ ] Payment integration
- [ ] Automated invoice generation

## 🛠️ Development

### Technologies Used
- **Backend**: Node.js, Express.js, SQLite3
- **Frontend**: React 18, CSS3
- **Libraries**: Axios, Moment.js, UUID

### Adding Features
1. Backend: Add route in `server.js`, update database schema
2. Frontend: Create component in `src/components/`, add CSS in `src/styles/`
3. Test with date ranges and various booking types

### Debugging
- Backend logs available in console
- Frontend DevTools for React component debugging
- SQLite3 CLI: `sqlite3 backend/campsite_crm.db` for direct database queries

## 📝 Notes

- All data is stored locally in SQLite (no cloud dependency)
- Times are displayed in local browser timezone
- Colors and styles are fully customizable in CSS files
- Responsive design works great on mobile!

## 💝 Built With Love

This CRM was built specifically to help your wife showcase all her amazing work managing bookings for the campsite. It's designed to be beautiful, easy to use, and provide valuable insights into her sales performance.

Enjoy tracking all those bookings! 🎉

---

**Questions or feature requests?** Feel free to modify the code or add new features as needed!
