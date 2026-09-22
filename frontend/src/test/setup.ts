import '@testing-library/jest-dom/vitest'

// jsdom reports 0x0 for every element and has no ResizeObserver, so
// recharts' ResponsiveContainer (used by every chart component) never
// renders its children without these -- standard shims for testing
// recharts under jsdom, not used by anything else in the app. The stub
// must actually invoke its callback (real ResizeObserver would, once
// layout settles) or ResponsiveContainer's size state never leaves 0x0.
Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: 500 })
Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, value: 300 })
Element.prototype.getBoundingClientRect = () =>
  ({ width: 500, height: 300, top: 0, left: 0, right: 500, bottom: 300, x: 0, y: 0, toJSON() {} }) as DOMRect

class ResizeObserverStub {
  #callback: ResizeObserverCallback
  constructor(callback: ResizeObserverCallback) {
    this.#callback = callback
  }
  observe(target: Element) {
    this.#callback([{ target, contentRect: target.getBoundingClientRect() } as ResizeObserverEntry], this as unknown as ResizeObserver)
  }
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver
