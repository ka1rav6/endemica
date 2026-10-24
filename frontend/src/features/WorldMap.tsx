import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AttributionControl,
  GeoJSONSource,
  Map as MapLibreMap,
  NavigationControl,
  Popup,
  type ExpressionSpecification,
  type MapLayerMouseEvent,
} from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { Feature, FeatureCollection, LineString, Point as GeoPoint } from 'geojson';
import type { Country, OriginContribution, Route } from '@/types/api';
import { greatCircleLine } from '@/lib/geo';
import { formatPassengers } from '@/lib/format';

const BOUNDARIES_URL = '/data/country_boundaries.geojson';

const COLOURS = {
  land: '#1b2733',
  landOutbreak: '#f87171',
  landSelected: '#2dd4bf',
  outline: '#2c3b4b',
  arcObserved: '#2dd4bf',
  arcEstimated: '#60a5fa',
  water: '#080d13',
} as const;

interface Props {
  countries: Country[];
  selectedIso3: string | null;
  onSelect: (iso3: string) => void;
  origins: OriginContribution[];
  routes: Route[];
}

interface BoundaryCollection {
  type: 'FeatureCollection';
  features: {
    type: 'Feature';
    id?: string;
    properties: Record<string, unknown>;
    geometry: unknown;
  }[];
}

function arcFeatures(
  routes: Route[],
  origins: OriginContribution[],
): FeatureCollection<LineString> {
  const rateByOrigin = new Map(origins.map((o) => [o.origin_iso3, o]));
  const maxRate = Math.max(...origins.map((o) => o.arrival_rate_per_day), Number.EPSILON);

  const features: Feature<LineString>[] = [];
  for (const route of routes) {
    const { origin_lat: oLat, origin_lon: oLon, dest_lat: dLat, dest_lon: dLon } = route;
    if (oLat === null || oLon === null || dLat === null || dLon === null) continue;
    const contribution = rateByOrigin.get(route.origin_iso3);
    const share = contribution ? contribution.arrival_rate_per_day / maxRate : 0;
    features.push({
      type: 'Feature',
      properties: {
        origin: route.origin_iso3,
        originName: route.origin_name,
        dest: route.dest_iso3,
        destName: route.dest_name,
        passengers: route.passengers_per_day,
        valueType: route.value_type,
        source: route.source,
        width: 1 + share * 4,
        opacity: 0.35 + share * 0.5,
      },
      geometry: {
        type: 'LineString',
        coordinates: greatCircleLine({ lat: oLat, lon: oLon }, { lat: dLat, lon: dLon }),
      },
    });
  }

  return { type: 'FeatureCollection', features };
}

function outbreakFeatures(countries: Country[]): FeatureCollection<GeoPoint> {
  const features: Feature<GeoPoint>[] = [];
  for (const country of countries) {
    const { centroid_lat: lat, centroid_lon: lon } = country;
    if (!country.has_reported_outbreak || lat === null || lon === null) continue;
    features.push({
      type: 'Feature',
      properties: { iso3: country.iso3, name: country.name },
      geometry: { type: 'Point', coordinates: [lon, lat] },
    });
  }
  return { type: 'FeatureCollection', features };
}

