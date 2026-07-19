# Codex Pet Club Skill

让 Codex 按网站唯一 ID 自动安装桌宠，省去手动下载、解压与搬运文件。

## 能做什么

- 浏览远端已发布桌宠
- 下载并校验 Codex v2 桌宠包
- 记录已安装桌宠的目录版本与校验和
- 安装前自动备份同名本地桌宠
- 校验或打包本地桌宠
- 上传投稿并进入审核队列
- 绑定网站账户生成的 Skill Key，让作品自动归属账户
- 查看当前绑定的创作者身份，或解除本机绑定
- 按提交 ID 查询待审、通过、下架或拒绝状态
- 查看备份并一键恢复

安装与投稿都会校验 ZIP 路径、SHA-256、`spriteVersionNumber: 2`，以及 `1536 × 2288` WebP 图集尺寸。CLI 兼容 Windows 工具生成的 UTF-8 BOM，并在打包或安装时自动将 `pet.json` 规范化为无 BOM 的 UTF-8。

## 安装

把本仓库克隆到 Codex 的 skills 目录：

```powershell
git clone https://github.com/javaC2RenXiangjie/codex-pet-club-skill `
  "$env:USERPROFILE\.codex\skills\codex-pet-club"
```

重新打开 Codex 后，可以直接复制网站卡片中的 ID，然后说：

```text
使用 $codex-pet-club，把这个桌宠下载到我本地，ID：9d1ef2a4-55df-4d99-a722-18d1db7cb83a
```

Skill 默认连接正式桌宠库，无需额外配置。也可以直接调用随 Skill 提供的零依赖 CLI：

```powershell
python scripts/pet_club.py list
python scripts/pet_club.py install 9d1ef2a4-55df-4d99-a722-18d1db7cb83a
python scripts/pet_club.py installed
python scripts/pet_club.py configure --key cpc_sk_你的Key
python scripts/pet_club.py account
python scripts/pet_club.py validate C:\path\to\my-pet
python scripts/pet_club.py publish C:\path\to\my-pet
python scripts/pet_club.py status 9d1ef2a4-55df-4d99-a722-18d1db7cb83a
```

Key 在网站 `/account` 页面生成，原文只显示一次。配置时 CLI 会先向桌宠库验证身份，随后写入
`~/.codex/pet-club/config.json`；命令输出只显示 Key 掩码。投稿必须先绑定 Key，下载和安装桌宠不需要登录。
如果要解除这台电脑的绑定，运行：

```powershell
python scripts/pet_club.py configure --clear-key
```

解除本机绑定不会影响其他电脑。若要让所有使用同一个 Key 的电脑立即失效，请在网站账户页撤销该 Key。

本地开发时可临时覆盖桌宠库地址：

```powershell
python scripts/pet_club.py configure --api http://localhost:3001
```

## 仓库结构

```text
SKILL.md               Codex 工作流与安全规则
agents/openai.yaml     Skill 展示元数据
scripts/pet_club.py    本地与远端桌宠管理 CLI
references/api.md      桌宠库 API 契约
```

## 当前状态

这是 Codex Pet Club 的 beta 版本。上传需要创作者 Skill Key，默认进入审核队列，不会自动公开；公共库只返回已审核发布的桌宠。

## License

[MIT](LICENSE)
