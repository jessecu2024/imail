<p align="center">
  <img src="https://raw.githubusercontent.com/jessecu2024/imail/main/src/imail/static/icon.svg" alt="imail" width="96" />
</p>

<h1 align="center">imail</h1>

<p align="center"><b>把你从冗余邮件中拯救出来。</b></p>
<p align="center"><i>1 次决策 · 1 个按键 · 1 封邮件搞定。</i></p>

---

## 谁适合用?

- 📨 **每天处理 ≥20 封邮件**的人:学生回导师 / 教授约会议 / 运营回客户 / HR 回简历
- 🇨🇳 **常用 163 / QQ / 学校邮箱**的人:imail 对国内 IMAP 邮箱专门做过适配
- 🌍 **回英文邮件**的人:imail 默认生成英文回复(`Dear X, … Best regards, …`),不管原邮件什么语言
- 🔒 **不想把整个邮箱搬到云端**的人:imail 不上传你的邮件,所有账号密码存系统钥匙串

---

---

## 一、安装(挑一条最顺手的)

> ⚠️ 需要 macOS / Linux / Windows + Python ≥ 3.11。Mac 用户最简单。

### 🍎 Mac 推荐:Homebrew(一行命令)

```bash
brew tap jessecu2024/tap
brew install imail
```

第一次大约要 **12-15 分钟**(后台编译一个依赖),之后启动只要 1 秒。

### 🐍 跨平台:Python(`uv` 或 `pipx`)

```bash
# 推荐 uv(更快)
uv tool install imail-cli

# 没装 uv 的话用 pipx
pipx install imail-cli
```

> 💡 包名是 `imail-cli`(PyPI 上 `imail` 被占用了),命令还是 `imail`。

### 🐳 Docker(不想装 Python)

```bash
docker run --rm -p 8765:8765 \
  -v ~/.config/imail:/root/.config/imail \
  -e DEEPSEEK_API_KEY=sk-... \
  ghcr.io/jessecu2024/imail:latest
```

然后浏览器打开 `http://localhost:8765`。

---

## 二、申请 DeepSeek API key(免费注册,约 2 分钟)

imail 用 DeepSeek 生成回复。第一次用要去他们网站注册 + 拿一个 API key。

1. 打开 <https://platform.deepseek.com/api_keys>(国内可直接访问)
2. 注册账号(手机号 / 邮箱都行)
3. 充值 **¥1 - ¥5** 就足够用很久 — 写一个 3 语气回复大概只花 **¥0.001**(千分之一元),¥5 能用几个月
4. 点 **Create API key**,起个名字(随便取),复制那个 `sk-xxxxxxxx`

> 隐私提示:邮件正文会发到 DeepSeek 服务器生成回复。如果不希望任何邮件正文离开你的电脑,可以把 `IMAIL_BASE_URL` 换成本地 Ollama / vLLM —— 见 Settings → Replies。

### 设置 key

把 key 加进你的 shell 配置(`~/.zshrc` 或 `~/.bashrc`):

```bash
export DEEPSEEK_API_KEY=sk-你的key
```

重启终端,然后启动 imail:

```bash
imail
```

浏览器会自动打开 <http://127.0.0.1:8765>。

> 💡 嫌每次设环境变量麻烦?创建 `~/.config/imail/.env`,写一行 `DEEPSEEK_API_KEY=sk-...` 即可,以后 `imail` 启动自动加载。

---

## 三、添加你的邮箱账号

首次打开是一个 **Add account** 页面。选你的邮箱类型:

### 🟢 Gmail(OAuth 一次同意,推荐)

参考 [docs/gmail-setup.md](gmail-setup.md) 配 Google Cloud Console。略复杂,但一劳永逸。

### 🟡 163 / 126 / QQ 邮箱(IMAP + 授权码)

