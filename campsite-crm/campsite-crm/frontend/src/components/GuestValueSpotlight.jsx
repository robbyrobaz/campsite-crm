import React from 'react';

const getLoyaltyLabel = (visits) => {
  if (visits > 3) return { text: 'VIP', className: 'vip' };
  if (visits > 1) return { text: 'Loyal', className: 'loyal' };
  return { text: 'Returning', className: 'returning' };
};

function GuestValueSpotlight({ guests = [] }) {
  return (
    <div className="card guest-value-card">
      <div className="card-heading">
        <h3>✨ Guest Value Spotlight</h3>
        <p>Top 3 return guests by lifetime revenue</p>
      </div>
      {guests.length > 0 ? (
        <div className="guest-spotlight-grid">
          {guests.map((guest, index) => {
            const loyalty = getLoyaltyLabel(guest.visit_count);
            return (
              <div key={`${guest.guest_name}-${index}`} className="spotlight-card">
                <div className="spotlight-rank">#{index + 1}</div>
                <div className="spotlight-name">{guest.guest_name}</div>
                <div className="spotlight-stats">
                  <div>
                    <span className="label">Visits</span>
                    <strong>{guest.visit_count}x</strong>
                  </div>
                  <div>
                    <span className="label">Revenue</span>
                    <strong>${guest.total_revenue?.toFixed(2) || '0.00'}</strong>
                  </div>
                </div>
                <span className={`loyalty-pill ${loyalty.className}`}>{loyalty.text}</span>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="empty-state">
          <p>Return guests will populate this space once the same person books again.</p>
        </div>
      )}
    </div>
  );
}

export default GuestValueSpotlight;
