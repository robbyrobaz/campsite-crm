import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import '../styles/Contacts.css';

function Contacts({ refreshToken = 0 }) {
  const [recentContacts, setRecentContacts] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [selectedContact, setSelectedContact] = useState(null);
  const [selectedConversations, setSelectedConversations] = useState([]);
  const [gmailSuggestions, setGmailSuggestions] = useState([]);
  const [selectedSuggestionEmails, setSelectedSuggestionEmails] = useState([]);
  const [scanWindowDays, setScanWindowDays] = useState(45);
  const [scanMaxMessages, setScanMaxMessages] = useState(50);
  const [scanSource, setScanSource] = useState('');
  const [scanWarning, setScanWarning] = useState('');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [scanningSuggestions, setScanningSuggestions] = useState(false);
  const [applyingSuggestions, setApplyingSuggestions] = useState(false);
  const [mergingSummaries, setMergingSummaries] = useState(false);
  const [gmailConnected, setGmailConnected] = useState(null);

  const loadGmailStatus = async () => {
    try {
      const res = await axios.get('/api/auth/gmail/status');
      setGmailConnected(res.data?.connected ?? false);
    } catch (_) {
      setGmailConnected(false);
    }
  };

  const loadContacts = async (searchValue = '') => {
    const [recentRes, listRes] = await Promise.all([
      axios.get('/api/contacts/recent', { params: { limit: 12 } }),
      axios.get('/api/contacts', { params: { search: searchValue, limit: 150 } })
    ]);

    setRecentContacts(recentRes.data || []);
    setContacts(listRes.data || []);
  };

  const loadContactDetails = async (contactId) => {
    setLoadingDetails(true);
    try {
      const response = await axios.get(`/api/contacts/${contactId}`);
      setSelectedContact(response.data || null);
      setSelectedConversations(response.data?.conversations || []);
    } catch (error) {
      console.error('Error loading contact details:', error);
      alert(error.response?.data?.error || 'Unable to load contact details right now');
    } finally {
      setLoadingDetails(false);
    }
  };

  useEffect(() => {
    let isMounted = true;
    setLoading(true);
    loadGmailStatus();
    loadContacts(search)
      .catch((error) => {
        console.error('Error loading contacts:', error);
        if (isMounted) alert(error.response?.data?.error || 'Unable to load contacts right now');
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshToken]);

  const searchCountLabel = useMemo(() => {
    if (!search.trim()) return `${contacts.length} contacts`;
    return `${contacts.length} results`;
  }, [contacts.length, search]);

  const handleSearch = async () => {
    try {
      setLoading(true);
      await loadContacts(search);
    } catch (error) {
      console.error('Error searching contacts:', error);
      alert(error.response?.data?.error || 'Unable to search contacts right now');
    } finally {
      setLoading(false);
    }
  };

  const scanGmailSuggestions = async () => {
    setScanningSuggestions(true);
    setScanWarning('');
    try {
      const response = await axios.post('/api/contacts/suggestions/from-live-gmail', {
        scan_window_days: scanWindowDays,
        max_messages: scanMaxMessages
      });

      const suggestions = response.data?.suggestions || [];
      setGmailSuggestions(suggestions);
      setSelectedSuggestionEmails(suggestions.map((item) => item.email).filter(Boolean));
      setScanSource(response.data?.source || '');
      setScanWarning(response.data?.warning || '');
    } catch (error) {
      console.error('Error scanning Gmail suggestions:', error);
      alert(error.response?.data?.error || 'Unable to scan Gmail suggestions right now');
    } finally {
      setScanningSuggestions(false);
    }
  };

  const toggleSuggestion = (email) => {
    if (!email) return;
    setSelectedSuggestionEmails((prev) => {
      if (prev.includes(email)) return prev.filter((item) => item !== email);
      return [...prev, email];
    });
  };

  const applySelectedSuggestions = async () => {
    const selected = gmailSuggestions.filter((item) => selectedSuggestionEmails.includes(item.email));
    if (!selected.length) {
      alert('Select at least one suggestion to apply.');
      return;
    }

    setApplyingSuggestions(true);
    try {
      const response = await axios.post('/api/contacts/suggestions/apply', {
        suggestions: selected
      });
      alert(`Suggestions applied. Created: ${response.data?.created_count || 0}, Updated: ${response.data?.updated_count || 0}`);
      await loadContacts(search);
      setGmailSuggestions([]);
      setSelectedSuggestionEmails([]);
    } catch (error) {
      console.error('Error applying suggestions:', error);
      alert(error.response?.data?.error || 'Unable to apply suggestions right now');
    } finally {
      setApplyingSuggestions(false);
    }
  };

  const mergeRecentSummaries = async () => {
    setMergingSummaries(true);
    try {
      const response = await axios.post('/api/contacts/merge-recent-summaries', { days: 30 });
      alert(`Merged recent conversation summaries for ${response.data?.merged_count || 0} contact(s).`);
      await loadContacts(search);
      if (selectedContact?.id) {
        await loadContactDetails(selectedContact.id);
      }
    } catch (error) {
      console.error('Error merging recent summaries:', error);
      alert(error.response?.data?.error || 'Unable to merge recent summaries right now');
    } finally {
      setMergingSummaries(false);
    }
  };

  if (loading) {
    return (
      <div className="card">
        <h2>👥 Contacts</h2>
        <p>Loading contacts...</p>
      </div>
    );
  }

  return (
    <div className="contacts-layout">
      <section className="card">
        <h2>🤖 Gmail Suggestions</h2>
        <p className="section-subtext">Scan Gmail with ChatGPT and review suggestions before adding or updating contacts.</p>

        {gmailConnected === false && (
          <div className="gmail-notice gmail-notice--warn">
            Gmail not connected. Go to <strong>Settings → Gmail Account Connection</strong> to link your Google account before scanning.
          </div>
        )}

        <div className="contacts-actions-row">
          <label>
            Window (days)
            <input
              type="number"
              min={1}
              max={365}
              value={scanWindowDays}
              onChange={(e) => setScanWindowDays(Math.max(parseInt(e.target.value, 10) || 1, 1))}
            />
          </label>
          <label>
            Max messages
            <input
              type="number"
              min={5}
              max={100}
              value={scanMaxMessages}
              onChange={(e) => setScanMaxMessages(Math.max(Math.min(parseInt(e.target.value, 10) || 50, 100), 5))}
            />
          </label>
          <button className="btn btn-primary btn-small" type="button" onClick={scanGmailSuggestions} disabled={scanningSuggestions || gmailConnected === false}>
            {scanningSuggestions ? 'Scanning...' : 'Scan Gmail'}
          </button>
          <button className="btn btn-secondary btn-small" type="button" onClick={applySelectedSuggestions} disabled={applyingSuggestions || selectedSuggestionEmails.length === 0}>
            {applyingSuggestions ? 'Applying...' : `Apply Selected (${selectedSuggestionEmails.length})`}
          </button>
          <button className="btn btn-secondary btn-small" type="button" onClick={mergeRecentSummaries} disabled={mergingSummaries}>
            {mergingSummaries ? 'Merging...' : 'Merge Recent Summaries'}
          </button>
        </div>

        {scanSource ? <p className="section-subtext">Scan source: {scanSource}</p> : null}
        {scanWarning ? <p className="error-text">{scanWarning}</p> : null}

        {gmailSuggestions.length > 0 ? (
          <table className="data-table contacts-table">
            <thead>
              <tr>
                <th>Add</th>
                <th>Name</th>
                <th>Email</th>
                <th>Action</th>
                <th>Reason</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody>
              {gmailSuggestions.map((item) => (
                <tr key={`${item.email}_${item.thread_id || ''}`}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedSuggestionEmails.includes(item.email)}
                      onChange={() => toggleSuggestion(item.email)}
                    />
                  </td>
                  <td>{item.full_name || '-'}</td>
                  <td>{item.email || '-'}</td>
                  <td>{item.action === 'update' ? `Update (${item.existing_contact_name || 'existing'})` : 'Create'}</td>
                  <td>{item.reason || '-'}</td>
                  <td>{item.conversation_summary || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="empty-state">No suggestions loaded yet. Run a Gmail scan.</p>
        )}
      </section>

      <section className="card">
        <h2>🕒 Recent Contacts</h2>
        <p className="section-subtext">Most recently touched contacts and their latest interaction context.</p>

        {recentContacts.length > 0 ? (
          <table className="data-table contacts-table">
            <thead>
              <tr>
                <th>Contact</th>
                <th>Email</th>
                <th>Last Interaction</th>
                <th>Recent Context</th>
              </tr>
            </thead>
            <tbody>
              {recentContacts.map((contact) => {
                const latest = (contact.recent_interactions || [])[0] || null;
                return (
                  <tr key={contact.id}>
                    <td>{contact.full_name || '-'}</td>
                    <td>{contact.email || '-'}</td>
                    <td>{contact.last_conversation_at || contact.last_contacted_at || '-'}</td>
                    <td>{latest?.summary || contact.conversation_summary || '-'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <p className="empty-state">No recent contacts yet.</p>
        )}
      </section>

      <section className="card">
        <div className="contacts-toolbar">
          <h2>All Contacts</h2>
          <div className="contacts-search">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search name, email, company, notes"
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSearch();
              }}
            />
            <button className="btn btn-primary btn-small" type="button" onClick={handleSearch}>Search</button>
          </div>
        </div>
        <p className="section-subtext">{searchCountLabel}</p>

        <div className="contacts-grid">
          <div className="contacts-list">
            {contacts.length > 0 ? (
              <table className="data-table contacts-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Email</th>
                    <th>Status</th>
                    <th>Source</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {contacts.map((contact) => (
                    <tr key={contact.id} className={selectedContact?.id === contact.id ? 'row-selected' : ''}>
                      <td>
                        <button className="link-btn" type="button" onClick={() => loadContactDetails(contact.id)}>
                          {contact.full_name || '(No name)'}
                        </button>
                      </td>
                      <td>{contact.email || '-'}</td>
                      <td>{contact.status || '-'}</td>
                      <td>{contact.contact_source || '-'}</td>
                      <td>{contact.updated_at || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="empty-state">No contacts found.</p>
            )}
          </div>

          <div className="contacts-details">
            <h3>Conversation Detail</h3>
            {loadingDetails ? (
              <p>Loading contact details...</p>
            ) : selectedContact ? (
              <>
                <div className="contact-meta">
                  <div><strong>Name:</strong> {selectedContact.full_name || '-'}</div>
                  <div><strong>Email:</strong> {selectedContact.email || '-'}</div>
                  <div><strong>Status:</strong> {selectedContact.status || '-'}</div>
                  <div><strong>Source:</strong> {selectedContact.contact_source || '-'}</div>
                </div>

                <div className="conversation-list">
                  {selectedConversations.length > 0 ? selectedConversations.map((item) => (
                    <div key={item.id} className="conversation-item">
                      <div className="conversation-head">
                        <strong>{item.subject || 'No subject'}</strong>
                        <span>{item.occurred_at || item.created_at || '-'}</span>
                      </div>
                      <p>{item.summary}</p>
                    </div>
                  )) : <p>No conversation history yet.</p>}
                </div>
              </>
            ) : (
              <p>Select a contact to view interaction history.</p>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

export default Contacts;
