# Answer with HTML — 可移植维护版

仅在用户明确要求 HTML 输出或编辑现有页面时生成页面。普通问题不自动转换为 HTML。维护、设置和更新请求不生成页面。

本地版本基于上游 0.5.0，固定提交 `19b2b5b07676d3e65c83ca9a7b6621f300b54c92`。核心工作流适用于能够读写文件并运行 Node.js 20+ 的代理，不代表已测试所有代理产品或操作系统。

完整说明见 [README](README.md)、[SKILL.md](skills/answer-me-with-html/SKILL.md) 和 [验证记录](docs/acceptance.md)。默认离线；可信自定义 HTML/SVG 与网络资源需要每次调用分别显式启用。更新必须先暂存、构建、验证和备份，不要直接覆盖维护版。
