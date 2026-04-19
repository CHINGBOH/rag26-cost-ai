# XState v5 深度调研报告：常见坑与最佳实践

> 调研日期：2026-04-19
> XState 版本：^5.30.0
> TypeScript 版本要求：>= 5.0

## 一、XState v4 到 v5 核心变化

### 1.1 架构变化：Actor Model

XState v5 引入了完整的 Actor Model：
- **状态机即 Actor**：每个状态机实例都是一个独立的 Actor
- **通信机制**：通过事件异步消息传递
- **生命周期管理**：明确的 start() / stop() 方法

```typescript
// v4
const service = interpret(machine).start();

// v5
const actor = createActor(machine);
actor.start();
actor.stop(); // 必须显式停止
```

### 1.2 API 变更

| v4 | v5 |
|---|---|
| `interpret(machine)` | `createActor(machine)` |
| `service.send(event)` | `actor.send(event)` |
| `service.stop()` | `actor.stop()` |
| `service.onTransition()` | `actor.subscribe()` |
| `send(...)` action | `raise(...)` / `sendTo(...)` |
| `autoForward` | 废弃，推荐显式 `forwardTo` |

### 1.3 setup() API

v5 推荐使用 `setup()` 提前定义类型和逻辑：

```typescript
const machine = setup({
  types: {
    context: {} as { count: number },
    events: {} as { type: 'INC' } | { type: 'DEC' }
  },
  actions: {
    increment: assign({ count: ({ context }) => context.count + 1 })
  },
  guards: {
    canIncrement: ({ context }) => context.count < 10
  },
  actors: {
    fetchData: fromPromise(async ({ input }) => { ... })
  }
}).createMachine({ ... })
```

---

## 二、TypeScript 类型系统坑

### 2.1 assign() 类型安全问题

**问题**：`enqueueActions` 中的 `assign` 不是类型安全的。

```typescript
// ❌ 不会报错，但运行时可能出错
enqueue.assign({
  foo: undefined  // 应该是 string
})

// ✅ 使用函数形式才有类型检查
assign({
  foo: () => undefined  // TS 报错
})
```

**原因**：TypeScript 默认允许 `undefined` 赋值给可选属性，除非启用 `exactOptionalPropertyTypes`。

**解决方案**：
1. 始终使用函数形式 `assign({ prop: () => value })`
2. 启用 `exactOptionalPropertyTypes: true`（会有大量现有代码报错）

### 2.2 Context 不能是数组

**问题**：`assign` 使用 `Object.assign()`，会破坏数组结构。

```typescript
// ❌ 初始化是数组，assign 后变成对象
context: [] as string[]
// assign({ items: () => [...context, 'new'] })
// 结果: { '0': 'a', '1': 'b' } 而不是 ['a', 'b']
```

**解决方案**：始终将数组包装在对象中：

```typescript
context: { items: [] as string[] }
// 使用 assign({ items: ({ context }) => [...context.items, 'new'] })
```

### 2.3 fromPromise input 类型推断失效

**问题**：`fromPromise` 的 `input` 参数类型在 `setup()` 中可能推断为 `unknown`。

```typescript
// ❌ input 类型不明确
actors: {
  fetchUser: fromPromise(async ({ input }) => {
    // input.userId 报错 TS2339
    return fetch(`/api/${input.userId}`)
  })
}

// ✅ 明确声明 input 类型
actors: {
  fetchUser: fromPromise(async ({ input }: { input: { userId: string } }) => {
    return fetch(`/api/${input.userId}`)
  })
}
```

### 2.4 Guard 类型收窄问题

**问题**：`or()`、`and()`、`not()` 组合 guard 时类型报错。

```typescript
// ❌ v5 可能报错
on: {
  EVENT: {
    target: '#b',
    guard: not('falsy')  // TS2322
  }
}
```

**解决方案**：使用 `and()`、`or()` 函数：

```typescript
import { and, or, not } from 'xstate'

guard: not('falsy')  // 放在 guards 定义中而非内联
```

---

## 三、Actor 生命周期坑

### 3.1 内存泄漏：未停止的 Actor

**问题**：Actor 必须显式停止，否则会内存泄漏。

```typescript
// ❌ 忘记 stop
const actor = createActor(someMachine);
actor.start();
// 组件卸载时没有调用 actor.stop()
```

**解决方案**：
1. 组件卸载时调用 `actor.stop()`
2. 使用 `waitFor()` 等待异步操作完成后再停止
3. 使用 `toPromise()` 包装但需注意同步启动顺序

```typescript
// 正确顺序
const actor = createActor(TestMachine);
const p = toPromise(actor);  // 先建立 promise
actor.start();                // 再启动
await p;                      // 最后等待
```

### 3.2 订阅返回值误解

**问题**：`actor.subscribe()` 返回 `Subscription` 对象，但可能被误解为 `Unsubscribable`。

