import React from 'react';
import '../styles/BookingsTable.css';

function BookingsTable({ bookings, onDelete, loading }) {
  if (loading) {
    return <div className="loading">⏳ Loading bookings...</div>;
  }

  if (!bookings || bookings.length === 0) {
    return (
      <div className="card">
        <h2>📅 Bookings</h2>
        <div className="empty-state">
          <p>No bookings found for this period</p>
        </div>
      </div>
    );
  }

  const totalRevenue = bookings.reduce((sum, b) => sum + (b.revenue || 0), 0);
  const totalNights = bookings.reduce((sum, b) => sum + (b.nights || 0), 0);

  return (
    <div className="card">
      <div className="bookings-header">
        <h2>📅 All Bookings</h2>
        <div className="booking-summary">
          <div className="summary-stat">
            <span className="label">Total Bookings:</span>
            <span className="value">{bookings.length}</span>
          </div>
          <div className="summary-stat">
            <span className="label">Total Revenue:</span>
            <span className="value">${totalRevenue.toFixed(2)}</span>
          </div>
          <div className="summary-stat">
            <span className="label">Total Nights:</span>
            <span className="value">{totalNights}</span>
          </div>
        </div>
      </div>

      <div className="table-responsive">
        <table className="data-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Guest Name</th>
              <th>Type</th>
              <th>Group</th>
              <th>Nights</th>
              <th>Area</th>
              <th>Revenue</th>
              <th>Return?</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {bookings.map(booking => (
              <tr key={booking.id} className={booking.is_return_booking ? 'return-booking' : ''}>
                <td>
                  <strong>{new Date(booking.booking_date).toLocaleDateString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric'
                  })}</strong>
                </td>
                <td>{booking.guest_name}</td>
                <td>{booking.guest_type}</td>
                <td>{booking.group_type || '-'}</td>
                <td className="center">{booking.nights}</td>
                <td>{booking.area_rented}</td>
                <td className="revenue">${booking.revenue?.toFixed(2) || '0.00'}</td>
                <td className="center">
                  {booking.is_return_booking ? (
                    <span className="badge badge-return">🔄 Yes</span>
                  ) : (
                    <span className="badge badge-new">✨ New</span>
                  )}
                </td>
                <td className="actions">
                  <button
                    className="btn btn-danger btn-small"
                    onClick={() => onDelete(booking.id)}
                    title="Delete booking"
                  >
                    🗑️
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {bookings.length > 0 && (
        <div className="bookings-footer">
          <p>💡 Tip: Click the 🗑️ button to delete a booking</p>
        </div>
      )}
    </div>
  );
}

export default BookingsTable;
