import React, { useState } from 'react';
import '../styles/BookingForm.css';

function BookingForm({ onSubmit }) {
  const [formData, setFormData] = useState({
    guest_name: '',
    guest_type: 'individual',
    group_type: '',
    nights: 1,
    area_rented: 'cabin',
    revenue: '',
    notes: ''
  });

  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!formData.guest_name || !formData.revenue) {
      alert('Please fill in guest name and revenue');
      return;
    }

    setIsSubmitting(true);
    try {
      await onSubmit({
        ...formData,
        nights: parseInt(formData.nights),
        revenue: parseFloat(formData.revenue)
      });
      
      // Reset form
      setFormData({
        guest_name: '',
        guest_type: 'individual',
        group_type: '',
        nights: 1,
        area_rented: 'cabin',
        revenue: '',
        notes: ''
      });
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
