# 参与项目

欢迎通过 Issue 或 Discussion 先说明你准备处理的内容，避免重复工作。

## 最需要帮助的方向

- 强化学习：评估当前 observation / action / reward 设计，改进离线可运行的模型与训练流程。
- 卡牌与规则：补充后续卡包，核对效果、触发时点和边界组合。
- 英文本地化：提供可本地分发的英文卡图与对应卡牌译文。
- 测试：提交可复现的最小牌局、Replay 或自动化回归测试。
- 联机：不同地区、不同网络与重连场景的真实验证。

## 提交前

```powershell
python smoke_clean_release.py
python -m pytest tests -q
npm run test:multiplayer-electron
npm run electron:build-main
```

只提交当前改动需要的文件。不要提交：

- `data/codeman_ai/` 下的个人记忆、Replay、候选或 champion。
- `data/ai_challenges/` 与本机训练输出。
- `node_modules/`、缓存、日志、`.env`、密码或服务器私钥。
- 未确认分发权利的大型素材包；请先通过 Issue 讨论存放位置。

AI 改动请同时说明：起始模型、数据来源、训练配置、评估对手、随机种子与实际结果。不要只以单局胜负判断模型变强。

