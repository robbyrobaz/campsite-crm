import React, { useState } from 'react';
import '../styles/BookingForm.css';

const DEFAULT_DATE = new Date().toISOString().split('T')[0];

const ADD_ON_OPTIONS = [
  { key: 'Firewood Bundle', price: 12 },
  { key: 'Smore Kit', price: 10 },
  { key: 'Late Checkout', price: 25 },
  { key: 'Horse Stall Cleaning', price: 18 },
  { key: 'Kayak Rental', price: 30 }
];

function BookingForm({ onSubmit, statusOptions = [] }) {
  const [formData, setFormData] = useState({
    guest_name: '',
    guest_type: 'individual',
    group_type: '',
    nights: 1,
    area_rented: 'cabin',
    revenue: '',
    amount_paid: '',
    due_date: DEFAULT_DATE,
    notes: '',
    booking_date: DEFAULT_DATE,
    status: statusOptions.length > 0 ? statusOptions[1].value : 'confirmed'
  });

  const [addOnSelections, setAddOnSelections] = useState({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: value
    }));
  };

  const toggleAddOn = (name, enabled) => {
    setAddOnSelections((prev) => {
      const next = { ...prev };
      if (!enabled) {
        delete next[name];
      } else {
        next[name] = { quantity: 1 };
      }
      return next;
    });
  };

  const updateAddOnQuantity = (name, quantity) => {
    setAddOnSelections((prev) => ({
      ...prev,
      [name]: {
        quantity: Math.max(parseInt(quantity, 10) || 1, 1)
      }
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!formData.guest_name || !formData.revenue) {
      alert('Please fill in guest name and revenue');
      return;
    }

    const addOnsPayload = Object.entries(addOnSelections).map(([name, details]) => {
      const config = ADD_ON_OPTIONS.find((option) => option.key === name);
      const price = config?.price || 0;
      const quantity = details.quantity || 1;
      return {
        name,
        price,
        quantity,
        total: price * quantity
      };
    });

    setIsSubmitting(true);
    try {
      await onSubmit({
        ...formData,
        nights: parseInt(formData.nights, 10),
        revenue: parseFloat(formData.revenue),
        amount_paid: parseFloat(formData.amount_paid || 0),
        is_return_booking: formData.is_return_booking || 0,
        add_ons: addOnsPayload
      });

      setFormData({
        guest_name: '',
        guest_type: 'individual',
        group_type: '',
        nights: 1,
        area_rented: 'cabin',
        revenue: '',
        amount_paid: '',
        due_date: DEFAULT_DATE,
        notes: '',
        booking_date: DEFAULT_DATE,
        status: statusOptions.length > 0 ? statusOptions[1].value : 'confirmed'
      });
      setAddOnSelections({});
    } catch (error) {
      console.error('Error submitting form:', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="booking-form-container">
      <h2>➕ Add New Booking</h2>

      <form className="booking-form" onSubmit={handleSubmit}>
        <div className="form-section">
          <h3>Guest Information</h3>

          <div className="form-row">
            <div className="form-group">
              <label>Guest Name *</label>
              <input
                type="text"
                name="guest_name"
                value={formData.guest_name}
                onChange={handleChange}
                placeholder="Enter guest name"
                required
              />
            </div>

            <div className="form-group">
              <label>Guest Type</label>
              <select name="guest_type" value={formData.guest_type} onChange={handleChange}>
                <option value="individual">Individual</option>
                <option value="family">Family</option>
                <option value="group">Group</option>
                <option value="corporate">Corporate</option>
                <option value="church">Church/Organization</option>
              </select>
            </div>
          </div>

          <div className="form-group">
            <label>Group Type (if applicable)</label>
            <input
              type="text"
              name="group_type"
              value={formData.group_type}
              onChange={handleChange}
              placeholder="e.g., Horse riding group, Church youth group"
            />
          </div>
        </div>

        <div className="form-section">
          <h3>Booking Details</h3>

          <div className="form-row">
            <div className="form-group">
              <label>Nights *</label>
              <input
                type="number"
                name="nights"
                value={formData.nights}
                onChange={handleChange}
                min="1"
                required
              />
            </div>

            <div className="form-group">
              <label>Area Rented</label>
              <select name="area_rented" value={formData.area_rented} onChange={handleChange}>
                <option value="cabin">Cabin</option>
                <option value="tent">Tent Site</option>
                <option value="kitchen">Kitchen Area</option>
                <option value="barn">Horse Barn</option>
                <option value="pavilion">Pavilion</option>
                <option value="mixed">Mixed Areas</option>
              </select>
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>Booking Date *</label>
              <input
                type="date"
                name="booking_date"
                value={formData.booking_date}
                onChange={handleChange}
                required
              />
            </div>
            <div className="form-group">
              <label>Status</label>
              <select name="status" value={formData.status} onChange={handleChange}>
                {statusOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>Revenue *</label>
              <input
                type="number"
                name="revenue"
                value={formData.revenue}
                onChange={handleChange}
                placeholder="Enter revenue amount"
                step="0.01"
                min="0"
                required
              />
            </div>
            <div className="form-group">
              <label>Amount Paid</label>
              <input
                type="number"
                name="amount_paid"
                value={formData.amount_paid}
                onChange={handleChange}
                placeholder="0.00"
                step="0.01"
                min="0"
              />
            </div>
          </div>

          <div className="form-group">
            <label>Payment Due Date</label>
            <input
              type="date"
              name="due_date"
              value={formData.due_date}
              onChange={handleChange}
            />
          </div>
        </div>

        <div className="form-section">
          <h3>Add-on Upsells</h3>
          <div className="addons-grid">
            {ADD_ON_OPTIONS.map((option) => {
              const selected = !!addOnSelections[option.key];
              return (
                <div key={option.key} className="addon-row">
                  <label className="addon-toggle">
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={(e) => toggleAddOn(option.key, e.target.checked)}
                    />
                    <span>{option.key} (${option.price})</span>
                  </label>
                  {selected && (
                    <input
                      type="number"
                      min="1"
                      className="addon-qty"
                      value={addOnSelections[option.key].quantity}
                      onChange={(e) => updateAddOnQuantity(option.key, e.target.value)}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="form-section">
          <h3>Additional Notes</h3>
          <div className="form-group">
            <label>Notes</label>
            <textarea
              name="notes"
              value={formData.notes}
              onChange={handleChange}
              placeholder="Add any special notes about this booking..."
            />
          </div>
        </div>

        <div className="form-actions">
          <button
            type="submit"
            className="btn btn-primary"
            disabled={isSubmitting}
          >
            {isSubmitting ? '💾 Saving...' : '💾 Save Booking'}
          </button>
        </div>
      </form>
    </div>
  );
}

export default BookingForm;
