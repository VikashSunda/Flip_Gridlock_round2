import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import './index.css'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const CAUSE_COLORS = {
  vehicle_breakdown: '#d97706',
  accident: '#dc2626',
  tree_fall: '#ea580c',
  construction: '#2563eb',
  water_logging: '#0891b2',
  pot_holes: '#7c3aed',
  vip_movement: '#9333ea',
  procession: '#9333ea',
  congestion: '#dc2626',
  public_event: '#ea580c',
  protest: '#dc2626',
  road_conditions: '#64748b',
  others: '#64748b',
  Debris: '#64748b',
}

const SEVERITY_LABELS = {
  1: 'Low',
  2: 'Low',
  3: 'Low',
  4: 'Moderate',
  5: 'Moderate',
  6: 'High',
  7: 'High',
  8: 'Critical',
  9: 'Critical',
  10: 'Critical',
}

const SEVERITY_CLASS = {
  Low: 'low',
  Moderate: 'moderate',
  High: 'high',
  Critical: 'critical',
}

const BOUNDS = {
  minLat: 12.85,
  maxLat: 13.15,
  minLon: 77.45,
  maxLon: 77.75,
}

const FILTERS = [
  ['all', 'All'],
  ['accident', 'Accident'],
  ['vehicle_breakdown', 'Breakdown'],
  ['water_logging', 'Waterlogging'],
  ['tree_fall', 'Tree fall'],
  ['public_event', 'Public event'],
  ['vip_movement', 'VIP'],
]

const MISSION_STEPS = [
  ['0-5 min', 'Lock epicenter, clear approach lane, dispatch nearest response team.'],
  ['5-15 min', 'Hold downstream junctions before queue spillback reaches the corridor.'],
  ['15-45 min', 'Run diversion plan until historical clearance window closes.'],
]

const SHOWCASE_RULES = [
  {
    label: 'Critical now',
    reason: 'Highest severity live incident',
    match: event => event.severity_score >= 8 && event.junction && event.junction !== 'NULL',
  },
  {
    label: 'ORR cascade',
    reason: 'Best corridor spillover story',
    match: event => event.corridor?.includes('ORR') && event.severity_score >= 6,
  },
  {
    label: 'Planned event',
    reason: 'Shows planned + unplanned coverage',
    match: event => event.event_type === 'planned',
  },
  {
    label: 'Rain risk',
    reason: 'Great historical RAG angle',
    match: event => event.event_cause === 'water_logging',
  },
]