export function WorldMap({ countries, selectedIso3, onSelect, origins, routes }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);
  const [boundaryError, setBoundaryError] = useState<string | null>(null);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;

  const outbreakIso3 = useMemo(
    () => countries.filter((c) => c.has_reported_outbreak).map((c) => c.iso3),
    [countries],
  );

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new MapLibreMap({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {},
        layers: [
          { id: 'background', type: 'background', paint: { 'background-color': COLOURS.water } },
        ],
      },
      center: [12, 22],
      zoom: 1.45,
      minZoom: 0.8,
      maxZoom: 7,
      attributionControl: false,
      renderWorldCopies: true,
    });
    mapRef.current = map;

    map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
    map.addControl(
      new AttributionControl({
        compact: true,
        customAttribution:
          'Boundaries: Natural Earth (public domain). Arcs are computed great-circle paths between country centroids, not flight tracks.',
      }),
      'bottom-right',
    );

    map.on('load', () => {
      void (async () => {
        try {
          const response = await fetch(BOUNDARIES_URL);
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const data = (await response.json()) as BoundaryCollection;

          map.addSource('countries', { type: 'geojson', data: data as never, promoteId: 'iso3' });
          map.addLayer({
            id: 'country-fill',
            type: 'fill',
            source: 'countries',
            paint: { 'fill-color': COLOURS.land, 'fill-opacity': 0.92 },
          });
          map.addLayer({
            id: 'country-outline',
            type: 'line',
            source: 'countries',
            paint: { 'line-color': COLOURS.outline, 'line-width': 0.5 },
          });
          map.addLayer({
            id: 'country-selected',
            type: 'line',
            source: 'countries',
            paint: { 'line-color': COLOURS.landSelected, 'line-width': 2 },
            filter: ['==', ['get', 'iso3'], ''],
          });

          map.addSource('arcs', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] },
          });
          map.addLayer({
            id: 'arc-lines',
            type: 'line',
            source: 'arcs',
            layout: { 'line-cap': 'round' },
            paint: {
              'line-color': [
                'match',
                ['get', 'valueType'],
                'observed',
                COLOURS.arcObserved,
                COLOURS.arcEstimated,
              ] as ExpressionSpecification,
              'line-width': ['get', 'width'] as ExpressionSpecification,
              'line-opacity': ['get', 'opacity'] as ExpressionSpecification,
              'line-dasharray': [
                'match',
                ['get', 'valueType'],
                'observed',
                ['literal', [1, 0]],
                ['literal', [2, 1.5]],
              ] as ExpressionSpecification,
            },
          });

          map.addSource('outbreaks', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] },
          });
          map.addLayer({
            id: 'outbreak-points',
            type: 'circle',
            source: 'outbreaks',
            paint: {
              'circle-radius': 5,
              'circle-color': COLOURS.landOutbreak,
              'circle-stroke-width': 1.5,
              'circle-stroke-color': '#0b1118',
            },
          });

          setReady(true);
        } catch (cause) {
          setBoundaryError(
            cause instanceof Error
              ? `Country boundaries could not be loaded (${cause.message}). Run \`just data-build\` to generate them.`
              : 'Country boundaries could not be loaded.',
          );
        }
      })();
    });

    map.on('click', 'country-fill', (event: MapLayerMouseEvent) => {
      const properties: unknown = event.features?.[0]?.properties;
      if (typeof properties !== 'object' || properties === null) return;
      const iso3: unknown = (properties as Record<string, unknown>)['iso3'];
      if (typeof iso3 === 'string' && iso3) selectRef.current(iso3);
    });

    map.on('mouseenter', 'country-fill', () => {
      map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mouseleave', 'country-fill', () => {
      map.getCanvas().style.cursor = '';
    });

    const popup = new Popup({ closeButton: false, closeOnClick: false, offset: 10 });
    map.on('mousemove', 'arc-lines', (event: MapLayerMouseEvent) => {
      const props = event.features?.[0]?.properties;
      if (!props) return;
      const valueType = String(props['valueType']);
      popup
        .setLngLat(event.lngLat)
        .setHTML(
          `<strong>${String(props['originName'])} → ${String(props['destName'])}</strong><br />` +
            `${formatPassengers(Number(props['passengers']))} · ${valueType}<br />` +
            `<span style="color:#6c8299">source: ${String(props['source'])}</span>`,
        )
        .addTo(map);
    });
    map.on('mouseleave', 'arc-lines', () => {
      popup.remove();
    });

    return () => {
      popup.remove();
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    map.setPaintProperty('country-fill', 'fill-color', [
      'case',
      ['==', ['get', 'iso3'], selectedIso3 ?? ''],
      COLOURS.landSelected,
      ['in', ['get', 'iso3'], ['literal', outbreakIso3]],
      COLOURS.landOutbreak,
      COLOURS.land,
    ] as ExpressionSpecification);
    map.setFilter('country-selected', ['==', ['get', 'iso3'], selectedIso3 ?? '']);
  }, [ready, selectedIso3, outbreakIso3]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const source = map.getSource('arcs');
    if (source instanceof GeoJSONSource) void source.setData(arcFeatures(routes, origins));
  }, [ready, routes, origins]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const source = map.getSource('outbreaks');
    if (source instanceof GeoJSONSource) void source.setData(outbreakFeatures(countries));
  }, [ready, countries]);

  return (
    <div className="map">
      <div className="map__canvas" ref={containerRef} data-testid="map-canvas" />
      {boundaryError && (
        <div className="map__status">
          <div>
            <p style={{ maxWidth: 420 }}>{boundaryError}</p>
            <p style={{ color: 'var(--text-faint)', fontSize: 12 }}>
              The country list and all risk estimates still work without the map.
            </p>
          </div>
        </div>
      )}
      <div className="map__overlay">
        <div className="legend">
          <span className="legend__item">
            <span className="badge badge--unknown" style={{ color: COLOURS.landOutbreak }}>
              <span className="badge__dot" aria-hidden="true" />
              Reported outbreak
            </span>
          </span>
          <span className="legend__item">
            <span className="badge badge--observed badge--bar">
              <span className="badge__dot" aria-hidden="true" />
              Observed passengers
            </span>
          </span>
          <span className="legend__item">
            <span className="badge badge--estimated badge--bar">
              <span className="badge__dot" aria-hidden="true" />
              Modelled passengers
            </span>
          </span>
        </div>
        <p style={{ margin: '7px 0 0', fontSize: 11, color: 'var(--text-faint)' }}>
          Arc thickness is each origin&apos;s share of the modelled arrival rate. Arcs are
          great-circle paths between country centroids — they are not flight tracks.
        </p>
      </div>
    </div>
  );
}
