"""Seed a local demo database for screenshots and UI QA.

Usage: python scripts/seed_demo.py [database]
This development helper never touches the default api_chat database unless you
explicitly pass it as the argument.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apichat.db import Database
from apichat.models import Provider
from apichat.repository import Repository
from apichat.tokens import message_tokens


def seed(name: str) -> None:
    db = Database(
        {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "", "name": name}
    ).connect()
    repo = Repository(db)
    with db.cursor() as cursor:
        cursor.execute("SET FOREIGN_KEY_CHECKS=0")
        for table in ("usage_events", "messages", "conversations", "api_providers"):
            cursor.execute(f"DELETE FROM `{table}`")
        cursor.execute("SET FOREIGN_KEY_CHECKS=1")

    deepseek_id = repo.create_provider(
        Provider(
            id=0,
            alias="DeepSeek V3",
            provider="openai",
            base_url="https://api.deepseek.com/v1",
            api_key="sk-demo-deepseek",
            model="deepseek-chat",
            context_window=65_536,
            max_output_tokens=8192,
            temperature=0.7,
            system_prompt="你是一位严谨、务实的中文技术助手。回答时先给结论，再给必要的解释。",
            is_default=True,
        )
    )
    claude_id = repo.create_provider(
        Provider(
            id=0,
            alias="Claude Sonnet",
            provider="anthropic",
            base_url="https://api.anthropic.com/v1",
            api_key="sk-ant-demo",
            model="claude-sonnet-4-20250514",
            context_window=200_000,
            max_output_tokens=8192,
            temperature=0.5,
        )
    )
    repo.create_provider(
        Provider(
            id=0,
            alias="GPT-4o mini",
            provider="openai",
            base_url="https://api.openai.com/v1",
            api_key="sk-demo-openai",
            model="gpt-4o-mini",
            context_window=128_000,
            max_output_tokens=4096,
            temperature=0.7,
        )
    )
    repo.create_provider(
        Provider(
            id=0,
            alias="Gemini 2.5 Pro",
            provider="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            api_key="demo-gemini",
            model="gemini-2.5-pro",
            context_window=1_048_576,
            max_output_tokens=8192,
            temperature=0.6,
        )
    )
    deepseek_provider = repo.get_provider(deepseek_id)
    assert deepseek_provider is not None

    now = datetime.now()

    def add(
        conv_id: int,
        role: str,
        content: str,
        api_id: int,
        alias: str,
        model: str,
        minutes_ago: int,
        usage: tuple[int, int] | None = None,
    ) -> None:
        data = (
            {
                "api_id": api_id,
                "api_alias": alias,
                "model": model,
                "prompt_tokens": usage[0],
                "completion_tokens": usage[1],
                "total_tokens": usage[0] + usage[1],
            }
            if usage
            else None
        )
        msg_id = repo.add_message(
            conv_id,
            role,
            content,
            model=model,
            token_count=message_tokens(role, content),
            usage=data,
        )
        stamp = now - timedelta(minutes=minutes_ago)
        with db.cursor() as cursor:
            cursor.execute(
                "UPDATE messages SET created_at=%s, updated_at=%s WHERE id=%s",
                (stamp, stamp, msg_id),
            )
            cursor.execute(
                "UPDATE usage_events SET created_at=%s WHERE message_id=%s", (stamp, msg_id)
            )

    conv1 = repo.create_conversation(deepseek_id)
    repo.rename_conversation(conv1, "PySide6 多模型客户端架构", auto=True)
    add(
        conv1,
        "user",
        "我想用 Python + PySide6 做一个本地优先的多模型聊天客户端，支持多个 API、MySQL 存对话、"
        "每条消息可编辑重发，还要显示上下文剩余百分比。你建议怎么分层？",
        deepseek_id,
        "DeepSeek V3",
        "deepseek-chat",
        540,
    )
    add(
        conv1,
        "assistant",
        """建议按「UI / 应用服务 / 领域与数据 / 模型接入」四层拆，先把**可变状态集中到 MainWindow**，再让页面只负责渲染和发信号。

