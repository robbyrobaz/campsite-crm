import React from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend
} from 'chart.js';
import { Bar } from 'react-chartjs-2';

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

function GuestTypeChart({ data = [] }) {
  const labels = data.map((item) => item.guest_type || 'Unknown');
  const revenueData = data.map((item) => item.total_revenue || 0);
  const bookingCounts = data.map((item) => item.booking_count || 0);

  const chartData = {
    labels,
    datasets: [
      {
        label: 'Revenue',
        data: revenueData,
        backgroundColor: 'rgba(0, 217, 255, 0.8)',
        borderColor: 'rgba(0, 149, 202, 0.8)',
        yAxisID: 'yRevenue'
      },
      {
        label: 'Bookings',
        data: bookingCounts,
        backgroundColor: 'rgba(255, 86, 110, 0.7)',
        borderColor: 'rgba(255, 86, 110, 1)',
        yAxisID: 'yBookings'
      }
    ]
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      mode: 'index',
      intersect: false
    },
    plugins: {
      legend: {
        position: 'bottom'
      },
      tooltip: {
        callbacks: {
          label: (context) => {
            const label = context.dataset.label || '';
            const value = context.parsed.y;
            if (context.dataset.yAxisID === 'yRevenue') {
              return `${label}: $${value.toLocaleString()}`;
            }
            return `${label}: ${value}`;
          }
        }
      }
    },
    scales: {
      yRevenue: {
        type: 'linear',
        position: 'left',
        title: {
          display: true,
          text: 'Revenue ($)'
        },
        grid: {
          drawOnChartArea: true
        }
      },
      yBookings: {
        type: 'linear',
        position: 'right',
        title: {
          display: true,
          text: 'Booking Count'
        },
        grid: {
          drawOnChartArea: false
        }
      }
    }
  };

  return (
    <div className="card guest-type-chart-card">
      <div className="card-heading">
        <h3>📊 Revenue by Guest Type</h3>
        <p>Compare booking volume vs. revenue</p>
      </div>
      {labels.length > 0 ? (
        <div className="chart-wrapper">
          <Bar data={chartData} options={options} />
        </div>
      ) : (
        <div className="empty-state">
          <p>No guest type data available yet.</p>
        </div>
      )}
    </div>
  );
}

export default GuestTypeChart;
