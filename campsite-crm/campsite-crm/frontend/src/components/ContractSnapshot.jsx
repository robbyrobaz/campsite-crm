import React from 'react';
import '../styles/ContractSnapshot.css';

const formatDate = (value) => {
  if (!value || value === 'TBD') return 'TBD';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString();
};

function ContractSnapshot({ contracts = [] }) {
  return (
    <div className="card contract-card">
      <div className="section-header">
        <h3>🤝 Contract Snapshot</h3>
        <p>Active horse-group contracts & renewal windows</p>
      </div>
      {contracts.length > 0 ? (
        <div className="contract-list">
          {contracts.map(contract => (
            <div className="contract-row" key={contract.id}>
              <div>
                <p className="contract-name">{contract.contract_name}</p>
                <p className="contract-group">{contract.group_name}</p>
                <p className="contract-dates">
                  {formatDate(contract.start_date)} - {formatDate(contract.end_date)}
                </p>
              </div>
              <div className="contract-stats">
                <p>${contract.base_monthly_rate?.toFixed(2) || '0.00'}/mo</p>
                {contract.per_guest_rate && <p>+ ${contract.per_guest_rate.toFixed(2)} per guest</p>}
                <span className={`contract-status ${contract.status}`}>{contract.status}</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="empty-text">No active contracts right now.</p>
      )}
    </div>
  );
}

export default ContractSnapshot;
