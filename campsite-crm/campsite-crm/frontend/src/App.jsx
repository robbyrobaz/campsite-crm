import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import './App.css';
import './styles/InsightsExtras.css';
import Dashboard from './components/Dashboard';
import BookingForm from './components/BookingForm';
import BookingsTable from './components/BookingsTable';
import ReturnGuestAnalysis from './components/ReturnGuestAnalysis';
import AreaUtilization from './components/AreaUtilization';
import PaymentCenter from './components/PaymentCenter';
import WaitlistManager from './components/WaitlistManager';
import TaskManager from './components/TaskManager';
import IntegrationHub from './components/IntegrationHub';
import BookingAssistant from './components/BookingAssistant';
import Contacts from './components/Contacts';

const BOOKING_STATUS_OPTIONS = [
  { value: 'active', label: 'Active' },
  { value: 'confirmed', label: 'Confirmed' },
  { value: 'checked-in', label: 'Checked In' },
  { value: 'checked-out', label: 'Checked Out' },
  { value: 'canceled', label: 'Canceled' },
  { value: 'no-show', label: 'No-Show' }
];

const WAITLIST_STATUS_OPTIONS = [
  { value: 'waiting', label: 'Waiting' },
  { value: 'contacted', label: 'Contacted' },
  { value: 'converted', label: 'Converted' },
  { value: 'closed', label: 'Closed' }
];

const TABS = [
  { id: 'dashboard', label: 'Dashboard', icon: '📊' },
  { id: 'bookings', label: 'Bookings', icon: '📅' },
  { id: 'add', label: 'New Booking', icon: '➕' },
  { id: 'payments', label: 'Payments', icon: '💳' },
  { id: 'tasks', label: 'Tasks', icon: '✅' },
  { id: 'waitlist', label: 'Waitlist', icon: '📝' },
  { id: 'assistant', label: 'Booking Assistant', icon: '🧭' },
  { id: 'returns', label: 'Return Guests', icon: '🔄' },
  { id: 'areas', label: 'Area Usage', icon: '🏕️' },
  { id: 'contacts', label: 'Contacts', icon: '👥' },
  { id: 'settings', label: 'Settings', icon: '⚙️' }
];

const AUTH_STORAGE_KEY = 'campsite_crm_auth_v1';
const APPEARANCE_STORAGE_KEY = 'campsite_crm_appearance_v1';
const DEFAULT_APPEARANCE = {
  palette: 'turquoise-sunrise',
  shadow: 'lush'
};

const APPEARANCE_OPTIONS = [
  { value: 'turquoise-sunrise', label: 'Turquoise Sunrise' },
  { value: 'ocean-breeze', label: 'Ocean Breeze' },
  { value: 'mint-current', label: 'Mint Current' },
  { value: 'coral-glow', label: 'Coral Glow' },
  { value: 'sunset-citrus', label: 'Sunset Citrus' },
  { value: 'lavender-dusk', label: 'Lavender Dusk' },
  { value: 'berry-pop', label: 'Berry Pop' },
  { value: 'forest-mist', label: 'Forest Mist' },
  { value: 'midnight-teal', label: 'Midnight Teal' },
  { value: 'golden-hour', label: 'Golden Hour' },
  { value: 'slate-ice', label: 'Slate Ice' },
  { value: 'rosewater', label: 'Rosewater' },
  { value: 'ember-night', label: 'Ember Night' }
];

const SHADOW_OPTIONS = [
  { value: 'soft', label: 'Soft shadows' },
  { value: 'lush', label: 'Lush shadows' },
  { value: 'bold', label: 'Bold shadows' }
];

const decodeJwtPayload = (token) => {
  try {
    const payload = token.split('.')[1];
    if (!payload) return null;
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
    const json = decodeURIComponent(
      atob(base64)
        .split('')
        .map((char) => `%${(`00${char.charCodeAt(0).toString(16)}`).slice(-2)}`)
        .join('')
    );
    return JSON.parse(json);
  } catch (error) {
    return null;
  }
};