1. 登录 163 邮箱网页版 → 设置 → POP3/SMTP/IMAP
2. 开启 **IMAP/SMTP 服务**,会生成一个 **16 位授权码** — 注意是授权码不是登录密码
3. 在 imail 选 **163** preset,填:
   - 邮箱:`你@163.com`
   - 密码:刚才那 16 位授权码

QQ / 126 同理,见 [docs/imap-setup.md](imap-setup.md) 的详细步骤。

### 🔵 Outlook / Office 365 / iCloud / Yahoo

同 IMAP + 应用专用密码(app password)。各家生成 app password 的位置不同,参考 [imap-setup.md](imap-setup.md)。

---

## 四、第一次使用 · 1 分钟体验

加完账号 → imail 会**自动跳到你最新的未读邮件**(如果有):

```
┌──────────────────────────────────────────────────────────────┐
│  From       advisor@uni.edu                                  │
│  Subject    Can you join the panel on Thursday?              │
│  …                                                           │
└──────────────────────────────────────────────────────────────┘
  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
  │ 1·POSITIVE  │   │ 2·NEUTRAL   │   │ 3·NEGATIVE  │
  │ Yes, I'll…  │   │ Let me…     │   │ Thanks for  │
  │             │   │             │   │ asking, but │
  └─────────────┘   └─────────────┘   └─────────────┘
```

- 按 `1` → 选 **肯定** 回复
- 按 `2` → 选 **中性** 回复(适合"我想想再回")
- 按 `3` → 选 **拒绝** 回复

选完进**编辑/确认**界面 — 你能微调文字,然后:

- `⌘↵`(Mac) / `Ctrl+↵`(Win/Linux) → 立刻发送
- 按 `D` → 只**存草稿**,自己去邮箱客户端发

回复永远以 `Dear <对方>` 开头,以 `Best regards, Jie Xu` 结尾,英文。

---

## 五、主要功能

### 📥 Inbox(收件箱)

- **未读邮件**:发件人前面有个**红色小圆点** + 整行字加粗
- **已回复**:绿色 ✓ Replied 徽章 + 整行变淡
- **最新邮件在顶部**,自动按时间倒序

### 🚩 Flagged(红旗 — 加星标的邮件)

像 Apple Mail / Outlook 的"标记"功能。任何邮件(inbox / sent / junk)都能加红旗 — 点行右侧那个 ▶ 红色旗子即可。所有加红旗的邮件汇总在左栏 **Flagged** 文件夹。

### 📤 Sent(已发送)

- imail 处理过的回复显示在最顶部(本地存的,瞬间出)
- 真实 IMAP 已发邮件接在下面
- 每行最左侧的 "→" 表示"这是发出去的",一眼就和 inbox 区分开
- **点开一封发出去的回复 → 下面有"回复的原邮件"卡片** — 让你想起来当初是回复啥的

### ✉️ Reply / Reply all / Forward(回复、全部回复、转发)

打开任何邮件 → 上方有 5 个按钮:

| 按钮 | 作用 |
|---|---|
| 回复 | 收件人自动填发件人,Subject 自动加 `Re:` |
| 全部回复 | (目前同回复,Cc 解析下一版) |
| 转发 | 主题加 `Fwd:`,正文带 `>` 引用原文,收件人留空 |
| 🚩 加红旗 | 在 IMAP 服务器打 \Flagged 标记 |
| 🗑 删除 | 服务器 expunge,**手机 / 163 网页版同步消失** |

### 🗑 删除

无论哪个文件夹,鼠标移到行右侧出现 × 按钮。点了**直接在 IMAP 服务器 EXPUNGE**,不只是本地隐藏 —— 你手机上 163 客户端、163 网页版,都会同步看不到那封。

### ⚙️ Settings(设置)— 右上角齿轮

- **Language / 界面语言** — 切英文 / 中文
- **Accounts / 账号** — 增删,看详细信息
- **Replies / 回复设置** — 看当前用的 model、签名怎么改
- **Keyboard shortcuts / 快捷键** — 完整一表
- **Privacy & security / 隐私** — 数据存哪里、什么会上 DeepSeek
- **Local data / 本地数据** — 配置目录位置(`~/.config/imail`)
- **About / 关于** — 版本、源代码链接

