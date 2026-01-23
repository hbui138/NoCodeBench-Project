import { useState, useEffect } from 'react'
import TaskList from './components/TaskList'
import TaskDetail from './components/TaskDetail'
import BatchControl from './components/BatchControl'
import './App.css'

const API_BASE = 'http://localhost:8000'

function App() {
  const [tasks, setTasks] = useState([])
  const [selectedTask, setSelectedTask] = useState(null)
  const [taskDetail, setTaskDetail] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchTasks()
  }, [])

  const fetchTasks = async () => {
    try {
      const response = await fetch(`${API_BASE}/tasks`)
      if (!response.ok) throw new Error('Failed to fetch tasks')
      const data = await response.json()
      setTasks(data)
    } catch (err) {
      setError(err.message)
    }
  }

  const fetchTaskDetail = async (instanceId) => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(`${API_BASE}/tasks/${instanceId}`)
      if (!response.ok) throw new Error('Failed to fetch task details')
      const data = await response.json()
      setTaskDetail(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleTaskSelect = (task) => {
    setSelectedTask(task)
    fetchTaskDetail(task.id)
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>NoCode Agent</h1>
        <p>AI agent for generating code patches from documentation changes</p>
      </header>
      <div className="app-content">
        <div className="sidebar">
          <BatchControl />
          <TaskList 
            tasks={tasks}
            selectedTask={selectedTask}
            onTaskSelect={handleTaskSelect}
          />
        </div>
        <div className="main-content">
          {selectedTask && taskDetail ? (
            <TaskDetail 
              task={selectedTask}
              taskDetail={taskDetail}
              onRun={() => fetchTaskDetail(selectedTask.id)}
            />
          ) : (
            <div className="empty-state">
              <p>Select a task to view details</p>
            </div>
          )}
          {error && (
            <div className="error-message">
              Error: {error}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default App