### 推荐结构

| 层 | 职责 | 例子 |
|---|---|---|
| UI | 展示、交互、动画 | `ChatPage`、`MessageBubble` |
| 应用服务 | 编排流程、线程生命周期 | `MainWindow` |
| 领域/数据 | 对话、消息、用量 CRUD | `Repository` |
| 模型接入 | 流式 SSE、协议适配 | `LLMClient` |

### 流式回复的关键点

```python
worker = ChatStreamWorker(provider, messages, cancel_event)
worker.delta.connect(chat_page.update_stream)
worker.succeeded.connect(self._on_stream_succeeded)
worker.start()
```

- 网络请求只放在 `QThread`，**不要在 GUI 线程里 `requests.post`**。
- worker 只负责产生文本和 usage，落库由主线程完成，避免跨线程复用 MySQL 连接。
- 每个对话保存自己的 `api_id`；切换 API 只更新这个字段，不改历史消息。
- 上下文百分比用「消息 token 估算之和 ÷ 模型窗口」计算，明确标注为约值。""",
        deepseek_id,
        "DeepSeek V3",
        "deepseek-chat",
        538,
        (428, 862),
    )
    add(
        conv1,
        "user",
        "流式输出和数据库写入应该怎么分工？如果用户在生成过程中关闭窗口怎么办？",
        deepseek_id,
        "DeepSeek V3",
        "deepseek-chat",
        120,
    )
    add(
        conv1,
        "assistant",
        """流式阶段建议**只更新内存中的气泡**，收到 `[DONE]` 后再一次性写入 assistant 消息和 usage 事件。

关闭窗口时：

1. 先询问用户是否停止生成；
2. 设置 `cancel_event`，worker 在下一段 SSE 到达时退出；
3. 若 5 秒内没有结束，再终止线程，避免进程悬挂；
4. 已生成的用户消息保留，半截回复是否保留由产品决定。这个项目选择「停止时保存已生成部分」。

这样数据库不会出现大量空 assistant 消息，也能保证一次请求对应一条 usage 记录。""",
        deepseek_id,
        "DeepSeek V3",
        "deepseek-chat",
        118,
        (1260, 518),
    )
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE conversations SET last_message_at=%s WHERE id=%s",
            (now - timedelta(minutes=118), conv1),
        )

    conv2 = repo.create_conversation(claude_id)
    repo.rename_conversation(conv2, "MySQL 用量统计表设计", auto=True)
    add(
        conv2,
        "user",
        "用量统计要同时支持总量和按对话查看，还要在消息被编辑、截断、删除后自动更新。表应该怎么设计？",
        claude_id,
        "Claude Sonnet",
        "claude-sonnet-4-20250514",
        120,
    )
    add(
        conv2,
        "assistant",
        """核心原则：**原始消息只存一份，统计从消息/事件聚合，不维护容易漂移的缓存总量**。

```sql
CREATE TABLE usage_events (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  conversation_id BIGINT NOT NULL,
  message_id BIGINT NULL,
  api_alias VARCHAR(80),
  kind VARCHAR(16) DEFAULT 'chat',
  prompt_tokens INT DEFAULT 0,
  completion_tokens INT DEFAULT 0,
  total_tokens INT DEFAULT 0
);
```

- `message_id` 外键 `ON DELETE CASCADE`：删除或截断消息时，对应 usage 自动消失。
- 自动标题这类没有消息的调用，`message_id=NULL`，只挂 `conversation_id`。
- 总量查询直接 `SUM(total_tokens)`，不需要事务性维护 `total` 字段。
- 上下文占用与累计用量分开：前者按当前消息估算，后者是真实 API 账单。""",
        claude_id,
        "Claude Sonnet",
        "claude-sonnet-4-20250514",
        118,
        (356, 704),
    )
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE conversations SET last_message_at=%s WHERE id=%s",
            (now - timedelta(hours=2), conv2),
        )

    conv3 = repo.create_conversation(deepseek_id)
    repo.rename_conversation(conv3, "周末杭州两日游", auto=True)
    add(
        conv3,
        "user",
        "下周末去杭州两天，住在西湖附近，不想太赶。帮我排一个轻松一点的行程，顺便推荐几家本地菜。",
        deepseek_id,
        "DeepSeek V3",
        "deepseek-chat",
        60 * 26,
    )
    add(
        conv3,
        "assistant",
        """两天一夜可以这样安排，重点是**少换地方、把傍晚留给湖边**。