function App() {
  const googleClientId = process.env.REACT_APP_GOOGLE_CLIENT_ID || '';
  const googleButtonRef = useRef(null);

  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authUser, setAuthUser] = useState(null);
  const [authMethod, setAuthMethod] = useState('');
  const [authError, setAuthError] = useState('');
  const [activeTab, setActiveTab] = useState('dashboard');
  const [bookings, setBookings] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);

  const [statusSummary, setStatusSummary] = useState([]);
  const [arrivalRadar, setArrivalRadar] = useState([]);
  const [guestTypeData, setGuestTypeData] = useState([]);
  const [guestSpotlight, setGuestSpotlight] = useState([]);
  const [contracts, setContracts] = useState([]);
  const [returnGuests, setReturnGuests] = useState([]);
  const [paymentSummary, setPaymentSummary] = useState(null);
  const [messageQueue, setMessageQueue] = useState([]);
  const [pricingData, setPricingData] = useState([]);
  const [addonSummary, setAddonSummary] = useState({ total_addon_revenue: 0, items: [] });
  const [waitlistEntries, setWaitlistEntries] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [contactsRefreshToken, setContactsRefreshToken] = useState(0);
  const [appearance, setAppearance] = useState(DEFAULT_APPEARANCE);

  const [dateRange, setDateRange] = useState({
    startDate: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0],
    endDate: new Date().toISOString().split('T')[0]
  });

  const persistAuth = useCallback((session) => {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
    setIsAuthenticated(true);
    setAuthUser(session.user);
    setAuthMethod(session.method);
    setAuthError('');
  }, []);

  const handleBypassLogin = useCallback(() => {
    persistAuth({
      method: 'bypass',
      user: {
        name: 'Beta Tester',
        email: ''
      }
    });
  }, [persistAuth]);

  const handleLogout = useCallback(() => {
    localStorage.removeItem(AUTH_STORAGE_KEY);
    setIsAuthenticated(false);
    setAuthUser(null);
    setAuthMethod('');
    setAuthError('');
    if (window.google?.accounts?.id) {
      window.google.accounts.id.disableAutoSelect();
    }
  }, []);

  useEffect(() => {
    const saved = localStorage.getItem(AUTH_STORAGE_KEY);
    if (!saved) return;
    try {
      const parsed = JSON.parse(saved);
      if (parsed?.user?.name && parsed?.method) {
        setIsAuthenticated(true);
        setAuthUser(parsed.user);
        setAuthMethod(parsed.method);
      }
    } catch (error) {
      localStorage.removeItem(AUTH_STORAGE_KEY);
    }
  }, []);

  // Handle return from Gmail OAuth flow — switch to Settings tab so the user sees the result.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('gmail_connected') === '1' || params.get('gmail_error')) {
      setActiveTab('settings');
    }
  }, []);

  useEffect(() => {
    const rawAppearance = localStorage.getItem(APPEARANCE_STORAGE_KEY);
    if (!rawAppearance) return;

    try {
      const parsed = JSON.parse(rawAppearance);
      const nextPalette = APPEARANCE_OPTIONS.some((option) => option.value === parsed?.palette)
        ? parsed.palette
        : DEFAULT_APPEARANCE.palette;
      const nextShadow = SHADOW_OPTIONS.some((option) => option.value === parsed?.shadow)
        ? parsed.shadow
        : DEFAULT_APPEARANCE.shadow;
      setAppearance({ palette: nextPalette, shadow: nextShadow });
    } catch (error) {
      localStorage.removeItem(APPEARANCE_STORAGE_KEY);
    }
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = appearance.palette;
    document.documentElement.dataset.shadow = appearance.shadow;
    localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify(appearance));
  }, [appearance]);

  const handleGoogleCredential = useCallback((response) => {
    const payload = decodeJwtPayload(response?.credential || '');
    if (!payload?.email) {
      setAuthError('Google sign-in returned an invalid token. Try again.');
      return;
    }

    persistAuth({
      method: 'google',
      user: {
        name: payload.name || payload.email,
        email: payload.email,
        avatar: payload.picture || ''
      }
    });
  }, [persistAuth]);

  useEffect(() => {
    if (isAuthenticated || !googleClientId || !googleButtonRef.current) return;

    let isMounted = true;
    const initializeButton = () => {
      if (!isMounted || !window.google?.accounts?.id || !googleButtonRef.current) return;
      googleButtonRef.current.innerHTML = '';
      window.google.accounts.id.initialize({
        client_id: googleClientId,
        callback: handleGoogleCredential
      });
      window.google.accounts.id.renderButton(googleButtonRef.current, {
        theme: 'outline',
        size: 'large',
        shape: 'pill',
        width: 260
      });
    };

    if (window.google?.accounts?.id) {
      initializeButton();
      return () => {
        isMounted = false;
      };
    }

    const existingScript = document.querySelector('script[data-google-identity]');
    if (existingScript) {
      existingScript.addEventListener('load', initializeButton, { once: true });
      return () => {
        isMounted = false;
      };
    }

    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.defer = true;
    script.dataset.googleIdentity = 'true';
    script.onload = initializeButton;
    script.onerror = () => {
      setAuthError('Unable to load Google sign-in right now.');
    };
    document.head.appendChild(script);

    return () => {
      isMounted = false;
    };
  }, [googleClientId, handleGoogleCredential, isAuthenticated]);

  const fetchCoreData = async () => {
    setLoading(true);
    try {
      const [bookingsRes, summaryRes] = await Promise.all([
        axios.get('/api/bookings', { params: dateRange }),
        axios.get('/api/dashboard/summary', { params: dateRange })
      ]);
      setBookings(bookingsRes.data || []);
      setSummary(summaryRes.data || {});
    } catch (error) {
      console.error('Error fetching core data:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchDashboardExtras = async () => {
    try {
      const [
        statusRes,
        radarRes,
        guestTypeRes,
        returnGuestsRes,
        contractsRes,
        paymentRes,
        messagesRes,
        pricingRes,
        addonsRes
      ] = await Promise.all([
        axios.get('/api/bookings/status-summary', { params: dateRange }),
        axios.get('/api/bookings/arrival-radar'),
        axios.get('/api/bookings/by-guest-type', { params: dateRange }),
        axios.get('/api/return-guests'),
        axios.get('/api/contracts/active'),
        axios.get('/api/payments/summary', { params: dateRange }),
        axios.get('/api/messages/upcoming'),
        axios.get('/api/pricing/recommendations'),
        axios.get('/api/addons/summary', { params: dateRange })
      ]);

      const returnGuestRows = returnGuestsRes.data || [];

      setStatusSummary(statusRes.data || []);
      setArrivalRadar(radarRes.data || []);
      setGuestTypeData(guestTypeRes.data || []);
      setGuestSpotlight(returnGuestRows.slice(0, 3));
      setReturnGuests(returnGuestRows);
      setContracts(contractsRes.data || []);
      setPaymentSummary(paymentRes.data || null);
      setMessageQueue(messagesRes.data || []);
      setPricingData(pricingRes.data?.recommendations || []);
      setAddonSummary(addonsRes.data || { total_addon_revenue: 0, items: [] });
    } catch (error) {
      console.error('Error fetching dashboard extras:', error);
    }
  };

  const fetchWaitlist = async () => {
    try {
      const response = await axios.get('/api/waitlist');
      setWaitlistEntries(response.data || []);
    } catch (error) {
      console.error('Error fetching waitlist:', error);
    }
  };

  const fetchTasks = async () => {
    try {
      const response = await axios.get('/api/tasks');
      setTasks(response.data || []);
    } catch (error) {
      console.error('Error fetching tasks:', error);
    }
  };

  const refreshDashboard = () => {
    fetchCoreData();
    fetchDashboardExtras();
  };

  useEffect(() => {
    refreshDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateRange]);

  useEffect(() => {
    if (activeTab === 'waitlist') {
      fetchWaitlist();
    }
    if (activeTab === 'tasks') {
      fetchTasks();
    }
  }, [activeTab]);

  const handleAddBooking = async (bookingData) => {
    try {
      await axios.post('/api/bookings', bookingData);
      refreshDashboard();
      alert('Booking added successfully! 🎉');
    } catch (error) {
      console.error('Error adding booking:', error);
      alert('Failed to add booking');
    }
  };

  const handleDeleteBooking = async (id) => {
    if (window.confirm('Are you sure you want to delete this booking?')) {
      try {
        await axios.delete(`/api/bookings/${id}`);
        refreshDashboard();
        alert('Booking deleted');
      } catch (error) {
        console.error('Error deleting booking:', error);
      }
    }
  };

  const handleStatusUpdate = async (bookingId, newStatus) => {
    const booking = bookings.find((b) => b.id === bookingId);
    if (!booking) return;

    try {
      await axios.put(`/api/bookings/${bookingId}`, {
        ...booking,
        status: newStatus
      });
      refreshDashboard();
    } catch (error) {
      console.error('Error updating booking status:', error);
      alert('Unable to update booking status right now');
    }
  };

  const handlePaymentUpdate = async (bookingId, paymentData) => {
    const booking = bookings.find((b) => b.id === bookingId);
    if (!booking) return;

    try {
      await axios.put(`/api/bookings/${bookingId}`, {
        ...booking,
        ...paymentData
      });
      refreshDashboard();
    } catch (error) {
      console.error('Error updating payment details:', error);
      alert('Unable to update payment details right now');
    }
  };

  const handleAddWaitlistEntry = async (entry) => {
    try {
      await axios.post('/api/waitlist', entry);
      fetchWaitlist();
      alert('Waitlist entry added');
    } catch (error) {
      console.error('Error adding waitlist entry:', error);
      alert('Unable to add waitlist entry right now');
    }
  };

  const handleWaitlistStatusChange = async (entry, status) => {
    try {
      await axios.put(`/api/waitlist/${entry.id}`, { ...entry, status });
      fetchWaitlist();
    } catch (error) {
      console.error('Error updating waitlist status:', error);
      alert('Unable to update waitlist status right now');
    }
  };

  const handleConvertWaitlist = async (entry) => {
    const revenueValue = window.prompt(`Revenue for ${entry.guest_name}?`, '0');
    if (revenueValue === null) return;

    try {
      await axios.post(`/api/waitlist/${entry.id}/convert`, {
        revenue: parseFloat(revenueValue) || 0,
        area_rented: entry.preferred_area || 'tent',
        nights: 1,
        status: 'confirmed'
      });
      fetchWaitlist();
      refreshDashboard();
      alert('Converted to booking');
    } catch (error) {
      console.error('Error converting waitlist entry:', error);
      alert('Unable to convert waitlist entry right now');
    }
  };

  const handleDeleteWaitlistEntry = async (entryId) => {
    if (!window.confirm('Delete this waitlist entry?')) return;

    try {
      await axios.delete(`/api/waitlist/${entryId}`);
      fetchWaitlist();
    } catch (error) {
      console.error('Error deleting waitlist entry:', error);
      alert('Unable to delete waitlist entry right now');
    }
  };

  const handleAddTask = async (taskData) => {
    try {
      await axios.post('/api/tasks', taskData);
      fetchTasks();
    } catch (error) {
      console.error('Error adding task:', error);
      alert('Unable to add task right now');
    }
  };

  const handleUpdateTask = async (taskId, updates) => {
    try {
      await axios.put(`/api/tasks/${taskId}`, updates);
      fetchTasks();
    } catch (error) {
      console.error('Error updating task:', error);
      alert('Unable to update task right now');
    }
  };

  const handleDeleteTask = async (taskId) => {
    if (!window.confirm('Delete this task?')) return;
    try {
      await axios.delete(`/api/tasks/${taskId}`);
      fetchTasks();
    } catch (error) {
      console.error('Error deleting task:', error);
      alert('Unable to delete task right now');
    }
  };

  const summaryStats = summary || {
    total_bookings: 0,
    total_revenue: 0,
    return_bookings: 0
  };

  const activeBookings = bookings.filter((booking) =>
    ['active', 'confirmed', 'checked-in'].includes(booking.status)
  ).length;
  const overdueCount = paymentSummary?.overdue_count || 0;
  const waitlistOpenCount = waitlistEntries.filter((entry) => entry.status === 'waiting').length;
  const dateLabel = `${dateRange.startDate} to ${dateRange.endDate}`;

  if (!isAuthenticated) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <h1>Campsite CRM</h1>
          <p>Sign in with Google or use bypass mode while beta testing.</p>

          {googleClientId ? (
            <div className="google-signin-slot" ref={googleButtonRef} />
          ) : (
            <p className="auth-note">
              Google OAuth not configured. Add <code>REACT_APP_GOOGLE_CLIENT_ID</code> in frontend env.
            </p>
          )}

          <button className="bypass-btn" onClick={handleBypassLogin}>
            Continue with Beta Bypass
          </button>

          {authError && <p className="auth-error">{authError}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-left">
          <h1>Campsite CRM</h1>
          <p>Bookings, payments, and guest operations</p>
        </div>
        <div className="auth-session">
          <div className="auth-session-meta">
            <strong>{authUser?.name || 'Signed In'}</strong>
            <span>{authMethod === 'google' ? 'Google OAuth' : 'Bypass Mode'}</span>
          </div>
          <button className="logout-btn" onClick={handleLogout}>
            Logout
          </button>
        </div>
        <div className="header-kpis">
          <div className="header-kpi">
            <span>Bookings</span>
            <strong>{summaryStats.total_bookings || 0}</strong>
          </div>
          <div className="header-kpi">
            <span>Revenue</span>
            <strong>${(summaryStats.total_revenue || 0).toFixed(0)}</strong>
          </div>
          <div className="header-kpi">
            <span>Returns</span>
            <strong>{summaryStats.return_bookings || 0}</strong>
          </div>
        </div>
      </header>

      <div className="app-layout">
        <aside className="sidebar">
          <div className="sidebar-title">Workspace</div>
          <nav className="main-nav" aria-label="Main navigation">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                className={`nav-btn ${activeTab === tab.id ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                <span className="nav-icon">{tab.icon}</span>
                <span>{tab.label}</span>
              </button>
            ))}
          </nav>
          <div className="sidebar-footer">
            <div>
              <span>Period</span>
              <strong>{dateLabel}</strong>
            </div>
            <div>
              <span>Open Waitlist</span>
              <strong>{waitlistOpenCount}</strong>
            </div>
          </div>
        </aside>

        <section className="workspace">
          <main className="app-content">
            {activeTab === 'dashboard' && (
              <Dashboard
                summary={summary}
                bookings={bookings}
                loading={loading}
                statusSummary={statusSummary}
                arrivalRadar={arrivalRadar}
                guestValueSpotlight={guestSpotlight}
                guestTypeData={guestTypeData}
                contracts={contracts}
                paymentSummary={paymentSummary}
                messageQueue={messageQueue}
                pricingRecommendations={pricingData}
                addonSummary={addonSummary}
              />
            )}

            {activeTab === 'bookings' && (
              <BookingsTable
                bookings={bookings}
                statusOptions={BOOKING_STATUS_OPTIONS}
                onDelete={handleDeleteBooking}
                onStatusChange={handleStatusUpdate}
                loading={loading}
              />
            )}

            {activeTab === 'add' && (
              <BookingForm onSubmit={handleAddBooking} statusOptions={BOOKING_STATUS_OPTIONS} />
            )}

            {activeTab === 'payments' && (
              <PaymentCenter
                bookings={bookings}
                paymentSummary={paymentSummary}
                onUpdatePayment={handlePaymentUpdate}
              />
            )}

            {activeTab === 'waitlist' && (
              <WaitlistManager
                entries={waitlistEntries}
                statusOptions={WAITLIST_STATUS_OPTIONS}
                onAddEntry={handleAddWaitlistEntry}
                onStatusChange={handleWaitlistStatusChange}
                onConvert={handleConvertWaitlist}
                onDelete={handleDeleteWaitlistEntry}
              />
            )}

            {activeTab === 'tasks' && (
              <TaskManager
                tasks={tasks}
                onAddTask={handleAddTask}
                onUpdateTask={handleUpdateTask}
                onDeleteTask={handleDeleteTask}
              />
            )}

            {activeTab === 'assistant' && <BookingAssistant />}

            {activeTab === 'returns' && (
              <ReturnGuestAnalysis returnGuests={returnGuests} loading={loading} />
            )}

            {activeTab === 'areas' && (
              <AreaUtilization dateRange={dateRange} />
            )}

            {activeTab === 'contacts' && (
              <Contacts refreshToken={contactsRefreshToken} />
            )}

            {activeTab === 'settings' && (
              <>
                <div className="card appearance-settings-card">
                  <div className="appearance-settings-header">
                    <h3>Appearance</h3>
                    <p>Choose from vibrant gradient themes to match your style.</p>
                  </div>

                  <div className="form-row">
                    <div className="form-group">
                      <label htmlFor="appearance-palette">Color Theme</label>
                      <select
                        id="appearance-palette"
                        value={appearance.palette}
                        onChange={(event) => setAppearance((current) => ({ ...current, palette: event.target.value }))}
                      >
                        {APPEARANCE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </div>
                    <div className="form-group">
                      <label htmlFor="appearance-shadow">Shadow Depth</label>
                      <select
                        id="appearance-shadow"
                        value={appearance.shadow}
                        onChange={(event) => setAppearance((current) => ({ ...current, shadow: event.target.value }))}
                      >
                        {SHADOW_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="appearance-preview">
                    <div className="appearance-preview-gradient">
                      <strong>Live Preview</strong>
                      <span>Header + cards update instantly</span>
                    </div>
                  </div>
                </div>

                <IntegrationHub
                  onRefreshData={refreshDashboard}
                  onRefreshTasks={fetchTasks}
                  onRefreshContacts={() => setContactsRefreshToken((prev) => prev + 1)}
                  onRefreshWaitlist={fetchWaitlist}
                />
              </>
            )}
          </main>
        </section>

        <aside className="right-rail">
          <div className="rail-card">
            <h3>Filters</h3>
            <div className="date-range-selector">
              <div className="date-input-group">
                <label htmlFor="start-date">From</label>
                <input
                  id="start-date"
                  type="date"
                  value={dateRange.startDate}
                  onChange={(e) => setDateRange({ ...dateRange, startDate: e.target.value })}
                />
              </div>
              <div className="date-input-group">
                <label htmlFor="end-date">To</label>
                <input
                  id="end-date"
                  type="date"
                  value={dateRange.endDate}
                  onChange={(e) => setDateRange({ ...dateRange, endDate: e.target.value })}
                />
              </div>
              <button className="refresh-btn" onClick={refreshDashboard} disabled={loading}>
                {loading ? 'Loading...' : 'Refresh Data'}
              </button>
            </div>
          </div>

          <div className="rail-card">
            <h3>Live Ops</h3>
            <div className="rail-stats">
              <div className="rail-stat">
                <span>Active Stays</span>
                <strong>{activeBookings}</strong>
              </div>
              <div className="rail-stat">
                <span>Overdue Payments</span>
                <strong>{overdueCount}</strong>
              </div>
              <div className="rail-stat">
                <span>Waitlist Queue</span>
                <strong>{waitlistEntries.length}</strong>
              </div>
              <div className="rail-stat">
                <span>Return Guests</span>
                <strong>{returnGuests.length}</strong>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

export default App;
