import { useState, useEffect, useCallback, useMemo } from 'react'
import { Play, Loader2, Layers } from 'lucide-react'
import { API_BASE } from './lib/stream'

function fmtCause(c = '') {
  return c.replace(/_/g, ' ').replace(/\b\w/g, m => m.toUpperCase())
}

function sevClass(score = 0) {
  if (score >= 8) return 'critical'
  if (score >= 6) return 'high'
  if (score >= 4) return 'moderate'
  return 'low'
}

const DEMO_EVENT_IDS = ['FKID006314', 'FKID007573', 'FKID007569']

export default function AllocationPanel() {
  const [events, setEvents] = useState([])
  const [selected, setSelected] = useState(() => new Set())
  const [budget, setBudget] = useState(15)
  const [result, setResult] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/events?limit=8200`)
      .then(r => r.json())
      .then(d => {
        const evs = (d.events || [])
          .filter(e => e.severity_score >= 6 || e.priority === 'High')
          .sort((a, b) => b.severity_score - a.severity_score)
        setEvents(evs)
      })
      .catch(() => setError('Could not load events. Is the backend running on :8000?'))
  }, [])

  const toggle = useCallback((id) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }, [])

  const loadDemoScenario = useCallback(() => {
    setSelected(new Set(DEMO_EVENT_IDS))
    setBudget(15)
    setResult(null)
  }, [])

  const runAllocation = useCallback(async () => {
    if (running || selected.size === 0) return
    setRunning(true); setError(''); setResult(null)
    try {
      const res = await fetch(`${API_BASE}/allocate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_ids: [...selected], total_officers: Number(budget) }),
      })
      if (!res.ok) throw new Error(`Allocate failed (${res.status})`)
      setResult(await res.json())
    } catch (err) {
      setError(`${err.message}. Start the FastAPI backend on port 8000.`)
    } finally {
      setRunning(false)
    }
  }, [selected, budget, running])

  const queue = useMemo(() => {
    const sel = events.filter(e => selected.has(e.id))
    const rest = events.filter(e => !selected.has(e.id))
    return [...sel, ...rest].slice(0, 40)
  }, [events, selected])
  const maxBar = useMemo(
    () => Math.max(1, ...((result?.allocations || []).map(a => a.demand))),
    [result],
  )

  return (
    <div className="forecast-layout">

      <section className="forecast-form-panel">
        <div className="section-heading">
          <span>Allocate a finite force</span>
          <small>{selected.size} selected</small>
        </div>
        <p className="forecast-help">
          Per-event manpower in isolation over-commits a finite force. Pick the events
          that are active at the same time, set the officers you actually have, and see how
          a scarce budget splits — the real constraint every traffic command center faces.
        </p>

        <button className="secondary-action" onClick={loadDemoScenario} style={{ marginBottom: '10px' }}>
          <Layers size={14} />Load demo scenario (3 concurrent events)
        </button>

        <label className="field">
          <span>Officer budget</span>
          <input
            type="number" min="1" max="200" value={budget}
            onChange={e => setBudget(e.target.value)}
          />
        </label>

        <div className="section-heading" style={{ marginTop: '12px' }}>
          <span>Concurrent events</span>
          <small>high-priority queue</small>
        </div>
        <div className="alloc-queue">
          {queue.map(e => (
            <label key={e.id} className={`alloc-queue-item ${selected.has(e.id) ? 'is-selected' : ''}`}>
              <input type="checkbox" checked={selected.has(e.id)} onChange={() => toggle(e.id)} />
              <span className={`queue-severity queue-severity--${sevClass(e.severity_score)}`}>{e.severity_score}</span>
              <span className="alloc-queue-label">
                <b>{fmtCause(e.event_cause)}</b>
                <small>{e.corridor !== 'Non-corridor' ? e.corridor : (e.junction !== 'NULL' ? e.junction : e.police_station)}</small>
              </span>
            </label>
          ))}
        </div>

        <button className="primary-action" onClick={runAllocation} disabled={running || selected.size === 0}>
          {running
            ? <><Loader2 size={16} className="spin" />Allocating...</>
            : <><Play size={16} />Allocate budget</>}
        </button>
        {error && <div className="load-error">{error}</div>}
      </section>

      <section className="forecast-results">
        {!result && (
          <div className="forecast-empty">
            <h3>Resource allocation under scarcity</h3>
            <p>Select concurrent events and a budget, then allocate. When demand exceeds supply,
              the force splits by severity — every event still gets at least one unit.</p>
          </div>
        )}

        {result && (
          <>
            <div className="forecast-kpis">
              <div className={`kpi ${result.status === 'oversubscribed' ? 'kpi--warn' : 'kpi--accent'}`}>
                <span>Status</span>
                <strong>{result.status === 'oversubscribed' ? 'OVERSUBSCRIBED' : 'Sufficient'}</strong>
                <em>{result.total_demand} demanded · {result.budget} available</em>
              </div>
              <div className="kpi">
                <span>Total demand</span>
                <strong>{result.total_demand} units</strong>
                <em>across {result.events} events</em>
              </div>
              <div className="kpi">
                <span>Budget</span>
                <strong>{result.budget} officers</strong>
                <em>{result.status === 'oversubscribed' ? `short by ${result.total_demand - result.budget}` : 'fully met'}</em>
              </div>
            </div>

            <div className="forecast-card">
              <div className="section-heading">
                <span>Per-event allocation</span>
                <small>severity-proportional</small>
              </div>
              {(result.allocations || []).map(a => {
                const demandPct = Math.round((a.demand / maxBar) * 100)
                const allocPct = Math.round((a.allocated / maxBar) * 100)
                const cut = a.allocated < a.demand
                return (
                  <div key={a.event_id} className="alloc-row">
                    <div className="alloc-row-head">
                      <span className={`queue-severity queue-severity--${sevClass(a.severity)}`}>{a.severity}</span>
                      <b>{fmtCause(a.event_cause)}</b>
                      <small>{a.corridor && a.corridor !== 'Non-corridor' ? a.corridor : '—'}</small>
                      <span className={`alloc-figure ${cut ? 'is-cut' : ''}`}>{a.allocated} / {a.demand}</span>
                    </div>
                    <div className="alloc-bars">
                      <div className="alloc-bar alloc-bar--demand" style={{ width: `${demandPct}%` }} />
                      <div className="alloc-bar alloc-bar--alloc" style={{ width: `${allocPct}%` }} />
                    </div>
                  </div>
                )
              })}
              <p className="muted" style={{ marginTop: '8px' }}>
                Severity-proportional allocation; every event guaranteed ≥1 unit.
              </p>
            </div>

            <div className="forecast-card">
              <div className="section-heading"><span>How to read this</span><small>honesty note</small></div>
              <p className="muted">
                Manpower demand per event is a transparent heuristic — there is no deployment
                ground truth in the dataset. This view shows how a scarce force splits across
                simultaneous events, not a validated optimal deployment. {result.note}
              </p>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