### Day 1
- 上午：北山街散步 → 断桥 → 白堤
- 午后：孤山、浙江省博物馆，找家湖边咖啡馆休息
- 傍晚：苏堤看日落，晚饭去茅家埠一带

### Day 2
- 早上：灵隐寺、飞来峰（尽量 8 点前到）
- 中午：龙井村吃农家菜
- 下午：九溪十八涧慢走，返程

本地菜可以试试：**片儿川、东坡肉、龙井虾仁、宋嫂鱼羹**。避开湖滨步行街正中心的游客店，往北山街、茅家埠走会安静很多。""",
        deepseek_id,
        "DeepSeek V3",
        "deepseek-chat",
        60 * 26 - 2,
        (286, 492),
    )
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE conversations SET last_message_at=%s WHERE id=%s",
            (now - timedelta(hours=26), conv3),
        )

    conv4 = repo.create_conversation(deepseek_id)
    repo.rename_conversation(conv4, "Rust 所有权与生命周期", auto=True)
    add(
        conv4,
        "user",
        "用尽量直白的话解释 Rust 的所有权和生命周期，最好配一个会编译失败的例子。",
        deepseek_id,
        "DeepSeek V3",
        "deepseek-chat",
        60 * 52,
    )
    add(
        conv4,
        "assistant",
        """所有权可以记成三条规则：

1. 每个值有且只有一个所有者；
2. 所有者离开作用域，值就被释放；
3. 赋值或传参默认是移动，不是复制。

```rust
fn main() {
    let s = String::from("hello");
    let t = s;
    println!("{}", s); // error: borrow of moved value
}
```

生命周期不是让值活得更久，而是**告诉编译器引用至少能活多久**，从而拒绝悬垂引用。大多数业务代码里，先遵守所有权规则、必要时用 `clone()`，比一上来手写 `'a` 更容易推进。""",
        deepseek_id,
        "DeepSeek V3",
        "deepseek-chat",
        60 * 52 - 2,
        (212, 388),
    )
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE conversations SET last_message_at=%s WHERE id=%s",
            (now - timedelta(hours=52), conv4),
        )

    conv5 = repo.create_conversation(claude_id)
    repo.rename_conversation(conv5, "产品周报怎么写", auto=True)
    add(
        conv5,
        "user",
        "第一次写产品周报，给一个可以直接套用的结构，偏 B 端 SaaS。",
        claude_id,
        "Claude Sonnet",
        "claude-sonnet-4-20250514",
        60 * 80,
    )
    add(
        conv5,
        "assistant",
        """可以直接用这个五段式：

1. **本周结论**：一句话说明版本/指标是否按计划推进。
2. **关键进展**：只写结果和证据，不写流水账。
3. **数据变化**：对比上周，解释异常。
4. **风险与阻塞**：明确需要谁在什么时间做什么决定。
5. **下周计划**：不超过三件最重要的事。

B 端产品尤其要写清「影响了多少客户/多少收入/哪个关键流程」，而不是「开了几次会、画了几个原型」。""",
        claude_id,
        "Claude Sonnet",
        "claude-sonnet-4-20250514",
        60 * 80 - 2,
        (168, 312),
    )
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE conversations SET last_message_at=%s WHERE id=%s",
            (now - timedelta(hours=80), conv5),
        )

    repo.record_usage(
        conv1,
        deepseek_provider,
        "deepseek-chat",
        142,
        18,
        160,
        kind="title",
    )
    print(f"Seeded database {name}: 5 conversations, 4 providers")
    db.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "api_chat_demo"
    if target == "api_chat":
        raise SystemExit("Refusing to overwrite the default api_chat database.")
    seed(target)
