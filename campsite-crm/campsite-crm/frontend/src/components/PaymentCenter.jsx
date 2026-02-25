import React from 'react';

function PaymentCenter({ bookings = [], paymentSummary = null, onUpdatePayment }) {
  const activeBookings = bookings.filter((booking) => {
    const status = (booking.status || '').toLowerCase();
    return status !== 'canceled' && status !== 'no-show';
  });

  const handleQuickPay = (booking) => {
    const nextValue = window.prompt(`Amount paid for ${booking.guest_name}`, booking.amount_paid || 0);
    if (nextValue === null) return;

    const dueDate = window.prompt('Due date (YYYY-MM-DD)', booking.due_date || '');

    onUpdatePayment(booking.id, {
      amount_paid: parseFloat(nextValue) || 0,
      due_date: dueDate || null
    });
  };

  return (
    <div className="card">
      <h2>💳 Payment Center</h2>
      <div className="insights-grid">
        <div className="insight-card">
          <span className="icon">✅</span>
          <div>
            <h4>Collected</h4>
            <p>${paymentSummary?.total_collected?.toFixed(2) || '0.00'}</p>
          </div>
        </div>
        <div className="insight-card">
          <span className="icon">⏳</span>
          <div>
            <h4>Outstanding</h4>
            <p>${paymentSummary?.total_outstanding?.toFixed(2) || '0.00'}</p>
          </div>
        </div>
        <div className="insight-card">
          <span className="icon">🚨</span>
          <div>
            <h4>Overdue</h4>
            <p>{paymentSummary?.overdue_count || 0}</p>
          </div>
        </div>
      </div>

      <div className="table-responsive">
        <table className="data-table">
          <thead>
            <tr>
              <th>Guest</th>
              <th>Date</th>
              <th>Revenue</th>
              <th>Paid</th>
              <th>Balance</th>
              <th>Status</th>
              <th>Due Date</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {activeBookings.length > 0 ? activeBookings.map((booking) => (
              <tr key={booking.id}>
                <td>{booking.guest_name}</td>
                <td>{booking.booking_date}</td>
                <td>${(booking.revenue || 0).toFixed(2)}</td>
                <td>${(booking.amount_paid || 0).toFixed(2)}</td>
                <td>${(booking.balance_due || 0).toFixed(2)}</td>
                <td>{booking.payment_status || 'unpaid'}</td>
                <td>{booking.due_date || '-'}</td>
                <td>
                  <button
                    className="btn btn-secondary btn-small"
                    type="button"
                    onClick={() => handleQuickPay(booking)}
                  >
                    Update
                  </button>
                </td>
              </tr>
            )) : (
              <tr>
                <td colSpan={8}>No active bookings for this range.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default PaymentCenter;