function formatCause(cause = '') {
  return cause.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function cleanValue(value, fallback = 'Unknown') {
  if (!value || value === 'NULL' || value === 'Non-corridor') return fallback
  return value
}

function severityLabel(event) {
  return SEVERITY_LABELS[event?.severity_score] || 'Moderate'
}

function pointFromLatLon(latitude, longitude) {
  const x = ((longitude - BOUNDS.minLon) / (BOUNDS.maxLon - BOUNDS.minLon)) * 100
  const y = ((BOUNDS.maxLat - latitude) / (BOUNDS.maxLat - BOUNDS.minLat)) * 100
  return { x, y, visible: x >= 0 && x <= 100 && y >= 0 && y <= 100 }
}

function pickDemoEvent(events) {
  const eligible = events.filter(event =>
    event.latitude &&
    event.longitude &&
    event.junction &&
    event.junction !== 'NULL' &&
    event.severity_score >= 6
  )

  return [...eligible].sort((a, b) => {
    const corridorA = a.corridor && a.corridor !== 'Non-corridor' ? 1 : 0
    const corridorB = b.corridor && b.corridor !== 'Non-corridor' ? 1 : 0
    return (b.severity_score - a.severity_score) || (corridorB - corridorA)
  })[0] || events[0]
}

function pickShowcaseEvents(events) {
  const chosen = []
  const used = new Set()

  SHOWCASE_RULES.forEach(rule => {
    const match = events
      .filter(event => !used.has(event.id) && event.latitude && event.longitude && rule.match(event))
      .sort((a, b) => b.severity_score - a.severity_score)[0]

    if (match) {
      chosen.push({ ...match, showcaseLabel: rule.label, showcaseReason: rule.reason })
      used.add(match.id)
    }
  })

  return chosen
}

function StatusBadge({ status }) {
  const label = status === 'complete' ? 'Done' : status === 'running' ? 'Running' : 'Waiting'
  return <span className={`status-badge status-badge--${status}`}>{label}</span>
}

function App() {
  const [events, setEvents] = useState([])
  const [stats, setStats] = useState(null)
  const [selectedEvent, setSelectedEvent] = useState(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [activeFilter, setActiveFilter] = useState('all')
  const [loadError, setLoadError] = useState('')
  const [integrations, setIntegrations] = useState(null)

  const [spatialResult, setSpatialResult] = useState(null)
  const [ragResult, setRagResult] = useState(null)
  const [commandText, setCommandText] = useState('')
  const [agentStatuses, setAgentStatuses] = useState({
    spatial: 'idle',
    rag: 'idle',
    command: 'idle',
  })
  const [pipelineComplete, setPipelineComplete] = useState(false)

  const commandRef = useRef(null)

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/events?limit=8200`).then(r => r.json()),
      fetch(`${API_BASE}/stats`).then(r => r.json()),
      fetch(`${API_BASE}/integrations`).then(r => r.json()).catch(() => null),
    ])
      .then(([eventsData, statsData, integrationData]) => {
        const loadedEvents = eventsData.events || []
        setEvents(loadedEvents)
        setStats(statsData)
        setIntegrations(integrationData)
        setSelectedEvent(pickDemoEvent(loadedEvents))
      })
      .catch(err => {
        console.error('Failed to load ASTraM data:', err)
        setLoadError('Backend is not reachable. Start FastAPI on port 8000 to load live incident data.')
      })
  }, [])

  useEffect(() => {
    if (commandRef.current) {
      commandRef.current.scrollTop = commandRef.current.scrollHeight
    }
  }, [commandText])

  const filteredEvents = useMemo(() => {
    const subset = activeFilter === 'all'
      ? events
      : events.filter(event => event.event_cause === activeFilter)

    return [...subset]
      .filter(event => event.latitude && event.longitude)
      .sort((a, b) => (b.severity_score - a.severity_score))
  }, [events, activeFilter])

  const priorityQueue = useMemo(() => (
    filteredEvents
      .filter(event => event.priority === 'High' || event.severity_score >= 7)
      .slice(0, 12)
  ), [filteredEvents])

  const showcaseEvents = useMemo(() => pickShowcaseEvents(events), [events])
  const mapEvents = useMemo(() => filteredEvents.slice(0, 650), [filteredEvents])

  const currentSeverity = severityLabel(selectedEvent)
  const severityClass = SEVERITY_CLASS[currentSeverity] || 'moderate'
  const topAffected = spatialResult?.blast_radius?.affected_nodes?.slice(0, 5) || []
  const epicenterPoint = spatialResult?.epicenter
    ? pointFromLatLon(spatialResult.epicenter.latitude, spatialResult.epicenter.longitude)
    : selectedEvent
      ? pointFromLatLon(selectedEvent.latitude, selectedEvent.longitude)
      : null

  const impactSummary = spatialResult
    ? `${spatialResult.blast_radius.total_affected_junctions} junctions in ${spatialResult.blast_radius.max_radius_km} km`
    : 'Awaiting forecast'

  const savedMinutes = spatialResult?.counterfactual?.time_saved_mins
  const unitCount = spatialResult?.deployment_recommendation?.astram_units_needed
  const mapStatus = integrations?.mapmyindia?.status || 'offline_fallback'
  const geminiModel = integrations?.gemini?.model || 'gemini-3.5-flash'
  const capabilityScore = [
    stats?.total_events > 1000,
    stats?.junctions_in_graph > 10,
    mapStatus === 'connected',
    integrations?.gemini?.status === 'connected',
    Boolean(spatialResult && ragResult),
  ].filter(Boolean).length
  const confidenceScore = spatialResult && ragResult
    ? Math.min(
      96,
      68 +
        Math.min(12, spatialResult.blast_radius.critical_junctions * 3) +
        Math.min(10, Math.floor((ragResult.pattern_analysis?.total_similar_events_found || 0) / 2)) +
        (mapStatus === 'connected' ? 6 : 0)
    )
    : null
  const interventionScenarios = spatialResult ? [
    {
      label: 'Monitor only',
      units: 0,
      clearance: spatialResult.counterfactual.without_intervention_mins,
      saved: 0,
    },
    {
      label: 'Recommended',
      units: unitCount,
      clearance: spatialResult.counterfactual.with_intervention_mins,
      saved: spatialResult.counterfactual.time_saved_mins,
    },
    {
      label: 'Surge response',
      units: unitCount + 2,
      clearance: Math.max(8, spatialResult.counterfactual.with_intervention_mins - 8),
      saved: spatialResult.counterfactual.time_saved_mins + 8,
    },
  ] : []

  const handleSelectEvent = useCallback((event) => {
    setSelectedEvent(event)
    setSpatialResult(null)
    setRagResult(null)
    setCommandText('')
    setAgentStatuses({ spatial: 'idle', rag: 'idle', command: 'idle' })
    setPipelineComplete(false)
  }, [])

  const runAnalysis = useCallback(async () => {
    if (!selectedEvent || analyzing) return

    setAnalyzing(true)
    setSpatialResult(null)
    setRagResult(null)
    setCommandText('')
    setPipelineComplete(false)
    setAgentStatuses({ spatial: 'running', rag: 'running', command: 'idle' })

    try {
      const response = await fetch(`${API_BASE}/analyze/${selectedEvent.id}`, { method: 'POST' })
      if (!response.ok || !response.body) {
        throw new Error(`Analysis failed with HTTP ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue

          try {
            const data = JSON.parse(line.slice(6))

            if (data.type === 'status') {
              setAgentStatuses(prev => ({ ...prev, [data.agent]: 'running' }))
            }

            if (data.type === 'spatial_result') {
              setSpatialResult(data.data)
              setAgentStatuses(prev => ({ ...prev, spatial: 'complete' }))
            }

            if (data.type === 'rag_result') {
              setRagResult(data.data)
              setAgentStatuses(prev => ({ ...prev, rag: 'complete' }))
            }

            if (data.type === 'command_chunk') {
              setAgentStatuses(prev => ({ ...prev, command: 'running' }))
              setCommandText(prev => prev + data.text)
            }

            if (data.type === 'complete') {
              setAgentStatuses(prev => ({ ...prev, command: 'complete' }))
              setPipelineComplete(true)
            }

            if (data.type === 'error') {
              setCommandText(`### Pipeline Alert\n${data.message}`)
              setAgentStatuses(prev => ({ ...prev, command: 'complete' }))
            }
          } catch (err) {
            console.warn('Skipping malformed stream line', err)
          }
        }
      }
    } catch (err) {
      console.error('Analysis failed:', err)
      setCommandText(`### Pipeline Alert\n${err.message}. Check that the backend is running and the event data is loaded.`)
      setAgentStatuses(prev => ({ ...prev, command: 'complete' }))
    } finally {
      setAnalyzing(false)
    }
  }, [selectedEvent, analyzing])

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark">AN</div>
          <div>
            <h1>ASTraM Nexus</h1>
            <p>Event-driven congestion command center</p>
          </div>
        </div>

        <div className="topbar-metrics">
          <div>
            <strong>{stats?.total_events?.toLocaleString() || '--'}</strong>
            <span>historical incidents</span>
          </div>
          <div>
            <strong>{stats?.junctions_in_graph || '--'}</strong>
            <span>causal nodes</span>
          </div>
          <div>
            <strong>{stats?.spatial_edges || '--'}</strong>
            <span>road dependencies</span>
          </div>
        </div>

        <div className={`system-state system-state--${mapStatus}`}>
          <span />
          {mapStatus === 'connected' ? 'MapmyIndia credentials connected' : 'Offline graph fallback'}
        </div>
      </header>

      <main className="workspace">
        <aside className="left-rail">
          <section className="brief-panel">
            <p className="eyebrow">Demo objective</p>
            <h2>Forecast the blast radius, then issue a field order.</h2>
            <p>
              This screen is built for a 2 minute judge demo: pick an incident, run the
              three-agent pipeline, and show why the recommended deployment changes the outcome.
            </p>
          </section>

          <section className="readiness-panel">
            <div className="section-heading">
              <span>Readiness score</span>
              <small>{capabilityScore}/5 live</small>
            </div>
            <div className="score-ring">
              <strong>{Math.round((capabilityScore / 5) * 100)}%</strong>
              <span>submission ready</span>
            </div>
            <div className="readiness-item">
              <strong>Gemini command agent</strong>
              <span>{geminiModel}</span>
            </div>
            <div className="readiness-item">
              <strong>MapmyIndia routing</strong>
              <span>{mapStatus === 'connected' ? 'OAuth credentials connected, routing-ready' : 'Credential pending, local graph active'}</span>
            </div>
            <div className="readiness-item">
              <strong>Judge story</strong>
              <span>Every recommendation shows spatial cause, historical proof, and counterfactual outcome.</span>
            </div>
          </section>

          <section className="showcase-panel">
            <div className="section-heading">
              <span>Best demo cases</span>
              <small>Use these first</small>
            </div>
            <div className="showcase-list">
              {showcaseEvents.map(event => (
                <button
                  key={event.id}
                  className={`showcase-card ${selectedEvent?.id === event.id ? 'is-active' : ''}`}
                  onClick={() => handleSelectEvent(event)}
                >
                  <strong>{event.showcaseLabel}</strong>
                  <span>{event.showcaseReason}</span>
                  <small>{formatCause(event.event_cause)} - {cleanValue(event.junction, cleanValue(event.corridor))}</small>
                </button>
              ))}
            </div>
          </section>

          <section className="control-panel">
            <div className="section-heading">
              <span>Incident queue</span>
              <small>{filteredEvents.length.toLocaleString()} visible</small>
            </div>

            <div className="filter-grid">
              {FILTERS.map(([key, label]) => (
                <button
                  key={key}
                  className={`filter-chip ${activeFilter === key ? 'is-active' : ''}`}
                  onClick={() => setActiveFilter(key)}
                >
                  {label}
                </button>
              ))}
            </div>

            {loadError && <div className="load-error">{loadError}</div>}

            <div className="queue-list">
              {priorityQueue.map(event => (
                <button
                  key={event.id}
                  className={`queue-item ${selectedEvent?.id === event.id ? 'is-active' : ''}`}
                  onClick={() => handleSelectEvent(event)}
                >
                  <span className={`queue-severity queue-severity--${SEVERITY_CLASS[severityLabel(event)]}`}>
                    {event.severity_score}
                  </span>
                  <span>
                    <strong>{formatCause(event.event_cause)}</strong>
                    <small>{cleanValue(event.junction, cleanValue(event.corridor, event.police_station))}</small>
                  </span>
                </button>
              ))}
            </div>
          </section>
        </aside>

        <section className="map-stage">
          <div className="map-toolbar">
            <div>
              <p className="eyebrow">Bengaluru operational graph</p>
              <h2>{selectedEvent ? formatCause(selectedEvent.event_cause) : 'Select an incident'}</h2>
            </div>
            <div className="map-toolbar-actions">
              <span className="provider-chip">
                {spatialResult?.causal_analysis?.routing_provider || (mapStatus === 'connected' ? 'MapmyIndia ready' : 'Offline graph')}
              </span>
              <div className={`severity-pill severity-pill--${severityClass}`}>
                {currentSeverity} risk
              </div>
            </div>
          </div>

          <div className="map-canvas">
            <div className="map-grid" />
            <div className="road road-a" />
            <div className="road road-b" />
            <div className="road road-c" />
            <div className="road road-d" />

            <svg className="impact-lines" viewBox="0 0 100 100" preserveAspectRatio="none">
              {epicenterPoint && topAffected.map(node => {
                const nodePoint = pointFromLatLon(node.latitude, node.longitude)
                if (!epicenterPoint.visible || !nodePoint.visible) return null
                return (
                  <line
                    key={node.junction}
                    x1={epicenterPoint.x}
                    y1={epicenterPoint.y}
                    x2={nodePoint.x}
                    y2={nodePoint.y}
                  />
                )
              })}
            </svg>

            {mapEvents.map(event => {
              const { x, y, visible } = pointFromLatLon(event.latitude, event.longitude)
              if (!visible) return null

              const isSelected = selectedEvent?.id === event.id
              const color = CAUSE_COLORS[event.event_cause] || '#64748b'

              return (
                <button
                  key={event.id}
                  className={`map-dot ${isSelected ? 'is-selected' : ''}`}
                  style={{
                    left: `${x}%`,
                    top: `${y}%`,
                    '--dot-color': color,
                    '--dot-size': `${Math.max(7, Math.min(14, event.severity_score + 4))}px`,
                  }}
                  onClick={() => handleSelectEvent(event)}
                  title={`${formatCause(event.event_cause)} - ${event.address || event.id}`}
                />
              )
            })}

            {topAffected.map((node, index) => {
              const { x, y, visible } = pointFromLatLon(node.latitude, node.longitude)
              if (!visible) return null
              const impact = Math.round(node.causal_impact_probability * 100)
              return (
                <div
                  key={node.junction}
                  className="impact-node"
                  style={{
                    left: `${x}%`,
                    top: `${y}%`,
                    '--impact-delay': `${index * 140}ms`,
                    '--impact-size': `${44 + impact / 2}px`,
                  }}
                >
                  <span>{impact}%</span>
                </div>
              )
            })}

            {epicenterPoint?.visible && (
              <div
                className="epicenter-card"
                style={{ left: `${epicenterPoint.x}%`, top: `${epicenterPoint.y}%` }}
              >
                <span>Epicenter</span>
                <strong>{cleanValue(selectedEvent?.junction, spatialResult?.epicenter?.nearest_junction || 'Live event')}</strong>
              </div>
            )}

            <div className="map-legend">
              <span><i className="legend-dot incident" /> Incident density</span>
              <span><i className="legend-dot affected" /> Predicted spillover</span>
              <span><i className="legend-line" /> Causal impact path</span>
            </div>
          </div>

          <div className="bottom-strip">
            <div>
              <span>Blast radius</span>
              <strong>{impactSummary}</strong>
            </div>
            <div>
              <span>Recommended units</span>
              <strong>{unitCount || '--'}</strong>
            </div>
            <div>
              <span>Time saved</span>
              <strong>{savedMinutes ? `${savedMinutes} min` : '--'}</strong>
            </div>
            <button className="primary-action" onClick={runAnalysis} disabled={!selectedEvent || analyzing}>
              {analyzing ? 'Running agents...' : pipelineComplete ? 'Run again' : 'Run 3-agent forecast'}
            </button>
          </div>
        </section>

        <aside className="right-rail">
          <section className="incident-panel">
            <div className="section-heading">
              <span>Selected incident</span>
              <small>{selectedEvent?.id || '--'}</small>
            </div>

            {selectedEvent ? (
              <>
                <div className="incident-title-row">
                  <h2>{formatCause(selectedEvent.event_cause)}</h2>
                  <span className={`severity-pill severity-pill--${severityClass}`}>
                    {selectedEvent.severity_score}/10
                  </span>
                </div>

                <p className="incident-address">{selectedEvent.address}</p>

                <div className="fact-grid">
                  <div>
                    <span>Junction</span>
                    <strong>{cleanValue(selectedEvent.junction)}</strong>
                  </div>
                  <div>
                    <span>Corridor</span>
                    <strong>{cleanValue(selectedEvent.corridor)}</strong>
                  </div>
                  <div>
                    <span>Station</span>
                    <strong>{cleanValue(selectedEvent.police_station)}</strong>
                  </div>
                  <div>
                    <span>Closure</span>
                    <strong>{selectedEvent.requires_road_closure ? 'Required' : 'Not required'}</strong>
                  </div>
                </div>

                {selectedEvent.description && selectedEvent.description !== 'NULL' && (
                  <div className="field-note">
                    <span>Field note</span>
                    <p>{selectedEvent.description}</p>
                  </div>
                )}
              </>
            ) : (
              <p className="empty-copy">Choose an incident from the queue or map.</p>
            )}
          </section>

          <section className="agent-panel">
            <div className="section-heading">
              <span>Agent pipeline</span>
              <small>{pipelineComplete ? 'Complete' : analyzing ? 'In progress' : 'Ready'}</small>
            </div>

            <div className="agent-row">
              <div>
                <strong>Spatial-Causal Engine</strong>
                <span>Computes downstream spillover and affected junctions.</span>
              </div>
              <StatusBadge status={agentStatuses.spatial} />
            </div>
            <div className="agent-row">
              <div>
                <strong>RAG Intelligence Core</strong>
                <span>Finds similar incidents and clearance patterns.</span>
              </div>
              <StatusBadge status={agentStatuses.rag} />
            </div>
            <div className="agent-row">
              <div>
                <strong>Command Synthesizer</strong>
                <span>Turns evidence into deployment instructions.</span>
              </div>
              <StatusBadge status={agentStatuses.command} />
            </div>
          </section>

          {confidenceScore && (
            <section className="confidence-panel">
              <div className="section-heading">
                <span>Command confidence</span>
                <small>Explainability</small>
              </div>
              <div className="confidence-score">
                <strong>{confidenceScore}%</strong>
                <span>based on spatial propagation, historical matches, and provider readiness</span>
              </div>
              <div className="audit-list">
                <div>
                  <b>Spatial evidence</b>
                  <span>{spatialResult.blast_radius.total_affected_junctions} affected junctions, {spatialResult.blast_radius.critical_junctions} critical.</span>
                </div>
                <div>
                  <b>Historical evidence</b>
                  <span>{ragResult.pattern_analysis?.total_similar_events_found || 0} similar incidents retrieved.</span>
                </div>
                <div>
                  <b>Action evidence</b>
                  <span>{unitCount} ASTraM units reduce clearance by {savedMinutes} minutes.</span>
                </div>
              </div>
            </section>
          )}

          {spatialResult && (
            <section className="intel-panel">
              <div className="section-heading">
                <span>Blast radius</span>
                <small>{spatialResult.blast_radius.critical_junctions} critical</small>
              </div>
              {topAffected.map(node => {
                const impact = Math.round(node.causal_impact_probability * 100)
                return (
                  <div key={node.junction} className="impact-row">
                    <div>
                      <strong>{node.junction}</strong>
                      <span>{node.distance_km} km - impact in {node.estimated_time_to_impact_mins} min</span>
                    </div>
                    <div className="impact-meter">
                      <i style={{ width: `${impact}%` }} />
                      <b>{impact}%</b>
                    </div>
                  </div>
                )
              })}
            </section>
          )}

          {spatialResult?.counterfactual && (
            <section className="outcome-panel">
              <div className="section-heading">
                <span>Counterfactual outcome</span>
                <small>Judge-friendly proof</small>
              </div>
              <div className="comparison">
                <div>
                  <span>Without intervention</span>
                  <strong>{spatialResult.counterfactual.without_intervention_mins} min</strong>
                </div>
                <div>
                  <span>With deployment</span>
                  <strong>{spatialResult.counterfactual.with_intervention_mins} min</strong>
                </div>
              </div>
              <div className="save-callout">
                Saves {spatialResult.counterfactual.time_saved_mins} minutes with {unitCount} ASTraM units.
              </div>
            </section>
          )}

          {interventionScenarios.length > 0 && (
            <section className="whatif-panel">
              <div className="section-heading">
                <span>Intervention simulator</span>
                <small>What-if</small>
              </div>
              {interventionScenarios.map(scenario => (
                <div key={scenario.label} className="scenario-row">
                  <div>
                    <strong>{scenario.label}</strong>
                    <span>{scenario.units} ASTraM units</span>
                  </div>
                  <div>
                    <b>{scenario.clearance} min</b>
                    <em>{scenario.saved ? `saves ${scenario.saved} min` : 'no time saved'}</em>
                  </div>
                </div>
              ))}
            </section>
          )}

          {ragResult && (
            <section className="intel-panel">
              <div className="section-heading">
                <span>Historical proof</span>
                <small>{ragResult.pattern_analysis?.total_similar_events_found || 0} matches</small>
              </div>
              <div className="fact-grid compact">
                <div>
                  <span>Avg clearance</span>
                  <strong>{ragResult.pattern_analysis?.avg_clearance_time_mins || '--'} min</strong>
                </div>
                <div>
                  <span>Same corridor</span>
                  <strong>{ragResult.causal_context?.same_corridor_matches || 0}</strong>
                </div>
              </div>
              {(ragResult.pattern_analysis?.known_complications || []).slice(0, 2).map(item => (
                <p key={item} className="warning-line">{item}</p>
              ))}
            </section>
          )}

          <section className="mission-panel">
            <div className="section-heading">
              <span>Demo close</span>
              <small>Say this</small>
            </div>
            <div className="pitch-card">
              <strong>From reactive to prescriptive</strong>
              <span>Police do not just see congestion. They get the next junction to hold, how many units to send, and how many minutes the action saves.</span>
            </div>
            {MISSION_STEPS.map(([time, text]) => (
              <div key={time} className="mission-step">
                <strong>{time}</strong>
                <span>{text}</span>
              </div>
            ))}
          </section>

          {commandText && (
            <section className="command-panel" ref={commandRef}>
              <div className="section-heading">
                <span>Operational command</span>
                <button
                  className="copy-command"
                  onClick={() => navigator.clipboard?.writeText(commandText)}
                  type="button"
                >
                  Copy order
                </button>
              </div>
              <ReactMarkdown>{commandText}</ReactMarkdown>
            </section>
          )}
        </aside>
      </main>
    </div>
  )
}

export default App
