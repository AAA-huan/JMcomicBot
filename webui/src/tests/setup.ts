import { vi } from 'vitest'

// jsdom 未实现 ResizeObserver，Vuetify 组件依赖该接口
if (typeof globalThis.ResizeObserver === 'undefined') {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  globalThis.ResizeObserver =
    ResizeObserverStub as unknown as typeof ResizeObserver
}

// jsdom 未实现 matchMedia，主题 Store 依赖该接口
if (typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
}

// jsdom 未实现对象 URL，导出下载测试需要创建与释放 Blob 地址
if (typeof URL.createObjectURL !== 'function') {
  URL.createObjectURL = vi.fn(() => 'blob:jmbot-test')
  URL.revokeObjectURL = vi.fn()
}

// jsdom 未实现 visualViewport，Vuetify 弹层定位依赖该接口
if (typeof window.visualViewport === 'undefined') {
  Object.defineProperty(window, 'visualViewport', {
    writable: true,
    configurable: true,
    value: {
      width: 1024,
      height: 768,
      offsetLeft: 0,
      offsetTop: 0,
      pageLeft: 0,
      pageTop: 0,
      scale: 1,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    },
  })
}
