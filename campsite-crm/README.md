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

# Start the development server
npm start
```

The frontend will open at `http://localhost:3000`

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
- `GET /api/dashboard/summary` - Get dashboard statistics

### Bookings
- `GET /api/bookings` - Get all bookings
- `GET /api/bookings/grouped/:period` - Group bookings by day/week/month
- `POST /api/bookings` - Create new booking
- `PUT /api/bookings/:id` - Update booking
- `DELETE /api/bookings/:id` - Delete booking

### Analytics
- `GET /api/return-guests` - Get return guest analysis
- `GET /api/areas` - Get area utilization data

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
