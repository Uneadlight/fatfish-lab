"""Task 3 的"活体角色"实现：把 LLM 包成可以被编排器当子进程调用的 Dev / QA。

这里是边缘节点定位的落点——Dev/QA 跑在本机 Ollama 上（零边际成本、不出本机），
最终裁决仍归 pytest 退出码（见 `orchestrator/loop.py`）。

模块：
    ollama_agent  走 /api/chat，用 `<<<FILE: 路径>>>` 分节协议收发文件补丁
"""

__all__: list[str] = []
