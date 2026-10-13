import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ImageViewer, fitScale, toStage } from './ImageViewer.jsx';

describe('fitScale', () => {
  it('fits a picture in a space, never above its own size', () => {
    expect(fitScale(800, 600, { width: 400, height: 400 })).toBe(0.5);
    expect(fitScale(800, 600, { width: 400, height: 150 })).toBe(0.25);
    expect(fitScale(100, 50, { width: 400, height: 400 })).toBe(1);
  });

  it('swaps the sides of a picture turned a quarter', () => {
    expect(fitScale(800, 200, { width: 400, height: 400 }, 0)).toBe(0.5);
    expect(fitScale(800, 200, { width: 400, height: 400 }, 90)).toBe(0.5);
    expect(fitScale(800, 200, { width: 100, height: 400 }, 90)).toBe(0.5);
    expect(fitScale(800, 200, { width: 100, height: 400 }, 0)).toBe(0.125);
  });

  it('is 1 when nothing is known yet', () => {
    expect(fitScale(0, 0, { width: 400, height: 400 })).toBe(1);
    expect(fitScale(800, 600, { width: 0, height: 0 })).toBe(1);
  });
});

describe('toStage', () => {
  it('follows a point of the picture as it is turned clockwise', () => {
    expect(toStage([0.2, 0.1], 0)).toEqual([0.2, 0.1]);
    expect(toStage([0, 0], 90)).toEqual([1, 0]); // top left goes to top right
    expect(toStage([0.2, 0.1], 90)).toEqual([0.9, 0.2]);
    expect(toStage([0.2, 0.1], 180)).toEqual([0.8, 0.9]);
    expect(toStage([0, 0], 270)).toEqual([0, 1]); // top left goes to bottom left
    expect(toStage([0.2, 0.1], -90)).toEqual([0.1, 0.8]); // as 270
  });
});

describe('ImageViewer', () => {
  beforeEach(() => {
    // jsdom has no layout: the view is 400 x 300 and the picture 800 x 600.
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(400);
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(300);
  });

  const loaded = (props = {}) => {
    const view = render(<ImageViewer src="/p.png" alt="scan" {...props} />);
    const image = view.container.querySelector('img');
    Object.defineProperty(image, 'naturalWidth', { value: 800, configurable: true });
    Object.defineProperty(image, 'naturalHeight', { value: 600, configurable: true });
    fireEvent.load(image);
    return { ...view, image };
  };

  it('fits the picture in the view', () => {
    const { image } = loaded();
    expect(image.style.width).toBe('400px');
    expect(image.style.height).toBe('300px');
    expect(screen.getByRole('group', { name: 'scan' })).toBeInTheDocument();
  });

  it('shows it at a given scale, and turns it', () => {
    const { image, rerender } = loaded({ zoom: 0.25 });
    expect([image.style.width, image.style.height]).toEqual(['200px', '150px']);
    rerender(<ImageViewer src="/p.png" alt="scan" zoom={0.25} rotation={90} />);
    expect(image.style.transform).toBe('rotate(90deg)');
    // Fit again when turned: 600 x 800 in 400 x 300.
    rerender(<ImageViewer src="/p.png" alt="scan" zoom="fit" rotation={90} />);
    expect(image.style.width).toBe(`${800 * 0.375}px`);
  });

  it('draws the boxes on the picture, in its own coordinates, turning with it', () => {
    const { container } = loaded({ boxes: [[0.1, 0.2, 0.5, 0.3]], rotation: 90 });
    const box = container.querySelector('[data-box]');
    expect([box.style.left, box.style.top, box.style.width, box.style.height]).toEqual([
      '10%',
      '20%',
      '40%',
      '10%',
    ]);
    // The box is inside the picture's own frame, which carries the turn.
    expect(box.closest('[data-picture]').style.transform).toBe('rotate(90deg)');
  });

  it('brings the focused box to the middle of a zoomed view', () => {
    const { container } = loaded({ zoom: 2, boxes: [[0.4, 0.4, 0.6, 0.6]], focus: 0 });
    const root = container.firstElementChild;
    // 1600 x 1200 picture: the box centre is at (800, 600); the view is 400 x 300.
    expect([root.scrollLeft, root.scrollTop]).toEqual([600, 450]);
  });

  it('asks for a zoom when the wheel turns, and says when it cannot be loaded', () => {
    const onZoom = vi.fn();
    const onError = vi.fn();
    const { container, image } = loaded({ onZoom, onError });
    fireEvent.wheel(container.firstElementChild, { deltaY: -100 });
    expect(onZoom).toHaveBeenLastCalledWith(expect.closeTo(0.55, 5));
    fireEvent.wheel(container.firstElementChild, { deltaY: 100 });
    expect(onZoom).toHaveBeenLastCalledWith(expect.closeTo(0.5 / 1.1, 5));
    fireEvent.error(image);
    expect(onError).toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('could not be shown');
  });

  it('keeps the zoom within limits', () => {
    const onZoom = vi.fn();
    const { container } = loaded({ zoom: 16, onZoom });
    fireEvent.wheel(container.firstElementChild, { deltaY: -100 });
    expect(onZoom).toHaveBeenLastCalledWith(16);
  });
});
