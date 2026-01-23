import { useState, useEffect } from 'react'
import './BatchControl.css'

const API_BASE = 'http://localhost:8000'

function BatchControl() {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)

  const [reportContent, setReportContent] = useState(null)
  const [showModal, setShowModal] = useState(false)

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
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          limit: 0, 
          ids: []
        })
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

  const handleViewReport = async () => {
    try {
      const response = await fetch(`${API_BASE}/batch/report`)
      if (response.ok) {
        const data = await response.json()
        setReportContent(data.content) 
        setShowModal(true)
      } else {
        alert("Report not found yet. Make sure the batch is finished.")
      }
    } catch (error) {
      console.error('Failed to fetch report:', error)
      alert("Error connecting to server")
    }
  }

  const handleStop = async () => {
    try {
      const response = await fetch(`${API_BASE}/batch/stop`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({})
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

            <button 
              className="report-button"
              onClick={handleViewReport}
              style={{
                marginLeft: '10px',
                backgroundColor: '#009688', // Màu xanh Teal
                color: 'white',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '4px',
                cursor: 'pointer'
              }}
            >
              📊 View Summary Report
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

      {showModal && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.8)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 1000
        }}>
          <div style={{
            backgroundColor: '#1e1e1e',
            color: '#e0e0e0',
            width: '90%',
            maxWidth: '1000px',
            height: '80%',
            borderRadius: '8px',
            display: 'flex',
            flexDirection: 'column',
            padding: '20px',
            boxShadow: '0 4px 10px rgba(0,0,0,0.5)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '15px' }}>
              <h3 style={{ margin: 0 }}>Final Aggregated Report (Lastest)</h3>
              <button 
                onClick={() => setShowModal(false)}
                style={{
                  background: '#f44336', color: 'white', border: 'none',
                  padding: '5px 15px', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold'
                }}
              >
                Close X
              </button>
            </div>

            <div style={{ 
              flex: 1, 
              overflow: 'auto', 
              backgroundColor: '#000', 
              padding: '15px',
              border: '1px solid #333',
              borderRadius: '4px'
            }}>
              <pre style={{ 
                margin: 0, 
                fontFamily: 'Consolas, Monaco, "Courier New", monospace',
                fontSize: '13px',
                lineHeight: '1.4',
                whiteSpace: 'pre-wrap'
              }}>
                {reportContent || "Loading..."}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default BatchControl




