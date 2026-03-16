import React, { useMemo, useState } from 'react';
import axios from 'axios';
import '../styles/BookingAssistant.css';

const AMENITY_OPTIONS = [
  'power',
  'pet-friendly',
  'shade',
  'fire ring',
  'covered shelter',
  'horse stalls',
  'private restroom',
  'group-friendly'
];

const ADD_ON_OPTIONS = [
  { name: 'Firewood Bundle', price: 12 },
  { name: 'Smore Kit', price: 10 },
  { name: 'Late Checkout', price: 25 },
  { name: 'Kayak Rental', price: 30 }
];

const DEFAULT_DATE = new Date().toISOString().split('T')[0];

function BookingAssistant() {
  const [form, setForm] = useState({
    startDate: DEFAULT_DATE,
    nights: 2,
    partySize: 2,
    area: 'mixed'
  });
  const [selectedAmenities, setSelectedAmenities] = useState([]);
  const [selectedAddOns, setSelectedAddOns] = useState({});
  const [availability, setAvailability] = useState(null);
  const [costEstimate, setCostEstimate] = useState(null);
  const [cancelPreview, setCancelPreview] = useState(null);
  const [stayRules, setStayRules] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [managePreview, setManagePreview] = useState(null);
  const [alertContact, setAlertContact] = useState('');
  const [alertMessage, setAlertMessage] = useState('');
  const [siteLock, setSiteLock] = useState(false);
  const [loading, setLoading] = useState(false);

  const selectedAddOnPayload = useMemo(
    () => Object.entries(selectedAddOns).map(([name, quantity]) => {
      const option = ADD_ON_OPTIONS.find((row) => row.name === name);
      const price = option?.price || 0;
      const qty = Math.max(parseInt(quantity, 10) || 1, 1);
      return {
        name,
        price,
        quantity: qty
      };
    }),
    [selectedAddOns]
  );

  const toggleAmenity = (amenity) => {
    setSelectedAmenities((prev) => (
      prev.includes(amenity) ? prev.filter((item) => item !== amenity) : [...prev, amenity]
    ));
  };

  const toggleAddOn = (name, enabled) => {
    setSelectedAddOns((prev) => {
      const next = { ...prev };
      if (!enabled) delete next[name];
      else next[name] = 1;
      return next;
    });
  };

  const runAssistant = async () => {
    setLoading(true);
    try {
      const availabilityRes = await axios.get('/api/booking-assistant/availability', {
        params: {
          startDate: form.startDate,
          nights: form.nights,
          partySize: form.partySize,
          area: form.area,
          amenities: selectedAmenities.join(',')
        }
      });

      const costRes = await axios.post('/api/booking-assistant/cost-estimate', {
        area: form.area,
        nights: form.nights,
        partySize: form.partySize,
        add_ons: selectedAddOnPayload,
        site_lock: siteLock
      });

      const cancelRes = await axios.get('/api/booking-assistant/cancellation-preview', {
        params: {
          startDate: form.startDate,
          total: costRes.data?.total_estimate || 0
        }
      });

      const rulesRes = await axios.get('/api/booking-assistant/stay-rules', {
        params: {
          startDate: form.startDate,
          nights: form.nights,
          partySize: form.partySize
        }
      });

      const readinessRes = await axios.get('/api/booking-assistant/readiness-score', {
        params: {
          startDate: form.startDate,
          nights: form.nights,
          partySize: form.partySize,
          area: form.area,
          amenities: selectedAmenities.join(',')
        }
      });

      const manageRes = await axios.post('/api/booking-assistant/manage-preview', {
        current_start_date: form.startDate,
        proposed_start_date: availabilityRes.data?.alternative_dates?.[0]?.start_date || form.startDate,
        current_nights: form.nights,
        proposed_nights: form.nights,
        total: costRes.data?.total_estimate || 0
      });

      setAvailability(availabilityRes.data || null);
      setCostEstimate(costRes.data || null);
      setCancelPreview(cancelRes.data || null);
      setStayRules(rulesRes.data || null);
      setReadiness(readinessRes.data || null);
      setManagePreview(manageRes.data || null);
    } catch (error) {
      console.error('Booking assistant failed:', error);
      alert('Unable to load booking assistant results right now.');
    } finally {
      setLoading(false);
    }
  };

  const createAlert = async () => {
    if (!alertContact.trim()) {
      alert('Add email or phone for availability alerts.');
      return;
    }

    try {
      const response = await axios.post('/api/booking-assistant/availability-alerts', {
        guest_name: 'Booking Assistant Guest',
        contact: alertContact.trim(),
        preferred_area: form.area,
        requested_start_date: form.startDate,
        nights: form.nights,
        party_size: form.partySize
      });
      setAlertMessage(response.data?.message || 'Availability alert created');
    } catch (error) {
      console.error('Availability alert error:', error);
      alert('Unable to create availability alert right now.');
    }
  };

  return (
    <div className="assistant-page">
      <div className="assistant-header card">
        <h2>🧭 Booking Assistant</h2>
        <p>Modeled after top camping apps: availability, amenity fit, date alternatives, full cost preview, and cancellation clarity.</p>
      </div>

      <div className="assistant-inputs card">
        <div className="assistant-grid">
          <label>
            Start date
            <input
              type="date"
              value={form.startDate}
              onChange={(e) => setForm((prev) => ({ ...prev, startDate: e.target.value }))}
            />
          </label>
          <label>
            Nights
            <input
              type="number"
              min="1"
              value={form.nights}
              onChange={(e) => setForm((prev) => ({ ...prev, nights: parseInt(e.target.value, 10) || 1 }))}
            />
          </label>
          <label>
            Party size
            <input
              type="number"
              min="1"
              value={form.partySize}
              onChange={(e) => setForm((prev) => ({ ...prev, partySize: parseInt(e.target.value, 10) || 1 }))}
            />
          </label>
          <label>
            Preferred area
            <select
              value={form.area}
              onChange={(e) => setForm((prev) => ({ ...prev, area: e.target.value }))}
            >
              <option value="mixed">Mixed Areas</option>
              <option value="cabin">Cabin</option>
              <option value="tent">Tent Site</option>
              <option value="kitchen">Kitchen Area</option>
              <option value="barn">Horse Barn</option>
              <option value="pavilion">Pavilion</option>
            </select>
          </label>
        </div>

        <div className="assistant-subsection">
          <h4>Amenities wanted</h4>
          <div className="pill-grid">
            {AMENITY_OPTIONS.map((amenity) => (
              <button
                key={amenity}
                className={`pill-btn ${selectedAmenities.includes(amenity) ? 'active' : ''}`}
                onClick={() => toggleAmenity(amenity)}
                type="button"
              >
                {amenity}
              </button>
            ))}
          </div>
        </div>

        <div className="assistant-subsection">
          <h4>Add-ons to include in estimate</h4>
          <div className="addons-list">
            {ADD_ON_OPTIONS.map((option) => {
              const selected = selectedAddOns[option.name] !== undefined;
              return (
                <div className="addon-item" key={option.name}>
                  <label>
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={(e) => toggleAddOn(option.name, e.target.checked)}
                    />
                    {option.name} (${option.price})
                  </label>
                  {selected && (
                    <input
                      type="number"
                      min="1"
                      value={selectedAddOns[option.name]}
                      onChange={(e) => setSelectedAddOns((prev) => ({ ...prev, [option.name]: e.target.value }))}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <label className="site-lock-option">
          <input
            type="checkbox"
            checked={siteLock}
            onChange={(e) => setSiteLock(e.target.checked)}
          />
          Lock an exact site/spot for this quote (+$18)
        </label>

        <button className="refresh-btn" type="button" onClick={runAssistant} disabled={loading}>
          {loading ? 'Running...' : 'Run Booking Assistant'}
        </button>
      </div>

      {availability && (
        <div className="assistant-results">
          <div className="card">
            <h3>1) Availability by Area</h3>
            <div className="availability-grid">
              {availability.availability?.map((item) => (
                <div className={`availability-card ${item.available ? 'ok' : 'full'}`} key={item.area_key}>
                  <strong>{item.area_name}</strong>
                  <span>{item.remaining_units} of {item.capacity_units} units left</span>
                  <span>Max party: {item.max_party_size}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <h3>2) Amenity-Based Matches</h3>
            {availability.recommended_areas?.length > 0 ? (
              <div className="stack-list">
                {availability.recommended_areas.map((item) => (
                  <div className="stack-row" key={`rec-${item.area_key}`}>
                    <span>{item.area_name}</span>
                    <strong>{item.amenity_match_pct}% amenity match</strong>
                    <em>${item.base_rate}/night</em>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty-text">No matching area is currently available for this party size.</p>
            )}
          </div>

          <div className="card">
            <h3>3) Alternate Date Suggestions</h3>
            {availability.alternative_dates?.length > 0 ? (
              <div className="stack-list">
                {availability.alternative_dates.map((item) => (
                  <div className="stack-row" key={item.start_date}>
                    <span>{item.start_date}</span>
                    <strong>{item.end_date}</strong>
                    <em>{item.available_areas.join(', ')}</em>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty-text">No nearby alternate dates found in the next 30 days.</p>
            )}
          </div>
        </div>
      )}

      {costEstimate && (
        <div className="card">
          <h3>4) Full Trip Cost Estimate</h3>
          <div className="mini-kpis">
            <div><span>Total estimate</span><strong>${costEstimate.total_estimate.toFixed(2)}</strong></div>
            <div><span>Deposit today</span><strong>${costEstimate.deposit_due_today.toFixed(2)}</strong></div>
            <div><span>Remaining balance</span><strong>${costEstimate.remaining_balance.toFixed(2)}</strong></div>
          </div>
        </div>
      )}

      {cancelPreview && (
        <div className="card">
          <h3>5) Cancellation Preview</h3>
          <div className="stack-list">
            <div className="stack-row">
              <span>Full refund deadline</span>
              <strong>{cancelPreview.policy.full_refund_if_canceled_on_or_before}</strong>
              <em>${cancelPreview.refund_examples.full_refund_amount.toFixed(2)}</em>
            </div>
            <div className="stack-row">
              <span>Partial refund window</span>
              <strong>
                {cancelPreview.policy.partial_refund_if_canceled_between.start} to {cancelPreview.policy.partial_refund_if_canceled_between.end}
              </strong>
              <em>${cancelPreview.refund_examples.partial_refund_amount.toFixed(2)}</em>
            </div>
            <div className="stack-row">
              <span>Non-refundable from</span>
              <strong>{cancelPreview.policy.non_refundable_if_canceled_on_or_after}</strong>
              <em>$0.00</em>
            </div>
          </div>
        </div>
      )}

      {stayRules && (
        <div className="card">
          <h3>6) Stay Rules Checker</h3>
          <p className="assistant-mini-note">
            {stayRules.passes ? 'This trip passes current stay rules.' : 'This trip hits policy rules you should adjust before booking.'}
          </p>
          {stayRules.issues?.length > 0 ? (
            <ul className="plain-list">
              {stayRules.issues.map((issue) => <li key={issue}>{issue}</li>)}
            </ul>
          ) : (
            <p className="empty-text">No stay-rule issues detected.</p>
          )}
        </div>
      )}

      {managePreview && (
        <div className="card">
          <h3>7) Change or Cancel Preview</h3>
          <div className="stack-list">
            <div className="stack-row">
              <span>Change fee</span>
              <strong>${managePreview.change.change_fee.toFixed(2)}</strong>
              <em>{managePreview.change.risk_band}</em>
            </div>
            <div className="stack-row">
              <span>Refund estimate</span>
              <strong>${managePreview.cancellation.refund.toFixed(2)}</strong>
              <em>{managePreview.cancellation.policy_band}</em>
            </div>
            <div className="stack-row">
              <span>Rebooking credit</span>
              <strong>${managePreview.cancellation.credit.toFixed(2)}</strong>
              <em>Future-stay credit</em>
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <h3>8) Availability Alerts</h3>
        <p className="assistant-mini-note">Store an alert so staff can contact this guest when matching inventory opens.</p>
        <div className="alert-row">
          <input
            type="text"
            placeholder="Email or phone"
            value={alertContact}
            onChange={(e) => setAlertContact(e.target.value)}
          />
          <button type="button" className="btn btn-primary" onClick={createAlert}>Create Alert</button>
        </div>
        {alertMessage && <p className="assistant-mini-note success">{alertMessage}</p>}
      </div>

      {readiness && (
        <div className="card">
          <h3>9) Booking Readiness Score</h3>
          <div className="readiness-band">
            <strong>{readiness.readiness.score}/100</strong>
            <span>{readiness.readiness.band.toUpperCase()} booking confidence</span>
          </div>
          <p className="assistant-mini-note">
            Available areas: {readiness.readiness.factors.areas_available}/{readiness.readiness.factors.total_areas} |
            Best amenity match: {readiness.readiness.factors.best_amenity_match_pct}% |
            Rules passed: {readiness.readiness.factors.rules_passed ? 'yes' : 'no'}
          </p>
        </div>
      )}

      {costEstimate && (
        <div className="card">
          <h3>10) Site-Lock Cost Transparency</h3>
          <p className="assistant-mini-note">
            Site lock fee in quote: ${costEstimate.line_items.site_lock_fee.toFixed(2)}. Turn this on/off before sending final total to guests.
          </p>
        </div>
      )}
    </div>
  );
}

export default BookingAssistant;
