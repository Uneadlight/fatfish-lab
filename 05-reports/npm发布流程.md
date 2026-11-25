# npm 发布流程（2026-11-25 实测打通）

> 一句话：**用 Granular Access Token 发布，不用管 2FA、不用密码、不用扫码。**

## 一、为什么这件事花了很久

2026-11-25 晚上发布三个包（`dsh-env-doctor@0.6.25` / `dsh-vision@0.2.3` / `dsh-chat-background@0.3.2`），把能踩的坑全踩了一遍。记录在这里，以后按流程走，十分钟内发完。

## 二、三条登录路，只有一条能走

| 方式 | 结果 | 原因 |
|---|---|---|
| `npm login --auth-type=web` | ❌ 卡住 | 授权页要求「用**另一台有 passkey（通行密钥）的设备**扫码」做跨设备认证。只有一台电脑时这条路走不通 |
| `npm login --auth-type=legacy`（用户名+密码） | ❌ 报 npm 自身 bug | npm 11.19.1 下报 `Exit handler never called!`，走不完流程 |
| **GitHub OAuth** | ✅ **能用** | 网页登录页有「用 GitHub 账号登录」；GitHub 已登录时只需点一次「授权 npm 账户链接」 |

**GitHub OAuth 的实操**：
1. 用户在浏览器打开 `https://www.npmjs.com/login`
2. 选「**Sign in with GitHub / 用 GitHub 登录**」
3. GitHub 显示「**NPM 账户链接：NPM 希望访问您的 GitHub 账户**」→ 点绿色**「授权」**
4. 回到 npm，CLI 侧 `npm login --auth-type=web` 的后台进程输出 `Logged in on https://registry.npmjs.org/.`
5. 验证：`npm whoami --registry https://registry.npmjs.org` → `un10086`

## 三、发布凭据：Granular Access Token

**为什么不用 OTP**：账号的 2FA 是 `two-factor auth: auth-and-writes`，但绑的是**安全密钥（WebAuthn）而不是 TOTP 验证器**——拿不到 6 位码。

**为什么不用恢复码**：用一次恢复码会**冻结发布 72 小时**，它只能用于登录。

**正确做法**：
1. 浏览器打开 `https://www.npmjs.com/settings/un10086/tokens`
2. 点「**生成新令牌 / Generate New Token**」→ 选 **Granular Access Token**
3. 填：
   - **令牌名称**：`dsh-publish`
   - **☑ 绕过双因素认证（2FA）** ← **关键，必须勾**
   - **权限**：**读取和写入（发布并测试）**
   - **包范围**：**所有包**
   - **到期日期**：30 天或更长
4. 点「生成令牌」，复制 `npm_...`（**只显示一次**）
5. 存到 **`C:\Users\Administrator\.dsh\secrets\npm-token.txt`**

**token 格式校验**：`npm_` + 36 字符 = **总长 40**。

> 踩坑：从聊天里复制 token 时经常把末尾的句号/中文一起带进来，导致 `401`。用前先 `echo ${#TOKEN}` 核对长度 40。

## 四、发布命令

```bash
cd E:/DS公作区/<包名>
npm publish --registry https://registry.npmjs.org \
  "--//registry.npmjs.org/:_authToken=<token>"
```

**两个必须**：
1. **必须带 `--registry https://registry.npmjs.org`**——本机 npm 默认指向**淘宝镜像** `registry.npmmirror.com`，不显式指定推不上去
2. **必须带 token**——用 `--otp` 换不来码

**或者直接用脚本**（推荐）：

```bash
# 三个包全发
python E:/DS公作区/tools/publish-npm.py

# 只发一个
python E:/DS公作区/tools/publish-npm.py dsh-env-doctor

# 干跑看打包内容
python E:/DS公作区/tools/publish-npm.py --dry-run

# 只核对本地和线上版本
python E:/DS公作区/tools/publish-npm.py --check
```

## 五、发布后必须验证三件事

1. **线上版本对**：`npm view <包名> version --registry https://registry.npmjs.org`
   - 注意：刚发完几秒内可能查到旧版本（CDN 缓存），用 `npm view <包名> versions` 或 `dist-tags` 看更准
2. **tgz 实体对**：下载线上包，解出 `package/cordis.patch.yml`，用 `yaml.safe_load` 确认能解析、`name` 带引号
   - 这是 PR #17466 卡住的原始问题（缩进/引号坏导致装不上）
3. **PR 回信**：告诉维护者版本号和验证结果

## 六、2FA 与日常使用

- **发布**：用 token，**完全不需要 2FA**
- **网页上的敏感操作**（改设置、删 token）：需要 2FA（安全密钥 = Windows Hello / 指纹 / PIN）
- **分工**：网页操作用户自己在浏览器做；命令行发布我用 token。互不干扰

## 七、相关文件

| 文件 | 用途 |
|---|---|
| `C:\Users\Administrator\.dsh\secrets\npm-token.txt` | 发布 token（绕过 2FA，有效期到 2027-02-20） |
| `C:\Users\Administrator\.dsh\secrets\npm-recovery-codes.txt` | 恢复码（**只能登录，不能发布**） |
| `E:\DS公作区\tools\publish-npm.py` | 一键发布脚本 |
