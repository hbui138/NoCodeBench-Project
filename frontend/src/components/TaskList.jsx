import { useState } from 'react'
import './TaskList.css'

function TaskList({ tasks, selectedTask, onTaskSelect }) {
  const [searchTerm, setSearchTerm] = useState('')

  const filteredTasks = tasks.filter(task =>
    task.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
    task.project.toLowerCase().includes(searchTerm.toLowerCase())
  )

  return (
    <div className="task-list">
      <div className="task-list-header">
        <h2>Tasks ({tasks.length})</h2>
        <input
          type="text"
          placeholder="Search tasks..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="search-input"
        />
      </div>
      <div className="task-items">
        {filteredTasks.map(task => (
          <div
            key={task.id}
            className={`task-item ${selectedTask?.id === task.id ? 'selected' : ''}`}
            onClick={() => onTaskSelect(task)}
          >
            <div className="task-id">{task.id}</div>
            <div className="task-project">{task.project}</div>
            <div className={`task-status status-${task.status.toLowerCase()}`}>
              {task.status}
            </div>
          </div>
        ))}
        {filteredTasks.length === 0 && (
          <div className="no-tasks">No tasks found</div>
        )}
      </div>
    </div>
  )
}

export default TaskList




