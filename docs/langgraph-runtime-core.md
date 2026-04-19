# LangGraph Runtime 核心代码拆解

> 从 github.com/langchain-ai/langgraph 提取的核心 runtime 代码，供自研参考。

---

## 一、Checkpoint 数据结构（状态的快照）

文件：`libs/checkpoint/langgraph/checkpoint/base/__init__.py`

```python
class Checkpoint(TypedDict):
    """State snapshot at a given point in time."""

    v: int                              # checkpoint 格式版本
    id: str                             # UUID，单调递增，可排序
    ts: str                             # ISO 8601 时间戳
    channel_values: dict[str, Any]      # 各 Channel 的序列化值
    channel_versions: ChannelVersions   # 各 Channel 的版本号（单调递增）
    versions_seen: dict[str, ChannelVersions]  # 每个节点已看到的 Channel 版本
    updated_channels: list[str] | None  # 本步更新的 Channel 列表


class CheckpointMetadata(TypedDict, total=False):
    source: Literal["input", "loop", "update", "fork"]
    step: int                           # 超步序号
    parents: dict[str, str]             # 父 checkpoint ID
    run_id: str


class BaseCheckpointSaver(Generic[V]):
    """持久化抽象，子类实现 Postgres/Redis/Memory 版本。"""

    def get_tuple(self, config) -> CheckpointTuple | None: ...
    def put(self, config, checkpoint, metadata, new_versions) -> RunnableConfig: ...
    def put_writes(self, config, writes, task_id) -> None: ...
```

**核心设计**：
- `channel_versions` 是**向量时钟**的简化版，用来判断节点是否需要重新执行
- `versions_seen` 记录每个节点上次执行时看到的版本，如果 Channel 版本更新了，节点就会被触发
- Checkpoint 是一个**不可变快照链表**，`id` 单调递增支持 time-travel

---

## 二、Channel 抽象（State 的后端实现）

文件：`libs/langgraph/langgraph/channels/base.py`

```python
class BaseChannel(Generic[Value, Update, Checkpoint], ABC):
    """所有 Channel 的基类。每个 State Key 底层对应一个 Channel。"""

    def checkpoint(self) -> Checkpoint | Any:
        """返回可序列化的状态快照。"""
        return self.get()

    def from_checkpoint(self, checkpoint) -> Self:
        """从快照恢复新实例。"""

    def get(self) -> Value:
        """读取当前值。未初始化时抛 EmptyChannelError。"""

    def update(self, values: Sequence[Update]) -> bool:
        """用一批更新合并到当前值。
        返回 True 表示值确实变化了（会触发版本号递增）。
        """

    def consume(self) -> bool:
        """通知 Channel 有任务消费了它，可能清空值（如 Topic）。"""

    def finish(self) -> bool:
        """通知 Pregel 运行结束，Channel 可做收尾。"""
```

**内置 Channel 类型**：
- `LastValue` — 默认值，覆盖
- `BinaryOperatorAggregate` — 带 reducer 的累积（如 `operator.add`）
- `Topic` — 发布订阅，可清空
- `EphemeralValue` — 只存活一步，用完即焚
- `UntrackedValue` — 不进入 checkpoint（如临时标记）

**对你写 XState 的启示**：
你的 XState `context` 可以模仿这个设计——给每个字段配一个 `mergeStrategy`：
```typescript
type MergeStrategy = 'lastWriteWins' | 'append' | 'merge' | 'sum';
```

---

## 三、Pregel Superstep 执行循环（Runtime 心脏）

文件：`libs/langgraph/langgraph/pregel/_loop.py`

### 3.1 PregelLoop 状态机

```python
class PregelLoop:
    status: Literal[
        "input",           # 等待输入
        "pending",         # 准备执行
        "done",            # 完成
        "interrupt_before",# 执行前中断（Human-in-the-loop）
        "interrupt_after", # 执行后中断
        "out_of_steps",    # 超出最大步数
    ]
    step: int                # 当前超步序号
    checkpoint: Checkpoint   # 当前 checkpoint
    channels: dict[str, BaseChannel]
    tasks: dict[str, PregelExecutableTask]  # 本步要执行的节点
```

### 3.2 单步执行 tick()

