import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';
import Dashboard from './components/Dashboard';
import BookingForm from './components/BookingForm';
import BookingsTable from './components/BookingsTable';
import ReturnGuestAnalysis from './components/ReturnGuestAnalysis';
import AreaUtilization from './components/AreaUtilization';

function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [bookings, setBookings] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [dateRange, setDateRange] = useState({
    startDate: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0],
    endDate: new Date().toISOString().split('T')[0]
  });

  // Fetch data
  const fetchData = async () => {
    setLoading(true);
    try {
      const [bookingsRes, summaryRes] = await Promise.all([
        axios.get('/api/bookings', { params: dateRange }),
        axios.get('/api/dashboard/summary', { params: dateRange })
      ]);
      setBookings(bookingsRes.data);
      setSummary(summaryRes.data);
    } catch (error) {
      console.error('Error fetching data:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [dateRange]);

  const handleAddBooking = async (bookingData) => {
    try {
      await axios.post('/api/bookings', bookingData);
      fetchData();
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
        fetchData();
        alert('Booking deleted');
      } catch (error) {
        console.error('Error deleting booking:', error);
      }
    }
  };

  return (
    <div className="app">
      {/* Header */}
      <header className="app-header">
        <div className="header-content">
          <h1>✨ Campsite Sales Dashboard ✨</h1>
          <p>Track bookings, revenue & guest relationships</p>
        </div>
      </header>

      {/* Navigation */}
      <nav className="main-nav">
        <button
          className={`nav-btn ${activeTab === 'dashboard' ? 'active' : ''}`}
          onClick={() => setActiveTab('dashboard')}
        >
          📊 Dashboard
        </button>
        <button
          className={`nav-btn ${activeTab === 'bookings' ? 'active' : ''}`}
          onClick={() => setActiveTab('bookings')}
        >
          📅 Bookings
        </button>
        <button
          className={`nav-btn ${activeTab === 'add' ? 'active' : ''}`}
          onClick={() => setActiveTab('add')}
        >
          ➕ New Booking
        </button>
        <button
          className={`nav-btn ${activeTab === 'returns' ? 'active' : ''}`}
          onClick={() => setActiveTab('returns')}
        >
          🔄 Return Guests
        </button>
        <button
          className={`nav-btn ${activeTab === 'areas' ? 'active' : ''}`}
          onClick={() => setActiveTab('areas')}
        >
          🏕️ Area Usage
        </button>
      </nav>

      {/* Date Range Selector */}
      <div className="date-range-selector">
        <div className="date-input-group">
          <label>From:</label>
          <input
            type="date"
            value={dateRange.startDate}
            onChange={(e) => setDateRange({ ...dateRange, startDate: e.target.value })}
          />
        </div>
        <div className="date-input-group">
          <label>To:</label>
          <input
            type="date"
            value={dateRange.endDate}
            onChange={(e) => setDateRange({ ...dateRange, endDate: e.target.value })}
          />
        </div>
        <button className="refresh-btn" onClick={fetchData} disabled={loading}>
          {loading ? '⏳ Loading...' : '🔄 Refresh'}
        </button>
      </div>

      {/* Main Content */}
      <main className="app-content">
        {activeTab === 'dashboard' && (
          <Dashboard summary={summary} bookings={bookings} loading={loading} />
        )}
        {activeTab === 'bookings' && (
          <BookingsTable bookings={bookings} onDelete={handleDeleteBooking} loading={loading} />
        )}
        {activeTab === 'add' && (
          <BookingForm onSubmit={handleAddBooking} />
        )}
        {activeTab === 'returns' && (
          <ReturnGuestAnalysis dateRange={dateRange} />
        )}
        {activeTab === 'areas' && (
          <AreaUtilization dateRange={dateRange} />
        )}
      </main>

      {/* Footer */}
      <footer className="app-footer">
        <p>Built with 💕 for amazing campsites</p>
      </footer>
    </div>
  );
}

export default App;
