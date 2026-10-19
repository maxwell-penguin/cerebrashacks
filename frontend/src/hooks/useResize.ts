import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Hook for a drag-resizable pane dimension.
 *
 * @param initial Starting size in px.
 * @param min Smallest allowed size.
 * @param max Largest allowed size.
 * @param axis 'x' resizes horizontally, 'y' vertically.
 * @param invert Flip the drag direction, for handles on the opposite edge.
 * @returns `{ value, setValue, handleProps }`; spread `handleProps` onto the drag handle element.
 */
export function useResize(
  initial: number,
  min: number,
  max: number,
  axis: 'x' | 'y' = 'x',
  invert = false,
) {
  const [value, setValue] = useState(initial);
  const dragging = useRef(false);
  const startPos = useRef(0);
  const startValue = useRef(initial);

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragging.current = true;
      startPos.current = axis === 'x' ? e.clientX : e.clientY;
      startValue.current = value;
      document.body.style.cursor = axis === 'x' ? 'col-resize' : 'row-resize';
      document.body.style.userSelect = 'none';
    },
    [value, axis],
  );

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const rawDelta = (axis === 'x' ? e.clientX : e.clientY) - startPos.current;
      const delta = invert ? -rawDelta : rawDelta;
      const next = Math.min(max, Math.max(min, startValue.current + delta));
      setValue(next);
    };
    const onMouseUp = () => {
      if (dragging.current) {
        dragging.current = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      }
    };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [axis, min, max]);

  return {
    value,
    setValue,
    handleProps: { onMouseDown },
  };
}
