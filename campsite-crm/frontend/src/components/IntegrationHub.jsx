import React, { useEffect, useState } from 'react';
import axios from 'axios';
import '../styles/IntegrationHub.css';

const INITIAL_SETTINGS = {
  chatgpt_enabled: false,
  workspace_name: 'Campsite CRM',
  openai_api_key: '',
  openai_model: 'gpt-4.1-mini',
  mcp_shared_secret: '',
  oauth_enabled: false,
  oauth_client_id: '',
  oauth_client_secret: '',
  oauth_from_env: false,
  oauth_redirect_uri: '',
  gmail_scan_enabled: false,
  gmail_account_email: '',
  gmail_scan_window_days: 45,
  mcp_url: '',
  oauth_redirect_default: '',
  openai_key_configured: false,
  mcp_secret_configured: false,
  oauth_client_secret_configured: false,
  gmail_token_configured: false,
  gmail_connected: false,
  gmail_refresh_token_configured: false
};

function IntegrationHub({ onRefreshData, onRefreshTasks, onRefreshContacts, onRefreshWaitlist }) {
  const [settings, setSettings] = useState(INITIAL_SETTINGS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatInput, setChatInput] = useState('');
  const [includeContext, setIncludeContext] = useState(true);
  const [chatHistory, setChatHistory] = useState([]);
  const [scanningGmail, setScanningGmail] = useState(false);
  const [pendingScans, setPendingScans] = useState([]);
  const [approvingBatchId, setApprovingBatchId] = useState('');
  const [dataOpsStatus, setDataOpsStatus] = useState(null);
  const [dataOpsLoading, setDataOpsLoading] = useState(true);
  const [dataOpsAction, setDataOpsAction] = useState('');
  const [gmailStatus, setGmailStatus] = useState(null);
  const [connectingGmail, setConnectingGmail] = useState(false);
  const [disconnectingGmail, setDisconnectingGmail] = useState(false);
  const [gmailNotice, setGmailNotice] = useState('');

  const loadSettings = async () => {
    setLoading(true);
    try {
      const response = await axios.get('/api/integrations/chatgpt/settings');
      setSettings((prev) => ({ ...prev, ...response.data }));
    } catch (error) {
      console.error('Error loading integration settings:', error);
      alert('Unable to load integration settings right now');
    } finally {
      setLoading(false);
    }
  };

  const loadGmailStatus = async () => {
    try {
      const response = await axios.get('/api/auth/gmail/status');
      setGmailStatus(response.data || null);
    } catch (error) {
      console.error('Error loading Gmail status:', error);
    }
  };

  const loadPendingScans = async () => {
    try {
      const response = await axios.get('/api/integrations/chatgpt/gmail/scans/pending');
      setPendingScans(response.data || []);
    } catch (error) {
      console.error('Error loading pending scans:', error);
    }
  };

  const loadDataManagementStatus = async () => {
    setDataOpsLoading(true);
    try {
      const response = await axios.get('/api/data-management/status');
      setDataOpsStatus(response.data || null);
    } catch (error) {
      console.error('Error loading data management status:', error);
      setDataOpsStatus(null);
    } finally {
      setDataOpsLoading(false);
    }
  };

  useEffect(() => {
    // Check if we just returned from Gmail OAuth
    const params = new URLSearchParams(window.location.search);
    if (params.get('gmail_connected') === '1') {
      setGmailNotice('success');
      window.history.replaceState({}, '', window.location.pathname);
    } else if (params.get('gmail_error')) {
      setGmailNotice(`error:${params.get('gmail_error')}`);
      window.history.replaceState({}, '', window.location.pathname);
    }
    loadSettings();
    loadGmailStatus();
    loadPendingScans();
    loadDataManagementStatus();
  }, []);

  const saveSettings = async () => {
    setSaving(true);
    try {
      await axios.put('/api/integrations/chatgpt/settings', {
        chatgpt_enabled: settings.chatgpt_enabled,
        workspace_name: settings.workspace_name,
        openai_api_key: settings.openai_api_key,
        openai_model: settings.openai_model,
        mcp_shared_secret: settings.mcp_shared_secret,
        oauth_enabled: settings.oauth_enabled,
        oauth_client_id: settings.oauth_client_id,
        oauth_client_secret: settings.oauth_client_secret,
        oauth_redirect_uri: settings.oauth_redirect_uri,
        gmail_scan_window_days: settings.gmail_scan_window_days
      });
      await loadSettings();
      alert('Integration settings saved');
    } catch (error) {
      console.error('Error saving integration settings:', error);
      alert(error.response?.data?.error || 'Unable to save settings');
    } finally {
      setSaving(false);
    }
  };

  const connectGmail = async () => {
    setConnectingGmail(true);
    try {
      const response = await axios.get('/api/auth/gmail/connect-url');
      window.location.href = response.data.url;
    } catch (error) {
      console.error('Error starting Gmail OAuth:', error);
      alert(error.response?.data?.error || 'Unable to start Gmail connection. Make sure OAuth Client ID and Secret are saved first.');
      setConnectingGmail(false);
    }
  };

  const disconnectGmail = async () => {
    if (!window.confirm('Disconnect Gmail? The stored tokens will be removed and email scanning will stop.')) return;
    setDisconnectingGmail(true);
    try {
      await axios.post('/api/auth/gmail/disconnect');
      await loadGmailStatus();
      await loadSettings();
      setGmailNotice('');
    } catch (error) {
      console.error('Error disconnecting Gmail:', error);
      alert(error.response?.data?.error || 'Unable to disconnect Gmail');
    } finally {
      setDisconnectingGmail(false);
    }
  };

  const testConnection = async () => {
    setTesting(true);
    try {
      const response = await axios.post('/api/integrations/chatgpt/test');
      alert(`Connection OK (${response.data.model}): ${response.data.preview || 'No preview'}`);
    } catch (error) {
      console.error('Error testing ChatGPT connection:', error);
      alert(error.response?.data?.error || 'Connection test failed');
    } finally {
      setTesting(false);
    }
  };

  const askChatGpt = async () => {
    const trimmed = chatInput.trim();
    if (!trimmed) return;

    const nextHistory = [...chatHistory, { role: 'user', content: trimmed }];
    setChatHistory(nextHistory);
    setChatInput('');
    setChatLoading(true);

    try {
      const response = await axios.post('/api/chatgpt/chat', {
        message: trimmed,
        history: nextHistory,
        include_crm_context: includeContext
      });

      setChatHistory((prev) => [...prev, { role: 'assistant', content: response.data.reply || '' }]);

      if (onRefreshData) onRefreshData();
      if (onRefreshTasks) onRefreshTasks();
    } catch (error) {
      console.error('Error querying chat endpoint:', error);
      setChatHistory((prev) => [
        ...prev,
        { role: 'assistant', content: `Error: ${error.response?.data?.error || 'Unable to reach ChatGPT endpoint.'}` }
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  const scanGmail = async () => {
    setScanningGmail(true);
    try {
      const response = await axios.post('/api/integrations/chatgpt/gmail/scan', {
        scan_window_days: settings.gmail_scan_window_days
      });

      const found = response.data?.total_found || 0;
      if (found > 0) {
        alert(`Scan complete. Found ${found} pending updates to review.`);
      } else {
        alert('Scan complete. No new updates found.');
      }

      await loadPendingScans();
    } catch (error) {
      console.error('Error scanning Gmail:', error);
      alert(error.response?.data?.error || 'Failed to scan Gmail');
    } finally {
      setScanningGmail(false);
    }
  };

  const approveScan = async (batchId) => {
    setApprovingBatchId(batchId);
    try {
      const response = await axios.post(`/api/integrations/chatgpt/gmail/scans/${batchId}/approve`);
      alert(`Approved. Applied ${response.data?.total_applied || 0} interactions.`);
      await loadPendingScans();
      if (onRefreshContacts) onRefreshContacts();
      if (onRefreshData) onRefreshData();
    } catch (error) {
      console.error('Error approving scan:', error);
      alert(error.response?.data?.error || 'Failed to approve updates');
    } finally {
      setApprovingBatchId('');
    }
  };

  const runDataAction = async (actionKey, request) => {
    setDataOpsAction(actionKey);
    try {
      const response = await request();
      await loadDataManagementStatus();
      if (onRefreshData) onRefreshData();
      if (onRefreshTasks) onRefreshTasks();
      if (onRefreshContacts) onRefreshContacts();
      if (onRefreshWaitlist) onRefreshWaitlist();
      return response;
    } finally {
      setDataOpsAction('');
    }
  };

  const saveAllDataNow = async () => {
    try {
      const response = await runDataAction('save', () => axios.post('/api/data-management/save'));
      alert(`Data snapshot saved: ${response.data?.backup_file || 'Saved'}`);
    } catch (error) {
      console.error('Error saving data snapshot:', error);
      alert(error.response?.data?.error || error.response?.data?.message || 'Failed to save data snapshot');
    }
  };

  const populateDummyData = async () => {
    if (!window.confirm('Populate all CRM sections with dummy demo data? Existing dummy rows will be replaced.')) return;
    try {
      await runDataAction('populate', () => axios.post('/api/data-management/dummy/populate'));
      alert('Dummy data populated across bookings, contracts, waitlist, tasks, and contacts.');
    } catch (error) {
      console.error('Error populating dummy data:', error);
      alert(error.response?.data?.error || 'Failed to populate dummy data');
    }
  };

  const removeDummyData = async () => {
    if (!window.confirm('Remove all dummy CRM data now? Real data will not be deleted.')) return;
    try {
      await runDataAction('remove', () => axios.post('/api/data-management/dummy/remove'));
      alert('Dummy data removed.');
    } catch (error) {
      console.error('Error removing dummy data:', error);
      alert(error.response?.data?.error || 'Failed to remove dummy data');
    }
  };

  if (loading) {
    return (
      <div className="card">
        <h2>⚙️ ChatGPT + MCP Settings</h2>
        <p>Loading integration settings...</p>
      </div>
    );
  }

  return (
    <div className="integration-grid">
      <section className="card">
        <h2>⚙️ ChatGPT + MCP Settings</h2>
        <p className="section-subtext">Connect Campsite CRM to ChatGPT and enable Gmail interaction scanning.</p>

        <div className="integration-status-row">
          <div className="badge-pill">OpenAI Key: {settings.openai_key_configured ? 'Configured' : 'Missing'}</div>
          <div className={`badge-pill ${settings.gmail_connected ? 'badge-pill--success' : ''}`}>
            Gmail: {settings.gmail_connected ? `Connected${settings.gmail_account_email ? ` — ${settings.gmail_account_email}` : ''}` : 'Not connected'}
          </div>
          <div className="badge-pill">MCP Secret: {settings.mcp_secret_configured ? 'Configured' : 'Optional'}</div>
        </div>

        <div className="settings-grid">
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={settings.chatgpt_enabled}
              onChange={(e) => setSettings({ ...settings, chatgpt_enabled: e.target.checked })}
            />
            Enable ChatGPT Integration
          </label>

          <div className="form-group">
            <label>Workspace Name</label>
            <input
              type="text"
              value={settings.workspace_name}
              onChange={(e) => setSettings({ ...settings, workspace_name: e.target.value })}
            />
          </div>

          <div className="form-group">
            <label>OpenAI API Key</label>
            <input
              type="password"
              value={settings.openai_api_key}
              onChange={(e) => setSettings({ ...settings, openai_api_key: e.target.value })}
              placeholder="sk-..."
            />
          </div>

          <div className="form-group">
            <label>OpenAI Model</label>
            <input
              type="text"
              value={settings.openai_model}
              onChange={(e) => setSettings({ ...settings, openai_model: e.target.value })}
              placeholder="gpt-4.1-mini"
            />
          </div>

          <div className="form-group">
            <label>Gmail Scan Window (days)</label>
            <input
              type="number"
              min="1"
              value={settings.gmail_scan_window_days}
              onChange={(e) => setSettings({ ...settings, gmail_scan_window_days: parseInt(e.target.value, 10) || 1 })}
            />
          </div>

          <div className="form-group">
            <label>MCP Shared Secret (Bearer token)</label>
            <input
              type="password"
              value={settings.mcp_shared_secret}
              onChange={(e) => setSettings({ ...settings, mcp_shared_secret: e.target.value })}
              placeholder="Optional but recommended"
            />
          </div>

          {!settings.oauth_from_env && (
            <>
              <div className="form-group">
                <label>Google OAuth Client ID <span className="field-hint">(from Google Cloud Console)</span></label>
                <input
                  type="text"
                  value={settings.oauth_client_id}
                  onChange={(e) => setSettings({ ...settings, oauth_client_id: e.target.value })}
                  placeholder="xxxxxxx.apps.googleusercontent.com"
                />
              </div>

              <div className="form-group">
                <label>Google OAuth Client Secret</label>
                <input
                  type="password"
                  value={settings.oauth_client_secret}
                  onChange={(e) => setSettings({ ...settings, oauth_client_secret: e.target.value })}
                  placeholder="GOCSPX-..."
                />
              </div>
            </>
          )}
        </div>

        <div className="form-actions">
          <button className="btn btn-primary" type="button" onClick={saveSettings} disabled={saving}>
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
          <button className="btn btn-secondary" type="button" onClick={testConnection} disabled={testing}>
            {testing ? 'Testing...' : 'Test OpenAI Connection'}
          </button>
        </div>
      </section>

      <section className="card">
        <h2>📧 Gmail Account Connection</h2>
        <p className="section-subtext">
          Connect your Gmail account via OAuth to allow the CRM to scan emails for guest contacts and conversation history.
          {!settings.oauth_from_env && ' Requires Google OAuth credentials saved above.'}
        </p>

        {gmailNotice === 'success' && (
          <div className="gmail-notice gmail-notice--success">
            Gmail connected successfully! Email scanning is now enabled.
          </div>
        )}
        {gmailNotice.startsWith('error:') && (
          <div className="gmail-notice gmail-notice--error">
            Gmail connection failed: {gmailNotice.replace('error:', '')}
          </div>
        )}

        {gmailStatus ? (
          gmailStatus.connected ? (
            <div className="gmail-connected-block">
              <div className="gmail-connected-info">
                <span className="gmail-status-dot gmail-status-dot--on" />
                <strong>Connected</strong>
                {gmailStatus.account_email ? <span> as {gmailStatus.account_email}</span> : null}
                {gmailStatus.has_refresh_token ? <span className="badge-pill badge-pill--success">Auto-refresh enabled</span> : null}
              </div>
              <button
                className="btn btn-secondary"
                type="button"
                onClick={disconnectGmail}
                disabled={disconnectingGmail}
              >
                {disconnectingGmail ? 'Disconnecting...' : 'Disconnect Gmail'}
              </button>
            </div>
          ) : (
            <div className="gmail-connect-block">
              <div className="gmail-connected-info">
                <span className="gmail-status-dot gmail-status-dot--off" />
                <strong>Not connected</strong>
              </div>
              {!gmailStatus.oauth_from_env && !gmailStatus.oauth_client_configured && (
                <p className="section-subtext" style={{ color: 'var(--color-warning, #e07b00)' }}>
                  Save your Google OAuth Client ID and Client Secret above first.
                </p>
              )}
              {!gmailStatus.oauth_from_env && (
                <div className="gmail-callback-hint">
                  <strong>Authorized Redirect URI to register in Google Cloud Console:</strong>
                  <code>{gmailStatus.callback_uri}</code>
                </div>
              )}
              <button
                className="btn btn-primary"
                type="button"
                onClick={connectGmail}
                disabled={connectingGmail || (!gmailStatus.oauth_from_env && !gmailStatus.oauth_client_configured)}
              >
                {connectingGmail ? 'Redirecting to Google...' : 'Connect Gmail Account'}
              </button>
            </div>
          )
        ) : (
          <p className="chat-empty">Loading Gmail status...</p>
        )}
      </section>

      <section className="card">
        <h2>🗂️ Data Management</h2>
        <p className="section-subtext">Auto-save snapshots run in the backend on a timer. Use these controls to save now and add/remove full dummy CRM data.</p>

        {dataOpsLoading ? (
          <p className="chat-empty">Loading data management status...</p>
        ) : (
          <div className="data-status-grid">
            <div className="badge-pill">Auto-save every: {dataOpsStatus?.auto_save?.interval_minutes || '-'} min</div>
            <div className="badge-pill">Last save: {dataOpsStatus?.auto_save?.last_save_at || 'Not yet'}</div>
            <div className="badge-pill">Last mode: {dataOpsStatus?.auto_save?.last_save_type || '-'}</div>
            <div className="badge-pill">Bookings: {dataOpsStatus?.totals?.bookings ?? 0}</div>
            <div className="badge-pill">Contracts: {dataOpsStatus?.totals?.contracts ?? 0}</div>
            <div className="badge-pill">Waitlist: {dataOpsStatus?.totals?.waitlist_entries ?? 0}</div>
            <div className="badge-pill">Tasks: {dataOpsStatus?.totals?.tasks ?? 0}</div>
            <div className="badge-pill">Contacts: {dataOpsStatus?.totals?.contacts ?? 0}</div>
          </div>
        )}

        <div className="form-actions">
          <button className="btn btn-primary" type="button" onClick={saveAllDataNow} disabled={dataOpsAction !== ''}>
            {dataOpsAction === 'save' ? 'Saving...' : 'Save All Data Now'}
          </button>
          <button className="btn btn-secondary" type="button" onClick={populateDummyData} disabled={dataOpsAction !== ''}>
            {dataOpsAction === 'populate' ? 'Populating...' : 'Populate Dummy Data'}
          </button>
          <button className="btn btn-secondary" type="button" onClick={removeDummyData} disabled={dataOpsAction !== ''}>
            {dataOpsAction === 'remove' ? 'Removing...' : 'Remove Dummy Data'}
          </button>
          <button className="btn btn-secondary" type="button" onClick={loadDataManagementStatus} disabled={dataOpsAction !== ''}>
            Refresh Status
          </button>
        </div>

        {dataOpsStatus?.auto_save?.last_save_path ? (
          <p className="section-subtext data-save-path">Latest backup: {dataOpsStatus.auto_save.last_save_path}</p>
        ) : null}
        {dataOpsStatus?.auto_save?.last_error ? (
          <p className="section-subtext data-save-error">Last auto-save error: {dataOpsStatus.auto_save.last_error}</p>
        ) : null}
      </section>

      <section className="card">
        <h2>📬 Gmail Interaction Scan</h2>
        <p className="section-subtext">Scan recent Gmail messages, review pending interaction updates, then approve before applying to contacts.</p>

        <div className="form-actions">
          <button className="btn btn-primary" type="button" onClick={scanGmail} disabled={scanningGmail}>
            {scanningGmail ? 'Scanning...' : 'Scan Gmail for Recent Interactions'}
          </button>
        </div>

        <div className="scan-list">
          {pendingScans.length > 0 ? pendingScans.map((batch) => (
            <div key={batch.id} className="scan-card">
              <div className="scan-card-head">
                <div>
                  <strong>Batch {batch.id.slice(0, 8)}</strong>
                  <p>Found {batch.total_found} updates on {batch.created_at}</p>
                </div>
                <button
                  className="btn btn-secondary btn-small"
                  type="button"
                  onClick={() => approveScan(batch.id)}
                  disabled={approvingBatchId === batch.id}
                >
                  {approvingBatchId === batch.id ? 'Approving...' : 'Approve Updates'}
                </button>
              </div>
              <div className="scan-items">
                {batch.items?.length > 0 ? batch.items.map((item) => (
                  <div key={item.id} className="scan-item">
                    <strong>{item.full_name || item.email}</strong>
                    <span>{item.occurred_at || '-'} {item.direction ? `(${item.direction})` : ''}</span>
                    <p>{item.summary}</p>
                  </div>
                )) : <p className="chat-empty">No item preview available.</p>}
              </div>
            </div>
          )) : <p className="chat-empty">No pending scan updates right now.</p>}
        </div>
      </section>

      <section className="card">
        <h2>🧭 Setup Instructions</h2>
        <ol className="instructions-list">
          {!settings.oauth_from_env && (
            <>
              <li>In <strong>Google Cloud Console</strong>, create an OAuth 2.0 Client ID (Web application type). Add the Authorized Redirect URI shown in the Gmail Connection section above.</li>
              <li>Paste the Client ID and Client Secret into settings above and click <strong>Save Settings</strong>.</li>
            </>
          )}
          <li>Optionally add an OpenAI API key and enable ChatGPT integration for AI-powered email analysis.</li>
          <li>Click <strong>Connect Gmail Account</strong> in the Gmail Connection section and approve access in your browser.</li>
          <li>Once connected, go to the <strong>Contacts</strong> tab and run a Gmail scan. Review suggestions and apply the ones you want.</li>
          <li>Use the MCP endpoint URL below in your MCP client or ChatGPT bridge.</li>
        </ol>

        <div className="instruction-code">
          <strong>MCP URL</strong>
          <code>{settings.mcp_url || '-'}</code>
        </div>

        <div className="instruction-code">
          <strong>Quick MCP initialize example</strong>
          <code>{`curl -X POST ${settings.mcp_url || 'http://localhost:5000/mcp'} -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'`}</code>
        </div>
      </section>

      <section className="card integration-chat-card">
        <h2>💬 Ask ChatGPT Inside CRM</h2>
        <p className="section-subtext">This chat can include live CRM context (bookings, waitlist, tasks, summary).</p>

        <label className="toggle-row">
          <input
            type="checkbox"
            checked={includeContext}
            onChange={(e) => setIncludeContext(e.target.checked)}
          />
          Include live CRM context in prompts
        </label>

        <div className="chat-log">
          {chatHistory.length > 0 ? chatHistory.map((msg, index) => (
            <div key={`${msg.role}-${index}`} className={`chat-msg ${msg.role}`}>
              <strong>{msg.role === 'assistant' ? 'ChatGPT' : 'You'}</strong>
              <p>{msg.content}</p>
            </div>
          )) : (
            <p className="chat-empty">No chat yet. Ask about bookings, occupancy, overdue balances, or task planning.</p>
          )}
        </div>

        <div className="chat-input-row">
          <textarea
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            placeholder="Example: What tasks should we prioritize this week based on overdue bookings and upcoming arrivals?"
          />
          <button className="btn btn-primary" type="button" onClick={askChatGpt} disabled={chatLoading}>
            {chatLoading ? 'Thinking...' : 'Ask ChatGPT'}
          </button>
        </div>
      </section>
    </div>
  );
}

export default IntegrationHub;
