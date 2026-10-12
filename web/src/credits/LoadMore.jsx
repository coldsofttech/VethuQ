import { Button, Spinner } from '@fluentui/react-components';
import { useEffect, useRef } from 'react';

/** The end of a list: loads the next page when it scrolls into view (or when pressed). */
export function LoadMore({ more, loading, onMore }) {
  const node = useRef(null);
  useEffect(() => {
    if (!node.current || !more || typeof IntersectionObserver === 'undefined') return undefined;
    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && !loading) onMore();
    });
    observer.observe(node.current);
    return () => observer.disconnect();
  }, [more, loading, onMore]);
  return (
    <div ref={node}>
      {loading && <Spinner size="small" label="Loading" />}
      {!loading && more && <Button onClick={onMore}>Load more</Button>}
    </div>
  );
}
