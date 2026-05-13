import { useCallback, useRef, useState } from 'react';

/**
 * 拖拽调整高度的 Hook。
 * 返回当前高度、拖拽手柄的 onMouseDown 回调，以及 handleStyle（已含 cursor 等）。
 *
 * 用法：
 *   const { height, handleProps } = useResizableHeight({ initial: 520, min: 200 });
 *   <div style={{ height, overflow: 'auto' }}>…</div>
 *   <div {...handleProps} style={handleProps.style} />
 */
export function useResizableHeight(opts: { initial: number; min?: number; max?: number }) {
  const { initial, min = 80, max = 2000 } = opts;
  const [height, setHeight] = useState(initial);
  const startY = useRef(0);
  const startH = useRef(initial);

  const onMouseMove = useCallback(
    (e: MouseEvent) => {
      const next = Math.min(max, Math.max(min, startH.current + (e.clientY - startY.current)));
      setHeight(next);
    },
    [min, max],
  );

  const onMouseUp = useCallback(() => {
    document.removeEventListener('mousemove', onMouseMove);
    document.removeEventListener('mouseup', onMouseUp);
    document.body.style.userSelect = '';
    document.body.style.cursor = '';
  }, [onMouseMove]);

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      startY.current = e.clientY;
      startH.current = height;
      document.body.style.userSelect = 'none';
      document.body.style.cursor = 'ns-resize';
      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
    },
    [height, onMouseMove, onMouseUp],
  );

  const handleProps = {
    onMouseDown,
    style: {
      height: 8,
      cursor: 'ns-resize',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      opacity: 0.35,
      transition: 'opacity 0.15s',
      userSelect: 'none' as const,
    } as React.CSSProperties,
    onMouseEnter: (e: React.MouseEvent<HTMLDivElement>) => {
      (e.currentTarget as HTMLDivElement).style.opacity = '0.75';
    },
    onMouseLeave: (e: React.MouseEvent<HTMLDivElement>) => {
      (e.currentTarget as HTMLDivElement).style.opacity = '0.35';
    },
  };

  return { height, handleProps };
}
