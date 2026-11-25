# GitHub 网页登录态：我自己的浏览器拿着他的账号

2026-11-24 打通。**目标不是「能推代码」（`gh` token 早就行），是「能像人一样打开网页看什么都行」**——比如打开 PR 页面看到维护者完整的英文回复和语气，而不只是 API 返回的 JSON。

## 三种访问方式，边界不同

| 方式 | 能干什么 | 局限 |
| --- | --- | --- |
| `gh` CLI（`gho_` token） | 读写仓库、发 Release、开 PR、查 checks、看 issue | 只能碰 API 覆盖到的；网页设置页、安全日志、Actions 原始日志看不了 |
| 借屏幕（截屏 + 鼠标） | 任何他的浏览器能打开的页面 | 他的 Edge 得开着，窗口不能关，鼠标会动他的屏 |
| **原生 profile（本文）** | **headless 也能直接进 github.com，不用他开窗口** | profile 含凭据，等同敏感资产 |

## 失败的路：复制他的 Edge profile

第一次尝试是「把他 Edge 的 `Local State` + `Default\Network\Cookies` 复制到临时目录，用 `--user-data-dir` 指过去」。

**结果：GitHub 直接把我踢到登录页。**

```bash
# 打开 settings/profile，URL 被重定向：
https://github.com/login?return_to=https%3A%2F%2Fgithub.com%2Fsettings%2Fprofile
```

根因是 **Edge 155 的 App-Bound Encryption**：cookies 的加密密钥绑定在**原 profile 路径 + 系统服务**上，复制到别的目录后密钥解不开，浏览器认为「没有 cookie」。

> 这是浏览器的**安全设计**，防的就是「复制 profile 偷登录态」。绕过它等于降级安全性，不值得。

## 成功的路：用他的密码，在**我自己的** profile 里登一次

关键差别：**不要搬他的 profile，要在他给的密码基础上，让我自己的 profile 走一遍正常登录。**

### 步骤

1. **窗口模式**启动 Edge（不是 headless）：

   ```bash
   msedge.exe --remote-debugging-port=9222 \
     --user-data-dir="C:/Users/Administrator/.dsh/browsers/github" \
     --no-first-run --no-default-browser-check \
     "https://github.com/login"
   ```

   ⚠️ **必须窗口模式**：headless 打开 `github.com/login` 时 `document.body` 是 `null`（HTML 卡在 17K 字符不动，等 60 秒也一样），表单元素拿不到。首页能开，登录页不行。

2. **填表单提交**（CDP eval，密码从 `C:\Users\Administrator\.dsh\secrets\github-password.txt` 读，不落进命令历史）：

   ```js
   const u = document.querySelector('#login_field');
   const p = document.querySelector('#password');
   u.value = 'Uneadlight'; p.value = '<password>';
   u.dispatchEvent(new Event('input', {bubbles:true}));
   p.dispatchEvent(new Event('input', {bubbles:true}));
   document.querySelector('input[type=submit]').click();
   ```

3. **2FA 页默认是 WebAuthn**，要切到 TOTP：

   - 点 `More options` → 出现三个链接：`GitHub Mobile` / `Authenticator app` / `2FA recovery code`
   - 点 **`Authenticator app`** → URL 变成 `/sessions/two-factor/app`
   - 输入框 `#app_totp`（`name=app_otp`），填用户给的 6 位码并提交

4. **登录成功后，profile 固定保留**：

   ```
   C:\Users\Administrator\.dsh\browsers\github   （118 MB，含凭据）
   ```

   选 `.dsh` 的理由：**不在 git 仓库里**、也不在 `.tmp`（不会被清理脚本扫走）。

### 验证持久性（关键）

```bash
# 1. 关掉浏览器
# 2. 用同一 profile 以 headless 重启
msedge.exe --headless=new --remote-debugging-port=9222 \
  --user-data-dir="C:/Users/Administrator/.dsh/browsers/github" --disable-gpu about:blank

# 3. 打开设置页，查 meta
# 结果：{"title":"Your profile","url":"https://github.com/settings/profile","user_login":"Uneadlight"}
```

**关掉重开仍是 `user_login: Uneadlight`** —— 说明凭据存在 profile 里，不是靠进程内存。

### 启动脚本

`E:\DS公作区\tools\gh-browser.cmd`

```cmd
gh-browser.cmd           :: 窗口模式（任何页面都能渲染）
gh-browser.cmd headless  :: 无头模式 + CDP 9222
```

## 网络：时通时不通，别急着判「方案不行」

同一天、同一台机器、同一个 `github.com`：

| 时刻 | `curl github.com` |
| --- | --- |
| 21:47 | ❌ 000 / 21.055 s（超时） |
| 22:15（窗口刚开） | ❌ `ERR_CONNECTION_TIMED_OUT` |
| 22:20 | ✅ **200 / 0.97 s** |

而 `api.github.com` 一直 200（0.37 s）。

**判据**：失败时先跑 `curl -o NUL -w "%{http_code} %{time_total}" --max-time 15 https://github.com/`，分清楚是「网络没通」还是「方案不对」。用户能点开而我不行，多半是他点的那一刻正好通。

## 安全边界

| 资产 | 位置 | 级别 |
| --- | --- | --- |
| GitHub 密码 | `C:\Users\Administrator\.dsh\secrets\github-password.txt` | 等同账号本人 |
| 恢复码（10 个一次性） | 同上目录 `github-recovery-codes.txt` | 丢失 2FA 设备时的最后手段 |
| 登录态 profile | `C:\Users\Administrator\.dsh\browsers\github` | 谁拿到谁就能用这个账号 |

三条自我约束：

1. **不拷到别处**、不进 git、不塞进任何备份以外的位置
2. 用之前说一声（尤其改设置类动作）
3. 用完留痕（决策日志 / 记忆）

## 什么时候该重走一遍

- 登录态失效（打开设置页又被踢到 `/login`）→ 用密码 + TOTP 重登一次，同 profile
- 需要换成另一个 GitHub 账号 → 换 `--user-data-dir`，不要覆盖现在的
- profile 损坏 → 删掉重来（118 MB，重登一次就有了）
