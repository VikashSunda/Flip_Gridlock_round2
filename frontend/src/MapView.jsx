import { memo, useEffect, useMemo } from 'react'
import { MapContainer, TileLayer, CircleMarker, Marker, Polyline, Tooltip, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const BLR_CENTER = [12.9716, 77.5946]

const epicenterIcon = L.divIcon({
  className: 'mk-wrap',
  html: '<div class="mk mk-epicenter"></div>',
  iconSize: [18, 18],
  iconAnchor: [9, 9],
})

function buildAffectedIcon(impact, delayMs) {
  const size = Math.round(40 + impact / 3)
  return L.divIcon({
    className: 'mk-wrap',
    html: `<div class="mk mk-affected" style="width:${size}px;height:${size}px;--impact-delay:${delayMs}ms">${impact}%</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  })
}

function FlyToFocus({ lat, lon, zoom }) {
  const map = useMap()
  useEffect(() => {
    if (lat != null && lon != null) map.flyTo([lat, lon], zoom, { duration: 0.8 })
  }, [lat, lon, zoom, map])
  return null
}

function InvalidateOnMount() {
  const map = useMap()
  useEffect(() => {
    const t = setTimeout(() => map.invalidateSize(), 60)
    return () => clearTimeout(t)
  }, [map])
  return null
}

function MapView({ events, selected, epicenter, affected, causeColors, onSelect }) {
  const epi = epicenter
    ? [epicenter.latitude, epicenter.longitude]
    : selected
      ? [Number(selected.latitude), Number(selected.longitude)]
      : null

  const lineRenderer = useMemo(() => L.svg({ padding: 0.5 }), [])

  const affectedIcons = useMemo(
    () => affected.map((node, i) =>
      buildAffectedIcon(Math.round((node.relative_impact_score || 0) * 100), i * 120),
    ),
    [affected],
  )

  return (
    <MapContainer
      center={BLR_CENTER}
      zoom={11}
      preferCanvas
      zoomControl
      scrollWheelZoom
      className="map-leaflet"
    >
      <TileLayer
        url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
        subdomains="abcd"
        maxZoom={19}
      />

      {events.map((ev) => {
        const isSel = selected?.id === ev.id
        const color = causeColors[ev.event_cause] || '#64748b'
        const r = Math.max(4, Math.min(9, (ev.severity_score || 4) * 0.7 + 2))
        return (
          <CircleMarker
            key={ev.id}
            center={[Number(ev.latitude), Number(ev.longitude)]}
            radius={isSel ? r + 3 : r}
            pathOptions={{
              color: isSel ? '#5eead4' : 'rgba(255,255,255,0.35)',
              weight: isSel ? 2.5 : 1,
              fillColor: color,
              fillOpacity: isSel ? 0.95 : 0.82,
            }}
            eventHandlers={{ click: () => onSelect(ev) }}
          />
        )
      })}

      {epi && affected.map((node) => (
        <Polyline
          key={`line-${node.junction}`}
          positions={[epi, [node.latitude, node.longitude]]}
          pathOptions={{
            color: '#f87171',
            weight: 1.5,
            opacity: 0.65,
            dashArray: '5 6',
            className: 'spill-line',
            renderer: lineRenderer,
          }}
        />
      ))}

      {affected.map((node, i) => (
        <Marker
          key={`aff-${node.junction}`}
          position={[node.latitude, node.longitude]}
          icon={affectedIcons[i]}
          interactive={false}
          keyboard={false}
        />
      ))}

      {epi && (
        <Marker position={epi} icon={epicenterIcon} interactive={false} keyboard={false} zIndexOffset={1000}>
          <Tooltip permanent direction="right" offset={[12, 0]} className="mk-tip">
            {epicenter?.label || (selected ? 'Live event' : 'Epicenter')}
          </Tooltip>
        </Marker>
      )}

      <FlyToFocus lat={epi?.[0] ?? null} lon={epi?.[1] ?? null} zoom={epi ? 13 : 11} />
      <InvalidateOnMount />
    </MapContainer>
  )
}

export default memo(MapView)