```python
def tick(self) -> bool:
    """执行一个 Pregel Superstep。返回 True 表示还需要继续。"""

    # 1. 检查步数限制
    if self.step > self.stop:
        self.status = "out_of_steps"
        return False

    # 2. 根据更新的 Channel，计算下一批可执行节点
    self.tasks = prepare_next_tasks(
        self.checkpoint,
        self.checkpoint_pending_writes,
        self.nodes,           # 所有节点定义
        self.channels,        # 所有 Channel 当前值
        self.managed,         # 托管值
        self.config,
        self.step,
        self.stop,
        for_execution=True,
        updated_channels=self.updated_channels,
        ...
    )

    # 3. 没有可执行任务 -> 结束
    if not self.tasks:
        self.status = "done"
        return False

    # 4. 恢复之前 checkpoint 的 pending writes（用于重放/恢复）
    if not self.is_replaying and self.checkpoint_pending_writes:
        self._match_writes(self.tasks)

    # 5. 检查 interrupt_before（Human-in-the-loop）
    if self.interrupt_before and should_interrupt(
        self.checkpoint, self.interrupt_before, self.tasks.values()
    ):
        self.status = "interrupt_before"
        raise GraphInterrupt()   # 抛出特殊异常，外层捕获并保存状态

    # 6. 返回 True，让 Runner 去真正执行这些任务
    return True
```

### 3.3 单步收尾 after_tick()

```python
def after_tick(self) -> None:
    """所有任务执行完毕后，合并 writes 并保存 checkpoint。"""

    # 1. 收集所有任务写出的更新
    writes = [w for t in self.tasks.values() for w in t.writes]

    # 2. === 核心：用 apply_writes 合并所有更新到 Channel ===
    self.updated_channels = apply_writes(
        self.checkpoint,
        self.channels,
        self.tasks.values(),
        self.checkpointer_get_next_version,
        self.trigger_to_nodes,
    )

    # 3. 输出值（如果更新的 Channel 包含 output_keys）
    if not self.updated_channels.isdisjoint(self.output_keys):
        self._emit("values", ...)

    # 4. 清空 pending writes
    self.checkpoint_pending_writes.clear()

    # 5. === 核心：保存 checkpoint ===
    self._put_checkpoint({"source": "loop"})

    # 6. 检查 interrupt_after
    if self.interrupt_after and should_interrupt(
        self.checkpoint, self.interrupt_after, self.tasks.values()
    ):
        self.status = "interrupt_after"
        raise GraphInterrupt()
```

**Superstep 循环的完整流程**：
```
input -> tick() -> [tasks ready] -> Runner executes tasks concurrently
                                  -> after_tick() -> apply_writes + checkpoint
                                  -> tick() -> ...
```

---

## 四、状态合并算法 apply_writes

文件：`libs/langgraph/langgraph/pregel/_algo.py`

```python
def apply_writes(
    checkpoint: Checkpoint,
    channels: Mapping[str, BaseChannel],
    tasks: Iterable[WritesProtocol],
    get_next_version: GetNextVersion | None,
    trigger_to_nodes: Mapping[str, Sequence[str]],
) -> set[str]:
    """将一组任务的 writes 应用到 Channel 和 Checkpoint。
    返回被更新的 Channel 集合（用于决定下一步触发哪些节点）。
    """

    # 1. 按路径排序，确保确定性合并顺序
    tasks = sorted(tasks, key=lambda t: task_path_str(t.path[:3]))

    # 2. 更新 versions_seen：每个节点记录它当前看到的 Channel 版本
    for task in tasks:
        checkpoint["versions_seen"].setdefault(task.name, {}).update(
            {
                chan: checkpoint["channel_versions"][chan]
                for chan in task.triggers
                if chan in checkpoint["channel_versions"]
            }
        )

    # 3. 计算下一个全局版本号
    if get_next_version is not None:
        next_version = get_next_version(
            max(checkpoint["channel_versions"].values()) if checkpoint["channel_versions"] else None,
            None,
        )

    # 4. 消费被读取的 Channel（如 Topic 会被清空）
    for chan in {chan for task in tasks for chan in task.triggers if chan in channels}:
        if channels[chan].consume() and next_version is not None:
            checkpoint["channel_versions"][chan] = next_version

    # 5. 按 Channel 分组收集 writes
    pending_writes_by_channel: dict[str, list[Any]] = defaultdict(list)
    for task in tasks:
        for chan, val in task.writes:
            if chan in channels:
                pending_writes_by_channel[chan].append(val)

    # 6. 对每个 Channel 调用 update()，由 Channel 自己的 reducer 合并
    updated_channels: set[str] = set()
    for chan, vals in pending_writes_by_channel.items():
        if channels[chan].update(vals) and next_version is not None:
            checkpoint["channel_versions"][chan] = next_version
            if channels[chan].is_available():
                updated_channels.add(chan)   # 只有可用的 Channel 才能触发后续节点

    # 7. 未更新的 Channel 也通知有新 step（某些 Channel 需要知道 step 推进）
    for chan in channels:
        if channels[chan].is_available() and chan not in updated_channels:
            if channels[chan].update(EMPTY_SEQ) and next_version is not None:
                checkpoint["channel_versions"][chan] = next_version
                if channels[chan].is_available():
                    updated_channels.add(chan)

    # 8. 如果没有 Channel 能触发新节点，通知 finish
    if updated_channels.isdisjoint(trigger_to_nodes):
        for chan in channels:
            if channels[chan].finish() and next_version is not None:
                if channels[chan].is_available():
                    updated_channels.add(chan)

    return updated_channels
```

