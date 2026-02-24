# 🚀 Campsite CRM - Setup Guide

## First Time Setup

### Step 1: Install Node Dependencies

**Backend:**
```bash
cd /home/rob/.openclaw/workspace/campsite-crm/backend
npm install
```

**Frontend:**
```bash
cd /home/rob/.openclaw/workspace/campsite-crm/frontend
npm install
cp .env.example .env
# set REACT_APP_GOOGLE_CLIENT_ID if you want Google OAuth login enabled
```

### Step 2: Start the Backend Server

```bash
cd /home/rob/.openclaw/workspace/campsite-crm/backend
npm start
```

You should see:
```
✨ Campsite CRM Server running on port 5000
📊 Dashboard available at http://localhost:3000
Connected to SQLite database at /home/rob/.openclaw/workspace/campsite-crm/backend/campsite_crm.db
```

### Step 3: Start the Frontend (in a new terminal)

```bash
cd /home/rob/.openclaw/workspace/campsite-crm/frontend
npm start
```

This will automatically open http://localhost:3000 in your browser.

Login options on the app landing screen:
- Google OAuth (if `REACT_APP_GOOGLE_CLIENT_ID` is configured)
- `Continue with Beta Bypass` (always available in beta)

---

## What You Get

### 🎨 Beautiful Interface
- Turquoise (#00d9ff) and Pink (#ff006e) color scheme (perfect for your wife!)
- Responsive design works on desktop, tablet, and mobile
- Smooth animations and transitions
- Shiny cards with depth effect

### 📊 Core Features

1. **Dashboard**: Real-time overview of sales metrics
   - Total bookings
   - Total revenue
   - Total nights booked
   - Return booking percentage

2. **Booking Management**: Add and manage all bookings
   - Guest information
   - Booking details (nights, area, revenue)
   - Return customer tracking
   - Easy delete/edit functionality

3. **Return Guest Analysis**: Track repeat customers
   - Identify VIP guests
   - View visit count and revenue per guest
   - Loyalty badges for top customers

4. **Area Utilization**: See which areas generate most revenue
   - Revenue breakdown by area (Cabin, Tent, Kitchen, Barn, Pavilion)
   - Booking count per area
   - Performance metrics

### 🔄 Workflow

1. Add bookings as they come in
2. Dashboard automatically updates with metrics
3. Track return guests for loyalty programs
4. Analyze area performance for pricing optimization
5. Use date ranges to review specific periods

---

## Database

The application uses **SQLite3** - a file-based database that requires no setup.

- Database location: `/home/rob/.openclaw/workspace/campsite-crm/backend/campsite_crm.db`
- Automatically created on first run
- All bookings, guests, and areas are tracked
- Simple to back up (just copy the .db file)

---

## Customization

### Change Colors
Edit `/campsite-crm/frontend/src/App.css` and update:
```css
:root {
  --primary: #00d9ff;        /* Main turquoise */
  --secondary: #ff006e;       /* Pink accent */
  --accent: #fb5607;          /* Orange accent */
  /* ... other colors ... */
}
```

### Add Areas
Edit the area options in `BookingForm.jsx`:
```jsx
<select name="area_rented" value={formData.area_rented} onChange={handleChange}>
  <option value="cabin">Cabin</option>
  <option value="tent">Tent Site</option>
  {/* Add your custom areas here */}
</select>
```

### Change Date Format
Look for `moment()` usage in components and adjust formatting as needed.

---

## Troubleshooting

### Port Already in Use
If port 5000 or 3000 is already in use:

**Backend** (change port):
```bash
PORT=5001 npm start
```

**Frontend** (.env file):
```
REACT_APP_API_URL=http://localhost:5001
```

### Database Issues
If something goes wrong with the database, delete it and restart:
```bash
rm /home/rob/.openclaw/workspace/campsite-crm/backend/campsite_crm.db
npm start  # Restart backend
```

### Dependencies Not Installing
```bash
# Clear npm cache
npm cache clean --force

# Reinstall
npm install
```

---

## Daily Usage

### Adding Bookings
1. Click "➕ New Booking" tab
2. Fill in guest info and booking details
3. Click "💾 Save Booking"

### Viewing Reports
1. Use date range at top to filter
2. Click "📊 Dashboard" for overview
3. Click "🔄 Return Guests" to see loyalists
4. Click "🏕️ Area Usage" for area analytics

### Exporting Data
(Feature coming soon - for now, data is in SQLite database)

---

## Support & Customization

The code is yours to modify! Feel free to:
- Add new fields to bookings
- Create custom reports
- Change the color scheme
- Add email notifications
- Integrate with other systems

Just make sure both backend and frontend servers are running when testing changes.

---

## Next Steps

1. ✅ Start both servers
2. ✅ Add your first booking
3. ✅ Explore the dashboard
4. ✅ Customize colors/fields to match your style
5. 📧 Share feedback for improvements!

Enjoy! 🎉
