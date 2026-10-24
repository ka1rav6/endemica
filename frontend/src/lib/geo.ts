export interface Point {
  lat: number;
  lon: number;
}

const EARTH_RADIUS_KM = 6371.0088;

function toRadians(degrees: number): number {
  return (degrees * Math.PI) / 180;
}

function toDegrees(radians: number): number {
  return (radians * 180) / Math.PI;
}

export function greatCircleKm(a: Point, b: Point): number {
  const phi1 = toRadians(a.lat);
  const phi2 = toRadians(b.lat);
  const dPhi = phi2 - phi1;
  const dLambda = toRadians(b.lon - a.lon);
  const h = Math.sin(dPhi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLambda / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(Math.min(1, h)));
}

export function interpolateGreatCircle(a: Point, b: Point, fraction: number): Point {
  const phi1 = toRadians(a.lat);
  const lambda1 = toRadians(a.lon);
  const phi2 = toRadians(b.lat);
  const lambda2 = toRadians(b.lon);

  const delta =
    2 *
    Math.asin(
      Math.sqrt(
        Math.min(
          1,
          Math.sin((phi2 - phi1) / 2) ** 2 +
            Math.cos(phi1) * Math.cos(phi2) * Math.sin((lambda2 - lambda1) / 2) ** 2,
        ),
      ),
    );

  if (delta === 0) return { lat: a.lat, lon: a.lon };

  const A = Math.sin((1 - fraction) * delta) / Math.sin(delta);
  const B = Math.sin(fraction * delta) / Math.sin(delta);
  const x = A * Math.cos(phi1) * Math.cos(lambda1) + B * Math.cos(phi2) * Math.cos(lambda2);
  const y = A * Math.cos(phi1) * Math.sin(lambda1) + B * Math.cos(phi2) * Math.sin(lambda2);
  const z = A * Math.sin(phi1) + B * Math.sin(phi2);

  return {
    lat: toDegrees(Math.atan2(z, Math.sqrt(x * x + y * y))),
    lon: toDegrees(Math.atan2(y, x)),
  };
}

export function greatCircleLine(a: Point, b: Point, steps = 48): [number, number][] {
  const points: [number, number][] = [];
  let previousLon: number | null = null;
  let offset = 0;

  for (let i = 0; i <= steps; i += 1) {
    const point = interpolateGreatCircle(a, b, i / steps);
    let lon = point.lon + offset;
    if (previousLon !== null) {
      // Keep longitudes continuous so a path crossing the antimeridian is not
      // drawn as a line straight across the whole map.
      if (lon - previousLon > 180) {
        offset -= 360;
        lon -= 360;
      } else if (lon - previousLon < -180) {
        offset += 360;
        lon += 360;
      }
    }
    previousLon = lon;
    points.push([lon, point.lat]);
  }
  return points;
}
