/* Alpine.js component for the mail-triage SPA. */

function app() {
  return {
    /* ------------------------- state ------------------------- */
    view: "picker",          // 'picker' | 'add' | 'triage'
    status: { anthropic_configured: false, model: "", signoff: "", config_dir: "" },
    accounts: [],
    chosen: "",              // 'gmail' | 'outlook' | '163' | '126' | 'qq' | 'yahoo' | 'icloud' | 'custom'
    busy: false,
    error: "",
    message: "",

    /* available providers shown as tiles in the Add view */
    providers: [
      { id: "gmail",   name: "Gmail",   icon: "✦", tag: "OAuth" },
      { id: "outlook", name: "Outlook", icon: "▣", tag: "IMAP · App password" },
      { id: "163",     name: "163",     icon: "✱", tag: "IMAP · 授权码" },
      { id: "126",     name: "126",     icon: "✱", tag: "IMAP · 授权码" },
      { id: "qq",      name: "QQ Mail", icon: "★", tag: "IMAP · 授权码" },
      { id: "yahoo",   name: "Yahoo",   icon: "✿", tag: "IMAP · App password" },
      { id: "icloud",  name: "iCloud",  icon: "◐", tag: "IMAP · App-specific" },
      { id: "custom",  name: "Custom",  icon: "⚙", tag: "Any IMAP server" },
    ],

    /* form state */
    form: {
      gmail: { label: "", credentials_path: "" },
      imap:  { label: "", username: "", password: "", host: "", port: 993 },
    },

    /* triage session state */
    triage: {
      done: false,
      current: null,         // { email: {...}, replies: { positive, neutral, negative } }
      remaining: 0,
      processed: 0,
    },

    /* ------------------------- lifecycle ------------------------- */
    async boot() {
      this.bindKeys();
      await this.refresh();
    },

    async refresh() {
      try {
        const [s, a] = await Promise.all([
          fetch("/api/status").then((r) => r.json()),
          fetch("/api/accounts").then((r) => r.json()),
        ]);
        this.status = s;
        this.accounts = a;
        if (this.accounts.length === 0 && this.view === "picker") this.view = "add";
      } catch (e) {
        this.error = e.toString();
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
        outlook: "https://support.microsoft.com/en-us/account-billing/manage-app-passwords-for-two-step-verification-d6dc8c6d-4bf7-4851-ad95-6d07799387e9",
        "163":   "https://help.mail.163.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4287f3b3a5b8aa61b9d6f49d8e6c8e",
        "126":   "https://help.mail.163.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4287f3b3a5b8aa61b9d6f49d8e6c8e",
        qq:      "https://service.mail.qq.com/detail/0/75",
        yahoo:   "https://help.yahoo.com/kb/SLN15241.html",
        icloud:  "https://support.apple.com/en-us/HT204397",
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
        this.view = "picker";
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
        if (this.chosen !== "custom") delete body.host;  // server picks from preset
        const res = await fetch("/api/accounts/imap", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        this.resetForms();
        this.view = "picker";
        await this.refresh();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.busy = false;
      }
    },

    async removeAccount(id) {
      if (!confirm("Remove this account?")) return;
      await fetch("/api/accounts/" + encodeURIComponent(id), { method: "DELETE" });
      await this.refresh();
    },

    /* ------------------------- triage ------------------------- */
    async startTriage(accountId) {
      this.error = "";
      this.message = "";
      this.triage = { done: false, current: null, remaining: 0, processed: 0 };
      try {
        const res = await fetch("/api/triage/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ account_id: accountId, limit: 20 }),
        });
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        const data = await res.json();
        if (data.queued === 0) {
          this.triage.done = true;
        }
        this.view = "triage";
        if (data.queued > 0) await this.loadNext();
      } catch (e) {
        this.error = e.message;
        alert(e.message);  // visible in current view
      }
    },

    async loadNext() {
      this.triage.current = null;
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

    async chooseReply(tone) {
      if (!this.triage.current || this.busy) return;
      this.busy = true;
      this.message = "";
      try {
        const body = this.triage.current.replies[tone];
        const res = await fetch("/api/triage/draft", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ body }),
        });
        if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
        this.message = `✓ ${tone.toUpperCase()} draft saved. Loading next…`;
        this.triage.processed += 1;
        await this.loadNext();
        this.message = "";
      } catch (e) {
        this.message = "Error: " + e.message;
      } finally {
        this.busy = false;
      }
    },

    async skip() {
      if (this.busy) return;
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
      this.view = "picker";
      this.triage = { done: false, current: null, remaining: 0, processed: 0 };
      await this.refresh();
    },

    /* ------------------------- keyboard ------------------------- */
    bindKeys() {
      window.addEventListener("keydown", (e) => {
        // Don't hijack typing in inputs.
        if (e.target.matches("input, textarea")) return;
        if (this.view !== "triage" || this.triage.done || !this.triage.current) return;

        if (e.key === "1") { e.preventDefault(); this.chooseReply("positive"); }
        else if (e.key === "2") { e.preventDefault(); this.chooseReply("neutral"); }
        else if (e.key === "3") { e.preventDefault(); this.chooseReply("negative"); }
        else if (e.key === "s" || e.key === "S") { e.preventDefault(); this.skip(); }
        else if (e.key === "q" || e.key === "Q") { e.preventDefault(); this.endTriage(); }
      });
    },
  };
}
