import { useMemo } from 'react'
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar, Cell,
  PieChart, Pie, Legend, XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts'
import { BarChart3, Clock, Layers, Route, AlertTriangle, Gauge, Activity, CalendarClock } from 'lucide-react'

function fmtCause(c = '') {
  return c.replace(/_/g, ' ').replace(/\b\w/g, m => m.toUpperCase())
}

const sevColor = s => (s >= 8 ? '#f87171' : s >= 6 ? '#fbbf24' : s >= 4 ? '#60a5fa' : '#34d399')

const TOOLTIP = {
  contentStyle: {
    background: 'rgba(10, 16, 28, 0.96)',
    border: '1px solid rgba(255, 255, 255, 0.14)',
    borderRadius: 8,
    boxShadow: '0 18px 44px rgba(0,0,0,0.5)',
    fontSize: 12,
  },
  labelStyle: { color: '#8597b4', fontWeight: 700, marginBottom: 2 },
  itemStyle: { color: '#eaf1fb' },
  cursor: { fill: 'rgba(255, 255, 255, 0.05)' },
}

const AXIS_TICK = { fill: '#8597b4', fontSize: 11 }
const GRID = 'rgba(255, 255, 255, 0.06)'

export default function AnalyticsPanel({ events, causeColors }) {
  const byHour = useMemo(() => {
    const buckets = Array.from({ length: 24 }, (_, h) => ({
      label: String(h).padStart(2, '0'),
      count: 0,
    }))
    for (const e of events) {
      const dt = e.start_datetime
      if (!dt) continue
      const timePart = dt.replace('T', ' ').split(' ')[1]
      if (!timePart) continue
      const h = parseInt(timePart.slice(0, 2), 10)
      if (h >= 0 && h < 24) buckets[h].count++
    }
    return buckets
  }, [events])

  const byCause = useMemo(() => {
    const m = {}
    for (const e of events) {
      const c = e.event_cause || 'others'
      m[c] = (m[c] || 0) + 1
    }
    return Object.entries(m)
      .map(([cause, count]) => ({ cause, name: fmtCause(cause), count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 12)
  }, [events])

  const clearance = useMemo(() => {
    const edges = [0, 30, 60, 90, 120, 180, 360, Infinity]
    const labels = ['0–30', '30–60', '60–90', '90–120', '120–180', '180–360', '360+']
    const bins = labels.map(label => ({ label, count: 0 }))
    const vals = []
    for (const e of events) {
      const c = e.clearance_time_mins
      if (c == null || Number.isNaN(c) || c < 0) continue
      vals.push(c)
      for (let i = 0; i < edges.length - 1; i++) {
        if (c >= edges[i] && c < edges[i + 1]) { bins[i].count++; break }
      }
    }
    vals.sort((a, b) => a - b)
    const n = vals.length
    const median = n ? Math.round(vals[Math.floor(n / 2)]) : 0
    const mean = n ? Math.round(vals.reduce((s, v) => s + v, 0) / n) : 0
    return { bins, n, median, mean }
  }, [events])

  const byCorridor = useMemo(() => {
    const m = {}
    for (const e of events) {
      const c = e.corridor
      if (!c || c === 'Non-corridor' || c === 'NULL') continue
      m[c] = (m[c] || 0) + 1
    }
    return Object.entries(m)
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8)
  }, [events])

  const clearanceByCause = useMemo(() => {
    const groups = {}
    for (const e of events) {
      const c = e.clearance_time_mins
      if (c == null || Number.isNaN(c) || c < 0) continue
      const cause = e.event_cause || 'others'
      ;(groups[cause] ||= []).push(c)
    }
    return Object.entries(groups)
      .map(([cause, arr]) => {
        arr.sort((a, b) => a - b)
        return { cause, name: fmtCause(cause), median: Math.round(arr[Math.floor(arr.length / 2)]), n: arr.length }
      })
      .filter(d => d.n >= 5)
      .sort((a, b) => b.median - a.median)
      .slice(0, 10)
  }, [events])

  const severityDist = useMemo(() => {
    const counts = Array.from({ length: 10 }, (_, i) => ({ score: i + 1, count: 0 }))
    for (const e of events) {
      const s = e.severity_score
      if (s >= 1 && s <= 10) counts[s - 1].count++
    }
    return counts
  }, [events])

  const statusDist = useMemo(() => {
    const m = {}
    for (const e of events) { const s = e.status || 'unknown'; m[s] = (m[s] || 0) + 1 }
    const colors = { active: '#fbbf24', resolved: '#34d399', closed: '#5f7191' }
    const order = ['active', 'resolved', 'closed']
    return order
      .filter(k => m[k])
      .map(k => ({ name: k[0].toUpperCase() + k.slice(1), value: m[k], color: colors[k] }))
      .concat(
        Object.keys(m).filter(k => !order.includes(k))
          .map(k => ({ name: fmtCause(k), value: m[k], color: '#64748b' })),
      )
  }, [events])

  const heatmap = useMemo(() => {
    const dayOrder = [1, 2, 3, 4, 5, 6, 0]
    const dayLabels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    const grid = {}
    let max = 0
    for (const e of events) {
      const dt = e.start_datetime
      if (!dt) continue
      const [datePart, timePart] = dt.replace('T', ' ').split(' ')
      if (!datePart || !timePart) continue
      const [y, mo, d] = datePart.split('-').map(Number)
      if (!y || !mo || !d) continue
      const day = new Date(Date.UTC(y, mo - 1, d)).getUTCDay()
      const hour = parseInt(timePart.slice(0, 2), 10)
      if (hour < 0 || hour > 23) continue
      const key = `${day}-${hour}`
      grid[key] = (grid[key] || 0) + 1
      if (grid[key] > max) max = grid[key]
    }
    return { grid, max, dayOrder, dayLabels }
  }, [events])

  const kpis = useMemo(() => {
    let planned = 0, high = 0
    const corridors = new Set()
    for (const e of events) {
      if (e.event_type === 'planned') planned++
      if (e.priority === 'High') high++
      if (e.corridor && e.corridor !== 'Non-corridor' && e.corridor !== 'NULL') corridors.add(e.corridor)
    }
    return { total: events.length, planned, unplanned: events.length - planned, high, corridors: corridors.size }
  }, [events])

  return (
    <div className="analytics-wrap">
      <section className="brief-panel analytics-intro">
        <p className="eyebrow">Situational analytics</p>
        <h2>Dataset overview</h2>
        <p>
          Computed live in-browser from the {kpis.total.toLocaleString()} loaded incidents
          (Bengaluru, Nov 2023 – Apr 2024 snapshot). Descriptive only — no model inference here.
        </p>
      </section>

      <div className="forecast-kpis">
        <div className="kpi">
          <span>Total incidents</span>
          <strong>{kpis.total.toLocaleString()}</strong>
          <em>{kpis.high.toLocaleString()} high-priority</em>
        </div>
        <div className="kpi">
          <span>Planned / Unplanned</span>
          <strong>{kpis.planned} / {kpis.unplanned.toLocaleString()}</strong>
          <em>{kpis.total ? Math.round((kpis.planned / kpis.total) * 100) : 0}% planned</em>
        </div>
        <div className="kpi">
          <span>Median clearance</span>
          <strong>{clearance.median} min</strong>
          <em>mean {clearance.mean} min · n={clearance.n.toLocaleString()}</em>
        </div>
        <div className="kpi kpi--accent">
          <span>Corridors tracked</span>
          <strong>{kpis.corridors}</strong>
          <em>top {byCorridor.length} shown below</em>
        </div>
      </div>

      <div className="analytics-grid">

        <div className="forecast-card chart-card">
          <div className="section-heading">
            <span><Clock size={14} />Incidents by hour</span>
            <small>UTC (+00)</small>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={byHour} margin={{ top: 8, right: 10, left: -16, bottom: 0 }}>
              <defs>
                <linearGradient id="grad-hour" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#2dd4bf" stopOpacity={0.75} />
                  <stop offset="100%" stopColor="#2dd4bf" stopOpacity={0.04} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
              <XAxis dataKey="label" tick={AXIS_TICK} interval={2} axisLine={{ stroke: GRID }} tickLine={false} />
              <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} width={34} />
              <Tooltip {...TOOLTIP} />
              <Area type="monotone" dataKey="count" name="Incidents" stroke="#2dd4bf" strokeWidth={2} fill="url(#grad-hour)" />
            </AreaChart>
          </ResponsiveContainer>
          <p className="muted">Hour-of-day pattern of incident starts. Timestamps are stamped UTC; IST ≈ UTC + 5:30.</p>
        </div>

        <div className="forecast-card chart-card">
          <div className="section-heading">
            <span><Clock size={14} />Clearance-time spread</span>
            <small>minutes</small>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={clearance.bins} margin={{ top: 8, right: 10, left: -16, bottom: 0 }}>
              <defs>
                <linearGradient id="grad-clear" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#fbbf24" stopOpacity={0.95} />
                  <stop offset="100%" stopColor="#f87171" stopOpacity={0.9} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
              <XAxis dataKey="label" tick={{ fill: '#8597b4', fontSize: 10 }} axisLine={{ stroke: GRID }} tickLine={false} />
              <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} width={34} />
              <Tooltip {...TOOLTIP} />
              <Bar dataKey="count" name="Incidents" radius={[4, 4, 0, 0]} fill="url(#grad-clear)" />
            </BarChart>
          </ResponsiveContainer>
          <p className="muted">
            Median {clearance.median} min vs mean {clearance.mean} min — a heavy right tail. The median
            is a hard baseline; this variance is why clearance is shown as a band, not a point.
          </p>
        </div>

        <div className="forecast-card chart-card">
          <div className="section-heading">
            <span><Layers size={14} />Incidents by cause</span>
            <small>top {byCause.length}</small>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={byCause} layout="vertical" margin={{ top: 4, right: 16, left: 6, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} horizontal={false} />
              <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} />
              <YAxis type="category" dataKey="name" width={104} tick={{ fill: '#c6d3e7', fontSize: 10 }} axisLine={false} tickLine={false} />
              <Tooltip {...TOOLTIP} />
              <Bar dataKey="count" name="Incidents" radius={[0, 4, 4, 0]}>
                {byCause.map(d => <Cell key={d.cause} fill={causeColors[d.cause] || '#64748b'} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <p className="muted">Vehicle breakdowns dominate the mix — the dataset skews to highway/truck incidents.</p>
        </div>

        <div className="forecast-card chart-card">
          <div className="section-heading">
            <span><Route size={14} />Top corridors</span>
            <small>by incident count</small>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={byCorridor} layout="vertical" margin={{ top: 4, right: 16, left: 6, bottom: 0 }}>
              <defs>
                <linearGradient id="grad-corr" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.95} />
                  <stop offset="100%" stopColor="#2dd4bf" stopOpacity={0.85} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} horizontal={false} />
              <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} />
              <YAxis type="category" dataKey="name" width={104} tick={{ fill: '#c6d3e7', fontSize: 10 }} axisLine={false} tickLine={false} />
              <Tooltip {...TOOLTIP} />
              <Bar dataKey="count" name="Incidents" radius={[0, 4, 4, 0]} fill="url(#grad-corr)" />
            </BarChart>
          </ResponsiveContainer>
          <p className="muted">Where load concentrates — the corridors to pre-stage manpower and barricading on.</p>
        </div>

        <div className="forecast-card chart-card chart-card--wide">
          <div className="section-heading">
            <span><Gauge size={14} />Median clearance by cause</span>
            <small>n ≥ 5 · minutes</small>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={clearanceByCause} layout="vertical" margin={{ top: 4, right: 24, left: 6, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} horizontal={false} />
              <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} />
              <YAxis type="category" dataKey="name" width={120} tick={{ fill: '#c6d3e7', fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip {...TOOLTIP} formatter={(v, _n, p) => [`${v} min (n=${p.payload.n})`, 'Median']} />
              <Bar dataKey="median" name="Median" radius={[0, 4, 4, 0]}>
                {clearanceByCause.map(d => <Cell key={d.cause} fill={causeColors[d.cause] || '#64748b'} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <p className="muted">
            Some causes clear predictably (vehicle breakdown), others are high-variance (water logging) —
            this is exactly where the clearance model is strong vs weak, shown honestly.
          </p>
        </div>

        <div className="forecast-card chart-card">
          <div className="section-heading">
            <span><BarChart3 size={14} />Severity distribution</span>
            <small>score 1–10</small>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={severityDist} margin={{ top: 8, right: 10, left: -16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
              <XAxis dataKey="score" tick={AXIS_TICK} axisLine={{ stroke: GRID }} tickLine={false} />
              <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} width={40} />
              <Tooltip {...TOOLTIP} />
              <Bar dataKey="count" name="Incidents" radius={[4, 4, 0, 0]}>
                {severityDist.map(d => <Cell key={d.score} fill={sevColor(d.score)} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <p className="muted">How risk is distributed — the high/critical tail (score ≥ 6) is where deployment focus goes.</p>
        </div>

        <div className="forecast-card chart-card">
          <div className="section-heading">
            <span><Activity size={14} />Incident status</span>
            <small>{kpis.total.toLocaleString()} total</small>
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie data={statusDist} dataKey="value" nameKey="name" innerRadius={50} outerRadius={82} paddingAngle={2} stroke="none">
                {statusDist.map(d => <Cell key={d.name} fill={d.color} />)}
              </Pie>
              <Tooltip {...TOOLTIP} />
              <Legend verticalAlign="bottom" height={28} formatter={value => <span style={{ color: '#c6d3e7', fontSize: 11 }}>{value}</span>} />
            </PieChart>
          </ResponsiveContainer>
          <p className="muted">Resolved/closed are historical; “active” reflects rows still open in the snapshot — not a live feed.</p>
        </div>

        <div className="forecast-card chart-card chart-card--wide">
          <div className="section-heading">
            <span><CalendarClock size={14} />When incidents happen</span>
            <small>day × hour (UTC)</small>
          </div>
          <div className="heatmap">
            <div className="heatmap-hours">
              <span />
              {Array.from({ length: 24 }, (_, h) => (
                <span key={h} className="heatmap-hourlabel">{h % 3 === 0 ? String(h).padStart(2, '0') : ''}</span>
              ))}
            </div>
            {heatmap.dayOrder.map((day, i) => (
              <div key={day} className="heatmap-row">
                <span className="heatmap-daylabel">{heatmap.dayLabels[i]}</span>
                {Array.from({ length: 24 }, (_, h) => {
                  const c = heatmap.grid[`${day}-${h}`] || 0
                  const intensity = heatmap.max ? c / heatmap.max : 0
                  return (
                    <span
                      key={h}
                      className="heatmap-cell"
                      style={{ background: `rgba(45,212,191,${(0.04 + intensity * 0.85).toFixed(3)})` }}
                      title={`${heatmap.dayLabels[i]} ${String(h).padStart(2, '0')}:00 UTC · ${c} incidents`}
                    />
                  )
                })}
              </div>
            ))}
          </div>
          <p className="muted">Brighter = more incidents. Hours are local IST. Reads as staffing windows.</p>
        </div>
      </div>

      <section className="forecast-card analytics-note">
        <div className="section-heading"><span><AlertTriangle size={14} />How to read this</span><small>honesty note</small></div>
        <p className="muted">
          These are descriptive distributions of the historical snapshot, not predictions. They frame
          where and when incidents cluster so the forecast and allocation views can be read in context.
        </p>
      </section>
    </div>
  )
}
