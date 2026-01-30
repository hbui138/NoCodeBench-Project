import { useState, useCallback, useEffect } from 'react'
import './TaskDetail.css'

const API_BASE = 'http://localhost:8000'

const PatchViewer = ({ patch }) => {
  if (!patch) return <div className="no-patch">No patch generated</div>;

  return (
    <div className="patch-container">
      {patch.split('\n').map((line, index) => {
        let className = "diff-line";
        
        // Logic xác định màu sắc dựa vào ký tự đầu dòng
        if (line.startsWith('@@')) {
            className += " diff-header";
        } else if (line.startsWith('+++') || line.startsWith('---')) {
            className += " diff-file-header";
        } else if (line.startsWith('+')) {
            className += " diff-add";
        } else if (line.startsWith('-')) {
            className += " diff-remove";
        }

        return (
          <div key={index} className={className}>
            {line}
          </div>
        );
      })}
    </div>
  );
};

function TaskDetail({ task, taskDetail, onRun, refreshTrigger }) {
  const [result, setResult] = useState(null)
  const [reportText, setReportText] = useState(null)
  const [running, setRunning] = useState(false)
  const [activeTab, setActiveTab] = useState('details')

  const fetchLatestResult = useCallback(async () => {
    try {
      const detailResponse = await fetch(`${API_BASE}/results/${task.id}`)
      
      if (detailResponse.ok) {
        const detailData = await detailResponse.json()
        if (detailData.result) {
            setResult(detailData.result)
        }
      }
    } catch (error) {
      console.error("Auto-fetch result error:", error)
    }
  }, [task.id]) 

  const fetchSummaryReport = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/batch/report`)
      if (resp.ok) {
        const data = await resp.json()
        if (data.content) {
            setReportText(data.content)
        }
      }
    } catch (e) {
      console.error("Fetch report error:", e)
    }
  }, [])

  useEffect(() => {
    setResult(null) 
    setActiveTab('details')
    
    fetchLatestResult()
    fetchSummaryReport()
  }, [task.id, fetchLatestResult, fetchSummaryReport])

  useEffect(() => {
    if (refreshTrigger > 0) {
        fetchLatestResult()
        fetchSummaryReport()
    }
  }, [refreshTrigger, fetchLatestResult, fetchSummaryReport])

  const handleRun = async () => {
    setRunning(true)
    setResult(null)
    setReportText(null)
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

      await fetchLatestResult()
      await fetchSummaryReport()

      setActiveTab('result')
    } catch (error) {
      setResult({ status: 'error', detail: error.message })
    } finally {
      setRunning(false)
    }
  }

  const formatStat = (stats) => {
    if (!stats) return { rate: "0.0", text: "N/A" }
    const success = stats.success?.length || 0
    const fail = stats.fail?.length || 0
    const total = success + fail
    if (total === 0) return { rate: "0.0", text: "0/0" }
    const rate = ((success / total) * 100).toFixed(1)
    return { rate, text: `${rate}% (${success}/${total})` }
  }

  return (
    <div className="task-detail">
      {/* HEADER */}
      <div className="task-detail-header">
        <div>
          <h2>{task.id}</h2>
          <p className="task-repo">{taskDetail.repo}</p>
        </div>
        <button className="run-button" onClick={handleRun} disabled={running}>
          {running ? 'Running...' : 'Run Single Task'}
        </button>
      </div>

      {/* TABS */}
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
          Result Analysis
        </button>
        <button 
          className={`tab ${activeTab === 'report' ? 'active' : ''}`} 
          onClick={() => setActiveTab('report')} 
          disabled={!reportText}
        >
          Global Report
        </button>
      </div>

      {/* CONTENT */}
      <div className="tab-content">
        
        {/* === TAB 1: DETAILS === */}
        {activeTab === 'details' && (
          <div className="details-content">
             <div className="detail-section">
               <h3>Problem Statement</h3>
               <pre className="code-block">{taskDetail.problem_statement || 'N/A'}</pre>
             </div>
             <div className="detail-section">
               <h3>Base Commit</h3>
               <code className="commit-hash">{taskDetail.base_commit}</code>
             </div>
          </div>
        )}

        {/* === TAB 2: RESULT ANALYSIS === */}
        {activeTab === 'result' && result && (
          <div className="result-content">
            {/* 1. Status Badge */}
            <div className="result-section status-section">
                <h3>Execution Status</h3>
                {result.status === 'error' ? (
                    <div className="status-badge failed">EXECUTION ERROR</div>
                ) : (
                    <div className={`status-badge ${result.success ? 'true' : 'false'}`}>
                        {result.success ? '✓ PASSED' : '✗ FAILED'}
                    </div>
                )}
            </div>

            {/* 2. Metrics Dashboard */}
            {result.status === 'Completed' && (
                <div className="metrics-dashboard">
                    <div className="metric-card">
                        <h4>🪙 Tokens used</h4>
                        <div className="metric-big-number">{result.token_usage?.total?.toLocaleString()}</div>
                        <div className="metric-subtext">Prompt: {result.token_usage?.prompt}</div>
                    </div>
                    {(() => { const s = formatStat(result.p2p); return (
                        <div className="metric-card">
                            <h4>🛡️ P2P (Regression)</h4>
                            <div className={`metric-big-number ${parseFloat(s.rate) < 100 ? 'warn' : 'good'}`}>
                                {s.rate}%
                            </div>
                            <div className="metric-subtext">{s.text} passed</div>
                        </div>
                    )})()}
                    {(() => { const s = formatStat(result.f2p); return (
                        <div className="metric-card">
                            <h4>🐛 F2P (Bug Fix)</h4>
                            <div className={`metric-big-number ${parseFloat(s.rate) > 0 ? 'good' : 'bad'}`}>
                                {s.rate}%
                            </div>
                            <div className="metric-subtext">{s.text} passed</div>
                        </div>
                    )})()}
                </div>
            )}

            {/* 3. Generated Patch */}
            {result.patch && (
                <div className="result-section">
                    <h3>Generated Patch</h3>
                    <PatchViewer patch={result.patch} />
                </div>
            )}

            {/* 4. DETAILED FAILURE ANALYSIS */}
            {result.status === 'Completed' && (
                <div className="failure-analysis">
                    {/* F2P FAILURES */}
                    {result.f2p?.fail?.length > 0 && (
                        <div className="failure-box f2p-fail">
                            <h4>❌ F2P Failures (Bugs not fixed):</h4>
                            <ul>
                                {result.f2p.fail.map((t, i) => <li key={i}>{t}</li>)}
                            </ul>
                        </div>
                    )}
                    
                    {/* P2P FAILURES */}
                    {result.p2p?.fail?.length > 0 && (
                        <div className="failure-box p2p-fail">
                            <h4>⚠️ P2P Failures (Regression Bugs):</h4>
                            <ul>
                                {result.p2p.fail.map((t, i) => <li key={i}>{t}</li>)}
                            </ul>
                        </div>
                    )}

                    {/* If no failures */}
                    {result.f2p?.fail?.length === 0 && result.p2p?.fail?.length === 0 && (
                        <div className="success-message">
                            ✨ All tests passed! No errors found.
                        </div>
                    )}
                </div>
            )}
          </div>
        )}

        {/* === TAB 3: GLOBAL REPORT === */}
        {activeTab === 'report' && reportText && (
          <div className="report-content">
             <h3>Global Summary Report (_summary_report.txt)</h3>
             <pre className="report-pre">{reportText}</pre>
          </div>
        )}

        {/* Empty State */}
        {activeTab !== 'details' && !result && !reportText && (
            <div className="no-result">Run task to see results.</div>
        )}
      </div>
    </div>
  )
}

export default TaskDetail