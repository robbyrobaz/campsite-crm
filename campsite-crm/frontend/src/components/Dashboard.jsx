import React from 'react';
import '../styles/Dashboard.css';
import ArrivalRadar from './ArrivalRadar';
import GuestValueSpotlight from './GuestValueSpotlight';
import GuestTypeChart from './GuestTypeChart';
import ContractSnapshot from './ContractSnapshot';

const STATUS_LABELS = {
  active: 'Active',
  confirmed: 'Confirmed',
  'checked-in': 'Checked In',
  'checked-out': 'Checked Out',
  canceled: 'Canceled',
  'no-show': 'No-Show'
};

function Dashboard({
  summary,
  bookings,
  loading,
  statusSummary = [],
  arrivalRadar = [],
  guestValueSpotlight = [],
  guestTypeData = [],
  contracts = [],
  paymentSummary = null,
  messageQueue = [],
  pricingRecommendations = [],
  addonSummary = { total_addon_revenue: 0, items: [] }
}) {
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

      <section className="status-section">
        <h3>📍 Booking Status Tracker</h3>
        <div className="status-badges">
          {statusSummary.length > 0 ? (
            statusSummary.map((item) => (
              <div key={item.status} className={`status-chip status-chip-${item.status}`}>
                <span>{STATUS_LABELS[item.status] || item.status}</span>
                <strong>{item.count}</strong>
              </div>
            ))
          ) : (
            <div className="status-empty">No statuses yet</div>
          )}
        </div>
      </section>

      <div className="dashboard-grid">
        <div className="card compact-card">
          <div className="card-heading">
            <h3>💳 Payment Pulse</h3>
            <p>Outstanding balances and overdue stays</p>
          </div>
          <div className="mini-kpis">
            <div>
              <span>Collected</span>
              <strong>${paymentSummary?.total_collected?.toFixed(2) || '0.00'}</strong>
            </div>
            <div>
              <span>Outstanding</span>
              <strong>${paymentSummary?.total_outstanding?.toFixed(2) || '0.00'}</strong>
            </div>
            <div>
              <span>Overdue</span>
              <strong>{paymentSummary?.overdue_count || 0}</strong>
            </div>
          </div>
        </div>

        <div className="card compact-card">
          <div className="card-heading">
            <h3>🧺 Add-on Upsells</h3>
            <p>Extra revenue from bundles and rentals</p>
          </div>
          <div className="mini-kpis">
            <div>
              <span>Add-on Revenue</span>
              <strong>${addonSummary?.total_addon_revenue?.toFixed(2) || '0.00'}</strong>
            </div>
            <div>
              <span>Top Add-on</span>
              <strong>{addonSummary?.items?.[0]?.name || 'None yet'}</strong>
            </div>
            <div>
              <span>Units Sold</span>
              <strong>{addonSummary?.items?.reduce((sum, item) => sum + (item.quantity || 0), 0) || 0}</strong>
            </div>
          </div>
        </div>
      </div>

      <div className="dashboard-grid">
        <div className="card compact-card">
          <div className="card-heading">
            <h3>📬 Auto Message Queue</h3>
            <p>Pre-arrival, post-stay, and payment reminders</p>
          </div>
          {messageQueue.length > 0 ? (
            <div className="stack-list">
              {messageQueue.slice(0, 5).map((item) => (
                <div className="stack-row" key={`${item.booking_id}-${item.message_type}-${item.send_on}`}>
                  <span>{item.send_on}</span>
                  <strong>{item.guest_name}</strong>
                  <em>{item.message_type}</em>
                </div>
              ))}
            </div>
          ) : (
            <p className="empty-text">No upcoming messages.</p>
          )}
        </div>

        <div className="card compact-card">
          <div className="card-heading">
            <h3>📈 Pricing Guide (30d)</h3>
            <p>Occupancy-based suggested adjustments</p>
          </div>
          {pricingRecommendations.length > 0 ? (
            <div className="stack-list">
              {pricingRecommendations.slice(0, 5).map((item) => (
                <div className="stack-row" key={item.area}>
                  <span>{item.area}</span>
                  <strong>{item.occupancy_rate}%</strong>
                  <em>
                    {item.action === 'raise' ? `+${item.suggested_change_pct}%` : item.action === 'discount' ? `${item.suggested_change_pct}%` : 'hold'}
                  </em>
                </div>
              ))}
            </div>
          ) : (
            <p className="empty-text">Need more future bookings for guidance.</p>
          )}
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
              {bookings.slice(0, 10).map((booking) => (
                <tr key={booking.id}>
                  <td><strong>{booking.guest_name}</strong></td>
                  <td>{booking.guest_type}</td>
                  <td>{booking.nights}</td>
                  <td>{booking.area_rented}</td>
                  <td className="revenue">${(booking.revenue || 0).toFixed(2)}</td>
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

      <div className="dashboard-grid">
        <ArrivalRadar arrivals={arrivalRadar} />
        <GuestValueSpotlight guests={guestValueSpotlight} />
      </div>

      <div className="dashboard-grid">
        <GuestTypeChart data={guestTypeData} />
        <ContractSnapshot contracts={contracts} />
      </div>
    </div>
  );
}

export default Dashboard;
