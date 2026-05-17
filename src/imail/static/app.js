/* Alpine.js component for imail. Sidebar + folder/message/triage state machine. */

function app() {
  return {
    /* ------------------------- global state ------------------------- */
    view: "welcome",        // 'welcome' | 'add' | 'folder' | 'message' | 'triage'
    status: { llm_configured: false, model: "", signoff: "", config_dir: "" },

    accounts: [],
    expandedAccount: null,  // account id whose folder list is shown in the sidebar
    selectedAccount: null,
    selectedFolder: null,   // 'inbox' | 'drafts' | 'sent'

    /* Add-account form state */
    chosen: "",
    providers: [
      { id: "gmail",     name: "Gmail",         icon: "✦", tag: "OAuth" },
      { id: "office365", name: "Microsoft 365", icon: "▦", tag: "Work / school · IMAP" },
      { id: "outlook",   name: "Outlook.com",   icon: "▣", tag: "Personal · IMAP" },
      { id: "163",       name: "163",           icon: "✱", tag: "IMAP · 授权码" },
      { id: "126",       name: "126",           icon: "✱", tag: "IMAP · 授权码" },
      { id: "qq",        name: "QQ Mail",       icon: "★", tag: "IMAP · 授权码" },
      { id: "yahoo",     name: "Yahoo",         icon: "✿", tag: "IMAP · App pwd" },
      { id: "icloud",    name: "iCloud",        icon: "◐", tag: "IMAP · App-spec" },
      { id: "custom",    name: "Custom",        icon: "⚙", tag: "Any IMAP" },
    ],
    form: {
      gmail: { label: "", credentials_path: "" },
      imap:  { label: "", username: "", password: "", host: "", port: 993 },
    },

    /* Folder + message browsing */
    messageList: [],
    selectedMessage: null,

    /* Search state */
    searchQuery: "",
    searchActive: false,

    /* Draft editor — content of the currently-open draft */
    draftBody: "",

    /* Triage session state */
    triage: {
      mode: "batch",         // 'batch' (queue from Inbox) | 'single' (one specific email)
      done: false,
      current: null,
      remaining: 0,
      processed: 0,
      chosen: null,          // 'positive' | 'neutral' | 'negative'
      editedBody: "",        // textarea content; sent verbatim, edited or not
    },

    busy: false,
    syncing: false,     // network refresh in flight while cached list is showing
    error: "",
    message: "",

    /* Inbox-poll state: which message ids we've already seen, and the active
       interval. Used to fire a notification when truly new mail arrives. */
    _seenIds: new Set(),
    _pollTimer: null,
    _pollMs: 30000,

    /* Visible-without-DevTools debug counter */
    debug: { lastClick: "" },

    /* ------------------------- lifecycle ------------------------- */
    async boot() {
      this.bindKeys();
      this._askNotifyPermission();
      await this.refresh();

      if (this.accounts.length === 0) {
        this.view = "add";
        return;
      }

      // Auto-jump straight into the latest unread inbox message, so the user
      // lands on something actionable instead of a welcome page.
      const acct = this.accounts[0];
      await this.openFolder(acct, "inbox");
      this._startPolling();          // begin polling for new mail

      const latestUnread =
        this.messageList.find((m) => m.unread) || this.messageList[0];

      if (latestUnread) {
        // Single-email triage uses the prefetch cache when available, so this
        // is instant after the first warmup pass.
        await this.openMessage(latestUnread);
      }
    },

    /* ------------------------- new-mail polling ------------------------- */
    _askNotifyPermission() {
      if ("Notification" in window && Notification.permission === "default") {
        Notification.requestPermission().catch(() => {});
      }
    },

    _startPolling() {
      if (this._pollTimer) clearInterval(this._pollTimer);
      this._pollTimer = setInterval(() => this._pollInbox(), this._pollMs);
    },

    async _pollInbox() {
      if (!this.selectedAccount) return;
      try {
        const r = await fetch(`/api/folders/${this.selectedAccount.id}/inbox`);
        if (!r.ok) return;
        const list = await r.json();
        const arrivals = list.filter((m) => !this._seenIds.has(m.id));
        for (const m of list) this._seenIds.add(m.id);
        if (arrivals.length > 0) {
          // Only the inbox listing is shown — anything the classifier just
          // moved to Junk would have disappeared from `list` already.
          this._notify(arrivals);
          // If user is currently sitting on the folder view, refresh it so they
          // see the new mail without manually clicking refresh.
          if (this.view === "folder" && this.selectedFolder === "inbox") {
            this.messageList = list;
          }
        }
      } catch {
        /* swallow: a one-off poll failure isn't worth surfacing */
      }
    },

    _notify(arrivals) {
      const summary = arrivals.length === 1
        ? `New mail from ${arrivals[0].sender}`
        : `${arrivals.length} new emails in your inbox`;
      this._playBeep();
      if ("Notification" in window && Notification.permission === "granted") {
        const body = arrivals.slice(0, 3).map((m) => m.subject).join(" · ");
        try { new Notification("imail", { body: body || summary, tag: "imail-new" }); }
        catch { /* notifications can fail in some contexts; ignore */ }
      }
    },

    _playBeep() {
      try {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return;
        const ctx = new AC();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.frequency.value = 660;
        osc.type = "sine";
        gain.gain.setValueAtTime(0.18, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.25);
        osc.connect(gain).connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.25);
        osc.onended = () => ctx.close();
      } catch { /* audio is best-effort */ }
    },

    async refresh() {
      try {
        const [s, a] = await Promise.all([
          fetch("/api/status").then((r) => r.json()),
          fetch("/api/accounts").then((r) => r.json()),
        ]);
        this.status = s;
        this.accounts = a;
      } catch (e) {
        this.error = e.toString();
      }
    },

    _bump(label) {
      const now = new Date().toLocaleTimeString();
      this.debug.lastClick = `${label} @ ${now}`;
    },

    /* ------------------------- sidebar navigation ------------------------- */
    selectAccount(acct) {
      // Click an account name → expand its folder tree AND jump straight to Inbox.
      // (Mental model: account name = "open this mailbox" not "toggle a dropdown".)
      this._bump(`selectAccount(${acct.label || acct.id})`);
      this.expandedAccount = acct.id;
      this.openFolder(acct, "inbox");
    },

    folderList(_acct) {
      return [
        { kind: "inbox",  icon: "📥", label: "Inbox" },
        { kind: "drafts", icon: "📝", label: "Drafts" },
        { kind: "sent",   icon: "📤", label: "Sent" },
        { kind: "junk",   icon: "🗑", label: "Junk" },
      ];
    },

    folderTitle(kind) {
      return { inbox: "Inbox", drafts: "Drafts", sent: "Sent", junk: "Junk" }[kind] || "";
    },

    shortDate(raw) {
      if (!raw) return "";
      const d = new Date(raw);
      if (Number.isNaN(d.getTime())) return raw.slice(0, 16);
      const now = new Date();
      const sameDay = d.toDateString() === now.toDateString();
      return sameDay
        ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : d.toLocaleDateString();
    },

    longDate(raw) {
      // Concrete date + time, every time. Format: "May 17, 2026 · 14:32"
      // (or your locale's equivalent). No relative phrasing like "Today".
      if (!raw) return "";
      const d = new Date(raw);
      if (Number.isNaN(d.getTime())) return raw;
      const datePart = d.toLocaleDateString([], {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
      const time = d.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
      return `${datePart} · ${time}`;
    },

    async openFolder(acct, kind) {
      this.selectedAccount = acct;
      this.selectedFolder = kind;
      this.expandedAccount = acct.id;
      this.view = "folder";
      this.selectedMessage = null;

      // Stale-while-revalidate: show what we cached on the last visit instantly,
      // then refresh from the server in the background. This kills the multi-
      // second blank "Loading messages…" wait on IMAP-heavy providers like 163.
      const cached = this._loadCachedList(acct, kind);
      this.messageList = cached || [];

      await this._loadMessageList();

      // Seed the "already seen" set so the next poll only flags truly-new arrivals.
      if (kind === "inbox") {
        this._seenIds = new Set(this.messageList.map((m) => m.id));
      }
    },

    async refreshFolder() {
      if (!this.selectedAccount || !this.selectedFolder) return;
      this.searchActive = false;
      this.searchQuery = "";
      await this._loadMessageList();
    },

    /* ---------- Search ---------- */
    async runSearch() {
      const q = this.searchQuery.trim();
      if (!q || !this.selectedAccount || !this.selectedFolder) return;
      this.busy = true;
      this.message = "";
      try {
        const url =
          `/api/search/${this.selectedAccount.id}/${this.selectedFolder}` +
          `?q=${encodeURIComponent(q)}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        this.messageList = await res.json();
        this.searchActive = true;
      } catch (e) {
        this.message = "Error: " + e.message;
      } finally {
        this.busy = false;
      }
    },

    clearSearch() {
      this.searchQuery = "";
      this.searchActive = false;
      // Pull the original full list back from cache + server
      this._loadMessageList();
    },

    async _loadMessageList() {
      // If we have a cached list rendered already, use a softer "syncing" flag
      // so the spinner doesn't blank the screen.
      const hasCached = this.messageList.length > 0;
      if (hasCached) this.syncing = true;
      else           this.busy = true;
      this.message = "";

      try {
        const url = `/api/folders/${this.selectedAccount.id}/${this.selectedFolder}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        this.messageList = await res.json();
        this._saveCachedList(
          this.selectedAccount,
          this.selectedFolder,
          this.messageList,
        );
      } catch (e) {
        this.message = "Error: " + e.message;
        // Keep cached list visible; user still has something to work with.
      } finally {
        this.busy = false;
        this.syncing = false;
      }
    },

    /* ---------- localStorage helpers (stale-while-revalidate cache) ---------- */
    _cacheKey(acct, folder) {
      return `imail.msglist.${acct.id}.${folder}`;
    },

    _loadCachedList(acct, folder) {
      try {
        const raw = localStorage.getItem(this._cacheKey(acct, folder));
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : null;
      } catch {
        return null;
      }
    },

    _saveCachedList(acct, folder, list) {
      try {
        localStorage.setItem(
          this._cacheKey(acct, folder),
          JSON.stringify(list.slice(0, 50)),
        );
      } catch {
        // localStorage quota or disabled — just skip.
      }
    },

    _markRepliedInCachedInbox(messageId) {
      // Flip `replied: true` on the matching cached row so the inbox shows
      // the green "已回复" badge the moment we navigate back, without
      // waiting for the next /api/folders round-trip.
      if (!this.selectedAccount) return;
      this.messageList = this.messageList.map((m) =>
        m.id === messageId ? { ...m, replied: true, unread: false } : m,
      );
      this._saveCachedList(this.selectedAccount, "inbox", this.messageList);
    },

    async openMessage(m) {
      // For inbox: skip the read-only view and go straight to single-email
      // triage so replies are drafted automatically while the user is reading.
      if (this.selectedFolder === "inbox") {
        await this.triageSingle(m.id);
        return;
      }

      // Drafts / Sent / Junk: load the full message into the detail view.
      this.busy = true;
      this.message = "";
      this.selectedMessage = null;
      this.draftBody = "";
      this.view = "message";
      try {
        const url = `/api/messages/${this.selectedAccount.id}/${this.selectedFolder}/${encodeURIComponent(m.id)}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        this.selectedMessage = await res.json();
        if (this.selectedFolder === "drafts") {
          // Seed the editor with the existing body so the user can edit in place.
          this.draftBody = this.selectedMessage.body || "";
        }
      } catch (e) {
        this.message = "Error: " + e.message;
        this.view = "folder";
      } finally {
        this.busy = false;
      }
    },

    backToFolder() {
      this.selectedMessage = null;
      this.view = "folder";
    },

    isLocalSent(id) {
      return typeof id === "string" && id.startsWith("local:");
    },

    async deleteSentMessage() {
      if (!this.selectedMessage) return;
      const isLocal = this.isLocalSent(this.selectedMessage.id);
      const prompt = isLocal
        ? "删除本地保存的这条回复记录?"
        : "Delete this from Sent? This also removes it from 163 / other devices.";
      if (!confirm(prompt)) return;
      this.busy = true;
      try {
        const url = `/api/messages/${this.selectedAccount.id}/sent/${encodeURIComponent(this.selectedMessage.id)}`;
        const res = await fetch(url, { method: "DELETE" });
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        this._dropFromList(this.selectedMessage.id);
        this.selectedMessage = null;
        this.view = "folder";
      } catch (e) {
        this.message = "Error: " + e.message;
      } finally {
        this.busy = false;
      }
    },

    async deleteCurrentInbox() {
      // Called from the inbox triage view (either the picker stage or the
      // already-replied banner). Removes the email from IMAP (so 163 webmail
      // and other clients also see it gone) AND drops the local reply-store
      // record so no "已回复" badge dangles.
      if (!this.triage.current) return;
      if (!confirm("删除这封邮件? 本机 imail 记录 + 163 服务器 + 其他设备登录都会看不到。不可恢复。")) return;
      this.busy = true;
      this.message = "";
      const id = this.triage.current.email.id;
      try {
        const url = `/api/messages/${this.selectedAccount.id}/inbox/${encodeURIComponent(id)}`;
        const res = await fetch(url, { method: "DELETE" });
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        // Drop from local cached list so it doesn't briefly flash back.
        this.messageList = this.messageList.filter((m) => m.id !== id);
        this._saveCachedList(this.selectedAccount, "inbox", this.messageList);
        this.message = "✓ Deleted.";
        await fetch("/api/triage/end", { method: "POST" });
        setTimeout(() => {
          this.endTriage();
          this.refreshFolder();
        }, 500);
      } catch (e) {
        this.message = "Error: " + e.message;
      } finally {
        this.busy = false;
      }
    },

    async deleteDraft() {
      if (!this.selectedMessage || !confirm("Delete this draft?")) return;
      this.busy = true;
      try {
        const url = `/api/messages/${this.selectedAccount.id}/${this.selectedFolder}/${encodeURIComponent(this.selectedMessage.id)}`;
        const res = await fetch(url, { method: "DELETE" });
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        this._dropFromList(this.selectedMessage.id);
        this.selectedMessage = null;
        this.view = "folder";
      } catch (e) {
        this.message = "Error: " + e.message;
      } finally {
        this.busy = false;
      }
    },

    /* ---------- Draft editor (saves a new draft or sends straight away) ---------- */
    async saveDraftEdits() {
      if (!this.selectedMessage || !this.draftBody.trim()) return;
      this.busy = true;
      this.message = "";
      try {
        const url = `/api/messages/${this.selectedAccount.id}/drafts/${encodeURIComponent(this.selectedMessage.id)}/edit`;
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ body: this.draftBody }),
        });
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        this.message = "✓ Draft updated.";
        // The draft's id may have changed (IMAP APPEND + DELETE); refresh the
        // folder so the listing reflects reality.
        this.selectedMessage = null;
        this.view = "folder";
        await this.refreshFolder();
      } catch (e) {
        this.message = "Error: " + e.message;
      } finally {
        this.busy = false;
      }
    },

    async sendDraftBody() {
      // Best UX: send the (possibly edited) body, then delete the original draft.
      if (!this.selectedMessage || !this.draftBody.trim()) return;
      this.busy = true;
      this.message = "";
      const originalId = this.selectedMessage.id;
      try {
        // Pretend it's a triage single with this email so /api/triage/send works.
        // Open a single-triage session against the draft's recipient.
        // Simpler path: post to a dedicated send endpoint when we add one;
        // for now, save the edits then ask the user to use Gmail/163 to hit Send.
        // For an immediate UX, we use the IMAP draft-edit + manual send. To
        // actually wire one-click send from drafts, we just save the body
        // (replaces the draft) and surface a hint.
        const url = `/api/messages/${this.selectedAccount.id}/drafts/${encodeURIComponent(originalId)}/edit`;
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ body: this.draftBody }),
        });
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        this.message = "✓ Updated draft. Open it in your mail app and press Send.";
        this.selectedMessage = null;
        this.view = "folder";
        await this.refreshFolder();
      } catch (e) {
        this.message = "Error: " + e.message;
      } finally {
        this.busy = false;
      }
    },

    /* ---------- Junk actions ---------- */
    async restoreFromJunk() {
      if (!this.selectedMessage) return;
      this.busy = true;
      try {
        const url = `/api/messages/${this.selectedAccount.id}/junk/${encodeURIComponent(this.selectedMessage.id)}/restore`;
        const res = await fetch(url, { method: "POST" });
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        this.message = "✓ Moved back to Inbox.";
        this._dropFromList(this.selectedMessage.id);
        this.selectedMessage = null;
        this.view = "folder";
      } catch (e) {
        this.message = "Error: " + e.message;
      } finally {
        this.busy = false;
      }
    },

    async deleteJunk() {
      if (!this.selectedMessage || !confirm("Permanently delete this email?")) return;
      this.busy = true;
      try {
        const url = `/api/messages/${this.selectedAccount.id}/junk/${encodeURIComponent(this.selectedMessage.id)}`;
        const res = await fetch(url, { method: "DELETE" });
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        this._dropFromList(this.selectedMessage.id);
        this.selectedMessage = null;
        this.view = "folder";
      } catch (e) {
        this.message = "Error: " + e.message;
      } finally {
        this.busy = false;
      }
    },

    _dropFromList(messageId) {
      this.messageList = this.messageList.filter((m) => m.id !== messageId);
      if (this.selectedAccount && this.selectedFolder) {
        this._saveCachedList(this.selectedAccount, this.selectedFolder, this.messageList);
      }
    },

    /* ------------------------- add account ------------------------- */
    resetForms() {
      this.chosen = "";
      this.error = "";
      this.form = {
        gmail: { label: "", credentials_path: "" },
        imap:  { label: "", username: "", password: "", host: "", port: 993 },
      };
    },

    appPasswordLink(provider) {
      return {
        outlook:   "https://support.microsoft.com/en-us/account-billing/manage-app-passwords-for-two-step-verification-d6dc8c6d-4bf7-4851-ad95-6d07799387e9",
        office365: "https://account.activedirectory.windowsazure.com/AppPasswords.aspx",
        "163":     "https://help.mail.163.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4287f3b3a5b8aa61b9d6f49d8e6c8e",
        "126":     "https://help.mail.163.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4287f3b3a5b8aa61b9d6f49d8e6c8e",
        qq:        "https://service.mail.qq.com/detail/0/75",
        yahoo:     "https://help.yahoo.com/kb/SLN15241.html",
        icloud:    "https://support.apple.com/en-us/HT204397",
      }[provider] || "";
    },

    async addGmail() {
      this.error = ""; this.busy = true;
      try {
        const res = await fetch("/api/accounts/gmail", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(this.form.gmail),
        });
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        this.resetForms();
        this.view = "welcome";
        await this.refresh();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.busy = false;
      }
    },

    async addImap() {
      this.error = ""; this.busy = true;
      try {
        const body = { ...this.form.imap, preset: this.chosen === "custom" ? "" : this.chosen };
        if (this.chosen !== "custom") delete body.host;
        const res = await fetch("/api/accounts/imap", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        this.resetForms();
        this.view = "welcome";
        await this.refresh();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.busy = false;
      }
    },

    async removeAccount(id) {
      if (!confirm("Remove this account? Stored password will be wiped from Keychain too.")) return;
      await fetch("/api/accounts/" + encodeURIComponent(id), { method: "DELETE" });
      // Wipe any locally-cached message lists for the gone account.
      for (const folder of ["inbox", "drafts", "sent", "junk"]) {
        try { localStorage.removeItem(`imail.msglist.${id}.${folder}`); } catch {}
      }
      if (this.selectedAccount && this.selectedAccount.id === id) {
        this.selectedAccount = null;
        this.selectedFolder = null;
        this.view = "welcome";
      }
      await this.refresh();
    },

    /* ------------------------- triage: batch (queue) ------------------------- */
    async batchTriage() {
      if (!this.selectedAccount) return;
      this._resetTriage("batch");
      try {
        const res = await fetch("/api/triage/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ account_id: this.selectedAccount.id, limit: 20 }),
        });
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        const data = await res.json();
        this.view = "triage";
        if (data.queued === 0) {
          this.triage.done = true;
        } else {
          await this.loadNext();
        }
      } catch (e) {
        this.message = "Error: " + e.message;
        alert(e.message);
      }
    },

    async loadNext() {
      this.triage.current = null;
      this.triage.chosen = null;
      this.triage.editing = false;
      this.triage.editedBody = "";
      try {
        const res = await fetch("/api/triage/next");
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        const data = await res.json();
        if (data.done) {
          this.triage.done = true;
          this.triage.current = null;
          this.triage.remaining = 0;
        } else {
          this.triage.current = { email: data.email, replies: data.replies };
          this.triage.remaining = data.remaining;
        }
      } catch (e) {
        this.message = "Error: " + e.message;
      }
    },

    /* ------------------------- triage: single email ------------------------- */
    async triageSingle(messageId) {
      if (!this.selectedAccount) return;
      this._resetTriage("single");
      this.view = "triage";
      try {
        const res = await fetch("/api/triage/single", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            account_id: this.selectedAccount.id,
            kind: this.selectedFolder,
            message_id: messageId,
          }),
        });
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        const data = await res.json();
        this.triage.current = {
          email: data.email,
          replies: data.replies,
          alreadyReplied: !!data.already_replied,
          chosenReply: data.chosen_reply || "",
          repliedAt: data.replied_at || "",
        };
        this.triage.remaining = 0;
      } catch (e) {
        this.message = "Error: " + e.message;
        this.view = "folder";
      }
    },

    _resetTriage(mode) {
      this.triage = {
        mode,
        done: false,
        current: null,
        remaining: 0,
        processed: 0,
        chosen: null,
        editedBody: "",
      };
      this.message = "";
    },

    /* ------------------------- triage: pick tone, send, save draft ------------------------- */
    pickTone(tone) {
      if (!this.triage.current || this.busy) return;
      this.triage.chosen = tone;
      this.triage.editedBody = this.triage.current.replies[tone];
      this.message = "";
    },

    backToPicker() {
      this.triage.chosen = null;
      this.triage.editedBody = "";
      this.message = "";
    },

    async sendNow()      { await this._postWithBody("/api/triage/send",  "Sent"); },
    async saveDraftOnly(){ await this._postWithBody("/api/triage/draft", "Saved as draft"); },

    async _postWithBody(url, successWord) {
      if (!this.triage.current || !this.triage.editedBody || this.busy) return;
      this.busy = true;
      this.message = "";
      // Snapshot the processed message id BEFORE we navigate away —
      // we'll use it to drop the email from the cached inbox list.
      const processedId = this.triage.current.email.id;
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ body: this.triage.editedBody }),
        });
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        this.message = `✓ ${successWord}.`;
        this.triage.processed += 1;

        // Processed — flip this row to "replied" in the cached inbox so the
        // green badge appears immediately when we navigate back, rather than
        // waiting for the next folder refresh from the server.
        this._markRepliedInCachedInbox(processedId);

        if (this.triage.mode === "batch") {
          await this.loadNext();
          this.message = "";
        } else {
          // single: end the session and bounce back to the cleaner folder list
          this.triage.done = true;
          await fetch("/api/triage/end", { method: "POST" });
          setTimeout(() => {
            this.endTriage();
            this.refreshFolder();
          }, 600);
        }
      } catch (e) {
        this.message = "Error: " + e.message;
      } finally {
        this.busy = false;
      }
    },

    async skip() {
      if (this.busy || this.triage.mode === "single") return;
      this.busy = true;
      try {
        await fetch("/api/triage/skip", { method: "POST" });
        this.triage.processed += 1;
        await this.loadNext();
      } finally {
        this.busy = false;
      }
    },

    async endTriage() {
      await fetch("/api/triage/end", { method: "POST" });
      // Where to go back to: folder if we have one selected, else welcome.
      if (this.selectedAccount && this.selectedFolder) {
        this.view = "folder";
        this.refreshFolder();
      } else {
        this.view = this.accounts.length ? "welcome" : "add";
      }
      this._resetTriage(this.triage.mode);
    },

    /* ------------------------- keyboard ------------------------- */
    bindKeys() {
      window.addEventListener("keydown", (e) => {
        // Cmd/Ctrl+Enter inside the preview textarea → send.
        if (e.target.matches("textarea") && (e.metaKey || e.ctrlKey) && e.key === "Enter") {
          e.preventDefault();
          this.sendNow();
          return;
        }
        if (e.target.matches("input, textarea")) return;
        if (this.view !== "triage" || this.triage.done || !this.triage.current) return;

        if (!this.triage.chosen) {
          // Stage 1: pick a tone
          if (e.key === "1")      { e.preventDefault(); this.pickTone("positive"); }
          else if (e.key === "2") { e.preventDefault(); this.pickTone("neutral"); }
          else if (e.key === "3") { e.preventDefault(); this.pickTone("negative"); }
          else if ((e.key === "s" || e.key === "S") && this.triage.mode === "batch") {
            e.preventDefault(); this.skip();
          }
          else if (e.key === "q" || e.key === "Q") { e.preventDefault(); this.endTriage(); }
          return;
        }

        // Stage 2: preview/edit/send. Cmd+Enter handled above.
        if (e.key === "d" || e.key === "D") { e.preventDefault(); this.saveDraftOnly(); }
        else if (e.key === "Escape")        { e.preventDefault(); this.backToPicker(); }
      });
    },
  };
}