```typescript
// ❌ 错误理解
const subscription = actor.subscribe(state => { ... });
subscription.then?.()  // subscription 不是 Promise

// ✅ 正确用法
const subscription = actor.subscribe(state => { ... });
subscription.unsubscribe();  // 调用 unsubscribe 停止订阅
```

### 3.3 Context 初始化函数同步执行

**问题**：context 初始化函数如果抛出错误，难以捕获。

```typescript
const machine = setup({
  types: { input: {} as { signal: AbortSignal } }
}).createMachine({
  context: ({ input }) => {
    if (input.signal.aborted) throw new Error('aborted');  // 同步抛出
  }
});

// ❌ 这个 try-catch 无效
try {
  const actor = createActor(machine, { input });
  actor.start();
} catch (e) { }

// ✅ 正确方式：先建立监听
const actor = createActor(machine, { input });
actor.subscribe({
  error: (err) => console.error(err)  // 捕获初始化错误
});
actor.start();
```

---

## 四、Invoke 调用坑

### 4.1 Promise reject 但缺少 onError

**问题**：如果 `fromPromise` reject 且没有 `onError`，错误会被静默忽略。

```typescript
// ❌ 没有 onError
invoke: {
  src: 'fetchData',
  onDone: { target: 'success' }
}

// 如果 fetchData reject，状态机进入不可预测状态
```

**解决方案**：始终添加 `onError` 处理。

```typescript
// ✅
invoke: {
  src: 'fetchData',
  onDone: { target: 'success' },
  onError: { target: 'failure', actions: assign({ error: ({ event }) => event.error }) }
}
```

### 4.2 invoke input 函数中的事件类型

**问题**：`input` 函数中访问 `event` 参数时，类型是所有可能事件的联合。

```typescript
invoke: {
  src: 'processOrder',
  input: ({ event }) => {
    // event 是所有事件的联合类型
    // 访问 event.orderId 可能报错
    return { orderId: event.orderId }  // TS2339
  }
}
```

**解决方案**：使用 `assertEvent` 收窄类型。

```typescript
import { assertEvent } from 'xstate';

input: ({ event }) => {
  assertEvent(event, 'SUBMIT_ORDER');
  return { orderId: event.orderId };
}
```

### 4.3 Final State 与 onDone 混淆

**问题**：`state.onDone` 和 `invoke.onDone` 容易混淆。

| 概念 | 说明 |
|------|------|
| `state.onDone` | 复合状态机的子状态全部到达 final 状态 |
| `invoke.onDone` | 被调用的 actor（Promise/机器）完成 |

```typescript
// 复合状态机的 final child
states: {
  submitting: {
    initial: 'pending',
    states: {
      pending: { on: { DONE: 'completed' } },
      completed: { type: 'final' }  // 这会触发 submitting.onDone
    },
    onDone: { target: 'success' }  // 当所有 region 到达 final
  }
}
```

---

## 五、Parallel State 坑

### 5.1 Parallel 状态完成时机过早

**问题**：当 parallel 有多个 region 时，可能在所有 final state 到达前就触发 `onDone`。

```typescript
// ❌ B region 未到达 final，但机器已报告完成
type: 'parallel',
states: {
  A: { type: 'final' },  // 立即完成
  B: {
    initial: 'B1',
    states: {
      B1: {},  // 未到达 final
      B2: { type: 'final' }
    }
  }
}
```

**解决方案**：确保所有 region 同时有 final 状态。

### 5.2 Parallel 状态事件分发

**问题**：事件会同时分发给所有 active region，可能导致意外行为。

```typescript
type: 'parallel',
states: {
  upload: { ... },
  download: { ... }
}

// 发送 NEXT 事件，两个 region 都会处理
actor.send({ type: 'NEXT' });
```

**解决方案**：使用 guard 或 `stateIn()` 控制事件处理。

---

## 六、Actor 间通信坑

### 6.1 send() 不是 Promise

**问题**：`actor.send()` 返回 `void` 而非 `Promise`，但 TypeScript 可能误导性显示返回 `Awaitable<void>`。

```typescript
// ❌ 不生效
await actor.send({ type: 'INC' });

// ✅ 正确方式
actor.send({ type: 'INC' });
// 如果需要等待，使用 waitFor
import { waitFor } from 'xstate';
await waitFor(actor, 'success');
```

### 6.2 sendTo 目标 Actor 不存在

**问题**：尝试向不存在的子 Actor 发送事件会抛出错误。

```typescript
// ❌ grandchild 可能不存在
actions: sendTo('grandchild', { type: 'PONG' })
// Error: Unable to send event to actor 'grandchild'
```

**解决方案**：先检查 Actor 是否存在。

```typescript
actions: ({ context }) => {
  if (context.childRef) {
    return sendTo('child', { type: 'PONG' });
  }
}
```

### 6.3 autoForward 废弃

**问题**：`autoForward: true` 可能导致无限循环。