---

## 六、键盘快捷键(triage 视图里)

| 键 | 作用 |
|---|---|
| `1` | 选 positive 回复 |
| `2` | 选 neutral 回复 |
| `3` | 选 negative 回复 |
| `⌘↵` / `Ctrl+↵` | 立即发送所选回复 |
| `D` | 保存为草稿(不发) |
| `S` | 跳过这封 |
| `Q` | 结束本次处理 |

---

## 七、隐私 · 你的数据放哪里?

| 数据 | 在哪 |
|---|---|
| **邮件正文** | 本机内存。**会送到 DeepSeek 服务器**生成回复(不持久化在他们那) |
| **IMAP 密码 / 授权码** | macOS Keychain / Windows Credential Manager(系统级钥匙串),**不在文件里** |
| **OAuth token** | `~/.config/imail/token-*.json`,权限 0600(只有你能读) |
| **生成的 3 个回复** | `~/.config/imail/replies-*.json`,本地 JSON,加密由文件系统权限控制 |
| **你选了哪个回复** | 同上,永久保留 |

**imail 本身不向任何服务器发送遥测 / 统计数据**。

**imail 服务器只监听 127.0.0.1**(只你的电脑能访问),不要把它改成 0.0.0.0 上公网。

---

## 八、常见问题 (FAQ)

### 装完跑 `imail` 提示 `DEEPSEEK_API_KEY missing`

页面顶部会有红色横条提示三步:

1. 去 <https://platform.deepseek.com/api_keys> 拿 key
2. `export DEEPSEEK_API_KEY=sk-...` 或写进 `~/.config/imail/.env`
3. 重启 `imail`

### 我能完全离线(不依赖 DeepSeek)用吗?

可以。Settings → Replies → Endpoint 改成你本地跑的 Ollama / vLLM(任何 OpenAI 兼容接口都行):

```bash
export IMAIL_BASE_URL=http://localhost:11434/v1
export IMAIL_MODEL=qwen2.5:32b-instruct
imail
```

### 163 提示 "Unsafe Login" 或 "SMTP auth failed"

99% 是密码用错了。**必须用 16 位授权码,不是登录密码**。163 → 设置 → 邮箱账号 → POP3/IMAP/SMTP → 开启 IMAP/SMTP → 复制授权码。

### 我们公司 / 学校的邮箱(CityU / 某高校)登不上去

很多机构禁用了普通 IMAP / 拒绝第三方 OAuth。绕路:在原邮箱设个**自动转发**到你的 163,然后让 imail 接 163 即可。详见 [forwarding-workflow.md](forwarding-workflow.md)。

### 处理过的邮件红点又跳回来?

应该是过去版本的 bug,**v1.4.0 修了**。如果还看到:刷新页面,或 Settings → Accounts 删了重加。

### 这玩意要花多少钱?

DeepSeek 每封邮件 3 个回复一起算大概 **¥0.001**(千分之一元)。一天 30 封 = ¥0.03。一个月不到 ¥1。不充钱的话拿不到 key,所以你**至少需要充 ¥1**起步。

---

## 九、出问题了找谁?

- 直接微信我(你认识我的)
- 或者 GitHub 上提 issue:<https://github.com/jessecu2024/imail/issues/new?template=bug_report.yml>
- 想看代码 / 给意见:<https://github.com/jessecu2024/imail>

---

## 十、一句话总结

```
brew install jessecu2024/tap/imail   # (或 uv tool install imail-cli)
export DEEPSEEK_API_KEY=sk-...
imail
# → 浏览器自动开 http://127.0.0.1:8765 → 加账号 → 享受 1/2/3 处理邮件
```

祝清完邮箱后,你的下午多出 30 分钟做别的事。👋
