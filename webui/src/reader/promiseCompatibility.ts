/**
 * PDF.js 6 的 legacy 构建仍依赖 Promise.withResolvers。
 * 主线程和 Worker 都加载此模块，仅在浏览器缺少该 API 时安装标准行为。
 */
interface PromiseResolvers<T> {
  promise: Promise<T>
  resolve: (value: T | PromiseLike<T>) => void
  reject: (reason?: unknown) => void
}

if (!('withResolvers' in Promise)) {
  Object.defineProperty(Promise, 'withResolvers', {
    configurable: true,
    writable: true,
    value: function withResolvers<T>(this: PromiseConstructor): PromiseResolvers<T> {
      let resolve!: PromiseResolvers<T>['resolve']
      let reject!: PromiseResolvers<T>['reject']
      const promise = new this<T>((resolvePromise, rejectPromise) => {
        resolve = resolvePromise
        reject = rejectPromise
      })
      return { promise, resolve, reject }
    },
  })
}