**核心洞察**：
- **Channel 是状态合并的单元**：每个 key 有自己的 `update()` 策略（覆盖/追加/累加）
- **版本号驱动执行**：`channel_versions` 递增才触发节点，天然支持增量计算
- **确定性**：任务按 path 排序后合并，保证同样的并行 writes 永远得到同样结果

---

## 五、并发任务执行 PregelRunner

文件：`libs/langgraph/langgraph/pregel/_runner.py`

```python
class PregelRunner:
    """负责任务的并发执行、write 提交、错误处理和流式输出。"""

    def tick(self, tasks, ..., retry_policy=None) -> Iterator[None]:
        """执行任务集，yield 控制权给调用方以便输出流式结果。"""

        tasks = tuple(tasks)
        futures = FuturesDict(
            callback=weakref.WeakMethod(self.commit),  # 任务完成时自动 commit writes
            event=threading.Event(),
            future_type=concurrent.futures.Future,
        )

        yield  # 第一次 yield，让外层有机会处理输出

        # 单任务快速路径（无并发开销）
        if len(tasks) == 1:
            t = tasks[0]
            run_with_retry(t, retry_policy, ...)
            self.commit(t, None)   # 提交 writes
            return

        # 多任务：提交到线程池
        for t in tasks:
            fut = self.submit(
                run_with_retry, t, retry_policy,
                configurable={CONFIG_KEY_CALL: partial(_call, ...)},
            )
            futures[fut] = t

        # 等待任务完成，每完成一个 yield 一次（支持流式输出）
        end_time = timeout + time.monotonic() if timeout else None
        while len(futures) > 0:
            done, inflight = concurrent.futures.wait(
                futures,
                return_when=concurrent.futures.FIRST_COMPLETED,
                timeout=...,
            )
            for fut in done:
                task = futures.pop(fut)
                # ... 处理完成
            yield   # 每完成一批任务，yield 给外层

        futures.event.wait()  # 等待所有 callback 完成
        yield

        _panic_or_proceed(futures.done, panic=reraise)  # 如果有异常则抛出
```

**设计亮点**：
- **Generator 模式**：`tick()` 是生成器，每完成一些任务就 `yield`，让外层可以实时输出
- **FutureDict**：自定义 dict，任务完成时自动调用 `commit()` 把 writes 写回 Loop
- **单任务快速路径**：避免线程池开销

---

## 六、Checkpoint 创建与序列化

文件：`libs/langgraph/langgraph/pregel/_checkpoint.py`

```python
def empty_checkpoint() -> Checkpoint:
    return Checkpoint(
        v=LATEST_VERSION,
        id=str(uuid6(clock_seq=-2)),
        ts=datetime.now(timezone.utc).isoformat(),
        channel_values={},
        channel_versions={},
        versions_seen={},
    )


def create_checkpoint(
    checkpoint: Checkpoint,
    channels: Mapping[str, BaseChannel] | None,
    step: int,
    id: str | None = None,
) -> Checkpoint:
    """创建新 checkpoint，只序列化有版本的 Channel。"""
    ts = datetime.now(timezone.utc).isoformat()
    values = {}
    for k in channels:
        if k not in checkpoint["channel_versions"]:
            continue
        v = channels[k].checkpoint()
        if v is not MISSING:
            values[k] = v
    return Checkpoint(
        v=LATEST_VERSION,
        ts=ts,
        id=id or str(uuid6(clock_seq=step)),
        channel_values=values,
        channel_versions=checkpoint["channel_versions"],  # 引用同一 dict
        versions_seen=checkpoint["versions_seen"],
    )


def channels_from_checkpoint(
    specs: Mapping[str, BaseChannel | ManagedValueSpec],
    checkpoint: Checkpoint,
) -> tuple[Mapping[str, BaseChannel], ManagedValueMapping]:
    """从 checkpoint 恢复 Channel 实例。"""
    return {
        k: v.from_checkpoint(checkpoint["channel_values"].get(k, MISSING))
        for k, v in channel_specs.items()
    }, managed_specs
```

---

## 七、StateGraph 编译（Builder -> Runtime）

文件：`libs/langgraph/langgraph/graph/state.py`