```typescript
// ❌ 不推荐
invoke: {
  src: 'someService',
  autoForward: true  // 所有事件都被转发，可能死循环
}

// ✅ 使用 forwardTo 显式转发
invoke: {
  src: 'someService',
  on: {
    USER_EVENT: {
      actions: forwardTo('someService')
    }
  }
}
```

---

## 七、状态机配置坑

### 7.1 循环引用导致死锁

**问题**：两个状态机互相等待对方完成。

```
Parent 等待 Child 完成
  └─> Child 等待 Parent 发送事件
       └─> Parent 已等待中... 死锁！
```

**解决方案**：
1. 避免循环依赖
2. 使用超时机制
3. 使用 `sendParent()` 而非等待

### 7.2 状态转换动画（Reentrancy）

**问题**：同一状态间的转换默认不会 re-enter，导致 entry actions 不执行。

```typescript
// 从 idle 到 idle 默认不 re-enter
on: {
  REFRESH: { target: 'idle' }  // 如果已在 idle，不触发 entry
}
```

**解决方案**：使用 `reenter: true`。

```typescript
on: {
  REFRESH: { target: 'idle', reenter: true }  // 强制 re-enter
}
```

---

## 八、现有代码问题诊断

### 8.1 RecursionController 问题

查看 [StateMachine.ts](file:///home/l/rag-dashboard/src/backend/server/src/core/StateMachine.ts) 发现的问题：

1. **类型断言风险**：大量使用 `as RecursionContext` 和 `as any`
2. **invoke input 类型**：直接传递 context 而非 `{ input: context }`
3. **缺少 onError 处理**：多个 invoke 缺少错误处理路径

### 8.2 RAGMachine 改进建议

查看 [machine.ts](file:///home/l/rag-dashboard/src/backend/server/src/modules/rag/machine.ts) 发现：

1. **✅ 良好的类型定义**：使用了 Zod schema
2. **✅ 完整的错误处理**：所有 invoke 都有 onError
3. **⚠️ input 类型**：fromPromise input 应明确声明
4. **⚠️ this 引用**：setup 闭包中使用 this 需要注意

---

## 九、最佳实践清单

### 9.1 TypeScript 配置

```json
{
  "compilerOptions": {
    "strict": true,
    "strictNullChecks": true,
    "skipLibCheck": true,
    "exactOptionalPropertyTypes": true  // 可选，但推荐
  }
}
```

### 9.2 状态机结构

```typescript
const machine = setup({
  types: {
    context: {} as MyContext,
    events: {} as MyEvents,
    input: {} as MyInput
  },
  actions: {
    // 使用命名 actions
    logStart: () => console.log('started'),
    setData: assign({ data: ({ event }) => event.data })
  },
  guards: {
    isValid: ({ context }) => context.data !== undefined
  },
  actors: {
    fetchData: fromPromise(async ({ input }) => {
      return await api.fetch(input.url);
    })
  }
}).createMachine({
  id: 'my-machine',
  initial: 'idle',
  context: ({ input }) => ({ /* 初始化 */ }),
  states: {
    idle: {
      on: { START: 'loading' }
    },
    loading: {
      invoke: {
        src: 'fetchData',
        input: ({ context }) => ({ url: context.url }),
        onDone: { target: 'success', actions: 'setData' },
        onError: { target: 'failure', actions: assign({ error: ({ event }) => event.error }) }
      }
    },
    success: { type: 'final' },
    failure: {}
  }
});
```

### 9.3 Actor 生命周期

```typescript
class MyService {
  private actor: Actor<any>;

  start() {
    this.actor = createActor(this.machine);
    this.actor.subscribe({
      next: (state) => this.handleStateChange(state),
      error: (err) => this.handleError(err),
      complete: () => this.handleComplete()
    });
    this.actor.start();
  }

  stop() {
    this.actor?.stop();
  }
}
```

---

## 十、参考资料

1. [XState 官方文档](https://stately.ai/docs)
2. [XState v5 Migration Guide](https://stately.ai/docs/migration)
3. [XState GitHub Issues](https://github.com/statelyai/xstate/issues)
4. [TypeScript 5.0+ 要求](https://stately.ai/docs/typescript)

---

## 十一、总结

XState v5 是一次重大升级，Actor Model 和 setup() API 提供了更好的类型安全和模块化。但也带来了一些学习曲线和潜在坑点：

| 优先级 | 坑点 | 建议 |
|-------|------|------|
| 🔴 高 | assign 类型安全 | 始终用函数形式 |
| 🔴 高 | Actor 内存泄漏 | 显式 stop() |
| 🟡 中 | fromPromise input | 明确声明类型 |
| 🟡 中 | onError 缺失 | 每个 invoke 都加 |
| 🟡 中 | parallel 完成时机 | 确保所有 region 有 final |
| 🟢 低 | Context 数组 | 用对象包装 |

**核心原则**：
1. TypeScript 严格模式
2. 每个异步操作都有错误处理
3. Actor 必须有明确的生命周期管理
4. 使用 setup() 提前声明类型
