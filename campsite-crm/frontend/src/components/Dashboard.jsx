import React from 'react';
import '../styles/Dashboard.css';

function Dashboard({ summary, bookings, loading }) {
  if (loading) {
    return <div className="loading">⏳ Loading dashboard data...</div>;
  }

  const stats = summary || {
    total_bookings: 0,
    total_nights: 0,
    total_revenue: 0,
    return_bookings: 0
  };

  const returnPercentage = stats.total_bookings > 0 
    ? ((stats.return_bookings / stats.total_bookings) * 100).toFixed(1)
    : 0;

  return (
    <div className="dashboard">
      <h2>📊 Sales Overview</h2>
      
      <div className="stats-grid">
        <div className="stat-card">
          <h3>Total Bookings</h3>
          <div className="value">{stats.total_bookings}</div>
          <div className="unit">this period</div>
        </div>

        <div className="stat-card">
          <h3>Total Revenue</h3>
          <div className="value">${stats.total_revenue?.toFixed(2) || '0.00'}</div>
          <div className="unit">earned</div>
        </div>

        <div className="stat-card">
          <h3>Total Nights</h3>
          <div className="value">{stats.total_nights || 0}</div>
          <div className="unit">booked</div>
        </div>

        <div className="stat-card">
          <h3>Return Bookings</h3>
          <div className="value">{stats.return_bookings || 0}</div>
          <div className="unit">{returnPercentage}% of total</div>
        </div>
      </div>

      <div className="recent-bookings-preview">
        <h3>📅 Recent Bookings</h3>
        {bookings && bookings.length > 0 ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>Guest Name</th>
                <th>Type</th>
                <th>Nights</th>
                <th>Area</th>
                <th>Revenue</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {bookings.slice(0, 10).map(booking => (
                <tr key={booking.id}>
                  <td><strong>{booking.guest_name}</strong></td>
                  <td>{booking.guest_type}</td>
                  <td>{booking.nights}</td>
                  <td>{booking.area_rented}</td>
                  <td className="revenue">${booking.revenue.toFixed(2)}</td>
                  <td>{new Date(booking.booking_date).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty-state">
            <p>No bookings in this period yet</p>
          </div>
        )}
      </div>

      <div className="insights">
        <h3>💡 Insights</h3>
        <div className="insights-grid">
          <div className="insight-card">
            <span className="icon">💰</span>
            <div>
              <h4>Average Booking Value</h4>
              <p>${stats.total_bookings > 0 ? (stats.total_revenue / stats.total_bookings).toFixed(2) : '0.00'}</p>
            </div>
          </div>
          <div className="insight-card">
            <span className="icon">🏨</span>
            <div>
              <h4>Avg Nights per Booking</h4>
              <p>{stats.total_bookings > 0 ? (stats.total_nights / stats.total_bookings).toFixed(1) : '0.0'}</p>
            </div>
          </div>
          <div className="insight-card">
            <span className="icon">🔄</span>
            <div>
              <h4>Return Rate</h4>
              <p>{returnPercentage}%</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;
