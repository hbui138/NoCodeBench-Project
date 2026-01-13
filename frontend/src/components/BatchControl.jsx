import { useState, useEffect } from 'react'
import './BatchControl.css'

const API_BASE = 'http://localhost:8000'

function BatchControl() {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const interval = setInterval(() => {
      if (status?.is_running) {
        fetchStatus()
      }
    }, 2000)
    return () => clearInterval(interval)
  }, [status?.is_running])

  const fetchStatus = async () => {
    try {
      const response = await fetch(`${API_BASE}/batch/status`)
      if (response.ok) {
        const data = await response.json()
        setStatus(data)
      }
    } catch (error) {
      console.error('Failed to fetch batch status:', error)
    }
  }

  useEffect(() => {
    fetchStatus()
  }, [])

  const handleStart = async () => {
    setLoading(true)
    try {
      const response = await fetch(`${API_BASE}/batch/start`, {
        method: 'POST',
      })
      if (response.ok) {
        await fetchStatus()
      }
    } catch (error) {
      console.error('Failed to start batch:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleStop = async () => {
    try {
      const response = await fetch(`${API_BASE}/batch/stop`, {
        method: 'POST',
      })
      if (response.ok) {
        await fetchStatus()
      }
    } catch (error) {
      console.error('Failed to stop batch:', error)
    }
  }

  const progress = status?.total > 0 
    ? (status.processed / status.total) * 100 
    : 0

  return (
    <div className="batch-control">
      <h2>Batch Processing</h2>
      <div className="batch-status">
        {status?.is_running ? (
          <>
            <div className="progress-bar-container">
              <div 
                className="progress-bar" 
                style={{ width: `${progress}%` }}
              />
            </div>
            <div className="progress-text">
              {status.processed} / {status.total} tasks
            </div>
            <button 
              className="stop-button"
              onClick={handleStop}
            >
              Stop
            </button>
          </>
        ) : (
          <>
            <div className="batch-idle">
              {status?.processed > 0 
                ? `Completed: ${status.processed} tasks`
                : 'Ready to start'
              }
            </div>
            <button 
              className="start-button"
              onClick={handleStart}
              disabled={loading}
            >
              {loading ? 'Starting...' : 'Start Batch'}
            </button>
          </>
        )}
      </div>
      {status?.logs && status.logs.length > 0 && (
        <div className="batch-logs">
          <h3>Recent Logs</h3>
          <div className="log-content">
            {status.logs.slice(-5).map((log, idx) => (
              <div key={idx} className="log-entry">{log}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default BatchControl




