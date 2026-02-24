import React from 'react';
import '../styles/ReturnGuestAnalysis.css';

function ReturnGuestAnalysis({ returnGuests = [], loading }) {
  if (loading) {
    return <div className="loading">⏳ Loading guest analysis...</div>;
  }

  const guests = returnGuests || [];

  return (
    <div className="card">
      <h2>🔄 Return Guest Analysis</h2>
      
      {guests.length > 0 ? (
        <div className="return-guests-container">
          <div className="guests-list">
            {guests.map((guest, index) => (
              <div key={index} className="guest-card">
                <div className="guest-rank">#{index + 1}</div>
                <div className="guest-info">
                  <h3>{guest.guest_name}</h3>
                  <div className="guest-stats">
                    <div className="stat">
                      <span className="label">Visits:</span>
                      <span className="value">{guest.visit_count}x</span>
                    </div>
                    <div className="stat">
                      <span className="label">Total Revenue:</span>
                      <span className="value">${guest.total_revenue?.toFixed(2) || '0.00'}</span>
                    </div>
                    <div className="stat">
                      <span className="label">Avg per Visit:</span>
                      <span className="value">${(guest.total_revenue / guest.visit_count)?.toFixed(2) || '0.00'}</span>
                    </div>
                  </div>
                </div>
                <div className="loyalty-badge">
                  {guest.visit_count >= 5 && <span className="badge premium">⭐ VIP Guest</span>}
                  {guest.visit_count >= 3 && guest.visit_count < 5 && <span className="badge loyal">🌟 Loyal</span>}
                  {guest.visit_count >= 2 && guest.visit_count < 3 && <span className="badge returning">💙 Returning</span>}
                </div>
              </div>
            ))}
          </div>

          <div className="insights-panel">
            <h3>📊 Return Guest Insights</h3>
            <div className="insight">
              <span className="icon">👥</span>
              <div>
                <h4>Total Return Guests</h4>
                <p>{guests.length}</p>
              </div>
            </div>
            <div className="insight">
              <span className="icon">💰</span>
              <div>
                <h4>Return Guest Revenue</h4>
                <p>${guests.reduce((sum, g) => sum + (g.total_revenue || 0), 0).toFixed(2)}</p>
              </div>
            </div>
            <div className="insight">
              <span className="icon">📈</span>
              <div>
                <h4>Avg Visits per Guest</h4>
                <p>{(guests.reduce((sum, g) => sum + g.visit_count, 0) / guests.length).toFixed(1)}x</p>
              </div>
            </div>
            <div className="insight">
              <span className="icon">⭐</span>
              <div>
                <h4>Top Guest Value</h4>
                <p>${Math.max(...guests.map(g => g.total_revenue || 0)).toFixed(2)}</p>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="empty-state">
          <p>No return guests found yet</p>
          <p className="hint">Return guests appear after someone books more than once</p>
        </div>
      )}
    </div>
  );
}

export default ReturnGuestAnalysis;
