import React, { useState } from 'react';
import '../styles/TaskManager.css';

const INITIAL_TASK = {
  title: '',
  details: '',
  status: 'todo',
  due_date: ''
};

const STATUS_OPTIONS = [
  { value: 'todo', label: 'To Do' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'done', label: 'Done' }
];

function TaskManager({ tasks = [], onAddTask, onUpdateTask, onDeleteTask }) {
  const [formData, setFormData] = useState(INITIAL_TASK);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!formData.title.trim()) {
      alert('Task title is required');
      return;
    }

    await onAddTask({
      ...formData,
      title: formData.title.trim(),
      due_date: formData.due_date || null
    });

    setFormData(INITIAL_TASK);
  };

  return (
    <div className="card">
      <h2>✅ Team Task Board</h2>
      <p className="section-subtext">Track operational tasks and expose them to MCP/ChatGPT workflows.</p>

      <form className="task-form" onSubmit={handleSubmit}>
        <div className="task-form-grid">
          <div className="form-group">
            <label>Task Title *</label>
            <input
              type="text"
              value={formData.title}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
              placeholder="Example: Confirm horse group contract renewal"
              required
            />
          </div>

          <div className="form-group">
            <label>Status</label>
            <select
              value={formData.status}
              onChange={(e) => setFormData({ ...formData, status: e.target.value })}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label>Due Date</label>
            <input
              type="date"
              value={formData.due_date}
              onChange={(e) => setFormData({ ...formData, due_date: e.target.value })}
            />
          </div>
        </div>

        <div className="form-group">
          <label>Details</label>
          <textarea
            value={formData.details}
            onChange={(e) => setFormData({ ...formData, details: e.target.value })}
            placeholder="Optional implementation details or notes"
          />
        </div>

        <div className="form-actions">
          <button type="submit" className="btn btn-primary">Add Task</button>
        </div>
      </form>

      <div className="table-responsive" style={{ marginTop: '20px' }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Status</th>
              <th>Due Date</th>
              <th>Details</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {tasks.length > 0 ? tasks.map((task) => (
              <tr key={task.id}>
                <td>{task.title}</td>
                <td>
                  <select
                    className="status-select"
                    value={task.status || 'todo'}
                    onChange={(e) => onUpdateTask(task.id, { status: e.target.value })}
                  >
                    {STATUS_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </td>
                <td>{task.due_date || '-'}</td>
                <td>{task.details || '-'}</td>
                <td className="actions">
                  <button
                    className="btn btn-danger btn-small"
                    type="button"
                    onClick={() => onDeleteTask(task.id)}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            )) : (
              <tr>
                <td colSpan={5}>No tasks yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default TaskManager;
