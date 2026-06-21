import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import { motion } from 'framer-motion'
import {
  Radar, Radio, CalendarClock, Users, Wifi, WifiOff,
  Loader2, CheckCircle2, Circle, Play, Copy, Siren, BarChart3,
} from 'lucide-react'
import './index.css'
import ForecastPanel from './ForecastPanel'
import AllocationPanel from './AllocationPanel'
import AnalyticsPanel from './AnalyticsPanel'
import MapView from './MapView'
import { API_BASE, streamPipeline } from './lib/stream'

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

const FILTERS = [
  ['all', 'All'],
  ['accident', 'Accident'],
  ['vehicle_breakdown', 'Breakdown'],
  ['water_logging', 'Waterlogging'],
  ['tree_fall', 'Tree fall'],
  ['public_event', 'Public event'],
  ['vip_movement', 'VIP'],
]

const MODES = [
  ['live', 'Live incident', Radio],
  ['forecast', 'Event forecast', CalendarClock],
  ['allocate', 'Force allocation', Users],
  ['analytics', 'Analytics', BarChart3],
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
  const Icon = status === 'complete' ? CheckCircle2 : status === 'running' ? Loader2 : Circle
  return (
    <span className={`status-badge status-badge--${status}`}>
      <Icon size={12} className={status === 'running' ? 'spin' : ''} />
      {label}
    </span>
  )
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
  const [mode, setMode] = useState('live')


  const [replayActive, setReplayActive] = useState(false)
  const [replayTimeline, setReplayTimeline] = useState(null)
  const [replayLoading, setReplayLoading] = useState(false)
  const [replayPlaying, setReplayPlaying] = useState(false)
  const [replayClockSec, setReplayClockSec] = useState(0)
  const [replaySpeed, setReplaySpeed] = useState(60)
  const [firedAlertKeys, setFiredAlertKeys] = useState([])
  const [surgeLog, setSurgeLog] = useState([])
  const [activeAlert, setActiveAlert] = useState(null)

  const commandRef = useRef(null)
  const replayTimerRef = useRef(null)
  const autoAnalyzedRef = useRef(false)
  const runAnalysisRef = useRef(null)

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
  const topAffected = useMemo(
    () => spatialResult?.blast_radius?.affected_nodes?.slice(0, 5) || [],
    [spatialResult],
  )

  const mapEpicenter = useMemo(() => {
    if (spatialResult?.epicenter) {
      return {
        latitude: spatialResult.epicenter.latitude,
        longitude: spatialResult.epicenter.longitude,
        label: `Epicenter · ${cleanValue(selectedEvent?.junction, spatialResult.epicenter.nearest_junction || 'Live event')}`,
      }
    }
    if (selectedEvent) {
      return {
        latitude: Number(selectedEvent.latitude),
        longitude: Number(selectedEvent.longitude),
        label: cleanValue(selectedEvent.junction, 'Live event'),
      }
    }
    return null
  }, [spatialResult, selectedEvent])

  const impactSummary = spatialResult
    ? `${spatialResult.blast_radius.total_affected_junctions} junctions in ${spatialResult.blast_radius.max_radius_km} km`
    : 'Awaiting forecast'

  const savedMinutes = spatialResult?.counterfactual?.time_saved_mins
  const unitCount = spatialResult?.deployment_recommendation?.manpower?.units
  const mapStatus = integrations?.mapmyindia?.status || 'offline_fallback'
  const hasEvidence = Boolean(spatialResult && ragResult)

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
  ] : []

  const handleSelectEvent = useCallback((event) => {
    setSelectedEvent(event)
    setSpatialResult(null)
    setRagResult(null)
    setCommandText('')
    setAgentStatuses({ spatial: 'idle', rag: 'idle', command: 'idle' })
    setPipelineComplete(false)
  }, [])

  const runAnalysis = useCallback(async (eventOverride) => {
    const target = eventOverride && eventOverride.id ? eventOverride : selectedEvent
    if (!target || analyzing) return

    setAnalyzing(true)
    setSpatialResult(null)
    setRagResult(null)
    setCommandText('')
    setPipelineComplete(false)
    setAgentStatuses({ spatial: 'running', rag: 'running', command: 'idle' })

    try {
      await streamPipeline(`${API_BASE}/analyze/${target.id}`, null, {
        status: data => setAgentStatuses(prev => ({ ...prev, [data.agent]: 'running' })),
        spatial_result: data => {
          setSpatialResult(data.data)
          setAgentStatuses(prev => ({ ...prev, spatial: 'complete' }))
        },
        rag_result: data => {
          setRagResult(data.data)
          setAgentStatuses(prev => ({ ...prev, rag: 'complete' }))
        },
        command_chunk: data => {
          setAgentStatuses(prev => ({ ...prev, command: 'running' }))
          setCommandText(prev => prev + data.text)
        },
        complete: () => {
          setAgentStatuses(prev => ({ ...prev, command: 'complete' }))
          setPipelineComplete(true)
        },
        error: data => {
          setCommandText(`### Pipeline Alert\n${data.message}`)
          setAgentStatuses(prev => ({ ...prev, command: 'complete' }))
        },
      })
    } catch (err) {
      console.error('Analysis failed:', err)
      setCommandText(`### Pipeline Alert\n${err.message}. Check that the backend is running and the event data is loaded.`)
      setAgentStatuses(prev => ({ ...prev, command: 'complete' }))
    } finally {
      setAnalyzing(false)
    }
  }, [selectedEvent, analyzing])


  useEffect(() => { runAnalysisRef.current = runAnalysis }, [runAnalysis])


  const eventsById = useMemo(() => {
    const map = {}
    for (const e of events) map[e.id] = e
    return map
  }, [events])

  const analyzeAnchor = useCallback((alert) => {
    const anchor = eventsById[alert.anchor_event_id]
    setActiveAlert(alert)
    if (anchor) {
      setSelectedEvent(anchor)
      runAnalysisRef.current?.(anchor)
    }
  }, [eventsById])

  const startReplay = useCallback(async () => {
    setReplayActive(true)
    setReplayClockSec(0)
    setFiredAlertKeys([])
    setSurgeLog([])
    setActiveAlert(null)
    autoAnalyzedRef.current = false
    let tl = replayTimeline
    if (!tl) {
      setReplayLoading(true)
      try {
        tl = await fetch(`${API_BASE}/replay/timeline`).then(r => r.json())
        setReplayTimeline(tl)
      } catch (err) {
        console.error('Replay load failed:', err)
        setLoadError('Could not load the replay timeline. Is the backend running on :8000?')
        setReplayActive(false)
        return
      } finally {
        setReplayLoading(false)
      }
    }
    setReplayPlaying(true)
  }, [replayTimeline])

  const restartReplay = useCallback(() => {
    setReplayClockSec(0)
    setFiredAlertKeys([])
    setSurgeLog([])
    setActiveAlert(null)
    autoAnalyzedRef.current = false
    setReplayPlaying(true)
  }, [])

  const exitReplay = useCallback(() => {
    setReplayActive(false)
    setReplayPlaying(false)
    setReplayClockSec(0)
    setActiveAlert(null)
  }, [])


  useEffect(() => {
    if (!replayActive || !replayPlaying || !replayTimeline) return
    replayTimerRef.current = setInterval(() => {
      setReplayClockSec(prev => Math.min(prev + replaySpeed, replayTimeline.duration_sec))
    }, 250)
    return () => clearInterval(replayTimerRef.current)
  }, [replayActive, replayPlaying, replayTimeline, replaySpeed])


  useEffect(() => {
    if (replayTimeline && replayPlaying && replayClockSec >= replayTimeline.duration_sec) {
      setReplayPlaying(false)
    }
  }, [replayClockSec, replayTimeline, replayPlaying])


  const arrivedReplay = useMemo(() => {
    if (!replayActive || !replayTimeline) return null
    return replayTimeline.events.filter(e => e.t_offset_sec <= replayClockSec)
  }, [replayActive, replayTimeline, replayClockSec])

  const replayVisible = useMemo(() => {
    if (!arrivedReplay) return null
    return arrivedReplay.map(e => eventsById[e.id]).filter(Boolean)
  }, [arrivedReplay, eventsById])


  useEffect(() => {
    if (!replayActive || !replayTimeline) return
    const due = replayTimeline.alerts.filter(
      a => a.fire_at_offset_sec <= replayClockSec
        && !firedAlertKeys.includes(`${a.anchor_event_id}:${a.fire_at_offset_sec}`)
    )
    if (due.length === 0) return
    setFiredAlertKeys(prev => [...prev, ...due.map(a => `${a.anchor_event_id}:${a.fire_at_offset_sec}`)])
    setSurgeLog(prev => [...due.slice().reverse(), ...prev])
    setActiveAlert(due[due.length - 1])
    if (!autoAnalyzedRef.current) {
      autoAnalyzedRef.current = true
      const anchor = eventsById[due[0].anchor_event_id]
      if (anchor) {
        setSelectedEvent(anchor)
        runAnalysisRef.current?.(anchor)
      }
    }
  }, [replayClockSec, replayActive, replayTimeline, firedAlertKeys, eventsById])

  const replayClock = arrivedReplay && arrivedReplay.length
    ? arrivedReplay[arrivedReplay.length - 1].clock
    : replayTimeline?.events?.[0]?.clock || '--:--'
  const replayProgress = replayTimeline?.duration_sec
    ? Math.min(100, Math.round((replayClockSec / replayTimeline.duration_sec) * 100))
    : 0


  const displayMapEvents = useMemo(
    () => (replayVisible ? replayVisible.slice(-650) : mapEvents),
    [replayVisible, mapEvents],
  )
  const queueEvents = replayVisible
    ? [...replayVisible].reverse().filter(e => e.severity_score >= 6).slice(0, 12)
    : priorityQueue

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark"><Radar size={20} /></div>
          <div>
            <h1>ASTraM Nexus</h1>
            <p>Event-driven congestion command center</p>
          </div>
        </div>

        <div className="mode-switch" role="tablist">
          {MODES.map(([key, label, Icon]) => (
            <button
              key={key}
              className={`mode-tab ${mode === key ? 'is-active' : ''}`}
              onClick={() => setMode(key)}
            >
              {mode === key && (
                <motion.span
                  layoutId="mode-indicator"
                  className="mode-indicator"
                  transition={{ type: 'spring', stiffness: 420, damping: 34 }}
                />
              )}
              <Icon size={15} />
              <span className="mode-tab-label">{label}</span>
            </button>
          ))}
        </div>

        <div className="topbar-metrics">
          <div>
            <strong>{stats?.total_events?.toLocaleString() || '--'}</strong>
            <span>historical incidents</span>
          </div>
          <div>
            <strong>{stats?.junctions_in_graph || '--'}</strong>
            <span>graph junctions</span>
          </div>
          <div>
            <strong>{stats?.spatial_edges || '--'}</strong>
            <span>proximity edges</span>
          </div>
        </div>

        <div className={`system-state system-state--${mapStatus}`}>
          <span />
          {mapStatus === 'connected' ? <Wifi size={14} /> : <WifiOff size={14} />}
          {mapStatus === 'connected' ? 'MapmyIndia credentials set (routing offline)' : 'Offline graph fallback'}
        </div>
      </header>

      {mode === 'analytics' ? (
        <main className="workspace workspace--forecast">
          <AnalyticsPanel events={events} causeColors={CAUSE_COLORS} />
        </main>
      ) : mode === 'allocate' ? (
        <main className="workspace workspace--forecast">
          <AllocationPanel />
        </main>
      ) : mode === 'forecast' ? (
        <main className="workspace workspace--forecast">
          <ForecastPanel />
        </main>
      ) : (
      <main className="workspace">
        <aside className="left-rail">
          <section className="brief-panel">
            <p className="eyebrow">Reactive workflow</p>
            <h2>Estimate the spillover, then issue a field order.</h2>
            <p>
              Pick an incident and run the three-agent pipeline: spatial spillover,
              historical evidence, and a prescriptive deployment plan — every number
              tagged with its data source and sample size.
            </p>
          </section>

          <section className="readiness-panel">
            <div className="section-heading">
              <span>Provenance &amp; validation</span>
              <small>auditable</small>
            </div>
            <div className="readiness-item">
              <strong>Source</strong>
              <span>Historical snapshot (Nov 2023 – Apr 2024) — not a live external feed</span>
            </div>
            <div className="readiness-item">
              <strong>Spatial</strong>
              <span>Proximity heuristic: impact = severity × exp(−λ·d) × time-weight</span>
            </div>
            <div className="readiness-item">
              <strong>Clearance</strong>
              <span>Empirical median prior as a band — held-out MAE 40.7 min, within ±15 min 26% of the time</span>
            </div>
            <div className="readiness-item">
              <strong>Model check</strong>
              <span>An HGBR was tested; it did not beat the median baseline on MAE, so we ship the auditable prior</span>
            </div>
            <div className="readiness-item">
              <strong>Routing / Learning</strong>
              <span>Metering anchors over the offline incident graph (approximate, not validated road routes); feedback is outcome logging (refines priors on re-train)</span>
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
              <span>{replayActive ? 'Live incident feed' : 'Incident queue'}</span>
              <small>{replayActive
                ? `${arrivedReplay?.length || 0} arrived`
                : `${filteredEvents.length.toLocaleString()} visible`}</small>
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
              {queueEvents.map(event => (
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
          <div className={`replay-bar ${replayActive ? 'is-active' : ''}`}>
            <div className="replay-bar-main">
              {!replayActive ? (
                <>
                  <button className="primary-action replay-start" onClick={startReplay} disabled={replayLoading}>
                    {replayLoading ? 'Loading replay…' : '▶ Start historical replay'}
                  </button>
                  <span className="replay-hint">
                    Replays the {`2024-03-07`} snapshot and auto-detects sudden incident surges — not a live feed.
                  </span>
                </>
              ) : (
                <>
                  <button className="secondary-action" onClick={() => setReplayPlaying(p => !p)}>
                    {replayPlaying ? '⏸ Pause' : '▶ Play'}
                  </button>
                  <button className="secondary-action" onClick={restartReplay}>↻ Restart</button>
                  <span className="replay-clock">{replayClock}</span>
                  <div className="replay-progress"><i style={{ width: `${replayProgress}%` }} /></div>
                  <div className="replay-speeds">
                    {[[30, '1×'], [60, '2×'], [180, '6×']].map(([v, l]) => (
                      <button
                        key={v}
                        className={`speed-chip ${replaySpeed === v ? 'is-active' : ''}`}
                        onClick={() => setReplaySpeed(v)}
                      >{l}</button>
                    ))}
                  </div>
                  <button className="ghost-action" onClick={exitReplay}>Exit</button>
                </>
              )}
            </div>
            {replayActive && (
              <div className="replay-meta">
                <span className="replay-label">{replayTimeline?.window_label || 'Historical replay — not a live external feed'}</span>
                <span className="replay-rule">Detector rule: {replayTimeline?.rule_text || '--'}</span>
                <span className="replay-count">
                  {arrivedReplay?.length || 0}/{replayTimeline?.total_events || 0} incidents · {surgeLog.length} surge{surgeLog.length === 1 ? '' : 's'} detected
                </span>
              </div>
            )}
          </div>

          <div className="map-toolbar">
            <div>
              <p className="eyebrow">Bengaluru operational graph</p>
              <h2>{selectedEvent ? formatCause(selectedEvent.event_cause) : 'Select an incident'}</h2>
            </div>
            <div className="map-toolbar-actions">
              <span className="provider-chip">
                {spatialResult?.model?.routing_provider || (mapStatus === 'connected' ? 'MapmyIndia ready' : 'Offline graph')}
              </span>
              <div className={`severity-pill severity-pill--${severityClass}`}>
                {currentSeverity} risk
              </div>
            </div>
          </div>

          <div className="map-canvas">
            {replayActive && activeAlert && (
              <div className="surge-banner">
                <div className="surge-banner-icon"><Siren size={22} /></div>
                <div className="surge-banner-body">
                  <strong>Surge detected — {formatCause(activeAlert.dominant_cause)} cluster</strong>
                  <span>
                    {activeAlert.n} high-severity incidents within {activeAlert.radius_km} km in {activeAlert.span_mins} min
                    · near {cleanValue(activeAlert.police_station)} · {activeAlert.fire_at_clock}
                  </span>
                </div>
                <button className="secondary-action" onClick={() => analyzeAnchor(activeAlert)} disabled={analyzing}>
                  {analyzing ? 'Analyzing…' : 'Analyze anchor'}
                </button>
                <button className="banner-dismiss" onClick={() => setActiveAlert(null)} aria-label="Dismiss">×</button>
              </div>
            )}
            <MapView
              events={displayMapEvents}
              selected={selectedEvent}
              epicenter={mapEpicenter}
              affected={topAffected}
              causeColors={CAUSE_COLORS}
              onSelect={handleSelectEvent}
            />

            <div className="map-legend">
              <span><i className="legend-dot incident" /> Incident density</span>
              <span><i className="legend-dot affected" /> Predicted spillover</span>
              <span><i className="legend-line" /> Spillover path (proximity)</span>
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
              <span>Modeled recovery</span>
              <strong>{savedMinutes ? `~${savedMinutes} min` : '--'}</strong>
            </div>
            <button className="primary-action" onClick={() => runAnalysis()} disabled={!selectedEvent || analyzing}>
              {analyzing
                ? <><Loader2 size={16} className="spin" />Running agents...</>
                : <><Play size={16} />{pipelineComplete ? 'Run again' : 'Run 3-agent forecast'}</>}
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

          {replayActive && surgeLog.length > 0 && (
            <section className="intel-panel surge-log-panel">
              <div className="section-heading">
                <span>Surge log</span>
                <small>{surgeLog.length} detected</small>
              </div>
              <p className="muted" style={{ marginTop: '-2px', marginBottom: '8px' }}>
                First surge auto-runs the 3-agent pipeline; click any other to analyze its anchor.
              </p>
              {surgeLog.slice(0, 8).map(a => (
                <button
                  key={`${a.anchor_event_id}:${a.fire_at_offset_sec}`}
                  className={`surge-log-item ${selectedEvent?.id === a.anchor_event_id ? 'is-active' : ''}`}
                  onClick={() => analyzeAnchor(a)}
                >
                  <span className="surge-time">{a.fire_at_clock}</span>
                  <span className="surge-desc">
                    <strong>{a.n}× {formatCause(a.dominant_cause)}</strong>
                    <small>near {cleanValue(a.police_station)} · sev {a.anchor_severity}</small>
                  </span>
                  <span className="surge-go">Analyze →</span>
                </button>
              ))}
            </section>
          )}

          <section className="agent-panel">
            <div className="section-heading">
              <span>Agent pipeline</span>
              <small>{pipelineComplete ? 'Complete' : analyzing ? 'In progress' : 'Ready'}</small>
            </div>

            <div className={`agent-row is-${agentStatuses.spatial}`}>
              <div>
                <strong>Spatial Propagation Engine</strong>
                <span>Distance-decay spillover heuristic over the junction graph (not causal inference).</span>
              </div>
              <StatusBadge status={agentStatuses.spatial} />
            </div>
            <div className={`agent-row is-${agentStatuses.rag}`}>
              <div>
                <strong>RAG Intelligence Core</strong>
                <span>Finds similar incidents and clearance patterns.</span>
              </div>
              <StatusBadge status={agentStatuses.rag} />
            </div>
            <div className={`agent-row is-${agentStatuses.command}`}>
              <div>
                <strong>Command Synthesizer</strong>
                <span>Turns evidence into deployment instructions.</span>
              </div>
              <StatusBadge status={agentStatuses.command} />
            </div>
          </section>

          {hasEvidence && (
            <section className="confidence-panel">
              <div className="section-heading">
                <span>Evidence audit</span>
                <small>provenance</small>
              </div>
              <div className="audit-list">
                <div>
                  <b>Spatial evidence</b>
                  <span>{spatialResult.blast_radius.total_affected_junctions} affected junctions, {spatialResult.blast_radius.critical_junctions} critical (proximity heuristic).</span>
                </div>
                <div>
                  <b>Historical evidence</b>
                  <span>{ragResult.pattern_analysis?.total_similar_events_found || 0} similar incidents retrieved (TF-IDF + metadata).</span>
                </div>
                <div>
                  <b>Modeled action</b>
                  <span>{unitCount} units; modeled recovery ≈ {savedMinutes} min (heuristic, not a measured effect).</span>
                </div>
              </div>
            </section>
          )}

          {commandText && (
            <section className="command-panel command-panel--featured" ref={commandRef}>
              <div className="section-heading">
                <span>Operational command</span>
                <button
                  className="copy-command"
                  onClick={() => navigator.clipboard?.writeText(commandText)}
                  type="button"
                >
                  <Copy size={12} />Copy order
                </button>
              </div>
              <div className="command-body">
                <ReactMarkdown>{commandText}</ReactMarkdown>
              </div>
            </section>
          )}

          {spatialResult && (
            <section className="intel-panel">
              <div className="section-heading">
                <span>Blast radius</span>
                <small>{spatialResult.blast_radius.critical_junctions} critical</small>
              </div>
              {spatialResult.model?.note && (
                <p className="muted" style={{ marginTop: '-2px', marginBottom: '8px' }}>
                  {spatialResult.model.note}
                </p>
              )}
              {topAffected.map(node => {
                const impact = Math.round(node.relative_impact_score * 100)
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
                <span>Counterfactual (modeled)</span>
                <small>heuristic</small>
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
                Modeled recovery ≈ {spatialResult.counterfactual.time_saved_mins} min faster with {unitCount} units.
              </div>
              <p className="muted" style={{ marginTop: '4px' }}>
                Traffic-recovery estimate after the event ends — not the event duration. The
                intervention effect is assumed, not measured (no controlled trials in the data).
              </p>
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
                  <span>Median clearance</span>
                  <strong>{ragResult.pattern_analysis?.median_clearance_time_mins ?? '--'} min</strong>
                </div>
                <div>
                  <span>Same corridor</span>
                  <strong>{ragResult.match_context?.same_corridor_matches || 0}</strong>
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
        </aside>
      </main>
      )}
    </div>
  )
}

export default App
