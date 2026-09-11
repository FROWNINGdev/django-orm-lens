# 规则参考

本节收录 Django ORM Lens 规则参考中已有的简体中文翻译。每个 `DOL` 编号都对应一项由 VS Code 扩展在编写代码时运行的静态检查。

尚未翻译的规则请参阅[完整英文规则参考](../../../rules/README.md)。

## 日期时间规则

| 代码 | 规则 | 类别 | 默认严重程度 | 适用性 |
|---|---|---|---|---|
| [DOL021](DOL021.md) | 应使用 `timezone.now()`，而不是 `datetime.now()` | datetime | warning | suggestion |
| [DOL022](DOL022.md) | `datetime.utcnow()` 已被弃用 | datetime | warning | suggestion |
