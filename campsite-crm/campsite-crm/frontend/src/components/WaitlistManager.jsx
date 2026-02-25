import React, { useState } from 'react';

const INITIAL_FORM = {
  guest_name: '',
  party_size: 1,
  preferred_area: 'tent',
  requested_start_date: '',
  requested_end_date: '',
  contact_info: '',
  notes: ''
};

function WaitlistManager({
  entries = [],
  statusOptions = [],
  onAddEntry,
  onStatusChange,
  onConvert,
  onDelete
}) {
  const [formData, setFormData] = useState(INITIAL_FORM);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!formData.guest_name) {
      alert('Guest name is required');
      return;
    }

    await onAddEntry(formData);
    setFormData(INITIAL_FORM);
  };

  return (
    <div className="card">
      <h2>📝 Waitlist Manager</h2>
      <p className="section-subtext">Capture demand instantly and convert open slots to bookings.</p>

      <form className="booking-form" onSubmit={handleSubmit}>
        <div className="form-row">
          <div className="form-group">
            <label>Guest Name *</label>
            <input
              type="text"
              value={formData.guest_name}
              onChange={(e) => setFormData({ ...formData, guest_name: e.target.value })}
              required
            />
          </div>
          <div className="form-group">
            <label>Party Size</label>
            <input
              type="number"
              min="1"
              value={formData.party_size}
              onChange={(e) => setFormData({ ...formData, party_size: e.target.value })}
            />
          </div>
        </div>

        <div className="form-row">
          <div className="form-group">
            <label>Preferred Area</label>
            <select
              value={formData.preferred_area}
              onChange={(e) => setFormData({ ...formData, preferred_area: e.target.value })}
            >
              <option value="cabin">Cabin</option>
              <option value="tent">Tent Site</option>
              <option value="kitchen">Kitchen Area</option>
              <option value="barn">Horse Barn</option>
              <option value="pavilion">Pavilion</option>
              <option value="mixed">Mixed Areas</option>
            </select>
          </div>
          <div className="form-group">
            <label>Contact</label>
            <input
              type="text"
              value={formData.contact_info}
              onChange={(e) => setFormData({ ...formData, contact_info: e.target.value })}
              placeholder="Phone or email"
            />
          </div>
        </div>

        <div className="form-row">
          <div className="form-group">
            <label>Requested Start</label>
            <input
              type="date"
              value={formData.requested_start_date}
              onChange={(e) => setFormData({ ...formData, requested_start_date: e.target.value })}
            />
          </div>
          <div className="form-group">
            <label>Requested End</label>
            <input
              type="date"
              value={formData.requested_end_date}
              onChange={(e) => setFormData({ ...formData, requested_end_date: e.target.value })}
            />
          </div>
        </div>

        <div className="form-group">
          <label>Notes</label>
          <textarea
            value={formData.notes}
            onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
          />
        </div>

        <div className="form-actions">
          <button className="btn btn-primary" type="submit">Add Waitlist Entry</button>
        </div>
      </form>

      <div className="table-responsive" style={{ marginTop: '25px' }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Guest</th>
              <th>Party</th>
              <th>Area</th>
              <th>Requested Dates</th>
              <th>Contact</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {entries.length > 0 ? entries.map((entry) => (
              <tr key={entry.id}>
                <td>{entry.guest_name}</td>
                <td>{entry.party_size}</td>
                <td>{entry.preferred_area || '-'}</td>
                <td>{entry.requested_start_date || '-'} to {entry.requested_end_date || '-'}</td>
                <td>{entry.contact_info || '-'}</td>
                <td>
                  <select
                    className="status-select"
                    value={entry.status || 'waiting'}
                    onChange={(e) => onStatusChange(entry, e.target.value)}
                  >
                    {statusOptions.map((option) => (
                      <option value={option.value} key={option.value}>{option.label}</option>
                    ))}
                  </select>
                </td>
                <td className="actions">
                  <button
                    className="btn btn-secondary btn-small"
                    type="button"
                    onClick={() => onConvert(entry)}
                    disabled={entry.status === 'converted'}
                  >
                    Convert
                  </button>
                  <button
                    className="btn btn-danger btn-small"
                    type="button"
                    onClick={() => onDelete(entry.id)}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            )) : (
              <tr>
                <td colSpan={7}>No waitlist entries yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default WaitlistManager;