```python
class StateGraph(Generic[StateT, ContextT, InputT, OutputT]):
    """Builder 类。节点签名统一为 State -> Partial<State>。
    每个 state key 可用 Annotated[type, reducer] 配置合并策略。
    """

    def __init__(self, state_schema, context_schema=None, input_schema=None, output_schema=None):
        self.nodes = {}
        self.edges = set()
        self.branches = defaultdict(dict)
        self.channels = {}      # 从 schema 自动推导的 Channel
        self.managed = {}
        self.compiled = False

    def add_node(self, name, node, input_schema=None, retry_policy=None): ...
    def add_edge(self, from_node, to_node): ...
    def add_conditional_edges(self, from_node, router, path_map): ...

    def compile(self, checkpointer=None, interrupt_before=None, interrupt_after=None):
        """编译为可执行的 CompiledStateGraph（底层是 Pregel 实例）。"""
        # 1. 验证图结构无环/可达性
        # 2. 将每个 state key 映射为 Channel
        # 3. 将每个 node 包装为 PregelNode（订阅其输入 Channel，写入其输出 Channel）
        # 4. 返回 CompiledStateGraph，内部持有 PregelLoop + PregelRunner
```

**编译后的执行链路**：
```
StateGraph.compile()
  -> CompiledStateGraph (implements PregelProtocol)
    -> .invoke() / .stream()
      -> PregelLoop(input, checkpointer, ...)
        -> loop.tick() -> PregelRunner.tick(tasks) -> loop.after_tick()
        -> repeat until done / interrupt
```

---

## 八、对你的 XState 架构的直接映射

| LangGraph 概念 | 你的 XState 对应实现 |
|---------------|-------------------|
| `StateGraph` | `createMachine(...)` |
| `Channel` + `Reducer` | `context` 字段配 `mergeStrategy` |
| `PregelLoop.tick()` | `interpret(machine).send(event)` |
| `apply_writes()` | XState `assign()` 的批量合并逻辑 |
| `Checkpoint` | 把 `machine.getSnapshot()` 序列化到 Redis |
| `BaseCheckpointSaver` | 你的 `CheckpointService`（Redis/Postgres） |
| `PregelRunner` | Node.js `Promise.all()` 或 `worker_threads` |
| `interrupt()` / `GraphInterrupt` | XState 的 `after` 延迟 + 等待外部 `RESUME` 事件 |
| `channel_versions` | 每个 context key 的版本号 / hash |

**最简单的落地方式**：

```typescript
// 1. 给 context 每个字段配 reducer
interface AgentContext {
  query: string;                                    // lastWriteWins
  retrieval_results: Annotated<Chunk[], 'append'>;  // 累积
  messages: Annotated<Message[], 'append'];          // 累积
  confidence: number;                               // lastWriteWins
}

// 2. 每个 action 只返回 Partial<State>
const retrieveAction = assign(({ event, context }) => ({
  retrieval_results: event.payload.results,  // 由框架自动 append
}));

// 3. checkpoint 在每次 transition 后保存
const service = interpret(machine)
  .onTransition((state) => {
    checkpointService.save(state.context, state.value, state.event);
  })
  .start();

// 4. 恢复时从 Redis 加载最后一次 snapshot
const lastCheckpoint = await checkpointService.load(threadId);
const restoredService = interpret(machine)
  .start(lastCheckpoint.state);
```

---

## 九、最值得精读的文件清单

如果你要深入源码，按这个顺序读：

1. `libs/checkpoint/langgraph/checkpoint/base/__init__.py` — Checkpoint 数据结构与持久化接口
2. `libs/langgraph/langgraph/channels/base.py` — Channel 抽象与状态合并策略
3. `libs/langgraph/langgraph/pregel/_algo.py` — `apply_writes()` + `prepare_next_tasks()` 核心算法
4. `libs/langgraph/langgraph/pregel/_loop.py` — `PregelLoop.tick()` + `after_tick()` 超步循环
5. `libs/langgraph/langgraph/pregel/_runner.py` — `PregelRunner.tick()` 并发执行
6. `libs/langgraph/langgraph/pregel/_checkpoint.py` — checkpoint 创建/恢复
7. `libs/langgraph/langgraph/graph/state.py` — StateGraph Builder 与编译

---

## 十、一句话总结

> LangGraph Runtime = **Pregel 超步循环**（tick/after_tick）+ **Channel 状态合并**（apply_writes）+ **版本号驱动执行**（channel_versions）+ **快照持久化**（checkpoint）。
>
> 这四块你都可以在自己的 XState + TypeScript 架构中干净地复现，不需要 import 任何 LangChain 代码。
