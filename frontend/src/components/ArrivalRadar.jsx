import React from 'react';

const STATUS_LABELS = {
  active: 'Active',
  confirmed: 'Confirmed',
  'checked-in': 'Checked In',
  'checked-out': 'Checked Out',
  canceled: 'Canceled',
  'no-show': 'No-Show'
};

function ArrivalRadar({ arrivals = [] }) {
  return (
    <div className="card arrival-radar-card">
      <div className="card-heading">
        <h3>⏱️ Arrival & Departure Radar</h3>
        <p>Next 7 arrivals & stay details</p>
      </div>
      {arrivals.length > 0 ? (
        <div className="arrival-table">
          <div className="arrival-row arrival-row-heading">
            <span>Guest</span>
            <span>Area</span>
            <span>Status</span>
            <span>Nights</span>
            <span>Departure</span>
          </div>
          {arrivals.map((booking) => (
            <div key={booking.id} className="arrival-row">
              <span className="arrival-name">{booking.guest_name}</span>
              <span>{booking.area_rented}</span>
              <span>
                <span className={`status-pill status-pill-${booking.status || 'active'}`}>
                  {STATUS_LABELS[booking.status] || booking.status || 'Active'}
                </span>
              </span>
              <span>{booking.nights}</span>
              <span>{new Date(booking.departure_date).toLocaleDateString()}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <p>No upcoming arrivals scheduled yet</p>
        </div>
      )}
    </div>
  );
}

export default ArrivalRadar;
