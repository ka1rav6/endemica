import { describeError } from '@/lib/errors';

interface Props {
  error: unknown;
  onRetry?: () => void;
  context?: string;
}

export function ErrorNotice({ error, onRetry, context }: Props) {
  return (
    <div className="error" role="alert">
      <p style={{ margin: '0 0 6px' }}>{describeError(error, context)}</p>
      {onRetry && (
        <button type="button" className="button" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
