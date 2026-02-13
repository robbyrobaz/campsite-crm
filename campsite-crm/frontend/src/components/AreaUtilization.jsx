import React, { useState, useEffect } from 'react';
import axios from 'axios';
import '../styles/AreaUtilization.css';

function AreaUtilization({ dateRange }) {
  const [areas, setAreas] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchAreas();
  }, [dateRange]);

  const fetchAreas = async () => {
    setLoading(true);
    try {
      const response = await axios.get('/api/areas', { params: dateRange });
      setAreas(response.data || []);
    } catch (error) {
      console.error('Error fetching areas:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <div className="loading">⏳ Loading area data...</div>;
  }

  const totalRevenue = areas.reduce((sum, a) => sum + (a.total_revenue || 0), 0);

  const getAreaIcon = (areaName) => {
    const name = areaName?.toLowerCase() || '';
    if (name.includes('cabin')) return '🏠';
    if (name.includes('tent')) return '⛺';
    if (name.includes('kitchen')) return '🍳';
    if (name.includes('barn')) return '🐴';
    if (name.includes('pavilion')) return '🏛️';
    return '🏕️';
  };

  return (
    <div className="card">
      <h2>🏕️ Area Utilization & Revenue</h2>

      {areas && areas.length > 0 ? (
        <div className="areas-container">
          <div className="areas-grid">
            {areas.map((area, index) => {
              const revenuePercentage = totalRevenue > 0 ? (area.total_revenue / totalRevenue * 100) : 0;
              
              return (
                <div key={index} className="area-card">
                  <div className="area-header">
                    <h3>
                      <span className="icon">{getAreaIcon(area.area_rented)}</span>
                      {area.area_rented}
                    </h3>
                    <div className="revenue-highlight">${area.total_revenue?.toFixed(2) || '0.00'}</div>
                  </div>

                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width: `${revenuePercentage}%` }}></div>
                  </div>

                  <div className="area-stats">
                    <div className="stat">
                      <span className="stat-label">Bookings</span>
                      <span className="stat-value">{area.booking_count}</span>
                    </div>
                    <div className="stat">
                      <span className="stat-label">Nights</span>
                      <span className="stat-value">{area.total_nights}</span>
                    </div>
                    <div className="stat">
                      <span className="stat-label">% of Total</span>
                      <span className="stat-value">{revenuePercentage.toFixed(1)}%</span>
                    </div>
                  </div>

                  {area.booking_count > 0 && (
                    <div className="area-metrics">
                      <p>Avg per booking: ${(area.total_revenue / area.booking_count).toFixed(2)}</p>
                      <p>Avg nights: {(area.total_nights / area.booking_count).toFixed(1)}</p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="utilization-summary">
            <h3>📊 Summary</h3>
            <div className="summary-grid">
              <div className="summary-item">
                <span className="icon">📍</span>
                <div>
                  <h4>Total Areas Used</h4>
                  <p>{areas.length}</p>
                </div>
              </div>
              <div className="summary-item">
                <span className="icon">💰</span>
                <div>
                  <h4>Total Revenue</h4>
                  <p>${totalRevenue.toFixed(2)}</p>
                </div>
              </div>
              <div className="summary-item">
                <span className="icon">🎯</span>
                <div>
                  <h4>Top Area</h4>
                  <p>{areas.length > 0 ? areas[0].area_rented : 'N/A'}</p>
                </div>
              </div>
              <div className="summary-item">
                <span className="icon">📈</span>
                <div>
                  <h4>Total Bookings</h4>
                  <p>{areas.reduce((sum, a) => sum + (a.booking_count || 0), 0)}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="empty-state">
          <p>No area utilization data found</p>
          <p className="hint">Data will appear once bookings are added</p>
        </div>
      )}
    </div>
  );
}

export default AreaUtilization;
