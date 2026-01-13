import { useState } from 'react'
import './TaskDetail.css'

const API_BASE = 'http://localhost:8000'

function TaskDetail({ task, taskDetail, onRun }) {
  const [result, setResult] = useState(null)
  const [running, setRunning] = useState(false)
  const [activeTab, setActiveTab] = useState('details')

  const handleRun = async () => {
    setRunning(true)
    setResult(null)
    try {
      const response = await fetch(`${API_BASE}/run`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ instance_id: task.id }),
      })
      
      if (!response.ok) {
        throw new Error('Failed to run task')
      }
      
      const data = await response.json()
      setResult(data)
      setActiveTab('result')
    } catch (error) {
      setResult({ status: 'error', detail: error.message })
    } finally {
      setRunning(false)
    }
  }

  const formatDocChanges = (changes) => {
    if (Array.isArray(changes)) {
      return changes.join('\n')
    }
    return changes || ''
  }

  return (
    <div className="task-detail">
      <div className="task-detail-header">
        <div>
          <h2>{task.id}</h2>
          <p className="task-repo">{taskDetail.repo}</p>
        </div>
        <button
          className="run-button"
          onClick={handleRun}
          disabled={running}
        >
          {running ? 'Running...' : 'Run Task'}
        </button>
      </div>

      <div className="tabs">
        <button
          className={`tab ${activeTab === 'details' ? 'active' : ''}`}
          onClick={() => setActiveTab('details')}
        >
          Details
        </button>
        <button
          className={`tab ${activeTab === 'result' ? 'active' : ''}`}
          onClick={() => setActiveTab('result')}
          disabled={!result}
        >
          Result {result && `(${result.status})`}
        </button>
      </div>

      <div className="tab-content">
        {activeTab === 'details' && (
          <div className="details-content">
            <div className="detail-section">
              <h3>Problem Statement</h3>
              <pre className="code-block">{taskDetail.problem_statement || 'N/A'}</pre>
            </div>

            <div className="detail-section">
              <h3>Documentation Changes</h3>
              <pre className="code-block">{formatDocChanges(taskDetail.doc_changes)}</pre>
            </div>

            <div className="detail-section">
              <h3>Augmentations</h3>
              <pre className="code-block">{JSON.stringify(taskDetail.augmentations, null, 2)}</pre>
            </div>

            <div className="detail-section">
              <h3>Base Commit</h3>
              <code className="commit-hash">{taskDetail.base_commit}</code>
            </div>
          </div>
        )}

        {activeTab === 'result' && result && (
          <div className="result-content">
            {result.status === 'completed' && (
              <>
                <div className="result-section">
                  <h3>Status</h3>
                  <div className={`status-badge ${result.success ? 'success' : 'failed'}`}>
                    {result.success ? '✓ PASSED' : '✗ FAILED'}
                  </div>
                </div>

                {result.read_files && result.read_files.length > 0 && (
                  <div className="result-section">
                    <h3>Read Files ({result.read_files.length})</h3>
                    <ul className="file-list">
                      {result.read_files.map((file, idx) => (
                        <li key={idx}>{file}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {result.patch && (
                  <div className="result-section">
                    <h3>Generated Patch</h3>
                    <pre className="code-block">{result.patch}</pre>
                  </div>
                )}

                {result.eval_output && (
                  <div className="result-section">
                    <h3>Evaluation Output</h3>
                    <pre className="code-block eval-output">{result.eval_output}</pre>
                  </div>
                )}
              </>
            )}

            {result.status === 'error' && (
              <div className="error-section">
                <h3>Error</h3>
                <div className="error-detail">
                  <strong>Step:</strong> {result.step || 'Unknown'}<br />
                  <strong>Detail:</strong> {result.detail || 'Unknown error'}
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'result' && !result && (
          <div className="no-result">
            Run the task to see results
          </div>
        )}
      </div>
    </div>
  )
}

export default TaskDetail




