import type { ResponseWarning } from '@/types/api';

export function Warnings({ warnings }: { warnings: ResponseWarning[] }) {
  if (warnings.length === 0) return null;
  const order = { important: 0, caution: 1, info: 2 } as const;
  const sorted = [...warnings].sort((a, b) => order[a.severity] - order[b.severity]);
  return (
    <ul className="list" aria-label="Caveats for these numbers">
      {sorted.map((warning, index) => (
        <li key={`${warning.code}-${index}`} className={`warning warning--${warning.severity}`}>
          <strong
            style={{
              flex: 'none',
              textTransform: 'uppercase',
              fontSize: 10,
              letterSpacing: '0.05em',
            }}
          >
            {warning.severity}
          </strong>
          <span>{warning.message}</span>
        </li>
      ))}
    </ul>
  );
}
