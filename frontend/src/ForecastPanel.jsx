import { useState, useEffect, useCallback, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import { Play, Loader2, Copy, Send } from 'lucide-react'
import { API_BASE, streamPipeline } from './lib/stream'

const CAUSES = [
  'public_event', 'procession', 'protest', 'vip_movement', 'construction',
  'road_conditions', 'water_logging', 'accident', 'congestion', 'vehicle_breakdown', 'others',
]

const EMPTY_FORM = {
  event_cause: 'public_event',
  latitude: 12.9767,
  longitude: 77.5713,
  corridor: '',
  junction: '',
  start_datetime: '2024-04-20 18:00:00',
  scheduled_duration_mins: 180,
  priority: 'High',
  requires_road_closure: true,
  description: '',
}

function fmtCause(c = '') {
  return c.replace(/_/g, ' ').replace(/\b\w/g, m => m.toUpperCase())
}

export default function ForecastPanel() {
  const [presets, setPresets] = useState([])
  const [presetId, setPresetId] = useState('')
  const [form, setForm] = useState(EMPTY_FORM)
  const [edited, setEdited] = useState(false)

  const [running, setRunning] = useState(false)
  const [spatial, setSpatial] = useState(null)
  const [rag, setRag] = useState(null)
  const [command, setCommand] = useState('')
  const [statuses, setStatuses] = useState({ spatial: 'idle', rag: 'idle', command: 'idle' })
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')

  const [actualMins, setActualMins] = useState('')
  const [feedbackMsg, setFeedbackMsg] = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/events?event_type=planned&limit=500`)
      .then(r => r.json())
      .then(d => setPresets(d.events || []))
      .catch(() => setError('Could not load planned-event presets. Is the backend running on :8000?'))
  }, [])

  const applyPreset = useCallback((id) => {
    setPresetId(id)
    setEdited(false)
    const p = presets.find(e => e.id === id)
    if (!p) return
    setForm({
      event_cause: p.event_cause || 'public_event',
      latitude: p.latitude,
      longitude: p.longitude,
      corridor: p.corridor && p.corridor !== 'Non-corridor' ? p.corridor : '',
      junction: p.junction && p.junction !== 'NULL' ? p.junction : '',
      start_datetime: (p.start_datetime || EMPTY_FORM.start_datetime).replace(/\+00$|\+05:30$/, '').trim(),
      scheduled_duration_mins: p.scheduled_duration_mins || 180,
      priority: p.priority || 'High',
      requires_road_closure: !!p.requires_road_closure,
      description: p.description && p.description !== 'NULL' ? p.description : '',
    })
  }, [presets])

  const setField = (key, value) => {
    setForm(prev => ({ ...prev, [key]: value }))
    setEdited(true)
  }

  const runForecast = useCallback(async () => {
    if (running) return
    setRunning(true)
    setSpatial(null); setRag(null); setCommand(''); setDone(false); setError('')
    setFeedbackMsg(''); setActualMins('')
    setStatuses({ spatial: 'running', rag: 'running', command: 'idle' })

    const body = {
      ...form,
      latitude: Number(form.latitude),
      longitude: Number(form.longitude),
      scheduled_duration_mins: form.scheduled_duration_mins ? Number(form.scheduled_duration_mins) : null,
      source_event_id: presetId || null,
      edited,
    }

    try {
      await streamPipeline(`${API_BASE}/forecast`, body, {
        status: d => setStatuses(prev => ({ ...prev, [d.agent]: 'running' })),
        spatial_result: d => { setSpatial(d.data); setStatuses(prev => ({ ...prev, spatial: 'complete' })) },
        rag_result: d => { setRag(d.data); setStatuses(prev => ({ ...prev, rag: 'complete' })) },
        command_chunk: d => { setStatuses(prev => ({ ...prev, command: 'running' })); setCommand(prev => prev + d.text) },
        complete: () => { setStatuses(prev => ({ ...prev, command: 'complete' })); setDone(true) },
        error: d => { setError(d.message); setStatuses(prev => ({ ...prev, command: 'complete' })) },
      })
    } catch (err) {
      setError(`${err.message}. Start the FastAPI backend on port 8000.`)
    } finally {
      setRunning(false)
    }
  }, [form, presetId, edited, running])

  const submitFeedback = useCallback(async () => {
    if (!actualMins) return
    try {
      const res = await fetch(`${API_BASE}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          event_id: presetId || null,
          event_cause: form.event_cause,
          corridor: form.corridor,
          predicted_mins: spatial?.predicted_clearance?.median_mins ?? null,
          actual_mins: Number(actualMins),
        }),
      })
      const d = await res.json()
      setFeedbackMsg(`Logged (${d.count} total). Outcomes are tracked as prediction error and sharpen the priors on the next re-training run.`)
    } catch {
      setFeedbackMsg('Could not record feedback.')
    }
  }, [actualMins, presetId, form, spatial])

  const deployment = spatial?.deployment_recommendation || {}
  const manpower = deployment.manpower || {}
  const predicted = spatial?.predicted_clearance
  const counter = spatial?.counterfactual
  const contrast = spatial?.road_closure_contrast
  const topNodes = useMemo(() => spatial?.blast_radius?.affected_nodes?.slice(0, 6) || [], [spatial])

  return (
    <div className="forecast-layout">

      <section className="forecast-form-panel">
        <div className="section-heading">
          <span>Plan a future event</span>
          <small>{edited ? 'edited' : presetId ? 'preset' : 'new'}</small>
        </div>
        <p className="forecast-help">
          Pick a real planned event as a starting point, then tweak it. An unedited preset is
          scored against its actual outcome (predicted-vs-actual).
        </p>

        <label className="field">
          <span>Preset (real planned events)</span>
          <select value={presetId} onChange={e => applyPreset(e.target.value)}>
            <option value="">— choose a planned event —</option>
            {presets.slice(0, 200).map(p => (
              <option key={p.id} value={p.id}>
                {fmtCause(p.event_cause)} — {p.corridor !== 'Non-corridor' ? p.corridor : (p.junction !== 'NULL' ? p.junction : p.police_station)}
              </option>
            ))}
          </select>
        </label>

        <div className="field-row">
          <label className="field">
            <span>Cause</span>
            <select value={form.event_cause} onChange={e => setField('event_cause', e.target.value)}>
              {CAUSES.map(c => <option key={c} value={c}>{fmtCause(c)}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Priority</span>
            <select value={form.priority} onChange={e => setField('priority', e.target.value)}>
              <option>High</option><option>Low</option>
            </select>
          </label>
        </div>

        <div className="field-row">
          <label className="field"><span>Latitude</span>
            <input type="number" step="0.0001" value={form.latitude} onChange={e => setField('latitude', e.target.value)} />
          </label>
          <label className="field"><span>Longitude</span>
            <input type="number" step="0.0001" value={form.longitude} onChange={e => setField('longitude', e.target.value)} />
          </label>
        </div>

        <label className="field"><span>Corridor</span>
          <input value={form.corridor} placeholder="e.g. Mysore Road" onChange={e => setField('corridor', e.target.value)} />
        </label>

        <div className="field-row">
          <label className="field"><span>Start (IST)</span>
            <input value={form.start_datetime} onChange={e => setField('start_datetime', e.target.value)} />
          </label>
          <label className="field"><span>Duration (min)</span>
            <input type="number" value={form.scheduled_duration_mins} onChange={e => setField('scheduled_duration_mins', e.target.value)} />
          </label>
        </div>

        <label className="checkbox-field">
          <input type="checkbox" checked={form.requires_road_closure} onChange={e => setField('requires_road_closure', e.target.checked)} />
          <span>Requires road closure</span>
        </label>

        <button className="primary-action" onClick={runForecast} disabled={running}>
          {running
            ? <><Loader2 size={16} className="spin" />Forecasting...</>
            : <><Play size={16} />{done ? 'Re-run forecast' : 'Run forecast'}</>}
        </button>
        {error && <div className="load-error">{error}</div>}

        <div className="agent-mini">
          {['spatial', 'rag', 'command'].map(a => (
            <span key={a} className={`mini-badge mini-badge--${statuses[a]}`}>{a}</span>
          ))}
        </div>
      </section>

      <section className="forecast-results">
        {!spatial && !running && (
          <div className="forecast-empty">
            <h3>Proactive event forecast</h3>
            <p>Choose a preset and run a forecast to see predicted impact, manpower, barricading, and metering anchors — before the event happens.</p>
          </div>
        )}

        {spatial && (
          <>
            <div className="forecast-kpis">
              <div className="kpi">
                <span>Predicted clearance</span>
                <strong>{predicted?.median_mins ?? '--'} min</strong>
                <em>band {predicted?.range_mins?.[0]}–{predicted?.range_mins?.[1]} · {predicted?.confidence} conf.</em>
              </div>
              <div className="kpi">
                <span>Manpower (heuristic)</span>
                <strong>{manpower.units ?? '--'} units</strong>
                <em>{deployment.barricade_points?.length || 0} barricade points</em>
              </div>
              <div className="kpi">
                <span>Affected junctions</span>
                <strong>{spatial.blast_radius?.total_affected_junctions ?? '--'}</strong>
                <em>{spatial.blast_radius?.critical_junctions || 0} critical</em>
              </div>
              {predicted?.actual_mins != null && (
                <div className="kpi kpi--accent">
                  <span>Actual (this event)</span>
                  <strong>{predicted.actual_mins} min</strong>
                  <em>predicted vs actual</em>
                </div>
              )}
            </div>

            <p className="muted" style={{ margin: '2px 0 10px' }}>
              Held-out validation (temporal split, n=717): best-baseline MAE 40.7 min, within ±15 min 26% of the time.
              Clearance is a calibrated planning band, not a point forecast — an HGBR was tested and did not beat this baseline on MAE.
            </p>

            <div className="forecast-card">
              <div className="section-heading"><span>Manpower breakdown</span><small>transparent heuristic</small></div>
              <div className="breakdown-chips">
                {(manpower.breakdown || []).map(b => (
                  <span key={b.factor} className="breakdown-chip">{b.factor.replace(/_/g, ' ')} <b>+{b.units}</b></span>
                ))}
              </div>
              <p className="muted">{manpower.note}</p>
            </div>

            <div className="forecast-card">
              <div className="section-heading"><span>Barricade & metering anchors</span><small>graph-based, approximate</small></div>
              <div className="deploy-block">
                <b>Barricade points</b>
                <p>{deployment.barricade_points?.join(' · ') || 'None above threshold'}</p>
              </div>
              {(deployment.diversion_routes || []).map((d, i) => (
                <div key={i} className="deploy-block">
                  <b>Meter → {d.to}</b>
                  <p>{d.via?.join(' → ')} <em>(~{d.distance_km} km, {d.realism?.replace(/_/g, ' ')})</em></p>
                </div>
              ))}
            </div>

            <div className="forecast-card">
              <div className="section-heading"><span>Projected spillover</span><small>{spatial.blast_radius?.critical_junctions} critical</small></div>
              {topNodes.map(n => {
                const impact = Math.round((n.relative_impact_score || 0) * 100)
                return (
                  <div key={n.junction} className="impact-row">
                    <div><strong>{n.junction}</strong><span>{n.distance_km} km · impact in {n.estimated_time_to_impact_mins} min</span></div>
                    <div className="impact-meter"><i style={{ width: `${impact}%` }} /><b>{impact}%</b></div>
                  </div>
                )
              })}
            </div>

            {counter && (
              <div className="forecast-card">
                <div className="section-heading"><span>Counterfactual</span><small>heuristic</small></div>
                <div className="comparison">
                  <div><span>Without intervention</span><strong>{counter.without_intervention_mins} min</strong></div>
                  <div><span>With deployment</span><strong>{counter.with_intervention_mins} min</strong></div>
                </div>
                <div className="save-callout">Saves ~{counter.time_saved_mins} min (traffic recovery estimate)</div>
                <p className="muted" style={{marginTop:'4px'}}>Recovery time after the event ends — not the event's scheduled duration.</p>
                <p className="muted" style={{marginTop:'4px'}}>{counter.basis}</p>
                {contrast?.closure_true_median_mins != null && contrast.n_true >= 10 && (
                  <p className="muted">
                    Data contrast (confounded): road-closure events clear in {contrast.closure_true_median_mins} min
                    (n={contrast.n_true}) vs {contrast.closure_false_median_mins} min (n={contrast.n_false}).
                  </p>
                )}
              </div>
            )}

            {rag && (
              <div className="forecast-card">
                <div className="section-heading"><span>Historical evidence</span><small>{rag.pattern_analysis?.total_similar_events_found || 0} matches</small></div>
                <div className="fact-grid compact">
                  <div><span>Same event-type</span><strong>{rag.match_context?.same_event_type_matches || 0}</strong></div>
                  <div><span>Same cause</span><strong>{rag.match_context?.same_cause_matches || 0}</strong></div>
                  <div><span>Median clearance</span><strong>{rag.pattern_analysis?.median_clearance_time_mins ?? '--'} min</strong></div>
                </div>
                {(rag.pattern_analysis?.known_complications || []).slice(0, 2).map(c => (
                  <p key={c} className="warning-line">{c}</p>
                ))}
              </div>
            )}

            {command && (
              <div className="forecast-card command-panel">
                <div className="section-heading">
                  <span>Deployment plan</span>
                  <button className="copy-command" onClick={() => navigator.clipboard?.writeText(command)}><Copy size={12} />Copy</button>
                </div>
                <div className="command-body"><ReactMarkdown>{command}</ReactMarkdown></div>
              </div>
            )}

            {done && (
              <div className="forecast-card feedback-card">
                <div className="section-heading"><span>Outcome logging</span><small>feeds re-training</small></div>
                <p className="muted">After the event, log the actual clearance. Outcomes are recorded and tracked as prediction error; they sharpen the priors on the next re-training run (not an automatic online update).</p>
                <div className="feedback-row">
                  <input type="number" placeholder="actual clearance (min)" value={actualMins} onChange={e => setActualMins(e.target.value)} />
                  <button className="secondary-action" onClick={submitFeedback} disabled={!actualMins}><Send size={14} />Submit outcome</button>
                </div>
                {feedbackMsg && <p className="feedback-msg">{feedbackMsg}</p>}
              </div>
            )}
          </>
        )}
      </section>
    </div>
  )
}
